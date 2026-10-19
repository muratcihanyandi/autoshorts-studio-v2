"""Görev 2: kaynak çıktı yönü (auto / vertical / horizontal).

Yön seçimi tüm üretim guard'larını yönetir: vertical yatay tam kesiti
hiç üretmez ve Shorts üretimi bitince yatay dosyayı diskten siler;
horizontal bayraktan bağımsız yatay tam kesit üretir; auto eski
reaction_source davranışına düşer. Stok kapısı artık hazır klip
stoğuna bakar (test_channel_automation'da ayrıca kapsanır).
"""
from __future__ import annotations

import asyncio

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    ClipCandidate,
    MediaAsset,
    PublishingProfile,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.media_storage import ensure_media_tree
from app.services.source_orientation import produces_full_cut
from tests.conftest import _make_app


def _env(tmp_path):
    db_path = tmp_path / "orient.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        media_root=str(tmp_path / "media"),
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    ensure_media_tree(tmp_path / "media")
    return sessionmaker, settings, engine


def _run(coro):
    return asyncio.run(coro)


def _source(orientation: str, reaction: bool) -> SourceChannel:
    return SourceChannel(
        channel_id=1,
        youtube_channel_id="UC-x",
        title="Kaynak",
        output_orientation=orientation,
        reaction_source=reaction,
    )


def test_produces_full_cut_matrix():
    """Yön matrisi: auto bayrağa düşer, vertical asla, horizontal hep."""
    assert produces_full_cut(_source("auto", True)) is True
    assert produces_full_cut(_source("auto", False)) is False
    # Acik yon bayragi ezer.
    assert produces_full_cut(_source("vertical", True)) is False
    assert produces_full_cut(_source("horizontal", False)) is True


def test_api_accepts_and_updates_orientation(tmp_path):
    app = _make_app(tmp_path)
    seed = sa.create_engine(f"sqlite:///{app.state.test_db_path}")
    with seed.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO channels (name, status, ribbon_color) "
                "VALUES ('Kanal', 'connected', '#123456')"
            )
        )
    seed.dispose()
    with TestClient(app) as client:
        created = client.post(
            "/api/channels/1/sources",
            json={
                "youtube_channel_id": "UC-orient",
                "title": "Yonlu kaynak",
                "platform": "youtube",
                "output_orientation": "vertical",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["output_orientation"] == "vertical"

        patched = client.patch(
            f"/api/sources/{created.json()['id']}",
            json={"output_orientation": "horizontal"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["output_orientation"] == "horizontal"

        # Gecersiz yon reddedilir.
        bad = client.post(
            "/api/channels/1/sources",
            json={
                "youtube_channel_id": "UC-orient-2",
                "title": "Bozuk yon",
                "output_orientation": "diagonal",
            },
        )
        assert bad.status_code == 422


def test_vertical_orientation_never_renders_full_cut(tmp_path):
    """Vertical yön reaksiyon bayragi acik olsa bile yatay uretmez."""
    from app.services.vertical_pipeline import (
        VerticalPipelineError,
        VerticalPipelineService,
    )

    async def scenario():
        sessionmaker, settings, engine = _env(tmp_path)
        try:
            async with sessionmaker() as session:
                channel = Channel(name="Kanal", status="connected")
                session.add(channel)
                await session.flush()
                source = SourceChannel(
                    channel_id=channel.id,
                    youtube_channel_id="UC-v",
                    title="Dikey kaynak",
                    output_orientation="vertical",
                    reaction_source=True,
                    permission_status="authorized",
                )
                session.add(source)
                await session.flush()
                video = SourceVideo(
                    source_channel_id=source.id,
                    youtube_video_id="vid-v",
                    title="Video",
                    status="processed",
                )
                session.add(video)
                await session.commit()
                video_id = video.id
            service = VerticalPipelineService(sessionmaker, settings)
            try:
                await service.run_full_cut(video_id)
                return None
            except VerticalPipelineError as exc:
                return str(exc)
        finally:
            await engine.dispose()

    message = _run(scenario())
    assert message is not None
    assert "Yatay tam kesit" in message


def test_worker_fullcut_feed_follows_orientation(tmp_path):
    """Yatay yön (bayrak kapali olsa bile) tam kesit beslemesine girer;
    vertical yön girmez."""
    from app.worker import JobWorker

    async def scenario():
        sessionmaker, settings, engine = _env(tmp_path)
        try:
            async with sessionmaker() as session:
                channel = Channel(name="Kanal", status="connected")
                session.add(channel)
                await session.flush()
                session.add(
                    PublishingProfile(
                        channel_id=channel.id,
                        automation_state="running",
                    )
                )
                for key, orientation in (
                    ("h", "horizontal"),
                    ("v", "vertical"),
                ):
                    source = SourceChannel(
                        channel_id=channel.id,
                        youtube_channel_id=f"UC-{key}",
                        title=f"Kaynak {key}",
                        output_orientation=orientation,
                        reaction_source=False,
                        permission_status="authorized",
                    )
                    session.add(source)
                    await session.flush()
                    video = SourceVideo(
                        source_channel_id=source.id,
                        youtube_video_id=f"vid-{key}",
                        title=f"Video {key}",
                        status="processed",
                    )
                    session.add(video)
                    await session.flush()
                    session.add(
                        MediaAsset(
                            source_video_id=video.id,
                            origin="local_import",
                            status="processed",
                            stage="candidates",
                            file_path=f"/x/{key}.mp4",
                            file_bytes=10,
                        )
                    )
                await session.commit()
            worker = JobWorker(sessionmaker, settings)
            added = await worker.enqueue_render_jobs()
            async with sessionmaker() as session:
                from app.models import Job

                rows = (
                    (
                        await session.execute(
                            sa.select(Job).where(
                                Job.status.in_(("queued", "running"))
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            return added, rows
        finally:
            await engine.dispose()

    added, jobs = _run(scenario())
    fullcut = [job for job in jobs if job.job_type == "clip_render_full_cut"]
    assert added >= 1
    assert len(fullcut) == 1
    assert fullcut[0].payload["source_video_id"] == 1


def test_confirm_cleans_vertical_horizontal_file(tmp_path):
    """Vertical kaynakta #confirmed aninda yatay dosya silinir; auto
    (reaksiyon olmayan) kaynaktaki dosya kalir."""
    from app.services.status_service import StatusService

    async def scenario():
        sessionmaker, settings, engine = _env(tmp_path)
        try:
            paths = {}
            async with sessionmaker() as session:
                channel = Channel(name="Kanal", status="connected")
                session.add(channel)
                await session.flush()
                for key, orientation in (
                    ("v", "vertical"),
                    ("a", "auto"),
                ):
                    source = SourceChannel(
                        channel_id=channel.id,
                        youtube_channel_id=f"UC-{key}",
                        title=f"Kaynak {key}",
                        output_orientation=orientation,
                        reaction_source=False,
                        permission_status="authorized",
                    )
                    session.add(source)
                    await session.flush()
                    video = SourceVideo(
                        source_channel_id=source.id,
                        youtube_video_id=f"vid-{key}",
                        title=f"Video {key}",
                        status="processed",
                    )
                    session.add(video)
                    await session.flush()
                    media_file = (
                        tmp_path / "media" / "downloads" / f"{key}.mp4"
                    )
                    media_file.write_bytes(b"horizontal")
                    paths[key] = media_file
                    session.add(
                        MediaAsset(
                            source_video_id=video.id,
                            origin="local_import",
                            status="processed",
                            stage="candidates",
                            file_path=str(media_file),
                            file_bytes=9,
                        )
                    )
                    candidate = ClipCandidate(
                        source_video_id=video.id,
                        start_seconds=0.0,
                        end_seconds=30.0,
                        duration_seconds=30.0,
                        score=0.9,
                        status="selected",
                    )
                    session.add(candidate)
                    await session.flush()
                    session.add(
                        RenderedClip(
                            clip_candidate_id=candidate.id,
                            source_video_id=video.id,
                            orientation="vertical",
                            status="rendered",
                            file_path="/x/clip.mp4",
                            file_bytes=5,
                        )
                    )
                await session.commit()
            service = StatusService(sessionmaker, settings)
            confirmed_vertical = await service.maybe_confirm_source(1)
            confirmed_auto = await service.maybe_confirm_source(2)
            async with sessionmaker() as session:
                vertical_asset = await session.get(MediaAsset, 1)
                auto_asset = await session.get(MediaAsset, 2)
                return (
                    confirmed_vertical,
                    confirmed_auto,
                    vertical_asset.file_path,
                    auto_asset.file_path,
                    paths,
                )
        finally:
            await engine.dispose()

    (
        confirmed_vertical,
        confirmed_auto,
        vertical_path,
        auto_path,
        paths,
    ) = _run(scenario())
    assert confirmed_vertical is True
    assert confirmed_auto is True
    # Vertical: yatay dosya diskten kalkti, kayit dosyasiz satir olarak
    # durur. Auto: dosya yerinde kalir.
    assert vertical_path == ""
    assert not paths["v"].exists()
    assert auto_path != ""
    assert paths["a"].exists()
