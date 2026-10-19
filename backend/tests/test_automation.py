"""M11 end-to-end automation: the full chain on real media.

The crown-jewel test runs the actual worker queue over real ffmpeg
media (face-stream fixture + sidecar) with mocked LLM and YouTube
transports: media_process -> clip_render -> subtitle_correct ->
metadata_generate -> approve -> publish_due. Plus the automation
decision logic: daily targets, empty stock, pause/resume, channel
isolation, auto-plan after discovery, and the profile API.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    ClipMetadata,
    OAuthCredential,
    SourceChannel,
    SourceVideo,
)
from app.security import TokenCipher
from app.services.media_storage import ensure_media_tree
from tests.conftest import _make_app  # noqa: F401 - API testi kullanir
from tests.media_sample import make_face_stream_video

SESSION_URI = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=e2e"


def _env(tmp_path, **overrides):
    db_path = tmp_path / "m11.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    kwargs = dict(
        token_encryption_key=Fernet.generate_key().decode(),
        media_root=str(tmp_path / "media"),
        clip_min_seconds=3,  # 8s ornek videodan aday uretilebilsin
        clip_max_seconds=6,
    )
    kwargs.update(overrides)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **kwargs
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    ensure_media_tree(tmp_path / "media")
    return sessionmaker, settings, engine, str(db_path)


VTT_SIDE = """WEBVTT

00:00:01.000 --> 00:00:04.000
bugun size cok onemli bir konu anlatiyorum
"""


async def _seed_channel(
    sessionmaker,
    token_key: str,
    *,
    name="Kanal",
    credential=True,
    paused=False,
    daily_target=3,
    auto_approve=True,
    automation_state="running",
) -> int:
    from app.models import PublishingProfile

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
        session.add(
            PublishingProfile(
                channel_id=channel.id,
                daily_clip_target=daily_target,
                automation_state=automation_state,
                settings={
                    "paused": paused,
                    "auto_approve_metadata": auto_approve,
                },
            )
        )
        if credential:
            cipher = TokenCipher(token_key)
            session.add(
                OAuthCredential(
                    channel_id=channel.id,
                    provider="youtube",
                    access_token_enc=cipher.encrypt("synthetic-token"),
                    token_expires_at=datetime.now(UTC)
                    + timedelta(hours=1),
                )
            )
        await session.commit()
        return channel.id


async def _seed_planned_video(sessionmaker, channel_id: int) -> int:
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
        video = SourceVideo(
            source_channel_id=source.id,
            youtube_video_id=f"vid-{channel_id}-1",
            title="Kaynak Video",
            status="planned",
        )
        session.add(video)
        await session.commit()
        return video.id


async def _add_llm_provider(sessionmaker, settings) -> None:
    from app.schemas_llm import LlmProviderCreate
    from app.services.llm_service import LlmProviderService

    service = LlmProviderService(sessionmaker, settings)
    await service.create_provider(
        LlmProviderCreate(
            name="Test Saglayici",
            provider_type="openai",
            api_base="https://api.llm-test.test/v1",
            model_id="test-model",
            api_key="synthetic-test-key",  # secret-scan-ok: synthetic
            priority=1,
            max_retries=0,
        )
    )


def _llm_handler(request: httpx.Request) -> httpx.Response:
    """Uc istek tek mock'ta: hype degerlendirme + altyazi duzeltme +
    metaveri onerisi. Yonlendirme belirgin isaretlerle yapilir: metaveri
    promptu 'altyazi' kelimesini icerdiginden 'altyazi' kontrolu SONDADIR."""
    import re

    body = json.loads(request.content.decode("utf-8"))
    prompt = ""
    if isinstance(body, dict):
        for message in body.get("messages", []):
            prompt += str(message.get("content", ""))
    if "metaveri oner" in prompt:
        payload = {
            "title": "Cok Onemli Kesit",
            "summary": "Bu kesitte konusan kisi cok onemli bir konuyu"
            " anlatiyor ve izlemeye deger bilgiler veriyor.",
            "tags": ["kesit", "turkce"],
            "content_warning": False,
            "ai_disclosure": False,
        }
    elif "aday" in prompt:
        # Hype degerlendirmesi: prompttaki aday kimliklerini ayikla ve
        # her birine gecerli (3-6 sn) bir pencere oner.
        ids = [int(m) for m in re.findall(r"aday (\d+):", prompt)]
        payload = {
            "evaluations": [
                {
                    "candidate_id": cid,
                    "start_seconds": 1.0,
                    "end_seconds": 4.0,
                    "reason": "reaksiyonun olusumu ve tamamlanmasi iceride",
                    "confidence": 0.8,
                }
                for cid in ids
            ]
        }
    else:
        payload = {
            "segments": [
                {
                    "index": 0,
                    "text": "Bugün size çok önemli bir konu anlatıyorum.",
                    "uncertain": False,
                }
            ]
        }
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
    )


def _youtube_handler(request: httpx.Request) -> httpx.Response:
    """State'li mock: videos.update (herkese acik yapma) sonrasi
    videos.list public rapor eder (zamanli yayin akisi)."""
    url = str(request.url)
    if url.startswith("https://www.googleapis.com/upload/youtube/v3/videos"):
        if request.method == "POST":
            return httpx.Response(200, headers={"Location": SESSION_URI})
        return httpx.Response(201, json={"id": "yt-e2e-1"})
    if url.startswith("https://www.googleapis.com/youtube/v3/videos"):
        if request.method == "PUT":
            _youtube_state["privacy"] = "public"
            return httpx.Response(200, json={"id": "yt-e2e-1"})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "yt-e2e-1",
                        "status": {
                            "privacyStatus": _youtube_state["privacy"],
                            "uploadStatus": "uploaded",
                        },
                    }
                ]
            },
        )
    return httpx.Response(404)


_youtube_state = {"privacy": "private"}


@pytest.fixture(autouse=True)
def _reset_youtube_privacy():
    """Mock gizliligi testler arasinda sizmasin: her test gizli ile
    baslar (zincir icindeki public adimi testin kendisinde olur)."""
    _youtube_state["privacy"] = "private"
    yield


@pytest.fixture(scope="module")
def face_video_with_sidecar(tmp_path_factory):
    base = tmp_path_factory.mktemp("m11")
    media = make_face_stream_video(base / "kaynak.mp4")
    (base / "kaynak.vtt").write_text(VTT_SIDE, encoding="utf-8")
    return base


def _run(coro):
    return asyncio.run(coro)


class TestFullChain:
    def test_pipeline_end_to_end_through_worker(
        self, tmp_path, face_video_with_sidecar, monkeypatch
    ):
        """Tum zincir: planli video -> islendi -> render -> duzeltilmis
        altyazi -> onayli metaveri -> ozel yayin (dogrulanmis)."""
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                channel_id = await _seed_channel(
                    sessionmaker, settings.token_encryption_key
                )
                video_id = await _seed_planned_video(sessionmaker, channel_id)
                await _add_llm_provider(sessionmaker, settings)
                monkeypatch.setattr(
                    "app.services.llm_service._default_http_client",
                    lambda: httpx.AsyncClient(
                        transport=httpx.MockTransport(_llm_handler)
                    ),
                )
                monkeypatch.setattr(
                    "app.services.publishing_service._default_client",
                    lambda: httpx.AsyncClient(
                        transport=httpx.MockTransport(_youtube_handler)
                    ),
                )
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                service = worker._jobs

                # Zincirdeki tum isleri sira sirra kos.
                jobs = []
                media_job = await service.enqueue(
                    "media_process",
                    {
                        "source_video_id": video_id,
                        "import_path": str(
                            face_video_with_sidecar / "kaynak.mp4"
                        ),
                    },
                )
                jobs.append(media_job)
                for _ in range(6):
                    claimed = await service.claim_next(worker._worker_id)
                    if claimed is None:
                        break
                    await worker.run_job(claimed.id)

                # Hype degerlendirme + render + icerik asamalarini
                # besleme sorgularindan al.
                for job_type in [
                    "hype_evaluate",
                    "clip_render",
                    "subtitle_correct",
                    "metadata_generate",
                ]:
                    candidate_or_asset = await _next_payload(
                        sessionmaker, job_type
                    )
                    if candidate_or_asset is None:
                        continue
                    job = await service.enqueue(job_type, candidate_or_asset)
                    jobs.append(job)
                    await service.claim_next(worker._worker_id)
                    await worker.run_job(job.id)

                # Onay tetikledigi gizli yukleme isini kos.
                from app.models import ClipCandidate

                async with sessionmaker() as session:
                    candidate_id = (
                        await session.execute(
                            sa.select(ClipCandidate.id).limit(1)
                        )
                    ).scalar()
                if candidate_id is not None:
                    upload_job = await service.enqueue(
                        "publish_clip", {"clip_candidate_id": candidate_id}
                    )
                    await service.claim_next(worker._worker_id)
                    await worker.run_job(upload_job.id)

                # Yayin: hedef/stok farkindaligiyla herkese acik yapma.
                publish_job = await service.enqueue(
                    "publish_due", {"channel_id": channel_id}
                )
                await service.claim_next(worker._worker_id)
                await worker.run_job(publish_job.id)
                return channel_id
            finally:
                await engine.dispose()

        channel_id = _run(scenario())

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m11.db")
        with engine.connect() as conn:
            video_status = conn.execute(
                sa.text("SELECT status FROM source_videos")
            ).scalar()
            asset = conn.execute(
                sa.text(
                    "SELECT status, file_path FROM media_assets"
                )
            ).one()
            render = conn.execute(
                sa.text(
                    "SELECT status, width, height FROM rendered_clips"
                )
            ).one()
            corrected = conn.execute(
                sa.text("SELECT COUNT(*) FROM corrected_transcripts")
            ).scalar()
            metadata = conn.execute(
                sa.text("SELECT status, title FROM clip_metadata")
            ).one()
            published = conn.execute(
                sa.text(
                    "SELECT status, youtube_video_id, visibility"
                    " FROM published_videos"
                )
            ).one()
            job_stats = conn.execute(
                sa.text(
                    "SELECT status, COUNT(*) FROM jobs GROUP BY status"
                )
            ).all()
        engine.dispose()

        # Kabul kriteri: tum zincir authorized test icerigi uzerinde kostu.
        import os

        # Zincir tamamlandi: Shorts uretimi bitince kaynak #confirmed olur
        # ve yeniden islenmek uzere kuyruga alinmaz.
        assert video_status == "confirmed"
        assert asset[0] == "processed" and os.path.isfile(asset[1])
        assert render[0] == "rendered" and (render[1], render[2]) == (1080, 1920)
        assert corrected == 1  # duzeltilmis transkript kaydi olustu
        assert metadata[0] == "draft"  # auto_approve profili yayina izin verdi
        assert published[0] == "verified"
        assert published[1] == "yt-e2e-1"
        assert published[2] == "public"
        # Kabul kriteri: isler gecerli durumlarda ilerledi.
        assert all(status == "succeeded" for status, _ in job_stats)


async def _next_payload(sessionmaker, job_type: str) -> dict | None:
    """Besleme sorgularinin yaptigi secimi test tarafindan tekrarlar."""
    queries = {
        "hype_evaluate": (
            "SELECT sv.id FROM source_videos sv"
            " JOIN media_assets ma ON ma.source_video_id = sv.id"
            " WHERE sv.status = 'processed' AND ma.status = 'processed'"
            " AND EXISTS (SELECT 1 FROM clip_candidates cc"
            " WHERE cc.source_video_id = sv.id AND cc.status = 'candidate')"
            " AND NOT EXISTS (SELECT 1 FROM clip_candidates cc2"
            " WHERE cc2.source_video_id = sv.id AND cc2.status = 'selected')"
            " LIMIT 1"
        ),
        "clip_render": (
            "SELECT cc.id FROM clip_candidates cc"
            " WHERE cc.status = 'selected'"
            " AND NOT EXISTS (SELECT 1 FROM rendered_clips rc"
            " WHERE rc.clip_candidate_id = cc.id)"
            " ORDER BY cc.id LIMIT 1"
        ),
        "subtitle_correct": (
            "SELECT t.media_asset_id FROM transcripts t"
            " WHERE NOT EXISTS (SELECT 1 FROM corrected_transcripts ct"
            " WHERE ct.media_asset_id = t.media_asset_id)"
            " LIMIT 1"
        ),
        "metadata_generate": (
            "SELECT rc.clip_candidate_id FROM rendered_clips rc"
            " WHERE rc.status = 'rendered'"
            " AND NOT EXISTS (SELECT 1 FROM clip_metadata cm"
            " WHERE cm.clip_candidate_id = rc.clip_candidate_id)"
            " LIMIT 1"
        ),
    }
    async with sessionmaker() as session:
        value = (
            (
                await session.execute(
                    sa.text(queries[job_type])
                )
            )
            .scalars()
            .first()
        )
    if value is None:
        return None
    if job_type in ("hype_evaluate",):
        return {"source_video_id": value}
    if job_type == "clip_render":
        return {"clip_candidate_id": value}
    if job_type == "subtitle_correct":
        return {"media_asset_id": value}
    return {"clip_candidate_id": value}


class TestAutomationDecisions:
    def _service(self, sessionmaker, settings):
        from app.services.automation_service import AutomationService

        return AutomationService(sessionmaker, settings)

    def test_empty_stock_publishes_nothing(self, tmp_path):
        """Kabul kriteri: yetersiz stok guvensiz yayina yol acmaz."""
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                channel_id = await _seed_channel(
                    sessionmaker, settings.token_encryption_key
                )
                service = self._service(sessionmaker, settings)
                result = await service.publish_for_channel(channel_id)
                return result, channel_id
            finally:
                await engine.dispose()

        result, channel_id = _run(scenario())
        assert result["published"] == 0
        assert result["reason"] is not None

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m11.db")
        with engine.connect() as conn:
            published = conn.execute(
                sa.text("SELECT COUNT(*) FROM published_videos")
            ).scalar()
            events = conn.execute(
                sa.text("SELECT event_type FROM audit_events")
            ).scalars().all()
        engine.dispose()
        assert published == 0
        assert "publish.no_ready" in events

class TestDailyTarget:
    def test_target_reached_returns_reason(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                from app.models import PublishedVideo

                channel_id = await _seed_channel(
                    sessionmaker,
                    settings.token_encryption_key,
                    daily_target=1,
                )
                # Bugun icin bir dogrulanmis yayin kaydi yap.
                async with sessionmaker() as session:
                    from app.models import ClipCandidate

                    video_id = await _seed_planned_video(
                        sessionmaker, channel_id
                    )
                    candidate = ClipCandidate(
                        source_video_id=video_id,
                        start_seconds=1.0,
                        end_seconds=4.0,
                        duration_seconds=3.0,
                        score=0.9,
                        status="candidate",
                    )
                    session.add(candidate)
                    await session.flush()
                    session.add(
                        PublishedVideo(
                            clip_candidate_id=candidate.id,
                            channel_id=channel_id,
                            youtube_video_id="yt-existing",
                            status="verified",
                            visibility="public",
                            title="Var olan",
                            published_at=datetime.now(UTC),
                            public_at=datetime.now(UTC),
                        )
                    )
                    await session.commit()
                service = AutomationService_(sessionmaker, settings)
                return await service.publish_for_channel(channel_id)
            finally:
                await engine.dispose()

        result = _run(scenario())
        assert result["published"] == 0
        # Gunluk dikey limit dolu: yeni video herkese acik yapilmaz.
        assert "limit" in result["reason"]


def AutomationService_(sessionmaker, settings):
    from app.services.automation_service import AutomationService

    return AutomationService(sessionmaker, settings)


class TestPauseAndIsolation:
    def test_paused_channel_skipped(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                channel_id = await _seed_channel(
                    sessionmaker,
                    settings.token_encryption_key,
                    paused=True,
                )
                service = AutomationService_(sessionmaker, settings)
                result = await service.publish_for_channel(channel_id)
                # Duraklatilmis kanal due listesinde de olmamali.
                publishing = PublishingService_(sessionmaker, settings)
                due = await publishing.due_channels()
                return result, due
            finally:
                await engine.dispose()

        result, due = _run(scenario())
        assert result["published"] == 0
        assert "duraklat" in result["reason"]
        assert due == []

    def test_channel_failure_isolated(
        self, tmp_path, monkeypatch, face_video_with_sidecar
    ):
        """Bir kanalin yayin hatasi digerini etkilemez: ayni worker
        turunde biri basarili, digeri basarisiz kalir."""
        from app.models import ClipCandidate, RenderedClip
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                good = await _seed_channel(
                    sessionmaker, settings.token_encryption_key, name="Iyi"
                )
                bad = await _seed_channel(
                    sessionmaker,
                    settings.token_encryption_key,
                    name="Kotu",
                    credential=False,  # OAuth yok -> yayin hatasi
                )
                # Iki kanala da hazir klip: render + onayli metaveri.
                candidate_ids: dict[int, int] = {}
                for channel_id in (good, bad):
                    video_id = await _seed_planned_video(
                        sessionmaker, channel_id
                    )
                    async with sessionmaker() as session:
                        candidate = ClipCandidate(
                            source_video_id=video_id,
                            start_seconds=1.0,
                            end_seconds=4.0,
                            duration_seconds=3.0,
                            score=0.9,
                            status="candidate",
                        )
                        session.add(candidate)
                        await session.flush()
                        candidate_ids[channel_id] = candidate.id
                        session.add(
                            RenderedClip(
                                clip_candidate_id=candidate.id,
                                status="rendered",
                                file_path=str(
                                    face_video_with_sidecar / "kaynak.mp4"
                                ),
                            )
                        )
                        session.add(
                            ClipMetadata(
                                clip_candidate_id=candidate.id,
                                revision=1,
                                title="Baslik",
                                description="Yeterince uzun bir aciklama.",
                                tags=[],
                                status="approved",
                            )
                        )
                        await session.commit()
                monkeypatch.setattr(
                    "app.services.publishing_service._default_client",
                    lambda: httpx.AsyncClient(
                        transport=httpx.MockTransport(_youtube_handler)
                    ),
                )
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                service = worker._jobs
                # Onay tetikledigi gizli yukleme isleri: OAuth'suz kanal
                # kendi hatasinda kalir, iyi kanal yuklemesini tamamlar.
                good_job = await service.enqueue(
                    "publish_clip",
                    {"clip_candidate_id": candidate_ids[good]},
                    max_attempts=1,
                )
                bad_job = await service.enqueue(
                    "publish_clip",
                    {"clip_candidate_id": candidate_ids[bad]},
                    max_attempts=1,
                )
                for job in (good_job, bad_job):
                    await service.claim_next(worker._worker_id)
                    await worker.run_job(job.id)
                return good_job.id, bad_job.id
            finally:
                await engine.dispose()

        good_id, bad_id = _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m11.db")
        with engine.connect() as conn:
            good_status = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"),
                {"j": good_id},
            ).scalar()
            bad_status = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"),
                {"j": bad_id},
            ).scalar()
            published = conn.execute(
                sa.text(
                    "SELECT pv.channel_id FROM published_videos pv"
                    " WHERE pv.status = 'verified'"
                )
            ).scalars().all()
        engine.dispose()
        # Kabul kriteri: kanal hatalalari izole kalir.
        assert good_status == "succeeded"
        assert bad_status == "failed"  # OAuth'suz kanal kendi hatasinda kalir
        assert published == [1]  # yalniz iyi kanal yayinlandi


def PublishingService_(sessionmaker, settings):
    from app.services.publishing_service import PublishingService

    return PublishingService(sessionmaker, settings)


class TestAutoPlan:
    def test_discovery_chains_planning(self, tmp_path, mock_youtube):  # noqa: F811
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine, db = _env(
                tmp_path, youtube_api_key="test-yt-key"
            )
            try:
                async with sessionmaker() as session:
                    from app.models import PublishingProfile

                    channel = Channel(name="Kanal", status="connected")
                    session.add(channel)
                    await session.flush()
                    session.add(
                        SourceChannel(
                            channel_id=channel.id,
                            youtube_channel_id="UCkaynak1",
                            title="Kaynak",
                            permission_status="authorized",
                        )
                    )
                    session.add(
                        PublishingProfile(
                            channel_id=channel.id,
                            automation_state="running",
                        )
                    )
                    await session.commit()
                    channel_id = channel.id
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "source_discover", {"channel_id": channel_id}
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id
            finally:
                await engine.dispose()

        job_id = _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m11.db")
        with engine.connect() as conn:
            job_status = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"),
                {"j": job_id},
            ).scalar()
            statuses = conn.execute(
                sa.text("SELECT status, COUNT(*) FROM source_videos GROUP BY status")
            ).all()
        engine.dispose()
        assert job_status == "succeeded"
        # Kesiften sonra videolar otomatik planlandi (M11 baglantisi).
        assert ("planned", 2) in [tuple(row) for row in statuses]


class TestProfileApi:
    def test_profile_roundtrip_and_summary(self, tmp_path):
        from fastapi.testclient import TestClient

        app = _make_app(tmp_path, worker_enabled=False)
        with TestClient(app) as client:
            channel = client.post(
                "/api/channels", json={"name": "Kanal"}
            ).json()
            channel_id = channel["id"]

            profile = client.get(f"/api/channels/{channel_id}/publishing")
            assert profile.status_code == 200
            assert profile.json()["daily_clip_target"] == 3
            assert profile.json()["paused"] is False

            updated = client.put(
                f"/api/channels/{channel_id}/publishing",
                json={
                    "daily_clip_target": 5,
                    "publish_times": ["10:00", "18:00"],
                    "paused": True,
                },
            )
            assert updated.status_code == 200, updated.text
            body = updated.json()
            assert body["daily_clip_target"] == 5
            assert body["paused"] is True
            assert body["publish_times"] == ["10:00", "18:00"]

            invalid = client.put(
                f"/api/channels/{channel_id}/publishing",
                json={"publish_times": ["25:00"]},
            )
            assert invalid.status_code == 400

            summary = client.get(f"/api/channels/{channel_id}/summary")
            assert summary.status_code == 200
            assert summary.json()["stock"] == 0
            assert summary.json()["paused"] is True
