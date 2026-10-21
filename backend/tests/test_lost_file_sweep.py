"""Kayıp dosya süpürmesi + toplu video durumu + overview havuzu.

2026-10-21 canlı olayın kalıcı çözümünün testleri: dosyaları sistem
dışından silinen videolar saatlik süpürmeyle kendiliğinden temizlenir;
hariç kalan videolar toplu işleme geri alınabilir; overview üretim
havuzunu görünür kılar.
"""
from __future__ import annotations

import asyncio

import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import Base
from tests.conftest import _make_app


def _env(tmp_path, media_root=None):
    db_path = tmp_path / "sweep.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    kwargs = dict(token_encryption_key=Fernet.generate_key().decode())
    if media_root is not None:
        kwargs["media_root"] = str(media_root)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **kwargs
    )
    engine, sessionmaker = create_engine_and_sessionmaker(
        settings.database_url
    )
    return sessionmaker, settings, engine


async def _seed_video(
    sessionmaker,
    video_id: int,
    *,
    status: str = "planned",
    file_path: str | None = "/nonexistent/x.mp4",
    public: bool = False,
) -> None:
    from app.models import (
        Channel,
        ClipCandidate,
        MediaAsset,
        PublishedVideo,
        SourceChannel,
        SourceVideo,
    )

    async with sessionmaker() as session:
        # Kanal ve kaynak yalnız ilk seed'de oluşur; sonraki videolar
        # aynı kaynağa bağlanır (tek kanallı stüdyo senaryosu).
        if (await session.get(Channel, 1)) is None:
            session.add(Channel(id=1, name="Kanal", status="connected"))
            await session.flush()
        source = (
            (
                await session.execute(
                    sa.select(SourceChannel).where(
                        SourceChannel.channel_id == 1
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if source is None:
            source = SourceChannel(
                channel_id=1,
                youtube_channel_id="UCsweep",
                title="Kaynak",
                permission_status="authorized",
            )
            session.add(source)
            await session.flush()
        session.add(
            SourceVideo(
                id=video_id,
                source_channel_id=source.id,
                youtube_video_id=f"vid-{video_id}",
                title=f"Video {video_id}",
                status=status,
            )
        )
        await session.flush()
        if file_path is not None:
            session.add(
                MediaAsset(
                    source_video_id=video_id,
                    origin="local_import",
                    status="processed",
                    stage="candidates",
                    file_path=file_path,
                )
            )
        if public:
            session.add(
                ClipCandidate(
                    source_video_id=video_id,
                    start_seconds=0.0,
                    end_seconds=10.0,
                    duration_seconds=10.0,
                    score=0.5,
                    status="selected",
                )
            )
            await session.flush()
            session.add(
                PublishedVideo(
                    clip_candidate_id=None,
                    source_video_id=video_id,
                    orientation="horizontal",
                    channel_id=1,
                    youtube_video_id=f"yt-{video_id}",
                    visibility="public",
                    status="verified",
                    title=f"Video {video_id}",
                )
            )
        await session.commit()


class TestLostFileSweep:
    def test_dead_asset_video_is_removed_living_and_public_untouched(
        self, tmp_path
    ):
        """Dosyası diskte olmayan video süpürülür (satırlar düşer, video
        hariç kalır); dosyası yaşayan ve yayında olan videoya
        dokunulmaz."""

        async def scenario():
            from app.services.media_cleanup import sweep_lost_source_files

            sessionmaker, settings, engine = _env(
                tmp_path, media_root=tmp_path
            )
            try:
                alive = tmp_path / "alive.mp4"
                alive.write_bytes(b"MP4")
                await _seed_video(sessionmaker, 1, file_path=str(alive))
                await _seed_video(sessionmaker, 2, file_path=str(tmp_path / "dead.mp4"))
                await _seed_video(
                    sessionmaker,
                    3,
                    file_path=str(tmp_path / "dead2.mp4"),
                    public=True,
                )
                result = await sweep_lost_source_files(
                    sessionmaker, settings
                )
                async with sessionmaker() as session:
                    from app.models import MediaAsset, SourceVideo

                    videos = {
                        v.id: v.status
                        for v in (
                            await session.execute(
                                sa.select(SourceVideo)
                            )
                        ).scalars()
                    }
                    assets = (
                        await session.execute(
                            sa.select(MediaAsset.source_video_id)
                        )
                    ).scalars().all()
                return result, videos, sorted(assets)
            finally:
                await engine.dispose()

        result, videos, assets = asyncio.run(scenario())
        assert result["swept"] == 1
        # Yalnız 2 numara (dosyası ölü, yayında değil) temizlendi.
        assert videos[2] == "excluded"
        assert videos[1] == "planned"
        assert videos[3] == "planned"
        assert assets == [1, 3]

    def test_empty_file_path_is_intentional_not_lost(self, tmp_path):
        """Retention/dikey temizliği bilinçli olarak boşalttığı
        file_path'ler ('') süpürme sayılmaz."""

        async def scenario():
            from app.services.media_cleanup import sweep_lost_source_files

            sessionmaker, settings, engine = _env(
                tmp_path, media_root=tmp_path
            )
            try:
                await _seed_video(sessionmaker, 1, file_path="")
                result = await sweep_lost_source_files(
                    sessionmaker, settings
                )
                async with sessionmaker() as session:
                    from app.models import MediaAsset

                    count = (
                        await session.execute(
                            sa.select(sa.func.count()).select_from(MediaAsset)
                        )
                    ).scalar()
                return result, count
            finally:
                await engine.dispose()

        result, count = asyncio.run(scenario())
        assert result["swept"] == 0
        assert count == 1

    def test_batch_limits_one_sweep(self, tmp_path):
        """Kayıp sayısı yığını aşarsa tek tur 'batch' kadarını alır;
        kalanlar sonraki saatlik tura kalır."""

        async def scenario():
            from app.services.media_cleanup import (
                LOST_SWEEP_BATCH,
                sweep_lost_source_files,
            )

            sessionmaker, settings, engine = _env(
                tmp_path, media_root=tmp_path
            )
            try:
                for i in range(LOST_SWEEP_BATCH + 5):
                    await _seed_video(
                        sessionmaker,
                        100 + i,
                        file_path=str(tmp_path / f"dead{i}.mp4"),
                    )
                result = await sweep_lost_source_files(
                    sessionmaker, settings
                )
                return result, LOST_SWEEP_BATCH
            finally:
                await engine.dispose()

        result, batch = asyncio.run(scenario())
        assert result["swept"] == batch


class TestBulkVideoStatus:
    def test_bulk_reinclude_reports_partial_success(self, tmp_path):
        """Hariç videoları toplu işleme alma: işlenmiş videonun hatası
        grubu durdurmaz, sonuç listesi taşır."""
        from pathlib import Path

        app = _make_app(tmp_path)
        db_path = Path(app.state.test_db_path)
        sync_engine = sa.create_engine(f"sqlite:///{db_path}")
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO channels (name, status, ribbon_color)"
                    " VALUES ('Kanal', 'connected', '#3550c4')"
                )
            )
            channel_id = conn.execute(
                sa.text("SELECT id FROM channels")
            ).scalar()
            conn.execute(
                sa.text(
                    "INSERT INTO source_channels"
                    " (channel_id, platform, youtube_channel_id, title,"
                    " permission_status, reaction_source, trim_start_seconds,"
                    " trim_end_seconds, filter_rules)"
                    " VALUES (:c, 'youtube', 'UCx', 'Kaynak',"
                    " 'authorized', 0, 0.0, 0.0, '{}')"
                ),
                {"c": channel_id},
            )
            source_id = conn.execute(
                sa.text("SELECT id FROM source_channels")
            ).scalar()
            for vid, status in ((1, "excluded"), (2, "excluded"), (3, "processed")):
                conn.execute(
                    sa.text(
                        "INSERT INTO source_videos"
                        " (source_channel_id, youtube_video_id, title,"
                        " status) VALUES (:s, :y, :t, :st)"
                    ),
                    {"s": source_id, "y": f"vid-{vid}", "t": f"V{vid}", "st": status},
                )
        sync_engine.dispose()

        with TestClient(app) as client:
            response = client.post(
                "/api/sources/videos/status",
                json={"ids": [1, 2, 3], "status": "planned"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["requested"] == 3
        assert body["updated"] == 2
        assert body["errors"] == 1


class TestOverviewPlannedPool:
    def test_overview_carries_planned_videos(self, tmp_path):
        app = _make_app(tmp_path)
        with TestClient(app) as client:
            response = client.get("/api/overview")
        assert response.status_code == 200
        body = response.json()
        assert "production" in body
        assert isinstance(body["production"]["planned_videos"], int)
