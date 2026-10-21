"""subtitle_style: klip-goreli ASS uretimi ve stil matematigi.

Zaman kaydirma (kaynak -> klip cubugu), dilim filtreleme, metin
temizligi (ASS override enjeksiyonu), PlayRes sabitleme ve konum ->
MarginV donusumu. Onizleme (SubtitlePreview) ayni tablolari
kullandigi icin buradaki matematik iki yuzlu sozlesmedir.
"""
from __future__ import annotations

from app.config import Settings
from app.services.subtitle_style import (
    FONT_NAME,
    POSITION_ANCHORS,
    SubtitleStyle,
    build_ass,
    margin_v_for,
)
from app.services.vertical_render import OUT_H, OUT_W, build_layout

WEBCAM_REGION = (280, 155, 85, 85)


def _layout():
    return build_layout(1280, 720, WEBCAM_REGION)


class TestTimingShift:
    def test_cues_shift_to_clip_timeline(self):
        layout = _layout()
        ass = build_ass(
            [
                {"start": 10.0, "end": 12.0, "text": "merhaba"},
                {"start": 12.0, "end": 13.5, "text": "dunya"},
            ],
            start=10.5,
            end=13.0,
            layout=layout,
        )
        assert "Dialogue: 0,0:00:00.00,0:00:01.50,Sub,,0,0,0,,merhaba" in ass
        assert "Dialogue: 0,0:00:01.50,0:00:02.50,Sub,,0,0,0,,dunya" in ass

    def test_out_of_range_segments_dropped(self):
        layout = _layout()
        ass = build_ass(
            [
                {"start": 0.0, "end": 1.0, "text": "once"},
                {"start": 99.0, "end": 100.0, "text": "sonra"},
                {"start": 4.0, "end": 4.01, "text": "kisa"},
                {"start": 3.0, "end": 9.0, "text": None},
            ],
            start=1.0,
            end=4.0,
            layout=layout,
        )
        assert ass == ""

    def test_broken_segments_skipped_not_fatal(self):
        layout = _layout()
        ass = build_ass(
            [
                {"start": "x", "end": 2.0, "text": "bozuk"},
                {"start": 1.5, "end": 2.5, "text": "saglam"},
            ],
            start=1.0,
            end=3.0,
            layout=layout,
        )
        assert "saglam" in ass
        assert "bozuk" not in ass


class TestStyleContract:
    def test_playres_and_font_pinned(self):
        ass = build_ass(
            [{"start": 0.0, "end": 1.0, "text": "selam"}],
            start=0.0,
            end=1.0,
            layout=_layout(),
        )
        assert f"PlayResX: {OUT_W}" in ass
        assert f"PlayResY: {OUT_H}" in ass
        assert FONT_NAME in ass
        # Stil dosyanin icinde: filtre grafigi force_style kullanmaz.
        assert "Outline, Shadow" in ass

    def test_braces_stripped_whitespace_flattened(self):
        ass = build_ass(
            [{"start": 0.0, "end": 1.0, "text": "{\\an8}  cok\n satirli  "}],
            start=0.0,
            end=1.0,
            layout=_layout(),
        )
        assert "{\\an8}" not in ass
        assert "cok satirli" in ass

    def test_margin_order_top_above_middle_above_bottom(self):
        layout = _layout()
        y1, y2 = layout.subtitle_band
        top = margin_v_for(layout, "top")
        middle = margin_v_for(layout, "middle")
        bottom = margin_v_for(layout, "bottom")
        # Yukari konum = metin alt kenari yukarda = buyuk MarginV.
        assert top > middle > bottom
        # Metin bandin icinde kalir: MarginV kadran altindan olculur.
        assert bottom >= OUT_H - y2
        assert top <= OUT_H - y1

    def test_from_settings_sanitizes(self):
        style = SubtitleStyle.from_settings(
            Settings(
                subtitle_font_size=999,
                subtitle_position="yanlis",
            )
        )
        assert style.font_size == 240  # sinirla kirpildi
        assert style.position == "middle"
        anchors = sorted(POSITION_ANCHORS.values())
        assert anchors == sorted(set(anchors))  # tutarli tekil tablo
