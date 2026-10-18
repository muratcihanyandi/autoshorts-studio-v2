"""publishing: schedule planning, guards, upload flow, reconciliation.

The YouTube upload protocol runs against a faithful MockTransport
(resumable session open -> PUT bytes -> videos.list verification);
OAuth credentials are seeded encrypted with a real Fernet key. Guard
behavior (rights, render, approval, duplicates) is verified on sqlite.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

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
    ClipCandidate,
    ClipMetadata,
    MediaAsset,
    OAuthCredential,
    PublishingProfile,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.security import TokenCipher
from app.services.publishing_schedule import (
    ScheduleError,
    is_due,
    next_due_time,
    parse_publish_times,
)
from tests.conftest import _make_app

SESSION_URI = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc123"


def _env(tmp_path, **overrides):
    db_path = tmp_path / "m10.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    kwargs = dict(token_encryption_key=Fernet.generate_key().decode())
    kwargs.update(overrides)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **kwargs
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine, str(db_path)


async def _seed(
    sessionmaker,
    token_key: str,
    tmp_path=None,
    *,
    source_status="authorized",
    metadata_status="approved",
    auto_approve=False,
    render_status="rendered",
    credential=True,
    reaction=False,
    full_cut=False,
) -> tuple[int, int]:
    """Baglam: kanal(bagli) -> kaynak -> video -> asset -> aday ->
    render + metaveri(+profil); (channel_id, candidate_id).
    M13: reaction=True kaynak reaksiyon kaynagi yapar; full_cut=True
    ayrica yatay tam kesit render + metaveri satirlarini ekler."""
    async with sessionmaker() as session:
        channel = Channel(name="Kanal", status="connected")
        session.add(channel)
        await session.flush()
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id="UCkaynak",
            title="Kaynak",
            permission_status=source_status,
            reaction_source=reaction,
        )
        session.add(source)
        await session.flush()
        video = SourceVideo(
            source_channel_id=source.id,
            youtube_video_id="vid-1",
            title="Kaynak Video",
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
        candidate = ClipCandidate(
            source_video_id=video.id,
            start_seconds=1.0,
            end_seconds=4.0,
            duration_seconds=3.0,
            score=0.9,
            status="candidate",
        )
        session.add(candidate)
        await session.flush()
        if render_status is not None:
            # Yuklenecek dosya gercek olmali: kucuk bir mp4 yaz.
            render_file = (
                tmp_path / "edited" / f"clip_{candidate.id}.mp4"
                if tmp_path is not None
                else None
            )
            if render_file is not None:
                render_file.parent.mkdir(parents=True, exist_ok=True)
                render_file.write_bytes(b"FAKE_MP4_CONTENT")
            session.add(
                RenderedClip(
                    clip_candidate_id=candidate.id,
                    orientation="vertical",
                    status=render_status,
                    file_path=str(render_file or "/edited/1.mp4"),
                )
            )
        if metadata_status is not None:
            session.add(
                ClipMetadata(
                    clip_candidate_id=candidate.id,
                    revision=1,
                    title="Yayinlanacak Baslik",
                    description="Bu kesitin aciklamasi yeterince uzun.",
                    tags=["kesit"],
                    status=metadata_status,
                )
            )
        if full_cut:
            # Yatay tam kesit: aday NULL, video dolu.
            full_cut_file = (
                tmp_path / "edited" / f"video_{video.id}_horizontal.mp4"
                if tmp_path is not None
                else None
            )
            if full_cut_file is not None:
                full_cut_file.parent.mkdir(parents=True, exist_ok=True)
                full_cut_file.write_bytes(b"FAKE_MP4_CONTENT")
            session.add(
                RenderedClip(
                    clip_candidate_id=None,
                    source_video_id=video.id,
                    orientation="horizontal",
                    status="rendered",
                    file_path=str(full_cut_file or "/edited/h.mp4"),
                )
            )
            session.add(
                ClipMetadata(
                    clip_candidate_id=None,
                    source_video_id=video.id,
                    revision=1,
                    title="Tam Kesit Basligi",
                    description="Reaksiyon videosunun tam kesit aciklamasi.",
                    tags=["reaksiyon"],
                    status=metadata_status,
                )
            )
        session.add(
            PublishingProfile(
                channel_id=channel.id,
                automation_state="running",
                settings={"auto_approve_metadata": auto_approve},
            )
        )
        if credential:
            cipher = TokenCipher(token_key)
            session.add(
                OAuthCredential(
                    channel_id=channel.id,
                    provider="youtube",
                    access_token_enc=cipher.encrypt("synthetic-access-token"),
                    token_expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        await session.commit()
        return channel.id, candidate.id


def youtube_handler(fail_put=False, privacy="private"):
    """YouTube resumable protokolunun sadik mock'u. Gorunurluk
    state'lidir: videos.update (herkese acik yapma) geldikten sonra
    videos.list ayni gizliligi rapor eder."""

    state = {"privacy": privacy}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://www.googleapis.com/upload/youtube/v3/videos"):
            if request.method == "POST":
                return httpx.Response(200, headers={"Location": SESSION_URI})
            if request.method == "PUT":
                if fail_put:
                    return httpx.Response(500, json={"error": "upload broke"})
                return httpx.Response(201, json={"id": "yt-vid-123"})
        if url.startswith("https://www.googleapis.com/youtube/v3/videos"):
            if request.method == "PUT":
                # videos.update: herkese acik yapma.
                state["privacy"] = "public"
                return httpx.Response(200, json={"id": "yt-vid-123"})
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "yt-vid-123",
                            "status": {
                                "privacyStatus": state["privacy"],
                                "uploadStatus": "uploaded",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"error": "beklenmeyen adres"})

    return handler


def _run(coro):
    return asyncio.run(coro)


async def _published_row_id(sessionmaker, clip_candidate_id: int) -> int:
    from app.models import PublishedVideo

    async with sessionmaker() as session:
        return (
            await session.execute(
                sa.select(PublishedVideo.id).where(
                    PublishedVideo.clip_candidate_id == clip_candidate_id
                )
            )
        ).scalar_one()


class TestSchedule:
    def test_parse_publish_times(self):
        slots = parse_publish_times(["20:00", "09:00"])
        assert [s.hour for s in slots] == [9, 20]
        assert parse_publish_times(None)[0].hour == 9  # varsayilan 3 slot
        with pytest.raises(ScheduleError):
            parse_publish_times([])
        with pytest.raises(ScheduleError):
            parse_publish_times(["25:00"])
        with pytest.raises(ScheduleError):
            parse_publish_times(["09:00", "09:00"])

    def test_next_due_time_timezone_aware(self):
        # 10:00 UTC = 13:00 Istanbul (kis saati, +03)
        now = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
        due = next_due_time(
            now_utc=now,
            timezone_name="Europe/Istanbul",
            publish_times=["14:00", "20:00"],
            last_published_at=None,
        )
        assert due == datetime(2026, 10, 17, 11, 0, tzinfo=UTC)  # 14:00 yerel

    def test_is_due_rules(self):
        now = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
        assert is_due(
            now_utc=now,
            timezone_name="Europe/Istanbul",
            publish_times=["14:00"],
            last_published_at=None,
        ) is True  # hic yayinlanmadi
        recent = now - timedelta(minutes=30)
        assert is_due(
            now_utc=now,
            timezone_name="Europe/Istanbul",
            publish_times=["14:00"],
            last_published_at=recent,
        ) is False  # slot daha gelmedi
        old = now - timedelta(days=2)
        assert is_due(
            now_utc=now,
            timezone_name="Europe/Istanbul",
            publish_times=["14:00"],
            last_published_at=old,
        ) is True  # kacirilan slot


class TestPublishFlow:
    def test_full_publish_private_verified(self, tmp_path):
        from app.services.publishing_service import PublishingService

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(
                    sessionmaker, settings.token_encryption_key, tmp_path
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    result = await service.publish_clip(candidate_id, http=http)
                    # Zamanli yayin: gizli yuklemeden sonra ayni oturumda
                    # herkese acik yapma ayri bir adimdir.
                    row_id = (
                        await _published_row_id(sessionmaker, candidate_id)
                    )
                    public = await service.make_public(row_id, http=http)
                return result, public
            finally:
                await engine.dispose()

        result, public = _run(scenario())
        assert result["youtube_video_id"] == "yt-vid-123"
        assert result["visibility"] == "private"
        assert public["visibility"] == "public"

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m10.db")
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT youtube_video_id, status, visibility, published_at,"
                    " public_at FROM published_videos"
                )
            ).one()
            events = conn.execute(
                sa.text("SELECT event_type FROM audit_events")
            ).scalars().all()
        engine.dispose()
        assert row[0] == "yt-vid-123"
        assert row[1] == "verified"  # gorunurluk dogrulandi
        assert row[2] == "public"
        # Yayin ani public adiminda yazilir; her iki alan da dolu.
        assert row[3] is not None
        assert row[4] is not None
        assert "publish.done" in events
        assert "publish.public" in events

    def test_duplicate_publish_skipped(self, tmp_path):
        from app.services.publishing_service import PublishingService

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(
                    sessionmaker, settings.token_encryption_key, tmp_path
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    first = await service.publish_clip(candidate_id, http=http)
                    second = await service.publish_clip(candidate_id, http=http)
                return first, second
            finally:
                await engine.dispose()

        first, second = _run(scenario())
        assert first["youtube_video_id"] == "yt-vid-123"
        # Kabul kriteri: yinelenen yukleme engellenir.
        assert second.get("skipped") is True
        assert second["youtube_video_id"] == first["youtube_video_id"]

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m10.db")
        with engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM published_videos")
            ).scalar()
        engine.dispose()
        assert count == 1

    def test_rights_guard_rejects_unauthorized_source(self, tmp_path):
        from app.services.publishing_service import (
            PublishingError,
            PublishingService,
        )

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(
                    sessionmaker,
                    settings.token_encryption_key,
                    tmp_path,
                    source_status="pending",
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    try:
                        await service.publish_clip(candidate_id, http=http)
                        error = None
                    except PublishingError as exc:
                        error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None and "hak kaydi" in error

    def test_approval_guard_then_publish_after_approve(self, tmp_path):
        from app.services.publishing_service import (
            PublishingError,
            PublishingService,
        )

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(
                    sessionmaker,
                    settings.token_encryption_key,
                    tmp_path,
                    metadata_status="draft",
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    try:
                        await service.publish_clip(candidate_id, http=http)
                        blocked = None
                    except PublishingError as exc:
                        blocked = str(exc)
                    await service.approve_metadata(candidate_id)
                    ok = await service.publish_clip(candidate_id, http=http)
                return blocked, ok
            finally:
                await engine.dispose()

        blocked, ok = _run(scenario())
        assert blocked is not None and "onay" in blocked
        assert ok["youtube_video_id"] == "yt-vid-123"

    def test_auto_approve_profile_bypasses_manual_approval(self, tmp_path):
        from app.services.publishing_service import PublishingService

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(
                    sessionmaker,
                    settings.token_encryption_key,
                    tmp_path,
                    metadata_status="draft",
                    auto_approve=True,
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    return await service.publish_clip(candidate_id, http=http)
            finally:
                await engine.dispose()

        result = _run(scenario())
        assert result["youtube_video_id"] == "yt-vid-123"

    def test_render_guard(self, tmp_path):
        from app.services.publishing_service import (
            PublishingError,
            PublishingService,
        )

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(
                    sessionmaker,
                    settings.token_encryption_key,
                    tmp_path,
                    render_status=None,
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    try:
                        await service.publish_clip(candidate_id, http=http)
                        error = None
                    except PublishingError as exc:
                        error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None and "render" in error

    def test_failed_upload_recorded_and_reconciled(self, tmp_path):
        """Kabul kriteri: basarisiz yukleme kurtarilabilir."""
        from app.services.publishing_service import (
            PublishingError,
            PublishingService,
        )

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(
                    sessionmaker, settings.token_encryption_key, tmp_path
                )
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler(fail_put=True))
                ) as http:
                    try:
                        await service.publish_clip(candidate_id, http=http)
                        failed = None
                    except PublishingError as exc:
                        failed = str(exc)
                # Ayni oturumdan devam: PUT duzeldi, session URI kayitli.
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    recovered = await service.publish_clip(candidate_id, http=http)
                return failed, recovered
            finally:
                await engine.dispose()

        failed, recovered = _run(scenario())
        assert failed is not None and "500" in failed
        assert recovered["youtube_video_id"] == "yt-vid-123"

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m10.db")
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT status, upload_session_uri FROM published_videos"
                )
            ).all()
        engine.dispose()
        assert len(rows) == 1  # kurtarma ayni satirda, yeni kayit degil
        assert rows[0][0] == "verified"
        assert rows[0][1] == SESSION_URI  # oturum adresi korunmus

    def test_worker_publish_due_job_end_to_end(self, tmp_path, monkeypatch):
        """Onay sonrasi gizli yukleme (publish_clip isleri), sonra
        publish_due: herkese acik yapma tam akis."""
        from app.worker import JobWorker, build_handlers

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                channel_id, candidate_id = await _seed(
                    sessionmaker, settings.token_encryption_key, tmp_path
                )
                monkeypatch.setattr(
                    "app.services.publishing_service._default_client",
                    lambda: httpx.AsyncClient(
                        transport=httpx.MockTransport(youtube_handler())
                    ),
                )
                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                # 1) Onay tetikledigi gizli yukleme isleri.
                upload = await worker._jobs.enqueue(
                    "publish_clip", {"clip_candidate_id": candidate_id}
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(upload.id)
                # 2) Plan saati: herkese acik yapma.
                job = await worker._jobs.enqueue(
                    "publish_due", {"channel_id": channel_id}
                )
                await worker._jobs.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id
            finally:
                await engine.dispose()

        job_id = _run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m10.db")
        with engine.connect() as conn:
            job_status = conn.execute(
                sa.text("SELECT status FROM jobs WHERE id = :j"), {"j": job_id}
            ).scalar()
            published = conn.execute(
                sa.text(
                    "SELECT status, youtube_video_id, visibility FROM"
                    " published_videos"
                )
            ).one()
        engine.dispose()
        assert job_status == "succeeded"
        assert published[0] == "verified"
        assert published[1] == "yt-vid-123"
        assert published[2] == "public"

    def test_worker_feed_enqueues_due_channels(self, tmp_path):
        from app.worker import JobWorker

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                channel_id, _ = await _seed(
                    sessionmaker, settings.token_encryption_key, tmp_path
                )
                worker = JobWorker(sessionmaker, settings)
                added = await worker.enqueue_publish_jobs()
                added_again = await worker.enqueue_publish_jobs()
                jobs = await worker._jobs.list_jobs()
                return added, added_again, [
                    (j.job_type, j.payload) for j in jobs
                ]
            finally:
                await engine.dispose()

        added, added_again, jobs = _run(scenario())
        # Hic yayinlanmamis bagli kanal: ilk kontrolde due.
        assert added == 1
        assert added_again == 0
        assert jobs == [("publish_due", {"channel_id": 1})]


class TestPublishingApi:
    def test_approve_publish_list_roundtrip(self, tmp_path, monkeypatch):
        key = Fernet.generate_key().decode()
        app = _make_app(
            tmp_path, worker_enabled=False, token_encryption_key=key
        )
        monkeypatch.setattr(
            "app.services.publishing_service._default_client",
            lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(youtube_handler())
            ),
        )
        with TestClient(app) as client:
            sessionmaker = client.app.state.sessionmaker  # lifespan sonrasi

            async def seed():
                return await _seed(
                    sessionmaker, key, tmp_path, metadata_status="draft"
                )

            channel_id, candidate_id = _run(seed())

            blocked = client.post(f"/api/clips/{candidate_id}/publish")
            assert blocked.status_code == 409  # metaveri henuz onayli degil

            approved = client.post(f"/api/clips/{candidate_id}/approve")
            assert approved.status_code == 200, approved.text
            assert approved.json()["revision"] == 1

            published = client.post(f"/api/clips/{candidate_id}/publish")
            assert published.status_code == 200, published.text
            assert published.json()["youtube_video_id"] == "yt-vid-123"

            listed = client.get(f"/api/channels/{channel_id}/published")
            assert listed.status_code == 200
            body = listed.json()
            assert body["total"] == 1
            assert body["videos"][0]["status"] == "verified"
            assert body["videos"][0]["visibility"] == "private"


class TestOrientationPublishing:
    """M13: yayin yone gore — dikey aday + yatay tam kesit iki ayri
    PublishedVideo satiri; yinelenen yayin reddedilir."""

    def test_both_orientations_publish_as_distinct_rows(self, tmp_path):
        from app.services.publishing_service import PublishingService

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _, candidate_id = await _seed(
                    sessionmaker,
                    settings.token_encryption_key,
                    tmp_path,
                    reaction=True,
                    full_cut=True,
                )
                async with sessionmaker() as session:
                    video_id = (
                        await session.execute(
                            sa.select(SourceVideo.id).limit(1)
                        )
                    ).scalar_one()
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    vertical = await service.publish_clip(
                        candidate_id, http=http
                    )
                    horizontal = await service.publish_full_cut(
                        video_id, http=http
                    )
                    # Kabul kriteri: ikisinin de yinelenen yayini reddi.
                    vertical_again = await service.publish_clip(
                        candidate_id, http=http
                    )
                    horizontal_again = await service.publish_full_cut(
                        video_id, http=http
                    )
                return (
                    vertical,
                    horizontal,
                    vertical_again,
                    horizontal_again,
                )
            finally:
                await engine.dispose()

        vertical, horizontal, v_again, h_again = _run(scenario())
        assert vertical["youtube_video_id"] == "yt-vid-123"
        assert vertical["clip_candidate_id"] is not None
        assert horizontal["youtube_video_id"] == "yt-vid-123"
        assert horizontal["source_video_id"] is not None
        assert v_again.get("skipped") is True
        assert h_again.get("skipped") is True

        engine = sa.create_engine(f"sqlite:///{tmp_path}/m10.db")
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT clip_candidate_id, orientation, status"
                    " FROM published_videos ORDER BY id"
                )
            ).all()
        engine.dispose()
        assert len(rows) == 2  # iki ayri satir
        assert rows[0][1] == "vertical" and rows[0][0] is not None
        assert rows[1][1] == "horizontal" and rows[1][0] is None
        assert all(row[2] == "verified" for row in rows)

    def test_full_cut_publish_refused_for_non_reaction(self, tmp_path):
        from app.services.publishing_service import (
            PublishingError,
            PublishingService,
        )

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                # Reaksiyon OLMAYAN kaynaga zorla tam kesit satiri ekle:
                # guvenlik yine de yayini reddetmeli.
                await _seed(
                    sessionmaker,
                    settings.token_encryption_key,
                    tmp_path,
                    full_cut=True,
                )
                async with sessionmaker() as session:
                    video_id = (
                        await session.execute(
                            sa.select(SourceVideo.id).limit(1)
                        )
                    ).scalar_one()
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    try:
                        await service.publish_full_cut(video_id, http=http)
                        error = None
                    except PublishingError as exc:
                        error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None and "reaksiyon" in error
        engine = sa.create_engine(f"sqlite:///{tmp_path}/m10.db")
        with engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM published_videos")
            ).scalar()
        engine.dispose()
        assert count == 0  # guvenlik yayini tamamen engelledi

    def test_full_cut_publish_requires_render_and_metadata(self, tmp_path):
        from app.services.publishing_service import (
            PublishingError,
            PublishingService,
        )

        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                # Reaksiyon kaynagi ama tam kesit render/metaveri YOK.
                _, candidate_id = await _seed(
                    sessionmaker,
                    settings.token_encryption_key,
                    tmp_path,
                    reaction=True,
                )
                async with sessionmaker() as session:
                    video_id = (
                        await session.execute(
                            sa.select(SourceVideo.id).limit(1)
                        )
                    ).scalar_one()
                service = PublishingService(sessionmaker, settings)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(youtube_handler())
                ) as http:
                    try:
                        await service.publish_full_cut(video_id, http=http)
                        error = None
                    except PublishingError as exc:
                        error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = _run(scenario())
        assert error is not None and "render" in error
