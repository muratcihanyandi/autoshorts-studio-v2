"""9:16 vertical rendering (M8) and 16:9 horizontal full cuts (M13).

Vertical layout: the output is 1080x1920 — the top fraction is the
webcam crop (padded face box, aspect-corrected to the section), the
rest is a center crop of the source video. Subtitles burn into the
bottom band of the video section with ASS-style positioning, so they
can never overlap the webcam section.

Horizontal full cuts (reaction sources) are 1920x1080 scale+pad
renders with input seeking (-ss/-to) for fast trimming; subtitles are
NEVER burned there and audio is preserved.

Rendering is one ffmpeg pass; validation re-probes the output
(resolution, duration tolerance, audio presence, A/V stream-duration
sync). Layout math is pure and unit-tested; the render tests run real
ffmpeg.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.services.media_probe import MediaProbeError, run_ffprobe

OUT_W = 1080
OUT_H = 1920
HORIZONTAL_W = 1920
HORIZONTAL_H = 1080
# Ust bolumun paylasacagi en buyuk yukseklik orani: cok dik webcam
# dikdortgenlerinde bile alt bant (icerik + altyazi) yasamali.
MAX_TOP_FRACTION = 0.65
DEFAULT_WEBCAM_PADDING = 0.35


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
    max_top_fraction: float = MAX_TOP_FRACTION,
    padding: float = DEFAULT_WEBCAM_PADDING,
) -> VerticalLayout:
    """Compute the two crop rectangles and the subtitle band.

    Kullanici istegi (2026-10-21): webcam ZOOMLANMAZ — bulunan
    dikdortgen (pad'li) en-boy orani korunarak tam genislikte ust
    bolume sigdirilir; bolum yuksekligi dikdortgenin oranindan tureir.
    Cok dik dikdortgenlerde yukseklik sinirina takilinca yanlardan
    pad'lenir (contain), asla kirpilmaz. Alt bant kaynak videonun
    merkez dilimidir.
    """
    if source_w <= 0 or source_h <= 0:
        raise VerticalRenderError("Kaynak video boyutlari gecersiz.")
    fx, fy, fw, fh = webcam
    if fw <= 0 or fh <= 0:
        raise VerticalRenderError("Webcam bolgesi gecersiz.")

    # Webcam: pad'li kutu; kaynak cerceveye sigdir (olcek kucultur,
    # merkez korunur) — en-boy duzeltme (zoom) YOK.
    cx = fx + fw / 2.0
    cy = fy + fh / 2.0
    box_w = fw * (1 + 2 * padding)
    box_h = fh * (1 + 2 * padding)
    scale = min(1.0, source_w / box_w, source_h / box_h)
    box_w *= scale
    box_h *= scale
    tx = _clamp(int(round(cx - box_w / 2)), 0, max(0, source_w - int(box_w)))
    ty = _clamp(int(round(cy - box_h / 2)), 0, max(0, source_h - int(box_h)))
    tw = min(int(box_w), source_w - tx)
    th = min(int(box_h), source_h - ty)
    if tw <= 0 or th <= 0:
        raise VerticalRenderError("Webcam bolgesi gecersiz.")

    # Ust bolum yuksekligi: dikdortgen tam genislige olceklendigindeki
    # yukseklik; cok dikse sinira kilitle ve genislik contain olur.
    max_top_h = int(round(out_h * max_top_fraction))
    top_h = int(round(th * out_w / tw))
    displayed_w = out_w
    if top_h > max_top_h:
        top_h = max_top_h
        displayed_w = max(1, int(round(tw * (top_h / th))))
    bottom_h = out_h - top_h

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
        top={
            "x": tx,
            "y": ty,
            "w": tw,
            "h": th,
            "out_h": top_h,
            "out_w": displayed_w,
        },
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
    """Iki kirpma + vstack; subtitle_path verilirse alt banda gomulur.

    Altyazi dosyasi ASS'tir ve stilini kendi icinde tasir (PlayRes
    1080x1920 — uretimi subtitle_style.build_ass); force_style
    kullanilmaz ki onizleme ayni degerlerle birebir cizilebilsin."""
    top = layout.top
    bottom = layout.bottom
    subtitle = (
        f"subtitles='{_escape_filter_path(subtitle_path)}'"
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
    # Ust bolum: dikdortgen olceklenir (out_w x out_h bolum icin),
    # dar kalirsa yanlardan pad'lenir — kirpma (zoom) yok.
    top_w = top.get("out_w", layout.out_w)
    return (
        f"[0:v]split=2[base1][base2];"
        f"[base1]crop={top['w']}:{top['h']}:{top['x']}:{top['y']}"
        f",scale={top_w}:{top['out_h']}"
        f",pad={layout.out_w}:{top['out_h']}:(ow-iw)/2:(oh-ih)/2[top];"
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
    threads: int = 0,
    timeout: float = 1800.0,
) -> Path:
    """Render the composed 9:16 clip; raises on ffmpeg failure.

    threads > 0 appends -threads N (Pi CPU limit); 0 leaves ffmpeg's
    own default."""
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
    ]
    if threads > 0:
        cmd += ["-threads", str(threads)]
    cmd.append(str(out))
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


def build_horizontal_filter() -> str:
    """1920x1080 scale+pad (aspect preserved, letterboxed); altyazi
    FIRMASIZ — yatay tam kesitlerde asla yakilmaz."""
    return (
        f"scale={HORIZONTAL_W}:{HORIZONTAL_H}"
        ":force_original_aspect_ratio=decrease,"
        f"pad={HORIZONTAL_W}:{HORIZONTAL_H}:(ow-iw)/2:(oh-ih)/2"
    )


async def render_horizontal(
    ffmpeg_bin: str,
    source_path: str | Path,
    out_path: str | Path,
    *,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
    source_duration: float | None = None,
    threads: int = 0,
    timeout: float = 1800.0,
) -> Path:
    """Render the trimmed 16:9 full cut; raises on ffmpeg failure.

    Input seeking (-ss/-to, both in the source's own timeline) keeps
    trimming fast; -to is the source duration minus the end trim and
    is omitted when the duration is unknown (no end trim then).
    threads > 0 appends -threads N (Pi CPU limit).
    """
    if trim_start < 0 or trim_end < 0:
        raise VerticalRenderError("Budama degerleri negatif olamaz.")
    if source_duration is not None:
        if source_duration <= 0:
            raise VerticalRenderError("Kaynak video suresi gecersiz.")
        if source_duration - trim_end <= trim_start:
            raise VerticalRenderError("Gecersiz budama araligi.")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{trim_start:.3f}",
    ]
    if source_duration is not None:
        cmd += ["-to", f"{source_duration - trim_end:.3f}"]
    cmd += [
        "-i", str(source_path),
        "-vf", build_horizontal_filter(),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
    ]
    if threads > 0:
        cmd += ["-threads", str(threads)]
    cmd.append(str(out))
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


async def validate_output(
    ffprobe_bin: str,
    out_path: str | Path,
    expected_duration: float,
    *,
    expected_size: tuple[int, int] = (OUT_W, OUT_H),
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

    if (width, height) != expected_size:
        problems.append(
            f"cozunurluk {width}x{height}, beklenen "
            f"{expected_size[0]}x{expected_size[1]}"
        )
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
