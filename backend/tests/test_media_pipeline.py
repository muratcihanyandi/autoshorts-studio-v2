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
from tests.media_sample import make_test_media


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

    def test_copies_sidecar_alongside_media(self, tmp_path):
        from app.services.media_download import LocalImportAdapter

        source = tmp_path / "kaynak.mp4"
        source.write_bytes(b"FAKEVIDEO")
        (tmp_path / "kaynak.vtt").write_text("WEBVTT\n", encoding="utf-8")
        dest_dir = tmp_path / "downloads"

        async def scenario():
            adapter = LocalImportAdapter(source)
            return await adapter.fetch(9, "vid-1", dest_dir)

        result = asyncio.run(scenario())
        assert (dest_dir / "9.mp4").is_file()
        assert (dest_dir / "9.vtt").is_file()


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


# --- Uctan uca boru hatti (ROADMAP M7 kabul kriterleri) ---

VTT_E2E = """WEBVTT

00:00:02.000 --> 00:00:05.000
bugun kanalda cok onemli bir konuyu anlatiyoruz

00:00:05.000 --> 00:00:10.000
bu konu seyirciler icin buyuk bir firsat sunuyor arkadaslar
"""


@pytest.fixture(scope="module")
def sample_pair(tmp_path_factory):
    """Sentetik medya + ayni adli altyazi: yerel iceri aktarim kaynagi."""
    base = tmp_path_factory.mktemp("e2e")
    media = make_test_media(base / "kaynak.mp4")
    (base / "kaynak.vtt").write_text(VTT_E2E, encoding="utf-8")
    return base


def _e2e_settings(tmp_path, **overrides):
    """Kisa klip sinirlari: 12s ornekten aday uretilebilsin.

    Medya agaci uygulamadaki lifespan gibi burada da kurulur; disk
    kontrolu (shutil.disk_usage) mevcut klasor ister.
    """
    from app.services.media_storage import ensure_media_tree

    ensure_media_tree(tmp_path / "media")
    kwargs = dict(
        media_root=str(tmp_path / "media"),
        clip_min_seconds=3,
        clip_max_seconds=6,
    )
    kwargs.update(overrides)
    return kwargs


def _sync_rows(tmp_path, query: str):
    engine = sa.create_engine(f"sqlite:///{tmp_path}/media.db")
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(query)).all()
    finally:
        engine.dispose()


async def _seed_extra_video(sessionmaker, source_id: int, video_id: int):
    async with sessionmaker() as session:
        session.add(
            SourceVideo(
                id=video_id,
                source_channel_id=source_id,
                youtube_video_id=f"vid-{video_id}",
                title=f"Ek video {video_id}",
                status="planned",
            )
        )
        await session.commit()


class TestMediaPipelineEndToEnd:
    def test_full_pipeline_with_local_import(self, tmp_path, sample_pair):
        from app.services.media_pipeline import MediaPipelineService

        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(
                tmp_path, **_e2e_settings(tmp_path)
            )
            try:
                _, _, video_id = await _seed_planned_video(sessionmaker)
                service = MediaPipelineService(sessionmaker, settings)
                result = await service.run(
                    video_id, import_path=str(sample_pair / "kaynak.mp4")
                )
                return result, video_id
            finally:
                await engine.dispose()

        result, video_id = asyncio.run(scenario())
        assert result == {"source_video_id": video_id, "processed": True}

        # Dort tablo da doldu mu?
        asset = _sync_rows(
            tmp_path, "SELECT id, status, stage, file_bytes, sha256 FROM media_assets"
        )
        assert len(asset) == 1
        assert asset[0].status == "processed"
        assert asset[0].file_bytes > 0
        assert len(asset[0].sha256) == 64

        inspection = _sync_rows(
            tmp_path,
            "SELECT duration_seconds, width, height, has_audio"
            " FROM media_inspections",
        )
        assert len(inspection) == 1
        assert inspection[0].duration_seconds > 10.0
        assert inspection[0].width == 320
        assert inspection[0].has_audio == 1

        transcripts = _sync_rows(
            tmp_path, "SELECT source, segment_count FROM transcripts"
        )
        assert len(transcripts) == 1
        assert transcripts[0].source == "sidecar"
        assert transcripts[0].segment_count == 2

        candidates = _sync_rows(
            tmp_path,
            "SELECT start_seconds, end_seconds, duration_seconds, score,"
            " status FROM clip_candidates",
        )
        assert len(candidates) >= 1
        duration = inspection[0].duration_seconds
        for row in candidates:
            # Kabul kriteri: aday zaman damgalari gecerli.
            assert 0 <= row.start_seconds < row.end_seconds <= duration
            assert 3 <= row.duration_seconds <= 6
            assert row.status == "candidate"

        # Video islendi; denetim izi her asamayi kaydetti.
        assert _sync_one(tmp_path, "source_videos", video_id, "status") == "processed"
        events = _sync_rows(tmp_path, "SELECT event_type FROM audit_events")
        event_types = {row.event_type for row in events}
        assert {
            "media.download",
            "media.inspect",
            "media.transcript",
            "media.analysis",
            "media.candidates",
        } <= event_types

        # Orijinal dosya yerinde kaldi (kabul kriteri: orijinaller korunur).
        assert (sample_pair / "kaynak.mp4").is_file()
        assert (sample_pair / "kaynak.vtt").is_file()

    def test_rerun_processed_video_is_idempotent(self, tmp_path, sample_pair):
        from app.services.media_pipeline import MediaPipelineService

        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(
                tmp_path, **_e2e_settings(tmp_path)
            )
            try:
                _, _, video_id = await _seed_planned_video(sessionmaker)
                service = MediaPipelineService(sessionmaker, settings)
                first = await service.run(
                    video_id, import_path=str(sample_pair / "kaynak.mp4")
                )
                second = await service.run(
                    video_id, import_path=str(sample_pair / "kaynak.mp4")
                )
                return first, second
            finally:
                await engine.dispose()

        first, second = asyncio.run(scenario())
        assert first["processed"] is True
        assert second.get("skipped") is True
        # Satir sayilari degismedi: tek varlik, tek inspeksiyon, ayni adaylar.
        assert len(_sync_rows(tmp_path, "SELECT id FROM media_assets")) == 1
        assert len(_sync_rows(tmp_path, "SELECT id FROM media_inspections")) == 1
        assert len(_sync_rows(tmp_path, "SELECT id FROM transcripts")) == 1

    def test_failure_recorded_and_retry_resumes(self, tmp_path, sample_pair):
        from app.services.media_pipeline import (
            MediaPipelineError,
            MediaPipelineService,
        )

        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(
                tmp_path, **_e2e_settings(tmp_path)
            )
            try:
                _, _, video_id = await _seed_planned_video(sessionmaker)
                service = MediaPipelineService(sessionmaker, settings)
                try:
                    await service.run(
                        video_id, import_path=str(tmp_path / "yok.mp4")
                    )
                    failed = None
                except MediaPipelineError as exc:
                    failed = str(exc)
                recovered = await service.run(
                    video_id, import_path=str(sample_pair / "kaynak.mp4")
                )
                return failed, recovered, video_id
            finally:
                await engine.dispose()

        failed, recovered, video_id = asyncio.run(scenario())
        assert failed is not None  # hata kayda gecti
        assert recovered["processed"] is True  # kurtarma ayni kaynaktan devam
        assert len(_sync_rows(tmp_path, "SELECT id FROM media_assets")) == 1
        assert _sync_one(tmp_path, "source_videos", video_id, "status") == "processed"
        asset = _sync_rows(
            tmp_path, "SELECT status, last_error FROM media_assets"
        )[0]
        assert asset.status == "processed"

    def test_corrupt_media_fails_integrity_and_stays_recoverable(
        self, tmp_path, sample_pair
    ):
        from app.services.media_pipeline import (
            MediaPipelineError,
            MediaPipelineService,
        )

        corrupt = tmp_path / "bozuk.mp4"
        media_bytes = (sample_pair / "kaynak.mp4").read_bytes()
        corrupt.write_bytes(media_bytes[: len(media_bytes) // 3])

        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(
                tmp_path, **_e2e_settings(tmp_path)
            )
            try:
                _, _, video_id = await _seed_planned_video(sessionmaker)
                service = MediaPipelineService(sessionmaker, settings)
                try:
                    await service.run(video_id, import_path=str(corrupt))
                    error = None
                except MediaPipelineError as exc:
                    error = str(exc)
                return error, video_id
            finally:
                await engine.dispose()

        error, video_id = asyncio.run(scenario())
        assert error is not None
        asset = _sync_rows(
            tmp_path, "SELECT status, stage, last_error FROM media_assets"
        )[0]
        # Hata kaydedildi; asama 'inspect'te kaldigi icin yeniden deneme
        # ayni asamadan devam eder (indirme tekrar yapilmaz).
        assert asset.status == "failed"
        assert asset.stage == "inspect"
        assert asset.last_error is not None
        assert _sync_one(tmp_path, "source_videos", video_id, "status") == "planned"

    def test_unauthorized_source_rejected(self, tmp_path, sample_pair):
        from app.services.media_pipeline import (
            MediaPipelineError,
            MediaPipelineService,
        )

        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(
                tmp_path, **_e2e_settings(tmp_path)
            )
            try:
                from sqlalchemy.ext.asyncio import AsyncSession

                async with sessionmaker() as session:  # type: AsyncSession
                    channel = Channel(name="Kanal")
                    session.add(channel)
                    await session.flush()
                    source = SourceChannel(
                        channel_id=channel.id,
                        youtube_channel_id="UCpend",
                        title="Bekleyen",
                        permission_status="pending",
                    )
                    session.add(source)
                    await session.flush()
                    video = SourceVideo(
                        source_channel_id=source.id,
                        youtube_video_id="vid-p",
                        title="Video",
                        status="planned",
                    )
                    session.add(video)
                    await session.commit()
                    video_id = video.id

                service = MediaPipelineService(sessionmaker, settings)
                try:
                    await service.run(
                        video_id, import_path=str(sample_pair / "kaynak.mp4")
                    )
                    error = None
                except MediaPipelineError as exc:
                    error = str(exc)
                return error
            finally:
                await engine.dispose()

        error = asyncio.run(scenario())
        assert error is not None
        assert "yetkili" in error

    def test_sequential_download_lock_serializes(self, tmp_path, sample_pair):
        from app.services.media_download import DownloadResult
        from app.services.media_pipeline import MediaPipelineService

        class _TrackingAdapter:
            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0

            async def fetch(self, source_video_id, youtube_video_id, dest_dir):
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                await asyncio.sleep(0.2)
                dest = dest_dir / f"{source_video_id}.mp4"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"FAKE")
                self.active -= 1
                return DownloadResult(
                    path=dest, origin="youtube", file_bytes=4
                )

        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(
                tmp_path, **_e2e_settings(tmp_path)
            )
            try:
                _, source_id, video_id = await _seed_planned_video(sessionmaker)
                await _seed_extra_video(sessionmaker, source_id, video_id + 1)
                tracker = _TrackingAdapter()
                lock = asyncio.Lock()
                service = MediaPipelineService(
                    sessionmaker,
                    settings,
                    youtube_adapter=tracker,
                    download_lock=lock,
                )
                results = await asyncio.gather(
                    service.run(video_id),
                    service.run(video_id + 1),
                    return_exceptions=True,
                )
                return tracker, results
            finally:
                await engine.dispose()

        tracker, results = asyncio.run(scenario())
        # Kabul kriteri: sirali indirme — ayni anda tek indirme.
        assert tracker.max_active == 1
        # Indirme tamamlandi; sahte dosya inspeksiyonda patlar (beklenen).
        for result in results:
            assert isinstance(result, Exception)

    def test_similarity_rejects_duplicate_across_videos(
        self, tmp_path, sample_pair
    ):
        from app.services.media_pipeline import MediaPipelineService

        async def scenario():
            sessionmaker, settings, engine = _pipeline_env(
                tmp_path, **_e2e_settings(tmp_path)
            )
            try:
                _, source_id, video_id = await _seed_planned_video(sessionmaker)
                await _seed_extra_video(sessionmaker, source_id, video_id + 1)
                service = MediaPipelineService(sessionmaker, settings)
                await service.run(
                    video_id, import_path=str(sample_pair / "kaynak.mp4")
                )
                # Ayni medya + ayni altyazi: icerik benzerligi yakalamali.
                await service.run(
                    video_id + 1, import_path=str(sample_pair / "kaynak.mp4")
                )
                return video_id
            finally:
                await engine.dispose()

        video_id = asyncio.run(scenario())
        first = _sync_rows(
            tmp_path,
            f"SELECT id, status FROM clip_candidates"
            f" WHERE source_video_id = {video_id}",
        )
        second = _sync_rows(
            tmp_path,
            f"SELECT id, status, duplicate_of_candidate_id"
            f" FROM clip_candidates WHERE source_video_id = {video_id + 1}",
        )
        assert first and all(row.status == "candidate" for row in first)
        assert second, "ikinci videonun adaylari uretildi"
        rejected = [row for row in second if row.status == "rejected"]
        assert rejected, "benzer adaylar reddedilmeli"
        first_ids = {row.id for row in first}
        for row in rejected:
            assert row.duplicate_of_candidate_id in first_ids
