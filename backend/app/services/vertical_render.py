"""9:16 vertical rendering (M8).

Layout: the output is 1080x1920 — the top fraction is the webcam crop
(padded face box, aspect-corrected to the section), the rest is a
center crop of the source video. Subtitles burn into the bottom band
of the video section with ASS-style positioning, so they can never
overlap the webcam section.

Rendering is one ffmpeg pass; validation re-probes the output
(resolution, duration tolerance, audio presence, A/V stream-duration
sync). Layout math is pure and unit-tested; the render test runs real
ffmpeg.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.services.media_probe import MediaProbeError, run_ffprobe

OUT_W = 1080
OUT_H = 1920
DEFAULT_TOP_FRACTION = 0.4
DEFAULT_WEBCAM_PADDING = 0.35
SUBTITLE_MARGIN_V = 80  # alt bantta kenardan px


class VerticalRenderError(Exception):
    """Render failure with a user-facing Turkish message."""


@dataclass
class VerticalLayout:
    out_w: int
    out_h: int
    top: dict  # kaynak koordinatlarinda kirpma {x, y, w, h} + out_h
    bottom: dict
    subtitle_band: tuple[int, int]  # cikti koordinatlarinda (y1, y2)

    def as_dict(self) -> dict:
        return {
            "out_w": self.out_w,
            "out_h": self.out_h,
            "top": dict(self.top),
            "bottom": dict(self.bottom),
            "subtitle_band": list(self.subtitle_band),
        }


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def build_layout(
    source_w: int,
    source_h: int,
    webcam: tuple[int, int, int, int],
    *,
    out_w: int = OUT_W,
    out_h: int = OUT_H,
    top_fraction: float = DEFAULT_TOP_FRACTION,
    padding: float = DEFAULT_WEBCAM_PADDING,
) -> VerticalLayout:
    """Compute the two crop rectangles and the subtitle band.

    The webcam box is padded and aspect-corrected to the top section's
    aspect (out_w / top_h); the bottom is a center crop matching the
    bottom section's aspect. Everything is clamped to the source frame.
    """
    if source_w <= 0 or source_h <= 0:
        raise VerticalRenderError("Kaynak video boyutlari gecersiz.")
    fx, fy, fw, fh = webcam
    if fw <= 0 or fh <= 0:
        raise VerticalRenderError("Webcam bolgesi gecersiz.")

    top_h = int(round(out_h * top_fraction))
    bottom_h = out_h - top_h

    # Webcam: pad, sonra ust bant en-boy oranina getir (genislet/kirp).
    cx = fx + fw / 2.0
    cy = fy + fh / 2.0
    box_w = fw * (1 + 2 * padding)
    box_h = fh * (1 + 2 * padding)
    target_aspect = out_w / top_h
    if box_w / box_h > target_aspect:
        box_w = box_h * target_aspect
    else:
        box_h = box_w / target_aspect
    # Kaynak cercevesine sigdir: olcegi kucult, merkez korunur.
    scale = min(1.0, source_w / box_w, source_h / box_h)
    box_w *= scale
    box_h *= scale
    tx = _clamp(int(round(cx - box_w / 2)), 0, max(0, source_w - int(box_w)))
    ty = _clamp(int(round(cy - box_h / 2)), 0, max(0, source_h - int(box_h)))
    tw = min(int(box_w), source_w - tx)
    th = min(int(box_h), source_h - ty)

    # Alt bant: merkez dikey dilim, alt bant en-boy oranina getir.
    bottom_aspect = out_w / bottom_h  # ~0.94 (dikey)
    crop_w = source_h * bottom_aspect
    if crop_w <= source_w:
        bx = int(round((source_w - crop_w) / 2))
        by = 0
        bw, bh = int(crop_w), source_h
    else:
        bx = 0
        bw = source_w
        bh = int(round(source_w / bottom_aspect))
        by = int(round((source_h - bh) / 2))

    subtitle_y1 = top_h + int(bottom_h * 0.68)
    subtitle_y2 = out_h - 24

    return VerticalLayout(
        out_w=out_w,
        out_h=out_h,
        top={"x": tx, "y": ty, "w": tw, "h": th, "out_h": top_h},
        bottom={"x": bx, "y": by, "w": bw, "h": bh, "out_h": bottom_h},
        subtitle_band=(subtitle_y1, subtitle_y2),
    )


def _escape_filter_path(path: str | Path) -> str:
    """ffmpeg filter icinde guvenli dosya yolu (surucu harfi, tirnak)."""
    text = str(path).replace("\\", "/")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    return text


def build_filter_graph(layout: VerticalLayout, subtitle_path: str | Path) -> str:
    top = layout.top
    bottom = layout.bottom
    subtitle = (
        f"subtitles='{_escape_filter_path(subtitle_path)}'"
        f":force_style='Alignment=2,MarginV={SUBTITLE_MARGIN_V},Fontsize=16'"
        if subtitle_path
        else ""
    )
    bottom_chain = (
        f"[base2]crop={bottom['w']}:{bottom['h']}:{bottom['x']}:{bottom['y']}"
        f",scale={layout.out_w}:{bottom['out_h']}"
    )
    if subtitle:
        bottom_chain += f",{subtitle}"
    bottom_chain += "[bottom]"
    return (
        f"[0:v]split=2[base1][base2];"
        f"[base1]crop={top['w']}:{top['h']}:{top['x']}:{top['y']}"
        f",scale={layout.out_w}:{top['out_h']}[top];"
        f"{bottom_chain};"
        f"[top][bottom]vstack=inputs=2[out]"
    )


async def render_vertical(
    ffmpeg_bin: str,
    source_path: str | Path,
    start_seconds: float,
    end_seconds: float,
    layout: VerticalLayout,
    out_path: str | Path,
    *,
    subtitle_path: str | Path | None = None,
    timeout: float = 1800.0,
) -> Path:
    """Render the composed 9:16 clip; raises on ffmpeg failure."""
    if end_seconds <= start_seconds:
        raise VerticalRenderError("Gecersiz klip araligi.")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_seconds:.3f}",
        "-t", f"{end_seconds - start_seconds:.3f}",
        "-i", str(source_path),
        "-filter_complex", build_filter_graph(layout, subtitle_path or ""),
        "-map", "[out]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
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
        raise VerticalRenderError("Render zaman asimina ugradi.") from None
    if proc.returncode != 0:
        tail = stderr.decode("utf-8", "replace").strip()[-500:]
        raise VerticalRenderError(f"Render basarisiz: {tail}")
    if not out.is_file() or out.stat().st_size == 0:
        raise VerticalRenderError("Render cikti dosyasi olusmadi.")
    return out


@dataclass
class ValidationReport:
    ok: bool
    width: int
    height: int
    duration_seconds: float
    has_audio: bool
    av_sync_delta: float
    problems: list[str]


async def validate_output(
    ffprobe_bin: str,
    out_path: str | Path,
    expected_duration: float,
    *,
    duration_tolerance: float = 0.75,
    sync_tolerance: float = 0.25,
) -> ValidationReport:
    """Re-probe the render: resolution, duration, audio, A/V sync."""
    try:
        raw = await run_ffprobe(ffprobe_bin, out_path)
    except MediaProbeError as exc:
        raise VerticalRenderError(f"Cikti dogrulanamadi: {exc}") from exc

    problems: list[str] = []
    video = None
    audio = None
    for stream in raw.get("streams", []):
        if stream.get("codec_type") == "video" and video is None:
            video = stream
        elif stream.get("codec_type") == "audio" and audio is None:
            audio = stream
    if video is None:
        raise VerticalRenderError("Cikti videosunda video akisi yok.")

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    has_audio = audio is not None

    try:
        duration = float(raw["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        duration = 0.0

    av_delta = 0.0
    if audio is not None:
        try:
            audio_dur = float(audio.get("duration") or 0)
            video_dur = float(video.get("duration") or duration)
            av_delta = abs(video_dur - audio_dur)
        except (TypeError, ValueError):
            av_delta = 0.0

    if (width, height) != (OUT_W, OUT_H):
        problems.append(f"cozunurluk {width}x{height}, beklenen {OUT_W}x{OUT_H}")
    if abs(duration - expected_duration) > duration_tolerance:
        problems.append(
            f"sure {duration:.2f}s, beklenen {expected_duration:.2f}s"
        )
    if not has_audio:
        problems.append("ses akisi yok")
    if audio is not None and av_delta > sync_tolerance:
        problems.append(f"ses/goruntu suresi farki {av_delta:.2f}s")

    return ValidationReport(
        ok=not problems,
        width=width,
        height=height,
        duration_seconds=duration,
        has_audio=has_audio,
        av_sync_delta=round(av_delta, 4),
        problems=problems,
    )
