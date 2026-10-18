"""Zamanli yayin (scheduled-public) oturumu: onayda gizli yukleme,
saati gelince herkese acik yapma, yon bazli gunluk limitler ve
yayinlanmis medyanin temizligi (retention).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import Base
from app.services.automation_service import AutomationService
from app.services.media_cleanup import cleanup_published_media
from app.services.publishing_service import PublishingService


def _env(tmp_path, **overrides):
    db_path = tmp_path / "sched.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **overrides
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine, str(db_path)


def _seed(db_path):
    """Kanal + profil + iki aday (dikey skorlari farkli) + yatay tam
    kesit: hepsi dogrulanmis-gizli yayin satiriyla."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO channels (name, status, ribbon_color) "
                    "VALUES ('Kanal', 'connected', '#111111')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO publishing_profiles "
                    "(channel_id, daily_clip_target, daily_horizontal_limit, "
                    " timezone, automation_state, horizontal_stock_target, "
                    " title_mode, description_mode, tags_mode, "
                    " content_warning_mode, ai_disclosure_mode, settings)"
                    " VALUES (1, 1, 1, 'Europe/Istanbul', 'running', 3, "
                    "'auto', 'auto', 'auto', 'auto', 'auto', '{}')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO source_channels "
                    "(channel_id, platform, youtube_channel_id, title, "
                    " permission_status, reaction_source, trim_start_seconds, "
                    " trim_end_seconds, filter_rules) "
                    "VALUES (1, 'youtube', 'UCsrc', 'Kaynak', "
                    "'authorized', 1, 0.0, 0.0, '{}')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO source_videos "
                    "(id, source_channel_id, youtube_video_id, title, status) "
                    "VALUES (1, 1, 'v1', 'Video', 'confirmed')"
                )
            )
            for cid, score in ((11, 0.9), (12, 0.5)):
                conn.execute(
                    sa.text(
                        "INSERT INTO clip_candidates "
                        "(id, source_video_id, start_seconds, end_seconds, "
                        " duration_seconds, score, status) "
                        f"VALUES ({cid}, 1, 0, 30, 30, {score}, 'selected')"
                    )
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO published_videos "
                        "(clip_candidate_id, orientation, channel_id, "
                        " youtube_video_id, visibility, status, title) "
                        f"VALUES ({cid}, 'vertical', 1, 'yt-{cid}', "
                        "'private', 'verified', 'Klip {cid}')"
                    )
                )
            # Yatay tam kesit: dogrulanmis-gizli.
            conn.execute(
                sa.text(
                    "INSERT INTO published_videos "
                    "(source_video_id, orientation, channel_id, "
                    " youtube_video_id, visibility, status, title) "
                    "VALUES (1, 'horizontal', 1, 'yt-h', 'private', "
                    "'verified', 'Tam kesit')"
                )
            )
    finally:
        engine.dispose()


async def _make_row_public(sessionmaker, row_id: int) -> None:
    from app.models import PublishedVideo

    async with sessionmaker() as session:
        row = await session.get(PublishedVideo, row_id)
        row.visibility = "public"
        now = datetime.now(UTC)
        row.public_at = now
        row.published_at = now
        await session.commit()


class TestDirectionalLimits:
    def test_vertical_limit_full_falls_back_to_horizontal(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _seed(db)
                service = AutomationService(sessionmaker, settings)
                made: list[tuple[int, str]] = []

                async def fake_make_public(row_id: int):
                    from app.models import PublishedVideo

                    async with sessionmaker() as session:
                        row = await session.get(PublishedVideo, row_id)
                        orientation = row.orientation
                    made.append((row_id, orientation))
                    return {
                        "youtube_video_id": "yt",
                        "visibility": "public",
                        "orientation": orientation,
                    }

                service._publishing.make_public = fake_make_public
                # Dikey limit 1, yatay limit 1: iki turluk yayin.
                first = await service.publish_for_channel(1)
                await _make_row_public(sessionmaker, made[0][0])
                second = await service.publish_for_channel(1)
                return first, second, made
            finally:
                await engine.dispose()

        first, second, made = asyncio.run(scenario())
        assert first["published"] == 1
        assert second["published"] == 1
        # Ilk tur en yuksek skorlu dikeyin SATIRI (id 1), ikinci yatay.
        assert made[0] == (1, "vertical")
        assert made[1][1] == "horizontal"

    def test_both_limits_full_publishes_nothing(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _seed(db)
                service = AutomationService(sessionmaker, settings)
                made: list[int] = []

                async def fake_make_public(row_id: int):
                    made.append(row_id)
                    return {"youtube_video_id": "yt", "visibility": "public"}

                service._publishing.make_public = fake_make_public
                # Bugunun sayimlari: dikey 1/1, yatay 1/1 — ikisi dolu.
                async with sessionmaker() as session:
                    from app.models import PublishedVideo

                    rows = (
                        (
                            await session.execute(
                                sa.select(PublishedVideo).where(
                                    PublishedVideo.status == "verified"
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                for row in rows:
                    row.visibility = "public"
                    now = datetime.now(UTC)
                    row.public_at = now
                    row.published_at = now
                async with sessionmaker() as session:
                    session.add_all(rows)
                    await session.commit()
                result = await service.publish_for_channel(1)
                return result, made
            finally:
                await engine.dispose()

        result, made = asyncio.run(scenario())
        assert result["published"] == 0
        assert made == []
        assert "limit" in result["reason"]

    def test_today_counts_split_by_orientation(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                _seed(db)
                service = PublishingService(sessionmaker, settings)
                return await service.today_published_counts(1)
            finally:
                await engine.dispose()

        counts = asyncio.run(scenario())
        assert counts == {"vertical": 0, "horizontal": 0}


class TestRetention:
    def _seed_files(self, tmp_path, db_path, public_at_age_days):
        clip_file = tmp_path / "clip.mp4"
        clip_file.write_bytes(b"CLIP")
        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"SOURCE")
        engine = sa.create_engine(f"sqlite:///{db_path}")
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO rendered_clips "
                        "(id, clip_candidate_id, source_video_id, orientation, "
                        " status, file_path, file_bytes, duration_seconds, "
                        " width, height, webcam_confidence) "
                        "VALUES (5, 11, 1, 'vertical', 'rendered', :clip, "
                        "4, 30, 1080, 1920, 0.0)"
                    ),
                    {"clip": str(clip_file)},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO media_assets "
                        "(source_video_id, origin, status, stage, file_path, "
                        " file_bytes) VALUES (1, 'youtube', 'processed', "
                        "'candidates', :src, 6)"
                    ),
                    {"src": str(source_file)},
                )
                conn.execute(
                    sa.text(
                        "UPDATE published_videos SET visibility='public', "
                        "public_at=:pa WHERE clip_candidate_id=11"
                    ),
                    {
                        "pa": (
                            datetime.now(UTC)
                            - timedelta(days=public_at_age_days)
                        ).isoformat()
                    },
                )
        finally:
            engine.dispose()
        return clip_file, source_file

    def test_retention_zero_cleans_clip_and_confirmed_source(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(
                tmp_path, media_retention_days=0
            )
            try:
                _seed(db)
                clip_file, source_file = self._seed_files(
                    tmp_path, db, public_at_age_days=1
                )
                result = await cleanup_published_media(
                    sessionmaker, settings
                )
                return result, clip_file, source_file
            finally:
                await engine.dispose()

        result, clip_file, source_file = asyncio.run(scenario())
        assert result["cleaned"] == 1
        assert not clip_file.exists()  # klip dosyasi silindi
        assert not source_file.exists()  # confirmed kaynagi da silindi

    def test_retention_never_keeps_files(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(
                tmp_path, media_retention_days=-1
            )
            try:
                _seed(db)
                clip_file, _ = self._seed_files(
                    tmp_path, db, public_at_age_days=365
                )
                result = await cleanup_published_media(
                    sessionmaker, settings
                )
                return result, clip_file
            finally:
                await engine.dispose()

        result, clip_file = asyncio.run(scenario())
        assert result["cleaned"] == 0
        assert clip_file.exists()

    def test_private_rows_never_touched(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(
                tmp_path, media_retention_days=0
            )
            try:
                _seed(db)
                clip_file, _ = self._seed_files(
                    tmp_path, db, public_at_age_days=365
                )
                # Satiri gizli birak: public_at yok.
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.begin() as conn:
                    conn.execute(
                        sa.text(
                            "UPDATE published_videos SET visibility='private',"
                            " public_at=NULL WHERE clip_candidate_id=11"
                        )
                    )
                eng.dispose()
                result = await cleanup_published_media(
                    sessionmaker, settings
                )
                return result, clip_file
            finally:
                await engine.dispose()

        result, clip_file = asyncio.run(scenario())
        assert result["cleaned"] == 0
        assert clip_file.exists()


class TestApproveEnqueuesUpload:
    def test_clip_approve_queues_private_upload(self, tmp_path):
        from tests.conftest import _make_app

        app = _make_app(tmp_path)
        _seed(app.state.test_db_path)
        from sqlalchemy.orm import Session

        from app.models import ClipMetadata

        engine = sa.create_engine(f"sqlite:///{app.state.test_db_path}")
        with Session(engine) as session:
            session.add(
                ClipMetadata(
                    clip_candidate_id=11,
                    revision=1,
                    title="Baslik",
                    description="Aciklama",
                    tags=[],
                    status="draft",
                )
            )
            session.commit()
        with TestClient(app) as client:
            response = client.post("/api/clips/11/approve")
        assert response.status_code == 200
        from app.models import Job

        with Session(engine) as session:
            job = next(
                j
                for j in session.query(Job).all()
                if (j.payload or {}).get("clip_candidate_id") == 11
            )
            assert job.job_type == "publish_clip"
            assert job.status == "queued"
        engine.dispose()
