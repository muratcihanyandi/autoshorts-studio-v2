"""ffprobe inspection and media integrity (M7).

External tools run as subprocesses (ADR-012): crashes stay isolated
from the worker process and the binaries are probed on PATH. A probe
that fails, times out, or returns an unusable stream layout raises
MediaProbeError with a Turkish, job-visible message.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class MediaProbeError(Exception):
    """Probe failure with a user-facing Turkish message."""


@dataclass
class InspectionData:
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    has_audio: bool
    format_name: str | None


def _parse_frame_rate(value: str | None) -> float:
    """'30000/1001' -> 29.97; bad or '0/0' values become 0.0."""
    if not value or "/" not in value:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
    num, _, den = value.partition("/")
    try:
        num_f, den_f = float(num), float(den)
    except ValueError:
        return 0.0
    if den_f == 0:
        return 0.0
    return num_f / den_f


def parse_probe(raw: dict) -> InspectionData:
    """Map ffprobe's JSON output onto the inspection record."""
    try:
        duration = float(raw["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaProbeError("Medya suresi okunamadi.") from exc

    video = None
    audio = None
    for stream in raw.get("streams", []):
        if stream.get("codec_type") == "video" and video is None:
            video = stream
        elif stream.get("codec_type") == "audio" and audio is None:
            audio = stream
    if video is None:
        raise MediaProbeError("Medyada video akisi bulunamadi.")

    return InspectionData(
        duration_seconds=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_parse_frame_rate(video.get("r_frame_rate")),
        video_codec=str(video.get("codec_name") or ""),
        audio_codec=str(audio.get("codec_name")) if audio else None,
        has_audio=audio is not None,
        format_name=raw.get("format", {}).get("format_name"),
    )


def integrity_ok(data: InspectionData) -> bool:
    """A file is processable only with a real video stream and duration."""
    return (
        data.duration_seconds > 0
        and data.width > 0
        and data.height > 0
        and data.fps > 0
        and bool(data.video_codec)
    )


async def run_ffprobe(
    ffprobe_bin: str, path: str | Path, *, timeout: float = 120.0
) -> dict:
    """Run ffprobe and return its parsed JSON; errors carry stderr tail."""
    proc = await asyncio.create_subprocess_exec(
        ffprobe_bin,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise MediaProbeError("ffprobe zaman asimina ugradi.") from None
    if proc.returncode != 0:
        tail = stderr.decode("utf-8", "replace").strip()[-500:]
        raise MediaProbeError(f"ffprobe basarisiz: {tail}")
    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MediaProbeError("ffprobe ciktisi JSON olarak okunamadi.") from exc


async def probe_media(ffprobe_bin: str, path: str | Path) -> InspectionData:
    raw = await run_ffprobe(ffprobe_bin, path)
    return parse_probe(raw)


def _sha256_sync(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def sha256_file(path: str | Path) -> str:
    """Chunked file hash off the event loop (files can be hundreds of MB)."""
    target = Path(path)
    if not target.is_file():
        raise MediaProbeError("Hash hesaplanacak dosya yok.")
    return await asyncio.to_thread(_sha256_sync, target)
