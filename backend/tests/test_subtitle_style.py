"""subtitle_style: klip-goreli ASS uretimi ve stil sozlesmesi.

Zaman kaydirma (kaynak -> klip cubugu), dilim filtreleme, metin
temizligi (ASS override enjeksiyonu), PlayRes sabitleme, 5 secilebilir
stil (Gorev 1) ve kadran uzerinde serbest konum (Gorev 2). Onizleme
(SubtitlePreview) ayni tablolari kullandigi icin buradaki matematik
iki yuzlu sozlesmedir.
"""
from __future__ import annotations

from app.config import Settings
from app.services.subtitle_style import (
    DEFAULT_POS_X_PERCENT,
    DEFAULT_POS_Y_PERCENT,
    DEFAULT_STYLE,
    SUBTITLE_STYLES,
    SubtitleStyle,
    build_ass,
)
from app.services.vertical_render import OUT_H, OUT_W


class TestTimingShift:
    def test_cues_shift_to_clip_timeline(self):
        ass = build_ass(
            [
                {"start": 10.0, "end": 12.0, "text": "merhaba"},
                {"start": 12.0, "end": 13.5, "text": "dunya"},
            ],
            start=10.5,
            end=13.0,
        )
        assert "Dialogue: 0,0:00:00.00,0:00:01.50,Sub,,0,0,0,," in ass
        assert "merhaba" in ass
        assert "dunya" in ass

    def test_out_of_range_segments_dropped(self):
        ass = build_ass(
            [
                {"start": 0.0, "end": 1.0, "text": "once"},
                {"start": 99.0, "end": 100.0, "text": "sonra"},
                {"start": 4.0, "end": 4.01, "text": "kisa"},
                {"start": 3.0, "end": 9.0, "text": None},
            ],
            start=1.0,
            end=4.0,
        )
        assert ass == ""

    def test_broken_segments_skipped_not_fatal(self):
        ass = build_ass(
            [
                {"start": "x", "end": 2.0, "text": "bozuk"},
                {"start": 1.5, "end": 2.5, "text": "saglam"},
            ],
            start=1.0,
            end=3.0,
        )
        assert "saglam" in ass
        assert "bozuk" not in ass


class TestStyleContract:
    def test_playres_pinned(self):
        ass = build_ass(
            [{"start": 0.0, "end": 1.0, "text": "selam"}],
            start=0.0,
            end=1.0,
        )
        assert f"PlayResX: {OUT_W}" in ass
        assert f"PlayResY: {OUT_H}" in ass
        # Stil dosyanin icinde: filtre grafigi force_style kullanmaz.
        assert "Outline, Shadow" in ass

    def test_braces_stripped_whitespace_flattened(self):
        ass = build_ass(
            [{"start": 0.0, "end": 1.0, "text": "{\\an8}  cok\n satirli  "}],
            start=0.0,
            end=1.0,
        )
        assert "{\\an8}" not in ass
        assert "cok satirli" in ass

    def test_from_settings_sanitizes(self):
        style = SubtitleStyle.from_settings(
            Settings(
                subtitle_font_size=999,
                subtitle_style_preset="yanlis",
                subtitle_pos_x_percent=1400,
                subtitle_pos_y_percent=-5,
            )
        )
        assert style.font_size == 240  # sinirla kirpildi
        assert style.style_key == DEFAULT_STYLE
        assert style.pos_x_percent == 100
        assert style.pos_y_percent == 0


class TestStylePresets:
    """Gorev 1: 5 secilebilir stil, saralar/renkler/konturlar ASS'e
    dosyanin icinde tasinir."""

    def test_five_styles_defined(self):
        assert set(SUBTITLE_STYLES) == {
            "klasik",
            "shorts_sari",
            "anton",
            "kutu",
            "noto",
        }

    def test_yellow_shorts_look(self):
        ass = build_ass(
            [{"start": 0.0, "end": 1.0, "text": "viral an"}],
            start=0.0,
            end=1.0,
            style=SubtitleStyle(style_key="shorts_sari"),
        )
        # Sarilar: &H0000EEFF (#FFEE00, ASS mavi-yesil-kirmizi sirasi).
        assert "&H0000EEFF" in ass
        # Klasik beyazla karismasin.
        assert ass.count("&H00FFFFFF") == 0

    def test_each_style_writes_own_font(self):
        for key, preset in SUBTITLE_STYLES.items():
            ass = build_ass(
                [{"start": 0.0, "end": 1.0, "text": "x"}],
                start=0.0,
                end=1.0,
                style=SubtitleStyle(style_key=key),
            )
            assert f"Style: Sub,{preset['font']}," in ass, key

    def test_boxed_style_uses_border_style_3(self):
        ass = build_ass(
            [{"start": 0.0, "end": 1.0, "text": "x"}],
            start=0.0,
            end=1.0,
            style=SubtitleStyle(style_key="kutu"),
        )
        # BorderStyle alaninin (16. alan) 3 olmasi lazim: "...,1,4,0,2,"
        # biciminde (BorderStyle, Outline, Shadow, Alignment).
        assert ",3,4,0,2," in ass

    def test_anton_and_noto_fonts_exist_in_image_assets(self):
        from pathlib import Path

        fonts = Path(__file__).resolve().parents[1] / "assets" / "fonts"
        assert (fonts / "Anton-Regular.ttf").is_file()
        assert (fonts / "NotoSans-Regular.ttf").is_file()

    def test_style_line_fully_resolved_no_literals(self):
        """2026-10-21 canlı olay: Style satırındaki iki preset değeri
        f-string olmayan bir satırda kaldığı için ASS'e LİTERAL olarak
        yazılıyor, libass bozuk stili reddediyor ve altyazı sessizce
        çizilmiyordu (subtitles_burned=true'ya rağmen). Stil satırı
        artık tamamen çözülmüş olmalı: literal süslü parantez yok,
        her preset rengi dosyada geçiyor, alan sayısı 23."""
        for key, preset in SUBTITLE_STYLES.items():
            ass = build_ass(
                [{"start": 0.0, "end": 1.0, "text": "x"}],
                start=0.0,
                end=1.0,
                style=SubtitleStyle(style_key=key),
            )
            style_line = next(
                line for line in ass.splitlines() if line.startswith("Style:")
            )
            assert "{" not in style_line and "}" not in style_line, key
            assert preset["primary"] in style_line, key
            assert preset["outline_colour"] in style_line, key
            assert preset["back"] in style_line, key
            # Format satırı 23 alan tanımlar; Style de tam olarak
            # 23 alan taşımalı (virgül sayısı = 22).
            assert style_line.count(",") == 22, key


class TestFreePosition:
    """Gorev 2: altyazi cimbasi (alt kenar ortasi) kadranin herhangi
    bir noktasina \\pos ile tasinir; varsayilan Shorts konumu."""

    def test_default_is_shorts_position(self):
        assert DEFAULT_POS_X_PERCENT == 50
        assert DEFAULT_POS_Y_PERCENT == 78
        x, y = SubtitleStyle().position_point()
        assert x == OUT_W // 2
        assert y == int(round(OUT_H * 0.78))

    def test_pos_tag_carries_anchor_pixel(self):
        style = SubtitleStyle(pos_x_percent=25, pos_y_percent=40)
        ass = build_ass(
            [{"start": 0.0, "end": 1.0, "text": "nereye"}],
            start=0.0,
            end=1.0,
            style=style,
        )
        x, y = style.position_point()
        assert f"{{\\pos({x},{y})}}nereye" in ass

    def test_position_point_stays_inside_frame(self):
        style = SubtitleStyle(pos_x_percent=0, pos_y_percent=100)
        x, y = style.position_point()
        assert 0 <= x <= OUT_W
        assert 0 <= y <= OUT_H

    def test_top_of_frame_no_longer_blocked_by_band(self):
        # Eski sistemde altyazi video bandina hapsoldu; yeni sistemde
        # kamera bolumunun ustune bile konabilir (kullanicinin karari).
        style = SubtitleStyle(pos_y_percent=10)
        ass = build_ass(
            [{"start": 0.0, "end": 1.0, "text": "yukari"}],
            start=0.0,
            end=1.0,
            style=style,
        )
        _, y = style.position_point()
        assert y < OUT_H * 0.2
        assert "\\pos" in ass
