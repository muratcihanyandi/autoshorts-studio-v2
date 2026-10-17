"""Authorized media-source adapters (M7).

An adapter turns one source video into a local file inside the
labelled media tree. Two origins exist:

- 'local_import': the operator places an already-authorized file on
  disk and the pipeline copies it in (original stays untouched).
- 'youtube': yt-dlp fetches the video from the authorized source
  channel. yt-dlp runs as a subprocess probed on PATH (ADR-012) —
  missing binary or failed exit surfaces as a Turkish job error, and
  the download rate limit from settings becomes --limit-rate.

Sequential downloads are enforced by the caller (worker registry)
through a shared asyncio.Lock passed to fetch(); adapters stay
individually testable.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from app.config import Settings

Runner = Callable[..., Awaitable[Any]]


class MediaDownloadError(Exception):
    """Download failure with a user-facing Turkish message."""


@dataclass
class DownloadResult:
    path: Path
    origin: str
    file_bytes: int


class MediaSourceAdapter(Protocol):
    async def fetch(
        self,
        source_video_id: int,
        youtube_video_id: str,
        dest_dir: Path,
    ) -> DownloadResult:
        """Place the media file in dest_dir and report it."""
        ...


class LocalImportAdapter:
    """Copy an operator-provided file into the media tree (never moves)."""

    def __init__(self, import_path: str | Path) -> None:
        self._import_path = Path(import_path)

    async def fetch(
        self,
        source_video_id: int,
        youtube_video_id: str,
        dest_dir: Path,
    ) -> DownloadResult:
        if not self._import_path.is_file():
            raise MediaDownloadError(
                f"Iceri aktarilacak dosya yok: {self._import_path}"
            )
        if self._import_path.stat().st_size == 0:
            raise MediaDownloadError("Iceri aktarilan dosya bos.")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{source_video_id}{self._import_path.suffix or '.mp4'}"
        await asyncio.to_thread(shutil.copy2, self._import_path, dest)
        return DownloadResult(
            path=dest, origin="local_import", file_bytes=dest.stat().st_size
        )


class YtDlpAdapter:
    """Fetch a YouTube video via the yt-dlp CLI (optional at runtime)."""

    def __init__(self, settings: Settings, runner: Runner | None = None) -> None:
        self._settings = settings
        # None -> gercek subprocess; testler sahte runner enjekte eder.
        self._runner = runner

    def build_command(
        self, youtube_video_id: str, dest_dir: Path, output_path: str
    ) -> list[str]:
        """Command template; rate limit applies when configured."""
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--merge-output-format", "mp4",
            "--write-auto-subs",
            "--sub-langs", "tr,en",
            "-f", "bv*+ba/b",
            "-o", output_path,
        ]
        if self._settings.download_rate_limit_kbps > 0:
            cmd += [
                "--limit-rate", f"{self._settings.download_rate_limit_kbps}K"
            ]
        cmd.append(f"https://www.youtube.com/watch?v={youtube_video_id}")
        return cmd

    async def _run_subprocess(self, cmd: list[str]) -> int:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), 3600.0)
        if proc.returncode != 0:
            tail = stderr.decode("utf-8", "replace").strip()[-500:]
            raise MediaDownloadError(f"yt-dlp basarisiz: {tail}")
        return proc.returncode

    async def fetch(
        self,
        source_video_id: int,
        youtube_video_id: str,
        dest_dir: Path,
    ) -> DownloadResult:
        if self._runner is None:
            if shutil.which("yt-dlp") is None:
                raise MediaDownloadError(
                    "yt-dlp bulunamadi; konteyner imajina kurulu olmali."
                )
            runner = self._run_subprocess
        else:
            runner = self._runner
        dest_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(dest_dir / f"{source_video_id}.%(ext)s")
        cmd = self.build_command(youtube_video_id, dest_dir, output_path)
        await runner(cmd)
        # yt-dlp uzantiyi kendisi secer: en yeni video dosyasini bul.
        candidates = sorted(
            (
                p
                for p in dest_dir.glob(f"{source_video_id}.*")
                if p.suffix in (".mp4", ".mkv", ".webm", ".m4a")
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise MediaDownloadError(
                "yt-dlp cikti dosyasi olusturmadi; indirme basarisiz."
            )
        media = candidates[0]
        return DownloadResult(
            path=media, origin="youtube", file_bytes=media.stat().st_size
        )
