"""Canlı görünüm servisleri: pipeline kartları, kütüphane, günlükler.

Schema'lı SQLite üzerinde üç salt-okunur görünüm doğrulanır: kart
alanları (aşama, indirme baytı, tahmin), etiket türetimi, filtreler ve
sayfalama. Tahminler yalnızca gerçek iş geçmişinden hesaplanır — geçmiş
yoksa alan None kalır, sayı uydurulmaz.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import Base
from app.services.audit_view import AuditViewService
from app.services.library_view import LibraryViewService
from app.services.pipeline_view import PipelineViewService


def _view_env(tmp_path, **overrides):
    """(sessionmaker, settings, engine, db_path) — şemalı sqlite."""
    db_path = tmp_path / "view.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    overrides.setdefault("media_root", "")
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **overrides
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine, str(db_path)


def _seed(
    db_path,
    *,
    with_channel: bool = True,
):
    """Kanal + yetkili kaynak + üç video + varlık/iş/olay tohumları."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            if with_channel:
                conn.execute(
                    sa.text(
                        "INSERT INTO channels (name, status, ribbon_color) "
                        "VALUES ('Test Kanal', 'connected', '#123456')"
                    )
                )
            conn.execute(
                sa.text(
                    "INSERT INTO source_channels "
                    "(channel_id, platform, youtube_channel_id, title, "
                    " permission_status, reaction_source, trim_start_seconds, "
                    " trim_end_seconds, filter_rules) "
                    "VALUES (1, 'youtube', 'UCsrc', 'Kaynak Kanal', "
                    "'authorized', 0, 0.0, 0.0, '{}')"
                )
            )
            # Videolar: 1 islenmis, 2 indiriliyor, 3 planli (kuyrukta).
            conn.execute(
                sa.text(
                    "INSERT INTO source_videos "
                    "(id, source_channel_id, youtube_video_id, title, status, "
                    " duration_seconds) VALUES "
                    "(1, 1, 'yt-1', 'Islenmis video', 'processed', 600), "
                    "(2, 1, 'yt-2', 'Indirilen video', 'planned', 900), "
                    "(3, 1, 'yt-3', 'Siradaki video', 'planned', 450)"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO media_assets "
                    "(source_video_id, origin, status, stage, file_path, "
                    " file_bytes) VALUES "
                    "(1, 'youtube', 'processed', 'candidates', '/x/1.mp4', 5000), "
                    "(2, 'youtube', 'downloading', 'download', '', 0)"
                )
            )
    finally:
        engine.dispose()


def _seed_jobs(db_path):
    """Bitmis (ortalama icin) + kosan + kuyrukta is."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    now = datetime.now(UTC)
    try:
        with engine.begin() as conn:
            base = now - timedelta(hours=2)
            conn.execute(
                sa.text(
                    "INSERT INTO jobs (job_type, payload, status, priority, "
                    "attempts, max_attempts, started_at, finished_at) VALUES "
                    "(:t, :p, 'succeeded', 5, 1, 3, :s, :f)"
                ),
                [
                    {
                        "t": "media_process",
                        "p": json.dumps({"source_video_id": 1}),
                        "s": base.isoformat(),
                        "f": (base + timedelta(minutes=10)).isoformat(),
                    },
                    {
                        "t": "media_process",
                        "p": json.dumps({"source_video_id": 9}),
                        "s": (base - timedelta(hours=1)).isoformat(),
                        "f": (
                            base - timedelta(hours=1) + timedelta(minutes=20)
                        ).isoformat(),
                    },
                ],
            )
            conn.execute(
                sa.text(
                    "INSERT INTO jobs (job_type, payload, status, priority, "
                    "attempts, max_attempts, started_at) VALUES "
                    "('media_process', :p, 'running', 5, 1, 3, :s)"
                ),
                {
                    "p": json.dumps({"source_video_id": 2}),
                    "s": (now - timedelta(minutes=2)).isoformat(),
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO jobs (job_type, payload, status, priority, "
                    "attempts, max_attempts) VALUES "
                    "('media_process', :p, 'queued', 5, 0, 3)"
                ),
                {"p": json.dumps({"source_video_id": 3})},
            )
    finally:
        engine.dispose()


def _seed_events(db_path):
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            for i, (etype, detail) in enumerate(
                [
                    ("media.download", {"source_video_id": 1, "file_bytes": 5000}),
                    ("media.download", {"source_video_id": 2, "file_bytes": 900}),
                    ("llm.provider_created", {"name": "p1"}),
                    ("source.confirmed", {"source_video_id": 1}),
                ]
            ):
                conn.execute(
                    sa.text(
                        "INSERT INTO audit_events (channel_id, event_type, detail) "
                        "VALUES (1, :t, :d)"
                    ),
                    {"t": etype, "d": json.dumps(detail)},
                )
    finally:
        engine.dispose()


class TestPipelineView:
    def test_overview_empty(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, _ = _view_env(tmp_path)
            try:
                result = await PipelineViewService(sessionmaker, settings).overview()
                return result
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        assert result["active"] == []
        assert result["queued"] == []
        assert result["recent"] == []

    def test_active_card_fields_and_download_bytes(self, tmp_path):
        async def scenario():
            media_root = tmp_path / "media"
            (media_root / "downloads").mkdir(parents=True)
            # Yarim indirme dosyasi: part boyutu kartta gorunmeli.
            part = media_root / "downloads" / "2.f401.mp4.part"
            part.write_bytes(b"x" * 4096)
            sessionmaker, settings, engine, db = _view_env(
                tmp_path, media_root=str(media_root)
            )
            try:
                _seed(db)
                _seed_jobs(db)
                result = await PipelineViewService(sessionmaker, settings).overview()
                return result
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        active = result["active"]
        assert len(active) == 1
        card = active[0]
        assert card["job_type"] == "media_process"
        assert card["title"] == "Indirilen video"
        assert card["channel_name"] == "Test Kanal"
        assert card["stage"] == "download"
        assert card["stage_index"] == 0
        assert card["stage_count"] == 5
        assert card["elapsed_seconds"] is not None and card["elapsed_seconds"] >= 0
        # Ortalama 2 bitmis isten (10+20 dk)/2 = 15 dk; 2 dk gecti -> ~13 dk.
        assert card["average_seconds"] == 900
        assert card["eta_seconds"] is not None and 700 <= card["eta_seconds"] <= 900
        # Indirme olcumu: part dosyasinin bayti + islenmis ortalamasi 5000.
        assert card["download"]["bytes"] == 4096
        assert card["download"]["expected_bytes"] == 5000
        # Kuyrukta tek is: sirada pozisyon 1.
        assert len(result["queued"]) == 1
        assert result["queued"][0]["title"] == "Siradaki video"
        assert result["queued"][0]["position"] == 1

    def test_recent_carries_error_summary(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _view_env(tmp_path)
            try:
                _seed(db)
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.begin() as conn:
                    conn.execute(
                        sa.text(
                            "INSERT INTO jobs (job_type, payload, status, "
                            "priority, attempts, max_attempts, last_error) "
                            "VALUES "
                            "('media_process', :p, 'failed', 5, 3, 3, :e)"
                        ),
                        {
                            "p": json.dumps({"source_video_id": 3}),
                            "e": "MediaPipelineError: yt-dlp basarisiz",
                        },
                    )
                eng.dispose()
                result = await PipelineViewService(sessionmaker, settings).overview()
                return result
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        failed = [r for r in result["recent"] if r["status"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["error"].startswith("MediaPipelineError")

    def test_api_endpoints_roundtrip(self, tmp_path):
        from tests.conftest import _make_app

        app = _make_app(tmp_path, media_root="")
        seed_db = app.state.test_db_path
        _seed(seed_db)
        _seed_jobs(seed_db)
        _seed_events(seed_db)
        with TestClient(app) as client:
            pipeline = client.get("/api/pipeline").json()
            assert len(pipeline["active"]) == 1
            assert pipeline["active"][0]["title"] == "Indirilen video"

            media = client.get("/api/media").json()
            assert media["sources_total"] == 3
            assert media["summary"]["processed"] == 1
            tags = {s["id"]: s["tag"] for s in media["sources"]}
            assert tags[1] == "#done"
            assert tags[2] == "#downloading"
            assert tags[3] == "#queued"

            logs = client.get("/api/logs").json()
            assert len(logs["entries"]) == 4
            assert logs["entries"][0]["channel_name"] == "Test Kanal"
            assert set(logs["categories"]) == {"media", "llm", "source"}

            only_media = client.get("/api/logs", params={"category": "media"}).json()
            assert len(only_media["entries"]) == 2

            channel_filter = client.get(
                "/api/logs", params={"channel_id": 1}
            ).json()
            assert len(channel_filter["entries"]) == 4

            # Sayfalama: en yeni iki olayin id'sinden sonrasina in.
            newest_two = logs["entries"][:2]
            cursor = min(e["id"] for e in newest_two)
            page2 = client.get("/api/logs", params={"before_id": cursor}).json()
            assert all(e["id"] < cursor for e in page2["entries"])
            assert len(page2["entries"]) == 2


class TestLibraryView:
    def test_failed_asset_reads_as_error(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _view_env(tmp_path)
            try:
                _seed(db)
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.begin() as conn:
                    conn.execute(
                        sa.text(
                            "UPDATE media_assets SET status='failed' "
                            "WHERE source_video_id=2"
                        )
                    )
                    conn.execute(
                        sa.text(
                            "INSERT INTO rendered_clips "
                            "(clip_candidate_id, source_video_id, orientation, "
                            " status, file_path, file_bytes, duration_seconds, "
                            " width, height, webcam_confidence) "
                            "VALUES (NULL, 1, 'vertical', 'rendered', "
                            "'/x/clip.mp4', 4096, 45.5, 1080, 1920, 0.0)"
                        )
                    )
                eng.dispose()
                result = await LibraryViewService(
                    sessionmaker, settings
                ).media_library()
                return result
            finally:
                await engine.dispose()

        result = asyncio.run(scenario())
        tags = {s["id"]: s["tag"] for s in result["sources"]}
        assert tags[2] == "#error"
        assert result["clips_total"] == 1
        clip = result["clips"][0]
        assert clip["title"] == "Islenmis video"
        assert clip["orientation"] == "vertical"
        assert result["summary"]["shorts_ready"] == 1

    def test_excluded_hidden_by_default(self, tmp_path):
        """Kabul kriteri: kuralin hariç tuttugu videolar varsayilan
        listede gorunmez; 'Haric' filtresi isteyince listelenir."""

        async def scenario():
            sessionmaker, settings, engine, db = _view_env(tmp_path)
            try:
                _seed(db)
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.begin() as conn:
                    conn.execute(
                        sa.text(
                            "UPDATE source_videos SET status='excluded' "
                            "WHERE id=3"
                        )
                    )
                eng.dispose()
                service = LibraryViewService(sessionmaker, settings)
                default = await service.media_library()
                with_excluded = await service.media_library(
                    include_excluded=True
                )
                return default, with_excluded
            finally:
                await engine.dispose()

        default, with_excluded = asyncio.run(scenario())
        default_ids = [s["id"] for s in default["sources"]]
        assert 3 not in default_ids
        assert len(default_ids) == 2
        assert default["sources_total"] == 2
        assert default["summary"]["sources_total"] == 2
        tags = {s["id"]: s["tag"] for s in with_excluded["sources"]}
        assert tags[3] == "#excluded"
        assert with_excluded["sources_total"] == 3
        assert with_excluded["summary"]["sources_total"] == 3


class TestAuditView:
    def test_pagination_and_categories(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _view_env(tmp_path)
            try:
                _seed(db)
                _seed_events(db)
                service = AuditViewService(sessionmaker, settings)
                first = await service.page(limit=2)
                second = await service.page(
                    limit=10, before_id=first["entries"][-1]["id"]
                )
                return first, second
            finally:
                await engine.dispose()

        first, second = asyncio.run(scenario())
        assert first["has_more"] is True
        assert len(first["entries"]) == 2
        assert first["entries"][0]["id"] > first["entries"][1]["id"]
        assert len(second["entries"]) == 2
        assert second["has_more"] is False
        assert second["entries"][0]["category"] in {"media", "llm", "source"}
