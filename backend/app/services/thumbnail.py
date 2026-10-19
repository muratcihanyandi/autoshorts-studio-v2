"""Thumbnail composition (M13).

The thumbnail is the sharpest of three sampled frames (25/50/75% of
the video, Laplacian variance), scaled and letterboxed to 1280x720,
with the approved `thumbnail_text` (fallback: title) drawn on top in
white with a black outline. Text rendering prefers the DejaVu font
shipped in the backend image (fonts-dejavu-core) via ffmpeg drawtext;
when no TTF is reachable (bare dev machines) OpenCV's built-in Hershey
font renders an ASCII-transliterated fallback so a thumbnail is always
produced. Frame selection and layout math are pure/deterministic.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import cv2
import numpy as np

THUMB_W = 1280
THUMB_H = 720
SAMPLE_FRACTIONS = (0.25, 0.50, 0.75)
# Arka plana siyah bant: metin bloğunun alt kenarındaki pay.
BOTTOM_MARGIN = 72
MAX_LINES = 3
FONT_SIZE_STEPS = (72, 56, 44)
# Gerçek font genişliği tahmini (DejaVu Bold ~0.62em/char, güvenli pay).
CHAR_WIDTH_FACTOR = 0.62
MAX_TEXT_WIDTH_RATIO = 0.82

# Arka uç imajında yüklü DejaVu (backend/Dockerfile: fonts-dejavu-core);
# geliştirme makineleri için yaygın sistem fontları yedek olarak.
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)

# cv2.putText (Hershey) ASCII dışı karakterleri çizemez: sesli harfleri
# yakınsak ASCII'ye çeviririz (yalnızca font bulunamazsa kullanılır).
_ASCII_MAP = str.maketrans(
    "çÇğĞıİöÖşŞüÜâÂîÎûÛ",
    "cCgGiIoOsSuUaAiIuU",
)


class ThumbnailError(Exception):
    """Thumbnail failure with a user-facing Turkish message."""


def find_font(font_path: str | None = None) -> str | None:
    """First existing font file; None when no TTF is reachable."""
    if font_path:
        return font_path if Path(font_path).is_file() else None
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def _video_duration(cap: cv2.VideoCapture) -> float:
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if frames > 0 and fps > 0:
        return frames / fps
    return 0.0


def read_sample_frames(
    video_path: str | Path,
    fractions: tuple[float, ...] = SAMPLE_FRACTIONS,
) -> list[np.ndarray]:
    """Readable frames at the given fractions; skips failed seeks."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ThumbnailError(f"Video acilamadi: {video_path}")
    frames: list[np.ndarray] = []
    try:
        duration = _video_duration(cap)
        for fraction in fractions:
            if duration > 0:
                cap.set(cv2.CAP_PROP_POS_MSEC, duration * fraction * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
                if duration <= 0:
                    # Sure bilinmiyorsa tek kare yeter.
                    break
        if not frames:
            cap.set(cv2.CAP_PROP_POS_MSEC, 0.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
    finally:
        cap.release()
    if not frames:
        raise ThumbnailError("Videodan kare okunamadi.")
    return frames


def sharpness_score(frame_bgr: np.ndarray) -> float:
    """Laplacian variance (higher = sharper)."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def pick_sharpest_frame(
    video_path: str | Path,
    fractions: tuple[float, ...] = SAMPLE_FRACTIONS,
) -> np.ndarray:
    frames = read_sample_frames(video_path, fractions)
    return max(frames, key=sharpness_score)


def fit_frame(
    frame_bgr: np.ndarray,
    out_w: int = THUMB_W,
    out_h: int = THUMB_H,
) -> np.ndarray:
    """Scale preserving aspect + centered black pad (letterbox)."""
    in_h, in_w = frame_bgr.shape[:2]
    scale = min(out_w / in_w, out_h / in_h)
    new_w = max(1, int(round(in_w * scale)))
    new_h = max(1, int(round(in_h * scale)))
    resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    top = (out_h - new_h) // 2
    left = (out_w - new_w) // 2
    canvas[top : top + new_h, left : left + new_w] = resized
    return canvas


def plan_text_lines(
    text: str,
    out_w: int = THUMB_W,
) -> tuple[list[str], int]:
    """Word-wrap the text for the thumbnail; returns (lines, fontsize).

    Font size shrinks stepwise when the text needs more than three
    lines. Deterministic, font-agnostic (conservative width estimate).
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        return [], 0
    max_width = int(out_w * MAX_TEXT_WIDTH_RATIO)
    lines: list[str] = []
    max_chars = 0
    for fontsize in FONT_SIZE_STEPS:
        max_chars = max(8, int(max_width / (fontsize * CHAR_WIDTH_FACTOR)))
        lines = _wrap_words(cleaned, max_chars)
        if len(lines) <= MAX_LINES:
            return lines, fontsize
    # En kucuk fontta da sigmiyorsa satirlari kirp (son satira uc nokta).
    lines = lines[:MAX_LINES]
    last = lines[-1]
    if len(last) > max_chars - 3:
        last = last[: max_chars - 3]
    lines[-1] = last.rstrip() + "..."
    return lines, FONT_SIZE_STEPS[-1]


def _wrap_words(text: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        # Tek kelime satira sigmiyorsa sert bolme.
        while len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _escape_drawtext(value: str) -> str:
    """ffmpeg drawtext metin kaçışı (expansion=none ile % güvenli)."""
    value = value.replace("\\", "\\\\")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    value = value.replace(",", "\\,")
    value = value.replace("[", "\\[")
    value = value.replace("]", "\\]")
    value = value.replace(";", "\\;")
    return value


def _escape_filter_path(path: str) -> str:
    """ffmpeg filtresi içinde güvenli font dosya yolu."""
    text = str(path).replace("\\", "/")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    return text


def build_drawtext_filters(
    lines: list[str], fontsize: int, font_path: str
) -> str:
    """One drawtext filter per line, centered, white + black outline."""
    filters = []
    line_step = int(fontsize * 1.3)
    bottom = THUMB_H - BOTTOM_MARGIN
    for index, line in enumerate(lines):
        y = bottom - (len(lines) - index) * line_step
        filters.append(
            "drawtext="
            f"fontfile='{_escape_filter_path(font_path)}'"
            f":text='{_escape_drawtext(line)}'"
            f":fontsize={fontsize}"
            ":fontcolor=white"
            ":borderw=4"
            ":bordercolor=black"
            ":x=(w-text_w)/2"
            f":y={y}"
            ":expansion=none"
        )
    return ",".join(filters)


def _draw_lines_opencv(canvas: np.ndarray, lines: list[str], fontsize: int):
    """cv2.putText fallback (Hershey, ASCII transliteration)."""
    scale = fontsize / 32.0
    thickness = max(2, int(round(fontsize / 18.0)))
    line_step = int(fontsize * 1.3)
    bottom = THUMB_H - BOTTOM_MARGIN
    for index, line in enumerate(lines):
        ascii_line = line.translate(_ASCII_MAP)
        (width, _), _ = cv2.getTextSize(
            ascii_line, cv2.FONT_HERSHEY_BOLD, scale, thickness
        )
        x = max(0, (THUMB_W - width) // 2)
        y = bottom - (len(lines) - index) * line_step + fontsize
        cv2.putText(
            canvas,
            ascii_line,
            (x, y),
            cv2.FONT_HERSHEY_BOLD,
            scale,
            (0, 0, 0),
            thickness + 4,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            ascii_line,
            (x, y),
            cv2.FONT_HERSHEY_BOLD,
            scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )


async def compose(
    ffmpeg_bin: str,
    video_path: str | Path,
    text: str,
    out_path: str | Path,
    *,
    font_path: str | None = None,
    timeout: float = 120.0,
) -> Path:
    """Compose the 1280x720 jpg thumbnail for a video.

    Sharpest sampled frame + letterbox + text overlay. Raises
    ThumbnailError on any failure; never returns a partial file.
    """
    frame = pick_sharpest_frame(video_path)
    canvas = fit_frame(frame)
    lines, fontsize = plan_text_lines(text or "")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    font = find_font(font_path)
    if lines and font:
        # ffmpeg drawtext: DejaVu/gerçek font, Türkçe karakter destekli.
        frame_png = out.with_suffix(".frame.png")
        if not cv2.imwrite(str(frame_png), canvas):
            raise ThumbnailError("Ara kare yazilamadi.")
        try:
            cmd = [
                ffmpeg_bin,
                "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(frame_png),
                "-vf", build_drawtext_filters(lines, fontsize, font),
                "-frames:v", "1",
                "-q:v", "2",
                str(out),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise ThumbnailError(
                    "Thumbnail yazimi zaman asimina ugradi."
                ) from None
            if proc.returncode != 0:
                tail = stderr.decode("utf-8", "replace").strip()[-300:]
                raise ThumbnailError(f"Thumbnail yazimi basarisiz: {tail}")
        finally:
            frame_png.unlink(missing_ok=True)
    else:
        if lines:
            _draw_lines_opencv(canvas, lines, fontsize)
        if not cv2.imwrite(str(out), canvas, [cv2.IMWRITE_JPEG_QUALITY, 90]):
            raise ThumbnailError("Thumbnail dosyasi yazilamadi.")

    if not out.is_file() or out.stat().st_size == 0:
        raise ThumbnailError("Thumbnail dosyasi olusmadi.")
    return out
