"""vertical_render: layout math, real ffmpeg render, output validation."""
from __future__ import annotations

import asyncio

import pytest

from app.services.vertical_render import (
    HORIZONTAL_H,
    HORIZONTAL_W,
    OUT_H,
    OUT_W,
    VerticalRenderError,
    build_filter_graph,
    build_horizontal_filter,
    build_layout,
    render_horizontal,
    render_vertical,
    validate_output,
)
from tests.media_sample import make_face_stream_video

# Yuz videosunda tespit edilen tipik bolge (test_webcam_detect dogruladi).
WEBCAM_REGION = (280, 155, 85, 85)


class TestLayout:
    def test_two_section_layout_with_subtitle_band(self):
        layout = build_layout(1280, 720, WEBCAM_REGION)
        assert (layout.out_w, layout.out_h) == (OUT_W, OUT_H)
        top, bottom = layout.top, layout.bottom
        # Ust bant: webcam merkezli, kaynaga sinirli
        assert top["w"] > 0 and top["h"] > 0
        assert 0 <= top["x"] and top["x"] + top["w"] <= 1280
        assert 0 <= top["y"] and top["y"] + top["h"] <= 720
        # Webcam kutusu kirpmanin icinde kalmali
        assert top["x"] <= WEBCAM_REGION[0] + WEBCAM_REGION[2] / 2 <= top["x"] + top["w"]
        assert top["y"] <= WEBCAM_REGION[1] + WEBCAM_REGION[3] / 2 <= top["y"] + top["h"]
        # Alt bant: merkez dikey dilim
        assert bottom["x"] == (1280 - bottom["w"]) // 2 or bottom["w"] == 1280
        # Altyazi bandi ust bantla cakismaz (kabul kriteri)
        y1, y2 = layout.subtitle_band
        assert y1 >= top["out_h"]
        assert y2 <= OUT_H
        assert y1 < y2

    def test_layout_clamps_tiny_frame(self):
        # Cok kucuk kaynak cercevesi patlamamali; kirpma cercee sigmali
        layout = build_layout(200, 150, (10, 10, 50, 50))
        assert 0 <= layout.top["x"] + layout.top["w"] <= 200
        assert 0 <= layout.top["y"] + layout.top["h"] <= 150

    def test_invalid_inputs_raise(self):
        with pytest.raises(VerticalRenderError):
            build_layout(0, 0, (1, 1, 10, 10))
        with pytest.raises(VerticalRenderError):
            build_layout(1280, 720, (0, 0, 0, 0))

    def test_webcam_rectangle_not_zoomed_full_width_top(self):
        """Kullanıcı isteği 2026-10-21: webcam zoomlanmaz — pad'li
        dikdörtgen en-boy oranı korunarak tam genişlikte üst bölümde
        olduğu gibi görünür; bölüm yüksekliği dikdörtgenin oranından
        türer (eski davranış bölgeyi bölüm oranına zorlayıp kırpıyordu)."""
        layout = build_layout(1280, 720, WEBCAM_REGION)
        top = layout.top
        assert top.get("out_w", OUT_W) == OUT_W
        # Zoom yok: üst bölüm çıkış orani kirpilan dikdortgenin oraniyla
        # ayni (yuvarlama payiyla).
        assert top["out_h"] == pytest.approx(
            OUT_W * top["h"] / top["w"], abs=1.5
        )
        assert layout.bottom["out_h"] == OUT_H - top["out_h"]
        assert layout.subtitle_band[0] >= top["out_h"]

    def test_tall_webcam_caps_top_and_pads_sides(self):
        """Çok dik webcam dikdörtgeni: üst bölüm yükseklik sınırına
        takılır, dikdörtgen yanlardan pad'lenerek TAMAMEN görünür kalır
        (asla kırpılmaz) ve alt bant yaşamaya devam eder."""
        layout = build_layout(1280, 720, (600, 100, 80, 500))
        top = layout.top
        assert top["out_h"] == int(round(OUT_H * 0.65))
        assert top["out_w"] < OUT_W  # contain: en-boy korunur, yanlar pad
        assert top["out_h"] == pytest.approx(
            top["out_w"] * top["h"] / top["w"], rel=0.005
        )
        assert layout.bottom["out_h"] == OUT_H - top["out_h"]

    def test_filter_graph_contains_both_crops_and_subtitles(self, tmp_path):
        layout = build_layout(1280, 720, WEBCAM_REGION)
        srt = tmp_path / "subs.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nmerhaba\n", encoding="utf-8")
        graph = build_filter_graph(layout, srt)
        assert "split=2" in graph and "vstack" in graph
        assert "subtitles=" in graph
        graph_plain = build_filter_graph(layout, "")
        assert "subtitles=" not in graph_plain


class TestRealRender:
    @pytest.fixture(scope="module")
    def face_video(self, tmp_path_factory):
        return make_face_stream_video(
            tmp_path_factory.mktemp("render") / "face_stream.mp4"
        )

    def test_render_and_validate(self, face_video, tmp_path):
        layout = build_layout(1280, 720, WEBCAM_REGION)
        srt = tmp_path / "subs.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:02,900\nselam arkadaslar\n",
            encoding="utf-8",
        )
        out = tmp_path / "edited" / "clip.mp4"

        async def scenario():
            await render_vertical(
                "ffmpeg",
                face_video,
                1.0,
                4.0,
                layout,
                out,
                subtitle_path=srt,
            )
            return await validate_output("ffprobe", out, 3.0)

        report = asyncio.run(scenario())
        assert report.ok, report.problems
        assert (report.width, report.height) == (1080, 1920)
        assert report.has_audio is True
        assert report.av_sync_delta <= 0.25
        assert abs(report.duration_seconds - 3.0) <= 0.75

    def test_render_without_subtitles(self, face_video, tmp_path):
        layout = build_layout(1280, 720, WEBCAM_REGION)
        out = tmp_path / "clip_nosub.mp4"

        async def scenario():
            await render_vertical(
                "ffmpeg", face_video, 0.0, 2.0, layout, out
            )
            return await validate_output("ffprobe", out, 2.0)

        report = asyncio.run(scenario())
        assert report.ok, report.problems

    def test_invalid_range_rejected(self, face_video, tmp_path):
        layout = build_layout(1280, 720, WEBCAM_REGION)

        async def scenario():
            try:
                await render_vertical(
                    "ffmpeg", face_video, 4.0, 4.0, layout, tmp_path / "x.mp4"
                )
                return False
            except VerticalRenderError:
                return True

        assert asyncio.run(scenario()) is True


@pytest.fixture(scope="module")
def hrender_face_video(tmp_path_factory):
    return make_face_stream_video(
        tmp_path_factory.mktemp("hrender") / "face_stream.mp4"
    )


class TestHorizontalRender:
    """M13: yatay tam kesit — 1920x1080, budama, altyazi YOK, ses VAR."""

    def test_filter_graph_has_no_subtitles(self):
        graph = build_horizontal_filter()
        assert "subtitles=" not in graph
        assert f"scale={HORIZONTAL_W}:{HORIZONTAL_H}" in graph
        assert "pad=" in graph

    def test_render_horizontal_with_trims(self, hrender_face_video, tmp_path):
        out = tmp_path / "edited" / "video_1_horizontal.mp4"

        async def scenario():
            await render_horizontal(
                "ffmpeg",
                hrender_face_video,
                out,
                trim_start=1.0,
                trim_end=2.0,
                source_duration=8.0,
            )
            return await validate_output(
                "ffprobe",
                out,
                5.0,
                expected_size=(HORIZONTAL_W, HORIZONTAL_H),
            )

        report = asyncio.run(scenario())
        assert report.ok, report.problems
        assert (report.width, report.height) == (1920, 1080)
        assert report.has_audio is True
        assert report.av_sync_delta <= 0.25
        assert abs(report.duration_seconds - 5.0) <= 0.75

    def test_render_horizontal_without_trims(self, hrender_face_video, tmp_path):
        out = tmp_path / "full.mp4"

        async def scenario():
            await render_horizontal(
                "ffmpeg", hrender_face_video, out, source_duration=8.0
            )
            return await validate_output(
                "ffprobe",
                out,
                8.0,
                expected_size=(HORIZONTAL_W, HORIZONTAL_H),
            )

        report = asyncio.run(scenario())
        assert report.ok, report.problems
        assert (report.width, report.height) == (1920, 1080)

    def test_unknown_duration_omits_end_trim(self, hrender_face_video, tmp_path):
        out = tmp_path / "nodur.mp4"

        async def scenario():
            # source_duration yok: -to eklenmez, video sonuna kadar okunur
            await render_horizontal(
                "ffmpeg", hrender_face_video, out, trim_start=0.0
            )
            return await validate_output(
                "ffprobe",
                out,
                8.0,
                expected_size=(HORIZONTAL_W, HORIZONTAL_H),
            )

        report = asyncio.run(scenario())
        assert report.ok, report.problems

    def test_invalid_trims_rejected(self, hrender_face_video, tmp_path):
        async def scenario():
            errors = []
            cases = [
                {"trim_start": -1.0, "source_duration": 8.0},
                {"trim_start": 6.0, "trim_end": 6.0, "source_duration": 8.0},
                {"source_duration": 0.0},
            ]
            for kwargs in cases:
                try:
                    await render_horizontal(
                        "ffmpeg",
                        hrender_face_video,
                        tmp_path / "bad.mp4",
                        **kwargs,
                    )
                    errors.append(None)
                except VerticalRenderError as exc:
                    errors.append(str(exc))
            return errors

        errors = asyncio.run(scenario())
        assert all(err is not None for err in errors)
