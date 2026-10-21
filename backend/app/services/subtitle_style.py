"""ASS subtitle generation for the vertical clip burn-in.

Transcript segments live on the SOURCE video's timeline; a clip is the
[source, end) window of that source. ffmpeg is invoked with input
seeking (-ss), so frame PTS restart at 0 — cues must be SHIFTED to
clip-relative time or they would never match the frames.

The whole style travels inside the ASS file (no force_style):
PlayResX/Y are pinned to the 1080x1920 output frame, so font size and
margins are real pixels of the delivered clip and the Settings-screen
preview can replicate the exact same math. Vertical position is an
anchor INSIDE the subtitle band (layout.subtitle_band): subtitles can
never climb over the webcam section.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.vertical_render import OUT_H, OUT_W, VerticalLayout

# Konum -> altyazinin ALT kenarinin bandin hangi oranina oturacagi.
# Arayuzdeki onizleme (SubtitlePreview) ayni tabloyu kullanir; bu
# degerler degisirse ikisi birlikte guncellenmelidir.
POSITION_ANCHORS: dict[str, float] = {
    "top": 0.35,
    "middle": 0.65,
    "bottom": 0.95,
}
DEFAULT_POSITION = "middle"
DEFAULT_FONT_SIZE = 64
FONT_NAME = "DejaVu Sans"  # imaj fonts-dejavu-core paketini tasir
TEXT_MARGIN_H = 60  # yatay kenar boslugu (piksel)
MIN_CUE_SECONDS = 0.05


@dataclass(frozen=True)
class SubtitleStyle:
    """Ayarlar ekranindan gelen stil (cikti kadraninin piksellerinde)."""

    font_size: int = DEFAULT_FONT_SIZE
    position: str = DEFAULT_POSITION

    @classmethod
    def from_settings(cls, settings: Any) -> "SubtitleStyle":
        """Runtime ayarlardan stil kur; bozuk degerler varsayilana
        duser (transkript uzerinden gelen ayarlar kirilgan olamaz)."""
        position = str(
            getattr(settings, "subtitle_position", "") or DEFAULT_POSITION
        )
        if position not in POSITION_ANCHORS:
            position = DEFAULT_POSITION
        raw_size = getattr(settings, "subtitle_font_size", DEFAULT_FONT_SIZE)
        try:
            size = int(raw_size)
        except (TypeError, ValueError):
            size = DEFAULT_FONT_SIZE
        return cls(font_size=max(8, min(240, size)), position=position)


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


def margin_v_for(layout: VerticalLayout, position: str) -> int:
    """Konumu ASS MarginV'ye cevir (Alignment=2: alt kenardan piksel)."""
    y1, y2 = layout.subtitle_band
    anchor = POSITION_ANCHORS.get(position, POSITION_ANCHORS[DEFAULT_POSITION])
    bottom_edge = y1 + (y2 - y1) * anchor
    return max(1, int(round(layout.out_h - bottom_edge)))


def build_ass(
    segments: list[dict],
    *,
    start: float,
    end: float,
    layout: VerticalLayout,
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
        f"Style: Sub,{FONT_NAME},{style.font_size},&H00FFFFFF,&H000000FF,"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,4,1,2,"
        f"{TEXT_MARGIN_H},{TEXT_MARGIN_H},"
        f"{margin_v_for(layout, style.position)},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_time(cue_start)},{_ass_time(cue_end)}"
        f",Sub,,0,0,0,,{text}"
        for cue_start, cue_end, text in cues
    ]
    return header + "\n".join(lines) + "\n"
