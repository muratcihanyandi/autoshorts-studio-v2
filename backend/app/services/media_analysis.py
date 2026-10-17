"""Audio/video analysis for clip planning (M7).

Three measurements feed candidate scoring, all via ffmpeg subprocesses
(ADR-012):

- silence runs: silencedetect filter -> intro/outro candidates
- scene changes: select=gt(scene,T) + showinfo -> cut timestamps
- audio energy: decode to mono 8kHz PCM, windowed RMS in Python

Log parsing lives in pure functions so crafted log text tests the
parsing without running ffmpeg; the real-media tests then verify the
measurements end to end.
"""
from __future__ import annotations

import asyncio
import math
import re
import sys
from array import array
from pathlib import Path

_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_PTS_TIME = re.compile(r"pts_time:\s*(\d+(?:\.\d+)?)")


def parse_silence_log(log_text: str) -> list[tuple[float, float]]:
    """Pair silence_start/silence_end lines into (start, end) runs."""
    starts: list[float] = []
    pairs: list[tuple[float, float]] = []
    for line in log_text.splitlines():
        start_match = _SILENCE_START.search(line)
        if start_match:
            starts.append(float(start_match.group(1)))
            continue
        end_match = _SILENCE_END.search(line)
        if end_match and starts:
            start = starts.pop(0)
            end = float(end_match.group(1))
            if end > start:
                pairs.append((max(0.0, start), end))
    # Kapanmayan sessizlik (dosya sonu) kapanis olarak ele alinmaz;
    # cagiran taraf duration ile tamamlar.
    return pairs


def parse_scene_log(log_text: str) -> list[float]:
    """Collect pts_time values from showinfo lines."""
    times: list[float] = []
    for line in log_text.splitlines():
        if "pts_time:" not in line:
            continue
        match = _PTS_TIME.search(line)
        if match:
            times.append(float(match.group(1)))
    return times


def intro_outro_from_silences(
    silences: list[tuple[float, float]], duration: float
) -> tuple[float, float]:
    """Leading/trailing silence -> (intro_end, outro_start).

    A silence run counts as intro only when it starts at ~0; as outro
    only when it runs to ~the end. Defaults keep the whole range.
    """
    intro_end = 0.0
    outro_start = duration
    for start, end in silences:
        if start <= 0.5 and end < duration - 0.5:
            intro_end = max(intro_end, end)
        elif end >= duration - 0.5 and start > 0.5:
            outro_start = min(outro_start, start)
    return intro_end, outro_start


async def detect_silence(
    ffmpeg_bin: str,
    path: str | Path,
    *,
    noise_db: float,
    min_seconds: float,
    timeout: float = 600.0,
) -> list[tuple[float, float]]:
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-i", str(path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_seconds}",
        "-f", "null",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("silencedetect zaman asimina ugradi.") from None
    return parse_silence_log(stderr.decode("utf-8", "replace"))


async def detect_scene_changes(
    ffmpeg_bin: str,
    path: str | Path,
    *,
    threshold: float,
    timeout: float = 600.0,
) -> list[float]:
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-i", str(path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("sahne analizi zaman asimina ugradi.") from None
    return parse_scene_log(stderr.decode("utf-8", "replace"))


def window_rms(samples: array, window_size: int) -> list[float]:
    """RMS per full window; trailing partial windows are dropped."""
    if window_size <= 0:
        return []
    windows: list[float] = []
    for offset in range(0, len(samples) - window_size + 1, window_size):
        chunk = samples[offset : offset + window_size]
        acc = 0.0
        for value in chunk:
            acc += value * value
        windows.append(math.sqrt(acc / window_size))
    return windows


def bytes_to_samples(data: bytes) -> array:
    """Little-endian s16 bytes -> int array (byte order normalized)."""
    samples = array("h")
    usable = len(data) - (len(data) % 2)
    samples.frombytes(data[:usable])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


async def audio_rms_windows(
    ffmpeg_bin: str,
    path: str | Path,
    *,
    sample_rate: int = 8000,
    window_seconds: float = 1.0,
    timeout: float = 600.0,
) -> list[float]:
    """Decode mono PCM and return per-second RMS levels (0..32768)."""
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-hide_banner",
        "-i", str(path),
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "s16le",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    collected = bytearray()

    async def read_stdout() -> None:
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(64 * 1024)
            if not chunk:
                break
            collected.extend(chunk)

    try:
        reader = asyncio.create_task(read_stdout())
        await asyncio.wait_for(proc.wait(), timeout)
        await reader
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("ses analizi zaman asimina ugradi.") from None
    window_size = max(1, int(sample_rate * window_seconds))
    return window_rms(bytes_to_samples(bytes(collected)), window_size)
