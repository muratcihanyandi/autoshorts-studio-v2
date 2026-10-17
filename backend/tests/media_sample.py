"""Synthetic test media for M7 media-tooling tests (shared helper).

Generates a deterministic 12s mp4 with real ffmpeg lavfi sources:
- video: 320x240 @ 15fps, hard color cuts at 4s and 8s (scene changes)
- audio: 440 Hz sine muted during 0-2s and 10-12s (silence runs)

The dev machine and the CI image both provide ffmpeg on PATH (see
AGENTS.md environment notes); tests fail honestly when it is missing.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

SCENE_CUTS = (4.0, 8.0)
SILENCE_RUNS = ((0.0, 2.0), (10.0, 12.0))
TOTAL_SECONDS = 12.0


def make_test_media(path: str | Path) -> Path:
    """Generate the synthetic clip at path; returns the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:r=15:d=4",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=15:d=4",
        "-f", "lavfi", "-i", "color=c=green:s=320x240:r=15:d=4",
        # Ornek seviyesinde kapili 440 Hz ton: 0-2s ve 10-12s sessiz.
        "-f", "lavfi", "-i",
        "aevalsrc='sin(2*PI*440*t)*if(between(t,0,2),0,if(between(t,10,12),0,0.4))':s=8000:d=12",
        "-filter_complex",
        "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]",
        "-map", "3:a",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        "-shortest",
        str(target),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    return target


ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FACE_IMAGE = ASSETS_DIR / "face_pd.jpg"


def make_face_stream_video(path: str | Path, duration: int = 8) -> Path:
    """'Yayinci' senaryosu: kamu malı yüz fotoğrafı, koyu zemin üzerinde
    üst-sol köşeye yerleştirilmiş, hafif salınımlı, sesli video.

    Yüz ~ (280, 155, 85, 85) bölgesinde 1280x720 karede; çok kareli
    tespit + kümeleme bunu yakalamalı (tek kare kaçırmalar normal).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG_BIN,
        "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-r", "15", "-t", str(duration), "-i", str(FACE_IMAGE),
        "-f", "lavfi", "-i",
        f"color=c=0x224466:s=1280x720:r=15:d={duration}",
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate=8000:duration={duration}",
        "-filter_complex",
        "[0:v]scale=480:600[jit];"
        "[jit]crop=460:580:x='10+6*sin(t)':y='10+5*cos(1.2*t)'[face];"
        "[1:v][face]overlay=40:40:shortest=1[v]",
        "-map", "[v]",
        "-map", "2:a",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        "-shortest",
        str(target),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    return target
