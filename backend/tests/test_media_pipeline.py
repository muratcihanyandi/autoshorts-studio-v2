"""Milestone 7 media pipeline: models, download, and orchestration.

Schema and constraint tests run on FK-enforcing sqlite (production
parity per ADR-008). Media-tooling tests invoke the real ffmpeg/ffprobe
binaries from PATH; the dev machine and CI image both provide them.
"""
from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import (
    Base,
    Channel,
    ClipCandidate,
    MediaAsset,
    MediaInspection,
    SourceChannel,
    SourceVideo,
    Transcript,
)


def _pipeline_env(tmp_path, **overrides):
    """Kendi motoruyla çalışan sqlite ortamı: (sessionmaker, settings, engine)."""
    db_path = tmp_path / "media.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **overrides
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine


def _sync_one(tmp_path, table: str, row_id: int, column: str):
    db_path = tmp_path / "media.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text(f"SELECT {column} FROM {table} WHERE id = {row_id}")
            ).scalar()
    finally:
        engine.dispose()


async def _seed_planned_video(sessionmaker) -> tuple[int, int, int]:
    """Yetkili kaynak + 'planned' video; (channel, source, video) id'leri."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with sessionmaker() as session:  # type: AsyncSession
        channel = Channel(name="Kanal")
        session.add(channel)
        await session.flush()
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
            title="Test videosu",
            status="planned",
        )
        session.add(video)
        await session.commit()
        return channel.id, source.id, video.id


class TestMediaModels:
    def test_rows_persist_with_relations(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(tmp_path)
            try:
                _, _, video_id = await _seed_planned_video(sessionmaker)
                async with sessionmaker() as session:
                    asset = MediaAsset(
                        source_video_id=video_id,
                        origin="local_import",
                        file_path="/media/downloads/1.mp4",
                        file_bytes=1024,
                        sha256="a" * 64,
                        status="inspected",
                        stage="inspect",
                        analysis={"silences": [[0.0, 2.0]]},
                    )
                    session.add(asset)
                    await session.flush()
                    session.add(
                        MediaInspection(
                            media_asset_id=asset.id,
                            duration_seconds=12.0,
                            width=320,
                            height=240,
                            fps=15.0,
                            video_codec="h264",
                            audio_codec="aac",
                            has_audio=True,
                            format_name="mov,mp4,m4a",
                            raw={"format": {"duration": "12.0"}},
                        )
                    )
                    session.add(
                        Transcript(
                            media_asset_id=asset.id,
                            language="tr",
                            source="sidecar",
                            segment_count=1,
                            segments=[
                                {"start": 0.0, "end": 2.0, "text": "merhaba"}
                            ],
                            raw_path="/media/downloads/1.vtt",
                        )
                    )
                    first = ClipCandidate(
                        source_video_id=video_id,
                        start_seconds=2.0,
                        end_seconds=22.0,
                        duration_seconds=20.0,
                        score=0.75,
                        status="candidate",
                        detail={"energy": 0.6, "scenes": 3},
                    )
                    session.add(first)
                    await session.flush()
                    session.add(
                        ClipCandidate(
                            source_video_id=video_id,
                            start_seconds=30.0,
                            end_seconds=50.0,
                            duration_seconds=20.0,
                            score=0.4,
                            status="rejected",
                            duplicate_of_candidate_id=first.id,
                            reason="benzer icerik",
                        )
                    )
                    await session.commit()
                    asset_id = asset.id
                    first_id = first.id

                async with sessionmaker() as session:
                    reloaded = await session.get(MediaAsset, asset_id)
                    candidates = (
                        (
                            await session.execute(
                                sa.select(ClipCandidate).where(
                                    ClipCandidate.source_video_id == video_id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    inspection = (
                        (
                            await session.execute(
                                sa.select(MediaInspection).where(
                                    MediaInspection.media_asset_id == asset_id
                                )
                            )
                        )
                        .scalars()
                        .one()
                    )
                    return reloaded, inspection, candidates, first_id
            finally:
                await engine.dispose()

        asset, inspection, candidates, first_id = asyncio.run(scenario())
        assert asset.origin == "local_import"
        assert asset.analysis["silences"] == [[0.0, 2.0]]
        assert inspection.duration_seconds == 12.0
        assert inspection.has_audio is True
        assert len(candidates) == 2
        rejected = [c for c in candidates if c.status == "rejected"][0]
        assert rejected.duplicate_of_candidate_id == first_id

    def test_unique_source_video_per_asset(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(tmp_path)
            try:
                _, _, video_id = await _seed_planned_video(sessionmaker)
                async with sessionmaker() as session:
                    session.add(
                        MediaAsset(
                            source_video_id=video_id,
                            origin="youtube",
                            file_path="/a.mp4",
                        )
                    )
                    await session.commit()
                async with sessionmaker() as session:
                    session.add(
                        MediaAsset(
                            source_video_id=video_id,
                            origin="youtube",
                            file_path="/b.mp4",
                        )
                    )
                    try:
                        await session.commit()
                        error = None
                    except IntegrityError as exc:
                        error = exc
                return error
            finally:
                await engine.dispose()

        assert asyncio.run(scenario()) is not None

    def test_unique_inspection_and_transcript_per_asset(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(tmp_path)
            try:
                _, _, video_id = await _seed_planned_video(sessionmaker)
                async with sessionmaker() as session:
                    asset = MediaAsset(
                        source_video_id=video_id,
                        origin="youtube",
                        file_path="/a.mp4",
                    )
                    session.add(asset)
                    await session.flush()
                    session.add(
                        MediaInspection(
                            media_asset_id=asset.id,
                            duration_seconds=5.0,
                            width=10,
                            height=10,
                            fps=30.0,
                            video_codec="h264",
                        )
                    )
                    session.add(
                        Transcript(
                            media_asset_id=asset.id,
                            source="sidecar",
                            segments=[],
                        )
                    )
                    await session.commit()
                    asset_id = asset.id
                inspection_error = None
                transcript_error = None
                async with sessionmaker() as session:
                    session.add(
                        MediaInspection(
                            media_asset_id=asset_id,
                            duration_seconds=6.0,
                            width=10,
                            height=10,
                            fps=30.0,
                            video_codec="h264",
                        )
                    )
                    try:
                        await session.commit()
                    except IntegrityError as exc:
                        inspection_error = exc
                async with sessionmaker() as session:
                    session.add(
                        Transcript(
                            media_asset_id=asset_id,
                            source="sidecar",
                            segments=[],
                        )
                    )
                    try:
                        await session.commit()
                    except IntegrityError as exc:
                        transcript_error = exc
                return inspection_error, transcript_error
            finally:
                await engine.dispose()

        inspection_error, transcript_error = asyncio.run(scenario())
        assert inspection_error is not None
        assert transcript_error is not None

    def test_check_constraints_reject_bad_values(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(tmp_path)
            try:
                _, _, video_id = await _seed_planned_video(sessionmaker)
                range_error = None
                status_error = None
                async with sessionmaker() as session:
                    session.add(
                        ClipCandidate(
                            source_video_id=video_id,
                            start_seconds=30.0,
                            end_seconds=30.0,
                            duration_seconds=0.0,
                        )
                    )
                    try:
                        await session.commit()
                    except IntegrityError as exc:
                        range_error = exc
                async with sessionmaker() as session:
                    session.add(
                        MediaAsset(
                            source_video_id=video_id,
                            origin="torrent",  # gecersiz origin
                            file_path="/a.mp4",
                        )
                    )
                    try:
                        await session.commit()
                    except IntegrityError as exc:
                        status_error = exc
                return range_error, status_error
            finally:
                await engine.dispose()

        range_error, status_error = asyncio.run(scenario())
        assert range_error is not None  # end > start ihlali
        assert status_error is not None  # origin sozlugu ihlali


class TestLocalImportAdapter:
    def test_copies_file_and_preserves_original(self, tmp_path):
        from app.services.media_download import LocalImportAdapter

        source = tmp_path / "kaynak.mp4"
        source.write_bytes(b"FAKEVIDEO" * 100)
        dest_dir = tmp_path / "media" / "downloads"

        async def scenario():
            adapter = LocalImportAdapter(source)
            return await adapter.fetch(7, "vid-1", dest_dir)

        result = asyncio.run(scenario())
        assert result.origin == "local_import"
        assert result.file_bytes == 900
        assert result.path.name == "7.mp4"
        assert result.path.is_file()
        # Orijinal dosya yerinde ve icerigi ayni (tasinmaz, kopyalanir).
        assert source.is_file()
        assert source.read_bytes() == result.path.read_bytes()

    def test_missing_and_empty_files_rejected(self, tmp_path):
        from app.services.media_download import (
            LocalImportAdapter,
            MediaDownloadError,
        )

        async def scenario():
            missing = LocalImportAdapter(tmp_path / "yok.mp4")
            try:
                await missing.fetch(1, "v", tmp_path / "d")
                missing_error = None
            except MediaDownloadError as exc:
                missing_error = str(exc)
            empty = tmp_path / "bos.mp4"
            empty.write_bytes(b"")
            empty_adapter = LocalImportAdapter(empty)
            try:
                await empty_adapter.fetch(1, "v", tmp_path / "d")
                empty_error = None
            except MediaDownloadError as exc:
                empty_error = str(exc)
            return missing_error, empty_error

        missing_error, empty_error = asyncio.run(scenario())
        assert missing_error is not None
        assert empty_error is not None


class TestYtDlpAdapter:
    def _settings(self, **overrides):
        return Settings(database_url="", **overrides)

    def test_command_construction_with_rate_limit(self, tmp_path):
        from app.services.media_download import YtDlpAdapter

        adapter = YtDlpAdapter(self._settings(download_rate_limit_kbps=512))
        cmd = adapter.build_command("abc123", tmp_path, str(tmp_path / "1.%(ext)s"))
        assert cmd[0] == "yt-dlp"
        assert "--limit-rate" in cmd
        assert cmd[cmd.index("--limit-rate") + 1] == "512K"
        assert cmd[-1] == "https://www.youtube.com/watch?v=abc123"
        assert "--write-auto-subs" in cmd  # transkript asamasi icin altyazi

    def test_command_without_rate_limit(self, tmp_path):
        from app.services.media_download import YtDlpAdapter

        adapter = YtDlpAdapter(self._settings(download_rate_limit_kbps=0))
        cmd = adapter.build_command("abc", tmp_path, str(tmp_path / "1.%(ext)s"))
        assert "--limit-rate" not in cmd

    def test_fetch_with_fake_runner(self, tmp_path):
        from app.services.media_download import YtDlpAdapter

        calls = []

        async def fake_runner(cmd):
            calls.append(cmd)
            output = tmp_path / "downloads" / "3.mp4"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"YTDLP-OUTPUT")
            return 0

        async def scenario():
            adapter = YtDlpAdapter(self._settings(), runner=fake_runner)
            return await adapter.fetch(
                3, "vid-abc", tmp_path / "downloads"
            )

        result = asyncio.run(scenario())
        assert result.origin == "youtube"
        assert result.path.name == "3.mp4"
        assert result.file_bytes == 12
        assert len(calls) == 1
        assert any("vid-abc" in part for part in calls[0])

    def test_missing_binary_reports_turkish_error(self, tmp_path, monkeypatch):
        from app.services.media_download import (
            MediaDownloadError,
            YtDlpAdapter,
        )

        monkeypatch.setattr(
            "app.services.media_download.shutil.which", lambda name: None
        )

        async def scenario():
            adapter = YtDlpAdapter(self._settings())  # gercek subprocess yolu
            try:
                await adapter.fetch(5, "vid-x", tmp_path / "downloads")
                return None
            except MediaDownloadError as exc:
                return str(exc)

        message = asyncio.run(scenario())
        assert message is not None
        assert "yt-dlp" in message
