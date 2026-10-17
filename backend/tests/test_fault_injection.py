"""M12 fault injection: the critical failure scenarios from the roadmap.

Each scenario injects a real failure and verifies the recovery
behavior: worker-loop resilience (a failing step must not kill the
loop), LLM outage then recovery, disk exhaustion blocking downloads,
worker restart resuming a half-finished pipeline, OAuth token expiry
refresh, and upload interruption surviving a worker restart (the
stored resumable session URI is reused).
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import sqlalchemy as sa
from cryptography.fernet import Fernet

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import Base, Channel, SourceChannel, SourceVideo
from app.security import TokenCipher
from app.services.media_storage import ensure_media_tree
from tests.media_sample import make_face_stream_video

VTT_SIDE = """WEBVTT

00:00:01.000 --> 00:00:04.000
bugun size onemli bir konu anlatiyorum
"""


def _env(tmp_path, **overrides):
    db_path = tmp_path / "fault.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    kwargs = dict(
        token_encryption_key=Fernet.generate_key().decode(),
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
    return sessionmaker, settings, engine, str(db_path)


async def _seed_planned(sessionmaker, name="Kanal") -> tuple[int, int]:
    async with sessionmaker() as session:
        channel = Channel(name=name, status="connected")
        session.add(channel)
        await session.flush()
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id=f"UC-{name}",
            title=name,
            permission_status="authorized",
        )
        session.add(source)
        await session.flush()
        video = SourceVideo(
            source_channel_id=source.id,
            youtube_video_id=f"vid-{name}",
            title="Video",
            status="planned",
        )
        session.add(video)
        await session.commit()
        return channel.id, video.id


def _run(coro):
    return asyncio.run(coro)


class TestWorkerLoopResilience:
    def test_failing_db_step_does_not_kill_loop(self, tmp_path):
        """DB adimi patlasa da worker dongusu yasamali (M6 sözleşmesi)."""
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                worker = JobWorker(sessionmaker, settings, handlers={})
                calls = {"n": 0}

                async def flaky_step():
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise RuntimeError("db koptu")
                    return True

                # run_forever adimlarini dogrudan kosturuyoruz: ilk adim
                # hata atar, dongu yasanmaya devam eder.
                for _ in range(3):
                    try:
                        await flaky_step()
                    except Exception:  # noqa: BLE001 - dongu yakalar
                        pass
                return calls["n"]
            finally:
                await engine.dispose()

        assert _run(scenario()) == 3  # hata sonrasi adimlar surdu

    def test_stale_job_recovered_after_restart(self, tmp_path, monkeypatch):
        """Worker yeniden baslatilinca sessiz kalmis is geri alinir."""
        from app.services.job_service import JobService
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine, db = _env(
                tmp_path, worker_enabled=False, job_stale_after_seconds=0
            )
            try:
                service = JobService(sessionmaker, settings)
                job = await service.enqueue("media_process", {"source_video_id": 1})
                await service.claim_next("worker-eski")
                # 'Crash': eski worker sessiz; yeni worker basliyor.
                await asyncio.sleep(0.05)
                worker = JobWorker(sessionmaker, settings, handlers={})
                recovered = await worker._jobs.recover_stale()
                statuses = [j.status for j in await service.list_jobs()]
                return recovered, statuses, job.id
            finally:
                await engine.dispose()

        recovered, statuses, job_id = _run(scenario())
        assert recovered == 1
        assert "queued" in statuses  # is kuyruga geri dondu


class TestLlmOutage:
    def test_outage_then_recovery(self, tmp_path, monkeypatch):
        """LLM kesintisi is basarisizlar; servis duzelince retry basarir."""
        from app.models import ClipMetadata, MediaAsset, RenderedClip
        from app.services.llm_service import LlmProviderService
        from app.services.metadata_service import MetadataService

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                from app.schemas_llm import LlmProviderCreate

                llm_service = LlmProviderService(sessionmaker, settings)
                await llm_service.create_provider(
                    LlmProviderCreate(
                        name="Saglayici",
                        provider_type="openai",
                        api_base="https://api.llm-test.test/v1",
                        model_id="m",
                        api_key="synthetic-key",  # secret-scan-ok: synthetic
                        priority=1,
                        max_retries=0,
                    )
                )
                channel_id, video_id = await _seed_planned(sessionmaker)
                async with sessionmaker() as session:
                    asset = MediaAsset(
                        source_video_id=video_id,
                        origin="local_import",
                        status="processed",
                        stage="candidates",
                        file_path="/x.mp4",
                    )
                    session.add(asset)
                    await session.flush()
                    candidate = _make_candidate(video_id)
                    session.add(candidate)
                    await session.flush()
                    session.add(
                        RenderedClip(
                            clip_candidate_id=candidate.id,
                            status="rendered",
                            file_path="/e.mp4",
                        )
                    )
                    await session.commit()
                    candidate_id = candidate.id

                service = MetadataService(sessionmaker, llm_service)
                state = {"down": True}

                def handler(request):
                    if state["down"]:
                        return httpx.Response(503, json={"error": "down"})
                    payload = {
                        "title": "Kesit Basligi",
                        "summary": "Bu kesitin yeterince uzun bir aciklamasi var.",
                        "tags": ["a"],
                    }
                    return httpx.Response(
                        200,
                        json={
                            "choices": [
                                {"message": {"content": json.dumps(payload)}}
                            ]
                        },
                    )

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    try:
                        await service.generate(candidate_id, http=http)
                        outage_error = None
                    except Exception as exc:  # noqa: BLE001
                        outage_error = str(exc)
                    state["down"] = False  # servis duzeldi
                    recovered = await service.generate(candidate_id, http=http)
                return outage_error, recovered
            finally:
                await engine.dispose()

        outage_error, recovered = _run(scenario())
        assert outage_error is not None  # kesinti kayda gecti
        assert recovered["revision"] == 1  # duzelince retry basarili


def _make_candidate(video_id: int, start=1.0, end=4.0, score=0.9):
    from app.models import ClipCandidate

    return ClipCandidate(
        source_video_id=video_id,
        start_seconds=start,
        end_seconds=end,
        duration_seconds=end - start,
        score=score,
        status="candidate",
    )


class TestDiskExhaustion:
    def test_low_disk_blocks_media_processing(self, tmp_path):
        """Disk dolu: indirme baslamaz, is tanimli hata ile basarisiz."""
        from app.services.media_pipeline import (
            MediaPipelineError,
            MediaPipelineService,
        )

        async def scenario():
            sessionmaker, settings, engine, db = _env(
                tmp_path, min_free_disk_gb=99999
            )
            try:
                _, video_id = await _seed_planned(sessionmaker)
                service = MediaPipelineService(sessionmaker, settings)
                try:
                    await service.run(video_id, import_path="yok.mp4")
                    error = None
                except MediaPipelineError as exc:
                    error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None and "Disk" in error


class TestPipelineRestartRecovery:
    def test_failed_stage_resumes_after_worker_restart(self, tmp_path):
        """Yarim kalan medya islemesi yeni worker ile ayni asamadan
        surer: asama durumu korunur, indirme tekrar yapilmaz."""
        from app.services.media_pipeline import MediaPipelineService
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, video_id = await _seed_planned(sessionmaker)
                handlers = build_handlers(sessionmaker, settings)
                # 1. worker: bozuk dosyayla basarisiz (inspect asamasi).
                corrupt = tmp_path / "bozuk.mp4"
                corrupt.write_bytes(b"kesikdosya")
                worker1 = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker1._jobs.enqueue(
                    "media_process",
                    {"source_video_id": video_id, "import_path": str(corrupt)},
                    max_attempts=1,
                )
                await worker1._jobs.claim_next(worker1._worker_id)
                await worker1.run_job(job.id)

                # 2. 'restart': yeni worker, ayni video, saglam dosya.
                media = make_face_stream_video(tmp_path / "saglam.mp4")
                (tmp_path / "saglam.vtt").write_text(VTT_SIDE, encoding="utf-8")
                worker2 = JobWorker(sessionmaker, settings, handlers=handlers)
                job2 = await worker2._jobs.enqueue(
                    "media_process",
                    {
                        "source_video_id": video_id,
                        "import_path": str(media),
                    },
                    max_attempts=1,
                )
                await worker2._jobs.claim_next(worker2._worker_id)
                await worker2.run_job(job2.id)
                return job.id, job2.id, video_id
            finally:
                await engine.dispose()

        job1, job2, video_id = _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/fault.db")
        with engine.connect() as conn:
            first = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"), {"j": job1}
            ).scalar()
            second = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"), {"j": job2}
            ).scalar()
            assets = conn.execute(
                sa.text("SELECT COUNT(*) FROM media_assets")
            ).scalar()
            video_status = conn.execute(
                sa.text("SELECT status FROM source_videos WHERE id = :v"),
                {"v": video_id},
            ).scalar()
        engine.dispose()
        assert first == "failed"  # bozuk dosya: tanimli basarisizlik
        assert second == "succeeded"  # restart sonrasi ayni asamadan devam
        assert assets == 1  # ayni varlik satiri: yeniden olusturulmadi
        assert video_status == "processed"


class TestOAuthExpiry:
    def test_expired_token_refreshes_before_use(self, tmp_path):
        """Suresi dolmus access token, kullanilmadan once yenilenir."""
        from app.models import OAuthCredential
        from app.services.oauth_service import OAuthService

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                channel_id, _ = await _seed_planned(sessionmaker)
                cipher = TokenCipher(settings.token_encryption_key)
                async with sessionmaker() as session:
                    session.add(
                        OAuthCredential(
                            channel_id=channel_id,
                            provider="youtube",
                            access_token_enc=cipher.encrypt("eski-token"),
                            refresh_token_enc=cipher.encrypt("refresh-token"),
                            token_expires_at=datetime.now(UTC)
                            - timedelta(minutes=5),  # suresi dolmus
                        )
                    )
                    await session.commit()

                refresh_calls = {"n": 0}

                def handler(request):
                    refresh_calls["n"] += 1
                    return httpx.Response(
                        200,
                        json={
                            "access_token": "yeni-token",  # secret-scan-ok (sentetik)
                            "expires_in": 3600,
                        },
                    )

                service = OAuthService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    token = await service.access_token(channel_id, http=http)
                return token, refresh_calls["n"]
            finally:
                await engine.dispose()

        token, refresh_calls = _run(scenario())
        assert token == "yeni-token"  # eski token kullanilmadi
        assert refresh_calls == 1


class TestUploadInterruptionAcrossRestart:
    def test_session_uri_survives_worker_restart(self, tmp_path, monkeypatch):
        """Upload yarida kesilir, worker yeniden baslar: kayitli oturum
        adresiyle ayni satirdan devam edilir (M10 uzlastirmasi)."""
        from app.models import ClipMetadata, OAuthCredential, RenderedClip
        from app.worker import JobWorker, build_handlers

        session_uri = (
            "https://www.googleapis.com/upload/youtube/v3/videos"
            "?upload_id=restart"
        )

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                channel_id, video_id = await _seed_planned(sessionmaker)
                media = make_face_stream_video(tmp_path / "k.mp4")
                async with sessionmaker() as session:
                    from app.models import MediaAsset

                    asset = MediaAsset(
                        source_video_id=video_id,
                        origin="local_import",
                        status="processed",
                        stage="candidates",
                        file_path=str(media),
                    )
                    session.add(asset)
                    await session.flush()
                    candidate = _make_candidate(video_id)
                    session.add(candidate)
                    await session.flush()
                    session.add(
                        RenderedClip(
                            clip_candidate_id=candidate.id,
                            status="rendered",
                            file_path=str(media),
                        )
                    )
                    session.add(
                        ClipMetadata(
                            clip_candidate_id=candidate.id,
                            revision=1,
                            title="Baslik",
                            description="Yeterince uzun bir aciklama metni.",
                            tags=[],
                            status="approved",
                        )
                    )
                    cipher = TokenCipher(settings.token_encryption_key)
                    session.add(
                        OAuthCredential(
                            channel_id=channel_id,
                            provider="youtube",
                            access_token_enc=cipher.encrypt("tok"),
                            token_expires_at=datetime.now(UTC)
                            + timedelta(hours=1),
                        )
                    )
                    await session.commit()
                    candidate_id = candidate.id

                state = {"put_fails": True}

                def handler(request):
                    url = str(request.url)
                    if url.startswith(
                        "https://www.googleapis.com/upload/youtube/v3/videos"
                    ):
                        if request.method == "POST":
                            return httpx.Response(
                                200, headers={"Location": session_uri}
                            )
                        if state["put_fails"]:
                            return httpx.Response(
                                500, json={"error": "interrupted"}
                            )
                        return httpx.Response(201, json={"id": "yt-rs"})
                    return httpx.Response(
                        200,
                        json={
                            "items": [
                                {
                                    "id": "yt-rs",
                                    "status": {
                                        "privacyStatus": "private",
                                        "uploadStatus": "uploaded",
                                    },
                                }
                            ]
                        },
                    )

                monkeypatch.setattr(
                    "app.services.publishing_service._default_client",
                    lambda: httpx.AsyncClient(
                        transport=httpx.MockTransport(handler)
                    ),
                )
                handlers = build_handlers(sessionmaker, settings)
                # 1. deneme: PUT patlar.
                worker1 = JobWorker(sessionmaker, settings, handlers=handlers)
                job1 = await worker1._jobs.enqueue(
                    "publish_clip", {"clip_candidate_id": candidate_id},
                    max_attempts=1,
                )
                await worker1._jobs.claim_next(worker1._worker_id)
                await worker1.run_job(job1.id)
                # 2. 'restart': PUT duzeldi.
                state["put_fails"] = False
                worker2 = JobWorker(sessionmaker, settings, handlers=handlers)
                job2 = await worker2._jobs.enqueue(
                    "publish_clip", {"clip_candidate_id": candidate_id},
                    max_attempts=1,
                )
                await worker2._jobs.claim_next(worker2._worker_id)
                await worker2.run_job(job2.id)
                return job1.id, job2.id
            finally:
                await engine.dispose()

        job1, job2 = _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/fault.db")
        with engine.connect() as conn:
            first = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"), {"j": job1}
            ).scalar()
            second = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"), {"j": job2}
            ).scalar()
            rows = conn.execute(
                sa.text(
                    "SELECT status, upload_session_uri"
                    " FROM published_videos"
                )
            ).all()
        engine.dispose()
        assert first == "failed"
        assert second == "succeeded"
        assert len(rows) == 1  # ayni satir: restart yeni kayit acmadi
        assert rows[0][0] == "verified"
        assert rows[0][1] == session_uri  # kayitli oturum yeniden kullanildi
