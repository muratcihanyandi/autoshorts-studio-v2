"""Media storage tree: labelled folders under MEDIA_ROOT."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.services.media_storage import (
    MEDIA_SUBDIRS,
    ensure_media_tree,
    media_subdir,
)
from app.worker import JobWorker
from tests.conftest import _make_app


class TestMediaTree:
    def test_ensure_media_tree_creates_labelled_folders(self, tmp_path):
        root = tmp_path / "Autoshorts_Studio"
        paths = ensure_media_tree(root)
        assert tuple(paths.keys()) == MEDIA_SUBDIRS
        for name, path in paths.items():
            assert path.is_dir(), name
        # İkinci çağrı idempotent.
        ensure_media_tree(root)

    def test_media_subdir_validates_name(self, tmp_path):
        assert media_subdir(tmp_path, "downloads") == Path(tmp_path) / "downloads"
        try:
            media_subdir(tmp_path, "baska")
            raised = False
        except ValueError:
            raised = True
        assert raised

    def test_lifespan_builds_tree_when_media_root_set(self, tmp_path):
        media_root = tmp_path / "media"
        with TestClient(_make_app(tmp_path, media_root=str(media_root))) as client:
            tree = client.app.state.media_tree
            assert set(tree.keys()) == set(MEDIA_SUBDIRS)
            assert (media_root / "downloads").is_dir()
            assert (media_root / "edited").is_dir()
            assert (media_root / "clips").is_dir()
            assert (media_root / "stock").is_dir()
            assert (media_root / "tmp").is_dir()

    def test_lifespan_without_media_root_creates_nothing(self, tmp_path):
        with TestClient(_make_app(tmp_path)) as client:
            assert getattr(client.app.state, "media_tree", None) is None

    def test_disk_ok_checks_media_root_disk(self, tmp_path):
        import asyncio

        import sqlalchemy as sa

        from app.db import create_engine_and_sessionmaker
        from app.models import Base
        from app.services.job_service import JobService

        db = tmp_path / "disk.db"
        eng = sa.create_engine(f"sqlite:///{db}")
        Base.metadata.create_all(eng)
        eng.dispose()
        media_root = str(tmp_path / "media")
        # lifespan'deki gibi agac kurulu olmali; yoksa disk_usage hata verir.
        ensure_media_tree(media_root)

        async def make_service(min_free_gb: float) -> JobService:
            settings = Settings(
                database_url=f"sqlite+aiosqlite:///{db}",
                media_root=media_root,
                min_free_disk_gb=min_free_gb,
            )
            engine, sessionmaker = create_engine_and_sessionmaker(
                settings.database_url
            )
            service = JobService(sessionmaker, settings)
            # motorun kapanmasini test sonrasina birakmamak icin kaydet
            service._test_engine = engine
            return service

        async def scenario():
            tight = await make_service(99999)
            loose = await make_service(0)
            results = (tight.disk_ok(), loose.disk_ok())
            await tight._test_engine.dispose()
            await loose._test_engine.dispose()
            return results

        tight_ok, loose_ok = asyncio.run(scenario())
        # media_root diskine bakar: 999GB sartiyla engellenmeli, 0 ile gecer.
        assert tight_ok is False
        assert loose_ok is True


class TestWorkerTmpCleanup:
    def test_cleanup_tmp_once_prunes_stale_files(self, tmp_path):
        import asyncio

        import sqlalchemy as sa

        from app.db import create_engine_and_sessionmaker
        from app.models import Base

        media_root = tmp_path / "media"
        ensure_media_tree(media_root)

        stale = media_root / "tmp" / "eski.ts"
        fresh = media_root / "tmp" / "yeni.ts"
        for path, age in ((stale, 48), (fresh, 1)):
            path.write_bytes(b"x")
            stamp = datetime.now(UTC) - timedelta(hours=age)
            os.utime(path, (stamp.timestamp(), stamp.timestamp()))

        db = tmp_path / "w.db"
        eng = sa.create_engine(f"sqlite:///{db}")
        Base.metadata.create_all(eng)
        eng.dispose()
        settings = Settings(
            database_url=f"sqlite+aiosqlite:///{db}",
            media_root=str(media_root),
        )
        engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)

        async def scenario():
            worker = JobWorker(sessionmaker, settings)
            removed = await worker.cleanup_tmp_once(max_age_hours=24)
            await engine.dispose()
            return removed

        removed = asyncio.run(scenario())
        assert removed == ["eski.ts"]
        assert not stale.exists()
        assert fresh.exists()

    def test_cleanup_disabled_without_media_root(self, tmp_path):
        import asyncio

        from app.db import create_engine_and_sessionmaker
        from app.models import Base

        import sqlalchemy as sa

        db = tmp_path / "w2.db"
        eng = sa.create_engine(f"sqlite:///{db}")
        Base.metadata.create_all(eng)
        eng.dispose()
        settings = Settings(database_url=f"sqlite+aiosqlite:///{db}")
        engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)

        async def scenario():
            worker = JobWorker(sessionmaker, settings)
            removed = await worker.cleanup_tmp_once()
            await engine.dispose()
            return removed

        assert asyncio.run(scenario()) == []
