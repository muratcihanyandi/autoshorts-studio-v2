"""Start/Stop era: channel automation state machine, stock-target
refill, no-reprocessing guarantees, hype selection, status tags,
content modes, and the whisper fallback.

These tests verify the goal's acceptance scenarios: start actually
makes the worker take work, the stock target (default 3) stops new
downloads, depletion resumes production, a source is never processed
twice, one video yields multiple Shorts, stop blocks new jobs, state
survives restarts, and LLM/download failures never halt the system.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    ChannelCharacter,
    Character,
    ClipCandidate,
    Job,
    MediaAsset,
    MediaInspection,
    PublishingProfile,
    RenderedClip,
    SourceChannel,
    SourceVideo,
    Transcript,
)
from app.services.media_storage import ensure_media_tree
from tests.conftest import _make_app
from tests.media_sample import make_face_stream_video

VTT_SIDE = """WEBVTT

00:00:01.000 --> 00:00:04.000
bugun size cok onemli bir konu anlatiyorum
"""


def _env(tmp_path, **overrides):
    db_path = tmp_path / "chauto.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    kwargs = dict(
        media_root=str(tmp_path / "media"),
        clip_min_seconds=3,
        clip_max_seconds=6,
    )
    kwargs.update(overrides)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **kwargs
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    ensure_media_tree(tmp_path / "media")
    return sessionmaker, settings, engine


def _run(coro):
    return asyncio.run(coro)


async def _seed_channel(
    sessionmaker, *, automation_state="stopped", stock_target=3, name="Kanal"
) -> int:
    async with sessionmaker() as session:
        channel = Channel(name=name, status="connected")
        session.add(channel)
        await session.flush()
        session.add(
            PublishingProfile(
                channel_id=channel.id,
                automation_state=automation_state,
                horizontal_stock_target=stock_target,
            )
        )
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id=f"UC-{name}",
            title=name,
            permission_status="authorized",
        )
        session.add(source)
        await session.commit()
        return channel.id


async def _seed_planned_video(sessionmaker, channel_id: int, n: int = 1):
    """n adet 'planned' video; video id listesi doner."""
    ids = []
    async with sessionmaker() as session:
        source = (
            (
                await session.execute(
                    sa.select(SourceChannel).where(
                        SourceChannel.channel_id == channel_id
                    )
                )
            )
            .scalars()
            .first()
        )
        for i in range(n):
            video = SourceVideo(
                source_channel_id=source.id,
                youtube_video_id=f"vid-{i}",
                title=f"Video {i}",
                status="planned",
            )
            session.add(video)
            await session.flush()
            ids.append(video.id)
        await session.commit()
    return ids


async def _make_processed(
    sessionmaker, channel_id: int, video_id: int, *, confirmed=False
):
    """Videoyu #done (#confirmed) durumuna getir: islenmis asset.
    Var olan asset satiri yeniden kullanilir (benzersizlik korunur)."""
    async with sessionmaker() as session:
        asset = (
            (
                await session.execute(
                    sa.select(MediaAsset).where(
                        MediaAsset.source_video_id == video_id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if asset is None:
            asset = MediaAsset(
                source_video_id=video_id,
                origin="local_import",
                status="processed",
                stage="candidates",
                file_path="/x.mp4",
                file_bytes=100,
            )
            session.add(asset)
            await session.flush()
        else:
            asset.status = "processed"
            asset.stage = "candidates"
        inspection = (
            (
                await session.execute(
                    sa.select(MediaInspection).where(
                        MediaInspection.media_asset_id == asset.id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if inspection is None:
            session.add(
                MediaInspection(
                    media_asset_id=asset.id,
                    duration_seconds=8.0,
                    width=1280,
                    height=720,
                    fps=15.0,
                    video_codec="h264",
                    has_audio=True,
                )
            )
        video = await session.get(SourceVideo, video_id)
        video.status = "confirmed" if confirmed else "processed"
        await session.commit()


async def _seed_ready_clip(sessionmaker, channel_id: int, video_id: int):
    """Gorev 2 stok semasi: videoya secilmis aday + render edilmis dikey
    klip ekler; aday kimligini doner."""
    from app.models import ClipCandidate, PublishedVideo, RenderedClip

    async with sessionmaker() as session:
        candidate = ClipCandidate(
            source_video_id=video_id,
            start_seconds=0.0,
            end_seconds=30.0,
            duration_seconds=30.0,
            score=0.9,
            status="selected",
        )
        session.add(candidate)
        await session.flush()
        render = RenderedClip(
            clip_candidate_id=candidate.id,
            source_video_id=video_id,
            orientation="vertical",
            status="rendered",
            file_path=f"/x/{candidate.id}.mp4",
            file_bytes=100,
        )
        session.add(render)
        await session.flush()
        await session.commit()
        return candidate.id


async def _publish_clip(sessionmaker, channel_id: int, candidate_id: int):
    """Hazir klipi paylasilmis yap: PublishedVideo satiri stoktan dusurur."""
    from app.models import PublishedVideo, SourceVideo, ClipCandidate

    async with sessionmaker() as session:
        candidate = await session.get(ClipCandidate, candidate_id)
        session.add(
            PublishedVideo(
                clip_candidate_id=candidate_id,
                source_video_id=candidate.source_video_id,
                orientation="vertical",
                channel_id=channel_id,
                youtube_video_id=f"yt-{candidate_id}",
                visibility="public",
                status="verified",
                title="Yayinlandi",
            )
        )
        await session.commit()



class TestStartStopStateMachine:
    def test_start_enqueues_refill_and_worker_processes(self, tmp_path):
        """Kabul: Baslat gercekten isi alir — stok bos, planned video
        var; start bir media_process isi kuyruga koyar ve worker onu
        gercekten isler (API'nin calismasi yeterli degil)."""
        from app.services.automation_service import AutomationService
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(sessionmaker)
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                service = AutomationService(sessionmaker, settings)
                result = await service.start(channel_id)

                # Start aninda tam bir media_process isi kuyrukta.
                jobs = [
                    j
                    for j in await JobService_list(sessionmaker)
                    if j[1] == "media_process"
                ]
                # Worker isi alir ve handler guard'i kanal calisirken
                # gercekten calistirir (indirme dosyasi yok -> hata, ama
                # 'skipped' DEGIL: handler kosmustur).
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job_row = await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job_row.id)
                return result, jobs, job_row.id, video_id
            finally:
                await engine.dispose()

        result, jobs, job_id, video_id = _run(scenario())
        assert result["automation_state"] == "running"
        assert result["refill"]["enqueued"] is True
        assert len(jobs) == 1
        # Is gercekten kostu: asset olusmustur (indirme asamasi hata
        # vermis olabilir ama is 'running' kanalda atlanmamistir).
        engine = sa.create_engine(f"sqlite:///{tmp_path}/chauto.db")
        with engine.connect() as conn:
            asset_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM media_assets")
            ).scalar()
        engine.dispose()
        assert asset_count == 1

    def test_stop_cancels_queued_jobs_and_blocks_new(self, tmp_path):
        """Kabul: Durdur siradaki isleri iptal eder, beslemeler yeni is
        eklemez ve handler durdurulmus kanalda isi atlar."""
        from app.services.automation_service import AutomationService
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(
                    sessionmaker, automation_state="running"
                )
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "media_process", {"source_video_id": video_id}
                )
                service = AutomationService(sessionmaker, settings)
                stop_result = await service.stop(channel_id)
                # Beslemeler artik hicbir yeni is eklemez.
                await worker.enqueue_planned_jobs()
                await worker.enqueue_render_jobs()
                after_feed = await JobService_list(sessionmaker)
                # Durdurulmus kanala sonradan kuyruga giren bir is
                # handler'da atlanir (asset olusmaz).
                late_job = await worker._jobs.enqueue(
                    "media_process", {"source_video_id": video_id}
                )
                claimed = await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(claimed.id)
                return stop_result, after_feed, job.id, late_job.id
            finally:
                await engine.dispose()

        stop_result, jobs, job_id, late_job_id = _run(scenario())
        assert stop_result["automation_state"] == "stopped"
        assert stop_result["cancelled_jobs"] == 1
        assert jobs == []  # besleme yeni is eklemedi
        engine = sa.create_engine(f"sqlite:///{tmp_path}/chauto.db")
        with engine.connect() as conn:
            status = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"),
                {"j": job_id},
            ).scalar()
            late_status = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"),
                {"j": late_job_id},
            ).scalar()
            asset_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM media_assets")
            ).scalar()
        engine.dispose()
        assert status == "cancelled"  # siradaki is kontrollu iptal
        assert late_status == "succeeded"  # is 'skipped' olarak sonuclandi
        assert asset_count == 0  # hicbir yarim cikti 'hazir' sayilmaz

    def test_state_survives_restart(self, tmp_path):
        """Kabul: uygulama yeniden basladiginda kuyruk ve otomasyon
        durumu veritabanindan geri yuklenir."""
        from app.services.automation_service import AutomationService

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(
                    sessionmaker, automation_state="running"
                )
                await _seed_planned_video(sessionmaker, channel_id, n=2)
                await AutomationService(sessionmaker, settings).stop(
                    channel_id
                )
            finally:
                await engine.dispose()
            # 'Yeniden baslatma': ayni dosya uzerinde yeni oturum.
            settings2 = Settings(
                database_url=f"sqlite+aiosqlite:///{tmp_path}/chauto.db"
            )
            engine2, sessionmaker2 = create_engine_and_sessionmaker(
                settings2.database_url
            )
            try:
                service = AutomationService(sessionmaker2, settings2)
                profile = await service.profile(channel_id)
                jobs = await JobService_list(sessionmaker2)
                return profile.automation_state, len(jobs)
            finally:
                await engine2.dispose()

        state, job_count = _run(scenario())
        assert state == "stopped"
        assert job_count == 0  # durdururken siradaki isler iptal edildi


class TestStockRefill:
    def test_stock_target_stops_new_downloads(self, tmp_path):
        """Kabul: hazir klip stogu hedefe ulasinca yeni yatay indirme yok."""
        from app.services.automation_service import refill_channel_stock

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(
                    sessionmaker, stock_target=3
                )
                await AutomationService_start(
                    sessionmaker, settings, channel_id
                )
                ids = await _seed_planned_video(sessionmaker, channel_id, n=5)
                for video_id in ids[:3]:
                    await _make_processed(sessionmaker, channel_id, video_id)
                    await _seed_ready_clip(sessionmaker, channel_id, video_id)
                result = await refill_channel_stock(
                    sessionmaker, settings, channel_id
                )
                jobs = await JobService_list(sessionmaker)
                return result, jobs
            finally:
                await engine.dispose()

        result, jobs = _run(scenario())
        assert result["enqueued"] is False
        assert result["reason"] == "stok hedefte"
        assert jobs == []

    def test_single_source_rule_one_active_job(self, tmp_path):
        """Kabul: ayni anda yalnizca bir yatay kaynak islenir — aktif
        media_process varken ikinci indirme baslamaz."""
        from app.services.automation_service import refill_channel_stock

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(sessionmaker)
                await AutomationService_start(
                    sessionmaker, settings, channel_id
                )
                await _seed_planned_video(sessionmaker, channel_id, n=4)
                first = await refill_channel_stock(
                    sessionmaker, settings, channel_id
                )
                second = await refill_channel_stock(
                    sessionmaker, settings, channel_id
                )
                return first, second
            finally:
                await engine.dispose()

        first, second = _run(scenario())
        assert first["enqueued"] is True
        assert second["enqueued"] is False
        assert second["reason"] == "baska bir yatay kaynak isleniyor"

    def test_stock_depletion_resumes_production(self, tmp_path):
        """Kabul: stok azaldiginda (klip paylasildiginda) otomasyon yeniden
        uretime gecer."""
        from app.services.automation_service import refill_channel_stock

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(sessionmaker, stock_target=2)
                await AutomationService_start(
                    sessionmaker, settings, channel_id
                )
                ids = await _seed_planned_video(sessionmaker, channel_id, n=4)
                clip_ids = []
                for video_id in ids[:2]:
                    await _make_processed(sessionmaker, channel_id, video_id)
                    clip_ids.append(
                        await _seed_ready_clip(
                            sessionmaker, channel_id, video_id
                        )
                    )
                # Stok dolu (2 hazir klip >= hedef 2): yeni indirme yok.
                full = await refill_channel_stock(sessionmaker, settings, channel_id)
                # Bir klip paylasildi: stok 1'e dusuyor, uretim surer.
                await _publish_clip(sessionmaker, channel_id, clip_ids[0])
                resumed = await refill_channel_stock(
                    sessionmaker, settings, channel_id
                )
                return full, resumed
            finally:
                await engine.dispose()

        full, resumed = _run(scenario())
        assert full["enqueued"] is False
        assert resumed["enqueued"] is True

    def test_processed_source_never_requeued(self, tmp_path):
        """Kabul: ayni kaynak ikinci kez islenmez — processed ve
        confirmed videolar refill tarafindan secilmez."""
        from app.services.automation_service import refill_channel_stock

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(sessionmaker)
                await AutomationService_start(
                    sessionmaker, settings, channel_id
                )
                ids = await _seed_planned_video(sessionmaker, channel_id, n=2)
                await _make_processed(sessionmaker, channel_id, ids[0])
                await _make_processed(
                    sessionmaker, channel_id, ids[1], confirmed=True
                )
                result = await refill_channel_stock(
                    sessionmaker, settings, channel_id
                )
                jobs = await JobService_list(sessionmaker)
                return result, jobs
            finally:
                await engine.dispose()

        result, jobs = _run(scenario())
        assert result["enqueued"] is False
        assert result["reason"] == "islenecek uygun kaynak yok"
        assert jobs == []


class TestHypeAndConfirmed:
    def test_multiple_shorts_selected_and_rendered(self, tmp_path):
        """Kabul: bir yatay videodan birden fazla bagimsiz Shorts;
        render beslemesi yalnizca secili adaylari alir."""
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path, shorts_per_video=2)
            try:
                channel_id = await _seed_channel(
                    sessionmaker, automation_state="running"
                )
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                await _make_processed(sessionmaker, channel_id, video_id)
                async with sessionmaker() as session:
                    # Iki cakismayan aday: hype (LLM'siz fallback) ikisini
                    # de secer.
                    session.add(
                        ClipCandidate(
                            source_video_id=video_id,
                            start_seconds=1.0,
                            end_seconds=4.0,
                            duration_seconds=3.0,
                            score=0.9,
                            status="candidate",
                        )
                    )
                    session.add(
                        ClipCandidate(
                            source_video_id=video_id,
                            start_seconds=4.5,
                            end_seconds=7.5,
                            duration_seconds=3.0,
                            score=0.7,
                            status="candidate",
                        )
                    )
                    await session.commit()

                worker = JobWorker(sessionmaker, settings)
                hype_added = await worker.enqueue_hype_jobs()
                hype_jobs = [
                    (j, t)
                    for j, t in await JobService_list(sessionmaker)
                    if t == "hype_evaluate"
                ]
                for job_id, _ in hype_jobs:
                    await worker._jobs.claim_next(worker._worker_id)
                    await worker.run_job(job_id)

                selected = await _candidate_statuses(sessionmaker)
                render_added = await worker.enqueue_render_jobs()
                render_jobs = [
                    (j, t)
                    for j, t in await JobService_list(sessionmaker)
                    if t == "clip_render"
                ]
                return (
                    hype_added,
                    selected,
                    render_added,
                    len(render_jobs),
                )
            finally:
                await engine.dispose()

        hype_added, selected, render_added, render_count = _run(scenario())
        assert hype_added == 1
        # Iki aday secildi (fallback: skor sirali, cakismayan).
        assert selected.count("selected") == 2
        assert render_added == 2
        assert render_count == 2

    def test_llm_refines_window_and_snaps_to_sentence(self, tmp_path):
        """LLM onerisi: zamanlar dogrulanir ve cumle sinirlarina
        hizalanir; gecersiz oneri orijinal pencereye duser."""
        from app.services.hype_service import snap_to_segments, validate_window

        segments = [
            {"start": 0.0, "end": 2.0, "text": "a"},
            {"start": 2.0, "end": 5.0, "text": "b"},
            {"start": 5.0, "end": 9.0, "text": "c"},
        ]
        # 3.0 bir cumlenin ortasi: 2.0'a cekilir (sure 3-6 icinde).
        assert snap_to_segments(
            3.0, 6.0, segments, duration=9.0, min_seconds=3, max_seconds=6
        ) == (2.0, 6.0)
        # 8.5 bir cumlenin ortasi: 9.0'a cekilir.
        assert snap_to_segments(
            4.0, 8.5, segments, duration=9.0, min_seconds=3, max_seconds=6
        ) == (4.0, 9.0)
        # Iki uc da cekilebilir ve sure sinirlari icinde kalir.
        assert snap_to_segments(
            1.5, 4.0, segments, duration=9.0, min_seconds=3, max_seconds=6
        ) == (0.0, 5.0)
        # Snap sure sinirini bozarsa uygulanmaz (min 4.5: cekince kisa kalir).
        assert snap_to_segments(
            1.5, 4.0, segments, duration=9.0, min_seconds=4.5, max_seconds=6
        ) == (1.5, 4.0)
        # Gecersiz oneriler reddedilir.
        assert validate_window(5.0, 5.0, 9.0, min_seconds=3, max_seconds=6) is None
        assert validate_window(-1.0, 4.0, 9.0, min_seconds=3, max_seconds=6) is None

    def test_hype_llm_context_spans_wide_window(self):
        """LLM bağlamı geniş (±90 sn, kullanıcı isteği 2026-10-21): hype
        anı 20 sn de 2 dk da olabildiğinden model anın doğal sınırlarını
        görebilmeli — dar bağlam aday penceresine kilitlenip süreyi
        sabitliyordu."""
        from app.config import Settings
        from app.models import ClipCandidate
        from app.services.hype_service import CONTEXT_SECONDS, HypeService

        assert CONTEXT_SECONDS >= 90.0
        service = HypeService(None, None, Settings(database_url=""))
        segments = [
            {"start": float(t), "end": float(t) + 10.0, "text": f"cumle {t}"}
            for t in range(0, 600, 10)
        ]
        context = {"segments": segments, "duration": 600.0, "analysis": {}}
        candidate = ClipCandidate(id=1, start_seconds=100.0, end_seconds=120.0)
        block = service._candidate_block(context, candidate)
        # ±90 sn baglam: 10-90 ve 120-200 arasi cumleler gorunur.
        assert "cumle 20" in block
        assert "cumle 90" in block
        assert "cumle 200" in block
        assert "cumle 0" not in block
        assert "cumle 210" not in block

    def test_maybe_confirm_source_after_renders(self, tmp_path):
        """#confirmed gecisi: tum secili adaylar render edilince kaynak
        nihailesir ve stoktan dusulur; tekrar kuyruga alinmaz."""
        from app.services.status_service import StatusService

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(sessionmaker)
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                await _make_processed(sessionmaker, channel_id, video_id)
                async with sessionmaker() as session:
                    c1 = ClipCandidate(
                        source_video_id=video_id,
                        start_seconds=1.0,
                        end_seconds=4.0,
                        duration_seconds=3.0,
                        score=0.9,
                        status="selected",
                    )
                    c2 = ClipCandidate(
                        source_video_id=video_id,
                        start_seconds=4.5,
                        end_seconds=7.5,
                        duration_seconds=3.0,
                        score=0.7,
                        status="selected",
                    )
                    session.add_all([c1, c2])
                    await session.flush()
                    session.add(
                        RenderedClip(
                            clip_candidate_id=c1.id, status="rendered"
                        )
                    )
                    await session.commit()
                    ids = [c1.id, c2.id]

                status = StatusService(sessionmaker, settings)
                first = await status.maybe_confirm_source(video_id)
                stock_before = await status.horizontal_stock_level(channel_id)
                async with sessionmaker() as session:
                    session.add(
                        RenderedClip(
                            clip_candidate_id=ids[1], status="rendered"
                        )
                    )
                    await session.commit()
                second = await status.maybe_confirm_source(video_id)
                stock_after = await status.horizontal_stock_level(channel_id)
                return first, second, stock_before, stock_after
            finally:
                await engine.dispose()

        first, second, stock_before, stock_after = _run(scenario())
        assert first is False  # eksik render: confirmed olmaz
        assert second is True
        assert stock_before == 1
        assert stock_after == 0  # stok hedefi yeniden uretime gecer


class TestStatusTags:
    def test_source_tag_vocabulary(self, tmp_path):
        """Etiketler gercek veritabani durumundan hesaplanir:
        #queued -> #downloading/#processing -> #done -> #confirmed,
        hata #error."""
        from app.services.status_service import StatusService

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(sessionmaker)
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                status = StatusService(sessionmaker, settings)
                queued = await status.source_tag(video_id)

                async with sessionmaker() as session:
                    asset = MediaAsset(
                        source_video_id=video_id,
                        origin="local_import",
                        status="downloading",
                        stage="download",
                        file_path="",
                    )
                    session.add(asset)
                    # Kosan bir is varken indirme asamasi #downloading.
                    session.add(
                        Job(
                            job_type="media_process",
                            payload={"source_video_id": video_id},
                            status="running",
                        )
                    )
                    await session.commit()
                    asset_id = asset.id
                downloading = await status.source_tag(video_id)

                async with sessionmaker() as session:
                    await session.execute(
                        sa.update(Job).where(Job.status == "running")
                        .values(status="failed")
                    )
                    await session.execute(
                        sa.update(MediaAsset)
                        .where(MediaAsset.id == asset_id)
                        .values(status="failed", last_error="bozuk")
                    )
                    await session.commit()
                error = await status.source_tag(video_id)

                await _make_processed(sessionmaker, channel_id, video_id)
                done = await status.source_tag(video_id)

                async with sessionmaker() as session:
                    await session.execute(
                        sa.update(SourceVideo)
                        .where(SourceVideo.id == video_id)
                        .values(status="confirmed")
                    )
                    await session.commit()
                confirmed = await status.source_tag(video_id)
                return queued, downloading, error, done, confirmed
            finally:
                await engine.dispose()

        queued, downloading, error, done, confirmed = _run(scenario())
        assert queued == "#queued"
        assert downloading == "#downloading"
        assert error == "#error"
        assert done == "#done"
        assert confirmed == "#confirmed"

    def test_engine_activity_reflects_running_jobs(self, tmp_path):
        from app.services.status_service import StatusService

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(
                    sessionmaker, automation_state="running"
                )
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                status = StatusService(sessionmaker, settings)
                idle = await status.engine_activity(channel_id)
                # Kosan bir media_process isi: asset indirme asamasinda.
                async with sessionmaker() as session:
                    session.add(
                        MediaAsset(
                            source_video_id=video_id,
                            origin="local_import",
                            status="downloading",
                            stage="download",
                            file_path="",
                        )
                    )
                    await session.commit()
                async with sessionmaker() as session:
                    job = Job(
                        job_type="media_process",
                        payload={"source_video_id": video_id},
                        status="running",
                    )
                    session.add(job)
                    await session.commit()
                downloading = await status.engine_activity(channel_id)
                # Stok hazirsa ve is yoksa 'stokta hazır'.
                await _make_processed(sessionmaker, channel_id, video_id)
                async with sessionmaker() as session:
                    await session.execute(
                        sa.delete(Job).where(Job.status == "running")
                    )
                    await session.commit()
                ready = await status.engine_activity(channel_id)
                return idle, downloading, ready
            finally:
                await engine.dispose()

        idle, downloading, ready = _run(scenario())
        assert idle == "idle"
        assert downloading == "downloading"
        assert ready == "stock_ready"


class TestMetadataModes:
    def test_modes_off_and_notification_forcing(self):
        """off: deterministik metaveri; on/off bildirim kararları LLM'yi
        ezer; auto LLM kararını kullanır."""
        from app.services.metadata_service import (
            MetadataProposal,
            MetadataService,
            fallback_description,
            fallback_title,
        )

        proposal = MetadataProposal(
            title="LLM Basligi",
            summary="LLM ozeti yeterince uzun bir aciklama metni.",
            tags=["llm"],
            content_warning=True,
            ai_disclosure=False,
        )
        context = {
            "video_title": "Kaynak Basligi",
            "channel_name": "Kanal",
            "transcript": "transkript metni burada",
            "title_pattern": "{title}",
            "description_pattern": "{summary}",
            "base_tags": ["sablon"],
            "modes": {
                "title_mode": "off",
                "description_mode": "off",
                "tags_mode": "off",
                "content_warning_mode": "on",
                "ai_disclosure_mode": "off",
            },
        }
        service = MetadataService.__new__(MetadataService)  # DB'siz
        composed = service._compose(proposal, context)
        # off: LLM degil deterministik degerler.
        assert composed["title"] == fallback_title("Kaynak Basligi")
        assert composed["description"] == fallback_description(
            "Kaynak Basligi", "transkript metni burada"
        )
        assert composed["tags"] == ["sablon"]
        # on/off bildirim kararlari LLM'yi ezer.
        assert composed["content_warning"] is True  # on (LLM zaten true)
        assert composed["ai_disclosure"] is False  # off (LLM de false)

        context["modes"]["content_warning_mode"] = "off"
        context["modes"]["ai_disclosure_mode"] = "on"
        composed2 = service._compose(proposal, context)
        assert composed2["content_warning"] is False
        assert composed2["ai_disclosure"] is True

    def test_all_off_skips_llm_entirely(self):
        from app.services.metadata_service import MetadataService

        service = MetadataService.__new__(MetadataService)
        modes = {
            "title_mode": "off",
            "description_mode": "off",
            "tags_mode": "off",
            "content_warning_mode": "off",
            "ai_disclosure_mode": "off",
        }
        assert service._llm_needed(modes) is False
        modes["content_warning_mode"] = "auto"
        assert service._llm_needed(modes) is True


class TestWhisperFallback:
    def test_whisper_runs_when_no_sidecar(self, tmp_path, monkeypatch):
        """Altyazi yok + yontem 'whisper': yerel Whisper CLI calisir
        (sahte runner SRT yazar), transkript kaydedilir."""
        import app.services.media_transcript as mt
        from app.services.media_pipeline import MediaPipelineService

        media = make_face_stream_video(tmp_path / "w.mp4")

        class FakeWhisper:
            def __init__(self, runner=None, env=None):
                pass

            async def transcribe(self, media_path, output_dir, **kwargs):
                srt = output_dir / f"{media.stem if hasattr(media, 'stem') else 'w'}.srt"
                srt.write_text(
                    "1\n00:00:00,500 --> 00:00:03,000\nwhisper transkript\n",
                    encoding="utf-8",
                )
                from app.services.media_transcript import parse_srt

                return parse_srt(srt.read_text(encoding="utf-8"))

        monkeypatch.setattr(mt, "WhisperTranscriber", FakeWhisper)

        async def scenario():
            sessionmaker, settings, engine = _env(
                tmp_path, transcription_method="whisper"
            )
            try:
                channel_id = await _seed_channel(sessionmaker)
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                pipeline = MediaPipelineService(sessionmaker, settings)
                asset_id = await pipeline._ensure_asset(video_id, True)
                async with sessionmaker() as session:
                    asset = await session.get(MediaAsset, asset_id)
                    asset.file_path = str(media)
                    await session.commit()
                await pipeline._stage_transcript(
                    asset_id, channel_id, video_id, "vid-0", None
                )
                async with sessionmaker() as session:
                    row = (
                        (
                            await session.execute(
                                sa.select(Transcript).where(
                                    Transcript.media_asset_id == asset_id
                                )
                            )
                        )
                        .scalars()
                        .one_or_none()
                    )
                    return row
            finally:
                await engine.dispose()

        row = _run(scenario())
        assert row is not None
        assert row.source == "whisper"
        assert row.segment_count == 1
        assert row.segments[0]["text"] == "whisper transkript"

    def test_whisper_primary_even_with_sidecar(self, tmp_path, monkeypatch):
        """Kullanıcı isteği (2026-10-22): 'whisper' yöntemi BİRİNCİLDİR —
        YouTube otomatik altyazısı (yan dosya) VARSA BİLE Whisper koşar,
        sidecar yalnızca Whisper hata verirse kullanılır."""

        import app.services.media_transcript as mt
        from app.services.media_pipeline import MediaPipelineService

        media = make_face_stream_video(tmp_path / "w2.mp4")
        # Yan altyazı var: yt-dlp tarzı '<id>.tr.vtt'.
        sidecar = tmp_path / "w2.tr.vtt"
        sidecar.write_text(
            "WEBVTT\n\n00:00:00.500 --> 00:00:03.000\n"
            "youtube otomatik altyazisi\n",
            encoding="utf-8",
        )

        class FakeWhisper:
            def __init__(self, runner=None, env=None):
                pass

            async def transcribe(self, media_path, output_dir, **kwargs):
                from app.services.media_transcript import parse_srt

                return parse_srt(
                    "1\n00:00:00,500 --> 00:00:03,000\n"
                    "whisper birincil transkript\n"
                )

        monkeypatch.setattr(mt, "WhisperTranscriber", FakeWhisper)

        async def scenario():
            sessionmaker, settings, engine = _env(
                tmp_path, transcription_method="whisper"
            )
            try:
                channel_id = await _seed_channel(sessionmaker)
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                pipeline = MediaPipelineService(sessionmaker, settings)
                asset_id = await pipeline._ensure_asset(video_id, True)
                async with sessionmaker() as session:
                    asset = await session.get(MediaAsset, asset_id)
                    asset.file_path = str(media)
                    await session.commit()
                await pipeline._stage_transcript(
                    asset_id, channel_id, video_id, "vid-0", None
                )
                async with sessionmaker() as session:
                    row = (
                        (
                            await session.execute(
                                sa.select(Transcript).where(
                                    Transcript.media_asset_id == asset_id
                                )
                            )
                        )
                        .scalars()
                        .one_or_none()
                    )
                    return row
            finally:
                await engine.dispose()

        row = _run(scenario())
        assert row is not None
        assert row.source == "whisper"
        assert row.segments[0]["text"] == "whisper birincil transkript"

    def test_whisper_failure_falls_back_to_sidecar(self, tmp_path, monkeypatch):
        """Whisper hata verirse iş kaybolmaz: yan altyazıya düşer."""

        import app.services.media_transcript as mt
        from app.services.media_pipeline import MediaPipelineService
        from app.services.media_transcript import TranscriptError

        media = make_face_stream_video(tmp_path / "w3.mp4")
        sidecar = tmp_path / "w3.tr.vtt"
        sidecar.write_text(
            "WEBVTT\n\n00:00:00.500 --> 00:00:03.000\n"
            "youtube otomatik altyazisi\n",
            encoding="utf-8",
        )

        class FailingWhisper:
            def __init__(self, runner=None, env=None):
                pass

            async def transcribe(self, media_path, output_dir, **kwargs):
                raise TranscriptError("whisper basarisiz")

        monkeypatch.setattr(mt, "WhisperTranscriber", FailingWhisper)

        async def scenario():
            sessionmaker, settings, engine = _env(
                tmp_path, transcription_method="whisper"
            )
            try:
                channel_id = await _seed_channel(sessionmaker)
                [video_id] = await _seed_planned_video(
                    sessionmaker, channel_id
                )
                pipeline = MediaPipelineService(sessionmaker, settings)
                asset_id = await pipeline._ensure_asset(video_id, True)
                async with sessionmaker() as session:
                    asset = await session.get(MediaAsset, asset_id)
                    asset.file_path = str(media)
                    await session.commit()
                await pipeline._stage_transcript(
                    asset_id, channel_id, video_id, "vid-0", None
                )
                async with sessionmaker() as session:
                    row = (
                        (
                            await session.execute(
                                sa.select(Transcript).where(
                                    Transcript.media_asset_id == asset_id
                                )
                            )
                        )
                        .scalars()
                        .one_or_none()
                    )
                    return row
            finally:
                await engine.dispose()

        row = _run(scenario())
        assert row is not None
        # Whisper degil: yan altyaziya dusuldu (kaynak adi import
        # kokune gore 'sidecar' ya da indirmeye gore 'auto_caption').
        assert row.source != "whisper"
        assert row.segments[0]["text"] == "youtube otomatik altyazisi"


class TestTerminalFailureAndResources:
    def test_terminal_media_failure_keeps_flow(self, tmp_path):
        """Kalici medya hatasi kanali DURDURMAZ (kullanici istegi
        2026-10-19): basarisiz videonun varligi 'failed' kalir, stok
        beslemesi bu videoyu atlayip siradakini secer."""
        from app.services.automation_service import (
            AutomationService,
            refill_channel_stock,
        )
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine = _env(tmp_path)
            try:
                channel_id = await _seed_channel(
                    sessionmaker, automation_state="running"
                )
                [video_a, video_b] = await _seed_planned_video(
                    sessionmaker, channel_id, n=2
                )
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "media_process",
                    {"source_video_id": video_a},
                    max_attempts=1,
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)  # MEDIA_ROOT'ta indirme hata verir
                profile = await AutomationService(
                    sessionmaker, settings
                ).profile(channel_id)
                state_after_failure = profile.automation_state
                # Stok beslemesi basarisiz videoyu atlar, siradakiye gecer.
                refill = await refill_channel_stock(
                    sessionmaker, settings, channel_id
                )
                return state_after_failure, refill, job.id, video_a, video_b
            finally:
                await engine.dispose()

        state, refill, job_id, video_a, video_b = _run(scenario())
        assert state == "running"  # kanal durmadi
        assert refill["enqueued"] is True

        engine = sa.create_engine(f"sqlite:///{tmp_path}/chauto.db")
        with engine.connect() as conn:
            s1 = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id=:j"), {"j": job_id}
            ).scalar()
            failed_count = conn.execute(
                sa.text(
                    "SELECT count(*) FROM media_assets"
                    " WHERE status = 'failed'"
                )
            ).scalar()
        engine.dispose()
        assert s1 == "failed"
        assert failed_count == 1  # video_a'nin varligi basarisiz kayitli
        # Yeni is basarisiz OLMAYAN videoyu isaret etmeli.
        assert refill["source_video_id"] == video_b

    def test_resource_gate_defers_claims(self, tmp_path, monkeypatch):
        """CPU/RAM hedefi asilinca yeni isler bekler (kilit degil)."""
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine = _env(
                tmp_path, cpu_target_percent=50, ram_target_percent=90
            )
            try:
                worker = JobWorker(sessionmaker, settings)
                import app.worker as worker_mod

                class FakePsutil:
                    @staticmethod
                    def cpu_percent(interval=None):
                        return 95.0

                    class virtual_memory:  # noqa: N801
                        @staticmethod
                        def percent():
                            return 40.0

                monkeypatch.setattr(worker_mod, "psutil", FakePsutil, raising=False)
                # psutil modul seviyesinde import edilir; resource_ok icinde
                # import psutil yapilir — sys.modules uzerinden degistir.
                import sys
                import types

                fake = types.ModuleType("psutil")
                fake.cpu_percent = lambda interval=None: 95.0

                class VM:
                    percent = 40.0

                fake.virtual_memory = lambda: VM()
                monkeypatch.setitem(sys.modules, "psutil", fake)
                blocked = worker._resource_ok()
                worker._effective = settings.model_copy(
                    update={"cpu_target_percent": 0, "ram_target_percent": 0}
                )
                allowed = worker._resource_ok()
                return blocked, allowed
            finally:
                await engine.dispose()

        blocked, allowed = _run(scenario())
        assert blocked is False
        assert allowed is True


class TestAutomationApi:
    def test_start_stop_settings_roundtrip(self, tmp_path):
        app = _make_app(tmp_path, worker_enabled=False)
        with TestClient(app) as client:
            channel_id = client.post(
                "/api/channels", json={"name": "Kanal"}
            ).json()["id"]

            settings0 = client.get(f"/api/channels/{channel_id}/automation")
            assert settings0.status_code == 200
            body = settings0.json()
            assert body["automation_state"] == "stopped"
            assert body["horizontal_stock_target"] == 3
            assert body["title_mode"] == "auto"

            started = client.post(
                f"/api/channels/{channel_id}/automation/start"
            )
            assert started.status_code == 200, started.text
            assert started.json()["automation_state"] == "running"

            # Ayarlar: stok hedefi + modlar + prompt + karakterler.
            character_id = client.post(
                "/api/characters", json={"name": "RRaenee"}
            ).json()["id"]
            saved = client.put(
                f"/api/channels/{channel_id}/automation",
                json={
                    "horizontal_stock_target": 5,
                    "title_mode": "on",
                    "description_mode": "off",
                    "tags_mode": "auto",
                    "content_warning_mode": "on",
                    "ai_disclosure_mode": "off",
                    "channel_system_prompt": "Bu kanal icin ozel prompt.",
                    "character_ids": [character_id],
                },
            )
            assert saved.status_code == 200, saved.text
            body = saved.json()
            assert body["horizontal_stock_target"] == 5
            assert body["title_mode"] == "on"
            assert body["content_warning_mode"] == "on"
            assert body["channel_system_prompt"] == "Bu kanal icin ozel prompt."
            assert [c["character_id"] for c in body["characters"]] == [
                character_id
            ]

            # Kaydedilen ayarlar yeniden okunanda ayni.
            reread = client.get(f"/api/channels/{channel_id}/automation")
            assert reread.json()["horizontal_stock_target"] == 5
            assert reread.json()["description_mode"] == "off"

            paused = client.post(
                f"/api/channels/{channel_id}/automation/pause"
            )
            assert paused.json()["automation_state"] == "paused"

            stopped = client.post(
                f"/api/channels/{channel_id}/automation/stop"
            )
            assert stopped.status_code == 200
            assert stopped.json()["automation_state"] == "stopped"

            # Gecersiz mod reddedilir.
            bad = client.put(
                f"/api/channels/{channel_id}/automation",
                json={"title_mode": "belirsiz"},
            )
            assert bad.status_code == 400

    def test_horizontal_and_shorts_listings(self, tmp_path):
        app = _make_app(tmp_path, worker_enabled=False)
        with TestClient(app) as client:
            channel_id = client.post(
                "/api/channels", json={"name": "Kanal"}
            ).json()["id"]
            source = client.post(
                f"/api/channels/{channel_id}/sources",
                json={
                    "youtube_channel_id": "UCtest",
                    "title": "Kaynak",
                    "rights_record": {
                        "granted_by": "Sahibi",
                        "evidence_url": "https://ornek.test/hak",
                    },
                },
            ).json()

            engine = sa.create_engine(f"sqlite:///{tmp_path}/test.db")
            with engine.connect() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO source_videos (source_channel_id,"
                        " youtube_video_id, title, status, discovered_at,"
                        " updated_at) VALUES (:s, 'v1', 'Video', 'planned',"
                        " datetime('now'), datetime('now'))"
                    ),
                    {"s": source["id"]},
                )
                conn.commit()
            engine.dispose()

            listed = client.get(f"/api/channels/{channel_id}/horizontal")
            assert listed.status_code == 200
            videos = listed.json()["videos"]
            assert len(videos) == 1
            assert videos[0]["tag"] == "#queued"

            shorts = client.get(f"/api/channels/{channel_id}/shorts")
            assert shorts.status_code == 200
            assert shorts.json()["total"] == 0

    def test_overview_carries_channel_rows_and_worker(self, tmp_path):
        app = _make_app(tmp_path, worker_enabled=False)
        with TestClient(app) as client:
            client.post("/api/channels", json={"name": "Kanal"}).json()
            body = client.get("/api/overview").json()
            assert "channel_rows" in body
            assert len(body["channel_rows"]) == 1
            row = body["channel_rows"][0]
            assert row["automation_state"] == "stopped"
            assert row["engine_activity"] == "stopped"
            assert row["horizontal_stock_target"] == 3
            assert "worker" in body
            assert body["worker"]["enabled"] is False
            assert body["worker"]["running"] is False


# --- yardimcilar ---


async def JobService_list(sessionmaker):
    """(id, job_type) listesi — aktif + tumu."""
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    sa.select(Job.id, Job.job_type).where(
                        Job.status.in_(("queued", "running", "cancelling"))
                    )
                )
            )
            .all()
        )
    return [(row[0], row[1]) for row in rows]


async def AutomationService_start(sessionmaker, settings, channel_id):
    from app.services.automation_service import AutomationService

    await AutomationService(sessionmaker, settings).start(channel_id)


async def _candidate_statuses(sessionmaker) -> list[str]:
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    sa.select(ClipCandidate.status).order_by(
                        ClipCandidate.id
                    )
                )
            )
            .scalars()
            .all()
        )
    return list(rows)
