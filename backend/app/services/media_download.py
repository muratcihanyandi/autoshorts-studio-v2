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
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from app.config import Settings

Runner = Callable[..., Awaitable[Any]]

# yt-dlp --newline ilerleme satiri: "[download]  63.4% of ~1.23GiB at ..."
_PROGRESS_LINE = re.compile(rb"\[download\]\s+(\d+(?:\.\d+)?)%")

DOWNLOAD_TIMEOUT_SECONDS = 14400.0


def parse_progress_line(line: bytes | str) -> float | None:
    """Bir yt-dlp satirindan yuzde cikarir; ilerleme satiri degilse None."""
    if isinstance(line, str):
        line = line.encode("utf-8", "replace")
    match = _PROGRESS_LINE.search(line)
    return float(match.group(1)) if match else None


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
        *,
        on_progress: Callable[[float], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        """Place the media file in dest_dir and report it. on_progress,
        verilirse indirme yuzdesiyle periyodik cagrilir (yt-dlp yolu)."""
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
        *,
        on_progress: Callable[[float], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        if not self._import_path.is_file():
            raise MediaDownloadError(
                f"Iceri aktarilacak dosya yok: {self._import_path}"
            )
        if self._import_path.stat().st_size == 0:
            raise MediaDownloadError("Iceri aktarilan dosya bos.")
        del on_progress  # yerel kopyalama anlik biter; yuzde anlamli degil
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{source_video_id}{self._import_path.suffix or '.mp4'}"
        await asyncio.to_thread(shutil.copy2, self._import_path, dest)
        # Ayni adli altyazi dosyasi varsa transkript asamasi icin tasinir.
        for sidecar_suffix in (".vtt", ".srt"):
            sidecar = self._import_path.with_suffix(sidecar_suffix)
            if sidecar.is_file():
                await asyncio.to_thread(
                    shutil.copy2,
                    sidecar,
                    dest_dir / f"{source_video_id}{sidecar_suffix}",
                )
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
            # YouTube timedtext limiti (HTTP 429) tek bir altyazi dilini
            # dusurebilir; video ve diger altyazilar insin. Video dosyasi
            # olusmazsa fetch asagidaki cikti kontroluyle yine hata verir.
            "--ignore-errors",
            # Ilerleme her guncellemeyi yeni satira yazar: stdout satir
            # satir okunup yuzde ayiklanir (UI'da "%63" gosterimi).
            "--newline",
            "--merge-output-format", "mp4",
            "--write-auto-subs",
            "--sub-langs", "tr,en",
            # 1080p tavan + H.264 tercihi: YouTube 1080p'de de AV1 sunar;
            # AV1'i OpenCV (webcam tespiti) cozumleyemez ve Pi'de cozumleme
            # 3-5 kat yavastir. H.264 yoksa sinirsiz yedek devreye girer.
            "-f",
            "bv*[height<=1080][vcodec^=avc]+ba"
            "/b[height<=1080][vcodec^=avc]"
            "/bv*[height<=1080]+ba/b[height<=1080]",
            "-o", output_path,
        ]
        if self._settings.download_rate_limit_kbps > 0:
            cmd += [
                "--limit-rate", f"{self._settings.download_rate_limit_kbps}K"
            ]
        cmd.append(f"https://www.youtube.com/watch?v={youtube_video_id}")
        return cmd

    async def _run_subprocess(
        self,
        cmd: list[str],
        on_progress: Callable[[float], Awaitable[None]] | None = None,
    ) -> int:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def run_with_progress() -> bytes:
            assert proc.stdout is not None and proc.stderr is not None
            stderr_task = asyncio.create_task(proc.stderr.read())
            last_percent = -1.0
            try:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    if on_progress is None:
                        continue
                    percent = parse_progress_line(line)
                    if percent is not None and percent > last_percent:
                        last_percent = percent
                        await on_progress(percent)
                return await stderr_task
            finally:
                if not stderr_task.done():
                    stderr_task.cancel()

        try:
            stderr = await asyncio.wait_for(
                run_with_progress(), DOWNLOAD_TIMEOUT_SECONDS
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise MediaDownloadError(
                "Indirme zaman asimina ugradi (4 saat)."
            ) from None
        if proc.returncode != 0:
            tail = stderr.decode("utf-8", "replace").strip()[-500:]
            raise MediaDownloadError(f"yt-dlp basarisiz: {tail}")
        return proc.returncode

    async def fetch(
        self,
        source_video_id: int,
        youtube_video_id: str,
        dest_dir: Path,
        *,
        on_progress: Callable[[float], Awaitable[None]] | None = None,
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
        # Yuzde monoton ilerler: yt-dlp birllesme/akis sonrasi geri
        # sarabilir; UI'da geri gitme gosterilmez.
        last_percent = -1.0

        async def guarded(percent: float) -> None:
            nonlocal last_percent
            if percent <= last_percent or on_progress is None:
                return
            last_percent = percent
            await on_progress(percent)

        await runner(cmd, on_progress=guarded if on_progress else None)
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
