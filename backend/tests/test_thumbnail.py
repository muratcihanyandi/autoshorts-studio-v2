"""thumbnail: frame selection, text layout, jpg composition.

Real composition runs against a real ffmpeg-generated clip (face
stream fixture); the approve-flow integration verifies the
rendered_clips.thumbnail_path wiring through the API.
"""
from __future__ import annotations

import asyncio

import cv2
import numpy as np
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.services.thumbnail import (
    THUMB_H,
    THUMB_W,
    ThumbnailError,
    compose,
    find_font,
    fit_frame,
    pick_sharpest_frame,
    plan_text_lines,
    sharpness_score,
)
from tests.conftest import _make_app
from tests.media_sample import make_face_stream_video


class TestPureLogic:
    def test_sharper_frame_wins(self):
        rng = np.random.default_rng(5)
        flat = np.full((240, 320, 3), 128, dtype=np.uint8)
        detailed = rng.integers(0, 256, size=(240, 320, 3), dtype=np.uint8)
        assert sharpness_score(detailed) > sharpness_score(flat)

    def test_fit_frame_letterboxes_non_widescreen(self):
        tall = np.full((720, 480, 3), 200, dtype=np.uint8)  # 2:3
        canvas = fit_frame(tall)
        assert canvas.shape[:2] == (THUMB_H, THUMB_W)
        # Yanlarda siyah bantlar, ortada icerik
        assert canvas[THUMB_H // 2, 5].tolist() == [0, 0, 0]
        assert canvas[THUMB_H // 2, 5].tolist() == [0, 0, 0]
        assert canvas[THUMB_H // 2, THUMB_W // 2].tolist() == [200, 200, 200]

    def test_plan_text_lines_wraps_and_shrinks(self):
        lines, fontsize = plan_text_lines("kisa metin")
        assert lines == ["kisa metin"]
        assert fontsize == 72

        long_text = " ".join(["cok"] * 40)
        lines, fontsize = plan_text_lines(long_text)
        assert 1 < len(lines) <= 3
        assert fontsize < 72

        empty = plan_text_lines("   ")
        assert empty == ([], 0)

    def test_find_font_returns_existing_or_none(self, tmp_path):
        fake = tmp_path / "fonty.ttf"
        fake.write_bytes(b"x")
        assert find_font(str(fake)) == str(fake)
        assert find_font(str(tmp_path / "yok.ttf")) is None
        # Gercek adaylardan biri varsa bulmali (dev makinesi/imaj)
        found = find_font()
        assert found is None or isinstance(found, str)


class TestCompose:
    @classmethod
    def setup_class(cls):
        import tempfile
        from pathlib import Path

        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = make_face_stream_video(cls.tmp / "face.mp4")

    def test_compose_produces_1280x720_jpg(self, tmp_path):
        out = tmp_path / "thumbs" / "thumb.jpg"

        async def scenario():
            return await compose(
                "ffmpeg", self.video, "Bu Kesite Bak", out
            )

        result = asyncio.run(scenario())
        assert result == out
        assert out.is_file() and out.stat().st_size > 5_000
        image = cv2.imread(str(out))
        assert image is not None  # gecerli jpg
        assert image.shape[:2] == (THUMB_H, THUMB_W)

    def test_compose_without_text(self, tmp_path):
        out = tmp_path / "plain.jpg"

        async def scenario():
            return await compose("ffmpeg", self.video, "", out)

        asyncio.run(scenario())
        image = cv2.imread(str(out))
        assert image is not None
        assert image.shape[:2] == (THUMB_H, THUMB_W)

    def test_compose_turkish_text(self, tmp_path):
        out = tmp_path / "tr.jpg"

        async def scenario():
            return await compose(
                "ffmpeg", self.video, "İzlemeye Değer Kesit", out
            )

        asyncio.run(scenario())
        image = cv2.imread(str(out))
        assert image is not None
        assert image.shape[:2] == (THUMB_H, THUMB_W)

    def test_compose_missing_video_raises(self, tmp_path):
        async def scenario():
            try:
                await compose(
                    "ffmpeg",
                    tmp_path / "yok.mp4",
                    "metin",
                    tmp_path / "x.jpg",
                )
                return None
            except ThumbnailError as exc:
                return str(exc)

        message = asyncio.run(scenario())
        assert message is not None

    def test_pick_sharpest_from_real_video(self):
        frame = pick_sharpest_frame(self.video)
        assert frame is not None and frame.size > 0
        assert frame.shape[:2] == (720, 1280)


class TestApproveFlowThumbnail:
    """Onay akisi: metaveri onayi thumbnail uretir ve yolu render
    satirina yazar (dikey aday + yatay tam kesit)."""

    @classmethod
    def setup_class(cls):
        import tempfile
        from pathlib import Path

        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = make_face_stream_video(cls.tmp / "face.mp4")

    def test_candidate_approve_composes_thumbnail(self, tmp_path):
        from app.models import (
            Base,
            Channel,
            ClipCandidate,
            ClipMetadata,
            MediaAsset,
            RenderedClip,
            SourceChannel,
            SourceVideo,
        )

        app = _make_app(
            tmp_path,
            worker_enabled=False,
            media_root=str(tmp_path / "media"),
        )
        with TestClient(app) as client:
            sessionmaker = client.app.state.sessionmaker

            async def seed():
                async with sessionmaker() as session:
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
                            file_path=str(self.video),
                        )
                    )
                    candidate = ClipCandidate(
                        source_video_id=video.id,
                        start_seconds=1.0,
                        end_seconds=4.0,
                        duration_seconds=3.0,
                        score=0.8,
                    )
                    session.add(candidate)
                    await session.flush()
                    session.add(
                        RenderedClip(
                            clip_candidate_id=candidate.id,
                            orientation="vertical",
                            status="rendered",
                            file_path=str(self.video),
                        )
                    )
                    session.add(
                        ClipMetadata(
                            clip_candidate_id=candidate.id,
                            revision=1,
                            title="Onaylanacak Baslik",
                            description="Aciklama yeterince uzun olmali.",
                            tags=["kesit"],
                            thumbnail_text="Kapak Metni",
                            status="draft",
                        )
                    )
                    await session.commit()
                    return candidate.id

            candidate_id = asyncio.run(seed())

            approved = client.post(f"/api/clips/{candidate_id}/approve")
            assert approved.status_code == 200, approved.text

            engine = sa.create_engine(
                f"sqlite:///{tmp_path}/test.db"
            )
            try:
                with engine.connect() as conn:
                    rel, status = conn.execute(
                        sa.text(
                            "SELECT thumbnail_path, status FROM"
                            " rendered_clips WHERE clip_candidate_id = :c"
                        ),
                        {"c": candidate_id},
                    ).one()
            finally:
                engine.dispose()
            assert status == "rendered"
            assert rel is not None  # goreli yol kaydedildi
            thumb = tmp_path / "media" / rel
            assert thumb.is_file()
            image = cv2.imread(str(thumb))
            assert image is not None
            assert image.shape[:2] == (THUMB_H, THUMB_W)

    def test_full_cut_approve_composes_thumbnail(self, tmp_path):
        from app.models import (
            Base,
            Channel,
            ClipMetadata,
            MediaAsset,
            RenderedClip,
            SourceChannel,
            SourceVideo,
        )

        app = _make_app(
            tmp_path,
            worker_enabled=False,
            media_root=str(tmp_path / "media"),
        )
        with TestClient(app) as client:
            sessionmaker = client.app.state.sessionmaker

            async def seed():
                async with sessionmaker() as session:
                    channel = Channel(name="Kanal")
                    session.add(channel)
                    await session.flush()
                    source = SourceChannel(
                        channel_id=channel.id,
                        youtube_channel_id="UCkaynak",
                        title="Kaynak",
                        permission_status="authorized",
                        reaction_source=True,
                    )
                    session.add(source)
                    await session.flush()
                    video = SourceVideo(
                        source_channel_id=source.id,
                        youtube_video_id="vid-1",
                        title="Reaksiyon Videosu",
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
                            file_path=str(self.video),
                        )
                    )
                    session.add(
                        RenderedClip(
                            clip_candidate_id=None,
                            source_video_id=video.id,
                            orientation="horizontal",
                            status="rendered",
                            file_path=str(self.video),
                        )
                    )
                    session.add(
                        ClipMetadata(
                            clip_candidate_id=None,
                            source_video_id=video.id,
                            revision=1,
                            title="Tam Kesit Basligi",
                            description="Reaksiyon videosunun tam kesidi.",
                            tags=["reaksiyon"],
                            status="draft",
                        )
                    )
                    await session.commit()
                    return video.id

            video_id = asyncio.run(seed())

            approved = client.post(f"/api/videos/{video_id}/approve")
            assert approved.status_code == 200, approved.text
            assert approved.json()["source_video_id"] == video_id

            engine = sa.create_engine(f"sqlite:///{tmp_path}/test.db")
            try:
                with engine.connect() as conn:
                    rel = conn.execute(
                        sa.text(
                            "SELECT thumbnail_path FROM rendered_clips"
                            " WHERE source_video_id = :v"
                            " AND orientation = 'horizontal'"
                        ),
                        {"v": video_id},
                    ).scalar_one()
            finally:
                engine.dispose()
            # thumbnail_text yok: baslik fallback olarak yazilir
            assert rel is not None
            thumb = tmp_path / "media" / rel
            assert thumb.is_file()
            image = cv2.imread(str(thumb))
            assert image is not None
            assert image.shape[:2] == (THUMB_H, THUMB_W)
