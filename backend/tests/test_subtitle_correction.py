"""subtitle_correction: LLM chain, timestamp preservation, idempotency.

The provider chain runs against an injected MockTransport (OpenAI
shape); the service contract (count/index validation, verbatim
timestamps, original transcript untouched) is verified on sqlite.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import sqlalchemy as sa
from cryptography.fernet import Fernet

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    CorrectedTranscript,
    MediaAsset,
    SourceChannel,
    SourceVideo,
    Transcript,
)
from app.schemas_llm import LlmProviderCreate
from app.services.llm_service import LlmProviderService
from app.services.subtitle_correction import (
    SubtitleCorrectionError,
    SubtitleCorrectionService,
)

ORIGINAL_SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "bugun size cok onemli bir konu anlatacagim"},
    {"start": 2.0, "end": 4.5, "text": "bu konu cok ilginc arkadaslar"},
    {"start": 4.5, "end": 7.0, "text": "herkes izlemeli bence"},
]

CORRECTED_RESPONSE = {
    "segments": [
        {
            "index": 0,
            "text": "Bugün size çok önemli bir konu anlatacağım.",
            "uncertain": False,
        },
        {
            "index": 1,
            "text": "Bu konu çok ilginç, arkadaşlar.",
            "uncertain": False,
        },
        {
            "index": 2,
            "text": "Herkes izlemeli bence.",
            "uncertain": True,
        },
    ]
}


def _openai_body(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def _env(tmp_path):
    db_path = tmp_path / "m9.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        token_encryption_key=Fernet.generate_key().decode(),
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine, str(db_path)


async def _seed(sessionmaker) -> tuple[int, int]:
    """Kanal -> kaynak -> video -> asset + transkript; (channel, asset)."""
    async with sessionmaker() as session:
        channel = Channel(name="Kanal")
        session.add(channel)
        await session.flush()
        from app.models import PublishingProfile

        # Start/Stop donemi: icerik beslemesi yalnizca calisan kanalda.
        session.add(
            PublishingProfile(
                channel_id=channel.id, automation_state="running"
            )
        )
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id="UCkaynak",
            title="Kaynak",
            permission_status="authorized",
        )
        session.add(source)
        await session.flush()
        video = SourceVideo(
            source_channel_id=source.id,
            youtube_video_id="vid-1",
            title="Video",
            status="processed",
        )
        session.add(video)
        await session.flush()
        asset = MediaAsset(
            source_video_id=video.id,
            origin="local_import",
            status="processed",
            stage="candidates",
            file_path="/x.mp4",
        )
        session.add(asset)
        await session.flush()
        session.add(
            Transcript(
                media_asset_id=asset.id,
                source="sidecar",
                segment_count=len(ORIGINAL_SEGMENTS),
                segments=ORIGINAL_SEGMENTS,
            )
        )
        await session.commit()
        return channel.id, asset.id


def _llm(sessionmaker, settings):
    return LlmProviderService(sessionmaker, settings)


async def _add_provider(sessionmaker, settings):
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


def _run(coro):
    return asyncio.run(coro)


class TestSubtitleCorrection:
    def test_correction_preserves_timestamps_and_flags(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                channel_id, asset_id = await _seed(sessionmaker)
                llm = _llm(sessionmaker, settings)
                service = SubtitleCorrectionService(sessionmaker, llm)

                async def handler(request):
                    return httpx.Response(200, json=_openai_body(CORRECTED_RESPONSE))

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    result = await service.correct_transcript(asset_id, http=http)
                return result, channel_id, asset_id
            finally:
                await engine.dispose()

        result, channel_id, asset_id = _run(scenario())
        assert result["segments"] == 3
        assert result["corrected"] == 3  # ucuncu satir buyuk harf + nokta aldi
        assert result["flagged"] == 1

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9.db")
        with engine.connect() as conn:
            corrected_row = conn.execute(
                sa.text("SELECT segments FROM corrected_transcripts")
            ).one()
            original_row = conn.execute(
                sa.text("SELECT segments FROM transcripts")
            ).one()
            events = conn.execute(
                sa.text("SELECT event_type FROM audit_events")
            ).scalars().all()
        engine.dispose()

        import json as _json

        segments = _json.loads(corrected_row[0])
        originals = _json.loads(original_row[0])
        # Kabul kriteri: zaman damgalari sessizce degismez — birebir kopya.
        for original_seg, corrected_seg in zip(originals, segments):
            assert corrected_seg["start"] == original_seg["start"]
            assert corrected_seg["end"] == original_seg["end"]
        assert segments[0]["text"].startswith("Bugün")
        assert segments[2]["uncertain"] is True
        # Orijinal transkript degismedi (kabul kriteri: geri kazanilabilir).
        assert originals[0]["text"] == ORIGINAL_SEGMENTS[0]["text"]
        assert "subtitle.corrected" in events

    def test_idempotent_rerun(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, asset_id = await _seed(sessionmaker)
                service = SubtitleCorrectionService(
                    sessionmaker, LlmProviderService(sessionmaker, settings)
                )

                async def handler(request):
                    return httpx.Response(200, json=_openai_body(CORRECTED_RESPONSE))

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    first = await service.correct_transcript(asset_id, http=http)
                    second = await service.correct_transcript(asset_id, http=http)
                return first, second
            finally:
                await engine.dispose()

        first, second = _run(scenario())
        assert "skipped" not in first
        assert second.get("skipped") is True

    def test_wrong_count_rejected_no_row(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _add_provider(sessionmaker, settings)
                _, asset_id = await _seed(sessionmaker)
                service = SubtitleCorrectionService(
                    sessionmaker, LlmProviderService(sessionmaker, settings)
                )
                broken = {"segments": CORRECTED_RESPONSE["segments"][:2]}

                async def handler(request):
                    return httpx.Response(200, json=_openai_body(broken))

                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as http:
                    try:
                        await service.correct_transcript(asset_id, http=http)
                        error = None
                    except SubtitleCorrectionError as exc:
                        error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None and "sayisi" in error
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9.db")
        with engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM corrected_transcripts")
            ).scalar()
        engine.dispose()
        assert count == 0  # gecersiz yanit hicbir sey kaydetmez

    def test_missing_transcript_errors(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                service = SubtitleCorrectionService(
                    sessionmaker, LlmProviderService(sessionmaker, settings)
                )
                try:
                    await service.correct_transcript(999999)
                    error = None
                except SubtitleCorrectionError as exc:
                    error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None  # varlik yok: tanimli hata yolu

    def test_worker_job_fails_cleanly_without_provider(self, tmp_path):
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, asset_id = await _seed(sessionmaker)
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "subtitle_correct",
                    {"media_asset_id": asset_id},
                    max_attempts=1,
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id
            finally:
                await engine.dispose()

        job_id = _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9.db")
        with engine.connect() as conn:
            status = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"), {"j": job_id}
            ).scalar()
            error = conn.execute(
                sa.text("SELECT last_error FROM jobs WHERE id = :j"), {"j": job_id}
            ).scalar()
        engine.dispose()
        # Saglayici hic yok: is tanimli sekilde basarisiz, mesaj kayitli.
        assert status == "failed"
        assert error is not None

    def test_worker_resolves_db_stored_cipher_key(self, tmp_path, monkeypatch):
        """TOKEN_ENCRYPTION_KEY yalnizca Ayarlar ekranindan (DB) girildiyse
        worker'in LLM cagrisi cipher'i efektif ayarlardan cozmeli; ham env
        ayarina bakmak zinciri 'anahtar yok' hatasiyla dusurur."""
        from app.schemas_settings import SettingsUpdate
        from app.services.settings_service import SettingsService
        from app.worker import JobWorker, build_handlers

        key = Fernet.generate_key().decode()

        async def handler(request):
            return httpx.Response(200, json=_openai_body(CORRECTED_RESPONSE))

        async def scenario():
            # Ortamda anahtar yok; yalnizca site ayari olarak DB'ye girilir.
            db_path = tmp_path / "m9db-key.db"
            sync_engine = sa.create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(sync_engine)
            sync_engine.dispose()
            settings = Settings(database_url=f"sqlite+aiosqlite:///{db_path}")
            engine, sessionmaker = create_engine_and_sessionmaker(
                settings.database_url
            )
            try:
                service = SettingsService(sessionmaker, settings)
                await service.update(
                    SettingsUpdate(token_encryption_key=key)
                )
                effective = await service.effective_settings()
                assert effective.token_encryption_key == key
                await _add_provider(sessionmaker, effective)
                _, asset_id = await _seed(sessionmaker)
                monkeypatch.setattr(
                    "app.services.llm_service._default_http_client",
                    lambda: httpx.AsyncClient(
                        transport=httpx.MockTransport(handler)
                    ),
                )
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                job = await worker._jobs.enqueue(
                    "subtitle_correct",
                    {"media_asset_id": asset_id},
                    max_attempts=1,
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id
            finally:
                await engine.dispose()

        job_id = _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m9db-key.db")
        with engine.connect() as conn:
            status = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"), {"j": job_id}
            ).scalar()
            corrected = conn.execute(
                sa.text("SELECT COUNT(*) FROM corrected_transcripts")
            ).scalar()
        engine.dispose()
        # Anahtar DB'de olsa da worker LLM zinciri calismali.
        assert status == "succeeded"
        assert corrected == 1

    def test_worker_feed_enqueues_uncorrected_assets(self, tmp_path):
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, asset_id = await _seed(sessionmaker)
                worker = JobWorker(sessionmaker, settings)
                added = await worker.enqueue_content_jobs()
                added_again = await worker.enqueue_content_jobs()
                jobs = await worker._jobs.list_jobs()
                return added, added_again, [
                    (j.job_type, j.payload) for j in jobs
                ]
            finally:
                await engine.dispose()

        added, added_again, jobs = _run(scenario())
        assert added == 1
        assert added_again == 0
        assert jobs == [("subtitle_correct", {"media_asset_id": 1})]
