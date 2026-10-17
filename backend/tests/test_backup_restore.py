"""Backup/restore tooling (M12): sqlite online backup + verified restore.

The tool must restore a populated database so the app can run against
it — verified by core-table row counts before and after.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    ClipCandidate,
    MediaAsset,
    SourceChannel,
    SourceVideo,
)

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "backup_database.py"


def _env(tmp_path):
    db_path = tmp_path / "backup.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{db_path}")
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine, str(db_path)


async def _populate(sessionmaker) -> None:
    async with sessionmaker() as session:
        channel = Channel(name="Kanal")
        session.add(channel)
        await session.flush()
        source = SourceChannel(
            channel_id=channel.id,
            youtube_channel_id="UCx",
            title="Kaynak",
            permission_status="authorized",
        )
        session.add(source)
        await session.flush()
        video = SourceVideo(
            source_channel_id=source.id,
            youtube_video_id="v1",
            title="Video",
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
                file_path="/x.mp4",
            )
        )
        session.add(
            ClipCandidate(
                source_video_id=video.id,
                start_seconds=1.0,
                end_seconds=4.0,
                duration_seconds=3.0,
                score=0.9,
                status="candidate",
            )
        )
        await session.commit()


class TestBackupRestore:
    def test_backup_then_restore_verifies_counts(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _env(tmp_path)
            try:
                await _populate(sessionmaker)
            finally:
                await engine.dispose()

        asyncio.run(scenario())

        backup_file = tmp_path / "backup.db.bak"
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS),
                "backup",
                "--url",
                f"sqlite:///{tmp_path}/backup.db",
                "--out",
                str(backup_file),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert backup_file.is_file() and backup_file.stat().st_size > 0

        # Kaynak DB'yi 'kaybet' ve yedekten farkli bir hedefe geri yukle.
        restored = tmp_path / "restored.db"
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS),
                "restore",
                "--url",
                f"sqlite:///{restored}",
                "--from",
                str(backup_file),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr

        # Dogrulama: cekirdek tablo sayilari birebir.
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS),
                "verify",
                "--url",
                f"sqlite:///{tmp_path}/backup.db",
                "--against",
                str(restored),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        import json

        report = json.loads(result.stdout)
        assert report["ok"] is True, report
        assert report["counts_after"]["channels"] == 1
        assert report["counts_after"]["clip_candidates"] == 1

        # Geri yuklenen DB uygulama modeliyle acilabilmeli.
        sync_engine = sa.create_engine(f"sqlite:///{restored}")
        with sync_engine.connect() as conn:
            channels = conn.execute(
                sa.text("SELECT COUNT(*) FROM channels")
            ).scalar()
        sync_engine.dispose()
        assert channels == 1

    def test_missing_source_fails_cleanly(self, tmp_path):
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS),
                "backup",
                "--url",
                f"sqlite:///{tmp_path}/yok.db",
                "--out",
                str(tmp_path / "out.bak"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
        assert "yok" in result.stderr or "Kaynak" in result.stderr
