"""Transcript parsing and sidecar discovery (M7).

yt-dlp writes auto-generated caption files next to the media
(--write-auto-subs), and local imports may carry their own sidecar.
Both VTT and SRT are parsed here in-process: timestamped segments
feed candidate scoring (M7) and later Turkish correction (M9).
Malformed cues are skipped, never fatal.
"""
from __future__ import annotations

import re
from pathlib import Path

_TIMESTAMP = re.compile(
    r"(\d{1,2}:)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)


def _seconds(hours: str | None, minutes: str, secs: str, millis: str) -> float:
    total = int(minutes) * 60 + int(secs) + int(millis.ljust(3, "0")) / 1000
    if hours:
        total += int(hours.rstrip(":")) * 3600
    return total


def _parse_cue_line(line: str) -> tuple[float, float] | None:
    """'00:00:01.000 --> 00:00:03.000' -> (1.0, 3.0); None when absent."""
    if "-->" not in line:
        return None
    stamps = _TIMESTAMP.findall(line)
    if len(stamps) < 2:
        return None
    start = _seconds(*stamps[0])
    end = _seconds(*stamps[1])
    if end <= start:
        return None
    return start, end


def _split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def parse_vtt(text: str) -> list[dict]:
    """Parse WEBVTT cue blocks into [{start, end, text}]."""
    segments: list[dict] = []
    for block in _split_blocks(text):
        cue = None
        text_lines: list[str] = []
        for line in block:
            if cue is None:
                cue = _parse_cue_line(line)
                continue
            text_lines.append(line)
        if cue is None or not text_lines:
            continue
        segments.append(
            {"start": cue[0], "end": cue[1], "text": " ".join(text_lines)}
        )
    return segments


def parse_srt(text: str) -> list[dict]:
    """Parse SRT blocks (optional leading index line) into segments."""
    segments: list[dict] = []
    for block in _split_blocks(text):
        cue = None
        text_lines: list[str] = []
        for line in block:
            if cue is None:
                cue = _parse_cue_line(line)
                if cue is not None:
                    continue
                # indeks satiri: atla, cue henuz yok
                continue
            text_lines.append(line)
        if cue is None or not text_lines:
            continue
        segments.append(
            {"start": cue[0], "end": cue[1], "text": " ".join(text_lines)}
        )
    return segments


def parse_sidecar_text(text: str) -> list[dict]:
    """Dispatch on the stronger VTT marker, else try SRT."""
    if text.lstrip().startswith("WEBVTT"):
        return parse_vtt(text)
    return parse_srt(text)


def find_sidecar(media_path: str | Path) -> Path | None:
    """Caption file next to the media: exact stem first, then
    language-suffixed names (yt-dlp writes '<id>.tr.vtt')."""
    media = Path(media_path)
    candidates: list[Path] = []
    for suffix in (".vtt", ".srt"):
        exact = media.with_suffix(suffix)
        candidates.append(exact)
        candidates.extend(
            p for p in sorted(media.parent.glob(f"{media.stem}.*{suffix}"))
            if p != exact
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def transcript_text_in_range(
    segments: list[dict], start: float, end: float
) -> str:
    """Joined text of segments overlapping [start, end)."""
    parts = [
        seg["text"]
        for seg in segments
        if seg["end"] > start and seg["start"] < end
    ]
    return " ".join(parts).strip()
