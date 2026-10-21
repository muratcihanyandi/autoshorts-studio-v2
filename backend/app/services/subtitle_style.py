"""ASS subtitle generation for the vertical clip burn-in.

Transcript segments live on the SOURCE video's timeline; a clip is the
[source, end) window of that source. ffmpeg is invoked with input
seeking (-ss), so frame PTS restart at 0 — cues must be SHIFTED to
clip-relative time or they would never match the frames.

The whole style travels inside the ASS file (no force_style):
PlayResX/Y are pinned to the 1080x1920 output frame, so font size and
margins are real pixels of the delivered clip and the Settings-screen
preview can replicate the exact same math.

Gorev 1 (2026-10-21): five selectable style presets, including the
yellow "Shorts" caption look. Gorev 2: the caption anchor (bottom
center, Alignment=2) can be placed ANYWHERE on the 1080x1920 frame via
percent sliders; the default is the standard Shorts position
(bottom-center, ~78% height). \\pos() overrides carry the anchor to the
exact pixel, so the caption never has to stay inside the video band.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.vertical_render import OUT_H, OUT_W

DEFAULT_FONT_SIZE = 64
TEXT_MARGIN_H = 60  # yatay kenar boslugu (piksel)
MIN_CUE_SECONDS = 0.05

# Shorts standardi: altyazi alt-ortada, ekranin ~%78 yuksekliginde
# (kamera bolumunun altinda, en alt kenardan yukarida; Shorts oynatici
# arayuzu en alt bandi kapatir).
DEFAULT_POS_X_PERCENT = 50
DEFAULT_POS_Y_PERCENT = 78

# ASS renkleri &HAABBGGRR (mavi-yesil-kirmizi bayt sirasi).
_WHITE = "&H00FFFFFF"
_YELLOW = "&H0000EEFF"  # #FFEE00 — YouTube Shorts'un tanidik sarisi
_BLACK = "&H00000000"
_SOFT_BACK = "&H64000000"
_BOX_BACK = "&H66000000"

# Ayarlar ekranindan secilebilen 5 stil (Gorev 1). Anahtar degerler
# ASCII; etiketler arayuzde Turkce verilir. Onizleme (SubtitlePreview)
# ayni tabloyu CSS karsiliklariyla yansitir; buradaki gorsel degerler
# degisirse ikisi birlikte guncellenmelidir.
SUBTITLE_STYLES: dict[str, dict[str, Any]] = {
    # Beyaz metin, kalin siyah kontur — mevcut klasik gorunum.
    "klasik": {
        "font": "DejaVu Sans",
        "primary": _WHITE,
        "outline_colour": _BLACK,
        "back": _SOFT_BACK,
        "bold": 0,
        "border_style": 1,
        "outline": 4,
        "shadow": 1,
    },
    # Shorts'un sarisi: parlak sar metin, kalin siyah kontur.
    "shorts_sari": {
        "font": "DejaVu Sans",
        "primary": _YELLOW,
        "outline_colour": _BLACK,
        "back": _SOFT_BACK,
        "bold": 1,
        "border_style": 1,
        "outline": 4,
        "shadow": 1,
    },
    # Anton: viral Shorts'larin iri, sikistik gorunumlu display fontu.
    "anton": {
        "font": "Anton",
        "primary": _WHITE,
        "outline_colour": _BLACK,
        "back": _SOFT_BACK,
        "bold": 1,
        "border_style": 1,
        "outline": 5,
        "shadow": 0,
    },
    # Beyaz metin yarim saydam siyah KUTU icinde (BorderStyle=3).
    "kutu": {
        "font": "DejaVu Sans",
        "primary": _WHITE,
        "outline_colour": _BLACK,
        "back": _BOX_BACK,
        "bold": 1,
        "border_style": 3,
        "outline": 4,
        "shadow": 0,
    },
    # Noto Sans: yumusak, modern ve genis Turkce glif kapsamli.
    "noto": {
        "font": "Noto Sans",
        "primary": _WHITE,
        "outline_colour": _BLACK,
        "back": _SOFT_BACK,
        "bold": 0,
        "border_style": 1,
        "outline": 3,
        "shadow": 0,
    },
}
DEFAULT_STYLE = "klasik"


@dataclass(frozen=True)
class SubtitleStyle:
    """Ayarlar ekranindan gelen stil (cikti kadraninin piksellerinde)."""

    font_size: int = DEFAULT_FONT_SIZE
    style_key: str = DEFAULT_STYLE
    pos_x_percent: int = DEFAULT_POS_X_PERCENT
    pos_y_percent: int = DEFAULT_POS_Y_PERCENT

    @classmethod
    def from_settings(cls, settings: Any) -> "SubtitleStyle":
        """Runtime ayarlardan stil kur; bozuk degerler varsayilana
        duser (transkript uzerinden gelen ayarlar kirilgan olamaz)."""
        style_key = str(
            getattr(settings, "subtitle_style_preset", "") or DEFAULT_STYLE
        )
        if style_key not in SUBTITLE_STYLES:
            style_key = DEFAULT_STYLE
        raw_size = getattr(settings, "subtitle_font_size", DEFAULT_FONT_SIZE)
        try:
            size = int(raw_size)
        except (TypeError, ValueError):
            size = DEFAULT_FONT_SIZE

        def percent(name: str, default: int) -> int:
            raw = getattr(settings, name, default)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return default
            return max(0, min(100, value))

        return cls(
            font_size=max(8, min(240, size)),
            style_key=style_key,
            pos_x_percent=percent(
                "subtitle_pos_x_percent", DEFAULT_POS_X_PERCENT
            ),
            pos_y_percent=percent(
                "subtitle_pos_y_percent", DEFAULT_POS_Y_PERCENT
            ),
        )

    @property
    def preset(self) -> dict[str, Any]:
        return SUBTITLE_STYLES[self.style_key]

    def position_point(self) -> tuple[int, int]:
        """Altyazi cimbasi (alt kenar ortasi, Alignment=2) — cikti
        kadraninda mutlak piksel. Gorev 2: serbest konum."""
        x = int(round(OUT_W * self.pos_x_percent / 100.0))
        y = int(round(OUT_H * self.pos_y_percent / 100.0))
        return x, y


def _ass_time(seconds: float) -> str:
    """Saniye -> 'H:MM:SS.cc' (ASS zaman biimi, centisaniye)."""
    centis = int(round(max(0.0, float(seconds)) * 100))
    hours, rem = divmod(centis, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _clean_text(text: object) -> str:
    """Tek satir guvenli ASS metni: suslu parantezler ASS override
    etiketi enjeksiyonunu engellemek icin ayiklanir, beyaz alan
    duzlestirilir."""
    flat = " ".join(str(text or "").split())
    return flat.replace("{", "").replace("}", "")


def build_ass(
    segments: list[dict],
    *,
    start: float,
    end: float,
    style: SubtitleStyle | None = None,
) -> str:
    """Klip-goreli ASS icerigi; cakisan dilim yoksa bos string doner
    (cagiran gomme olmadan render eder)."""
    style = style or SubtitleStyle()
    cues: list[tuple[float, float, str]] = []
    for seg in segments or []:
        try:
            seg_start = float(seg.get("start"))
            seg_end = float(seg.get("end"))
        except (TypeError, ValueError):
            continue
        text = _clean_text(seg.get("text"))
        if not text or seg_end <= start or seg_start >= end:
            continue
        cue_start = max(seg_start - start, 0.0)
        cue_end = min(seg_end - start, end - start)
        if cue_end - cue_start < MIN_CUE_SECONDS:
            continue
        cues.append((cue_start, cue_end, text))
    cues.sort(key=lambda cue: cue[0])
    if not cues:
        return ""

    preset = style.preset
    pos_x, pos_y = style.position_point()
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {OUT_W}\n"
        f"PlayResY: {OUT_H}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{preset['font']},{style.font_size},{preset['primary']},"
        f"&H000000FF,{preset['outline_colour']},{preset['back']},"
        f"{preset['bold']},0,0,0,100,100,0,0,"
        f"{preset['border_style']},{preset['outline']},{preset['shadow']},2,"
        f"{TEXT_MARGIN_H},{TEXT_MARGIN_H},1,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_time(cue_start)},{_ass_time(cue_end)}"
        f",Sub,,0,0,0,,{{\\pos({pos_x},{pos_y})}}{text}"
        for cue_start, cue_end, text in cues
    ]
    return header + "\n".join(lines) + "\n"
