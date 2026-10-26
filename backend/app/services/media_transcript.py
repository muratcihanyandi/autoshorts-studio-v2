"""Transcript parsing and sidecar discovery (M7).

yt-dlp writes auto-generated caption files next to the media
(--write-auto-subs), and local imports may carry their own sidecar.
Both VTT and SRT are parsed here in-process: timestamped segments
feed candidate scoring (M7) and later Turkish correction (M9).
Malformed cues are skipped, never fatal.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

_TIMESTAMP = re.compile(
    r"(\d{1,2}:)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)

# YouTube otomatik altyazilari (yt-dlp --write-auto-subs) kelime
# zamanlamasi etiketleri tasir: "<00:00:08.040><c> almaya</c>".
# Bunlar cue metnine karisirsa klipte zaman damgalari olarak görünür
# (2026-10-21 canli bulgu). VTT inline etiketleri ve HTML varliklari
# temizlenir.
_VTT_TAG = re.compile(r"<[^>]+>")
_HTML_ENTITIES = {
    "&gt;": ">",
    "&lt;": "<",
    "&amp;": "&",
    "&quot;": '"',
    "&#39;": "'",
    "&nbsp;": " ",
}


def _clean_cue_text(raw: str) -> str:
    """VTT/SRT cue metnini altyazi olarak kullanilabilir hale getir:
    inline etiketler ve HTML varliklari ayiklanir, beyaz alan
    duzlestirilir, bastaki konusmaci gecis isareti ('>>') kaldirilir."""
    text = _VTT_TAG.sub(" ", raw)
    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)
    text = " ".join(text.split())
    return re.sub(r"^>>\s*", "", text)


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
    """Parse WEBVTT cue blocks into [{start, end, text}].

    YouTube otomatik altyazilari 'kayan' cue'lar yazar: her blokta ilk
    satir onceki cue'nun metnini tekrarlar, asil ekleme sonraki
    satirdadir. Tekrar kaldirilir ki altyazida cumleler iki kez
    görünmesin (yalnizca ilk satir gercekten onceki cue ile ayniysa —
    manuel cok satirli altyazilar bozulmaz)."""
    segments: list[dict] = []
    prev_text = ""
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
        cleaned = [_clean_cue_text(line) for line in text_lines]
        cleaned = [line for line in cleaned if line]
        if len(cleaned) >= 2 and cleaned[0] == prev_text:
            cleaned = cleaned[1:]
        if not cleaned:
            continue
        cue_text = " ".join(cleaned)
        segments.append(
            {"start": cue[0], "end": cue[1], "text": cue_text}
        )
        prev_text = cue_text
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
        cleaned = " ".join(
            line
            for line in (_clean_cue_text(l) for l in text_lines)
            if line
        )
        if not cleaned:
            continue
        segments.append(
            {"start": cue[0], "end": cue[1], "text": cleaned}
        )
    return segments


def parse_sidecar_text(text: str) -> list[dict]:
    """Dispatch on the stronger VTT marker, else try SRT."""
    if text.lstrip().startswith("WEBVTT"):
        return parse_vtt(text)
    return parse_srt(text)


def find_sidecar(
    media_path: str | Path, preferred_lang: str = "tr"
) -> Path | None:
    """Caption file next to the media: exact stem first, then preferred
    language (Türkçe: '<id>.tr.vtt'), then other language-suffixed names."""
    media = Path(media_path)
    # 1. Tam dosya adı eşleşmesi (<id>.vtt / <id>.srt)
    for suffix in (".vtt", ".srt"):
        exact = media.with_suffix(suffix)
        if exact.is_file():
            return exact
    # 2. Öncelikli dil eki (<id>.tr.vtt / <id>.tr.srt)
    for suffix in (".vtt", ".srt"):
        pref = media.parent / f"{media.stem}.{preferred_lang}{suffix}"
        if pref.is_file():
            return pref
    # 3. Diğer yan altyazı dosyaları
    candidates: list[Path] = []
    for suffix in (".vtt", ".srt"):
        candidates.extend(
            p for p in sorted(media.parent.glob(f"{media.stem}.*{suffix}"))
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


async def load_segments(
    session: AsyncSession, media_asset_id: int
) -> list[dict]:
    """Mevcut en iyi transkript dilimleri: duzeltilmis (M9) yoksa ham
    (sidecar/Whisper). Aday secimi ve altyazi gomme ayni onceligi
    paylasir — duzeltilmis metin klipe de oyle dusmelidir."""
    from app.models import CorrectedTranscript, Transcript

    corrected = (
        (
            await session.execute(
                sa_select(CorrectedTranscript).where(
                    CorrectedTranscript.media_asset_id == media_asset_id
                )
            )
        )
        .scalars()
        .one_or_none()
    )
    if corrected is not None:
        return list(corrected.segments)
    original = (
        (
            await session.execute(
                sa_select(Transcript).where(
                    Transcript.media_asset_id == media_asset_id
                )
            )
        )
        .scalars()
        .one_or_none()
    )
    return list(original.segments) if original is not None else []


class TranscriptError(Exception):
    """Transcription failure with a user-facing Turkish message."""


class WhisperTranscriber:
    """Local Whisper fallback (openai-whisper paketi, `python -m whisper`).

    Runs Whisper on the backend's own interpreter so no PATH setup is
    needed; the package is installed either into the environment
    directly (Windows dev) or into the persistent media-tree target
    with PYTHONPATH (Linux/Pi container — see whisper_install). Test
    doubles inject a runner; the env carries the install plan's
    PYTHONPATH when a target install is in use.
    """

    def __init__(self, runner=None, env: dict | None = None) -> None:
        # None -> gercek subprocess; testler sahte runner enjekte eder.
        self._runner = runner
        self._env = env

    def build_command(
        self,
        media_path: str | Path,
        output_dir: Path,
        *,
        model: str,
        language: str,
    ) -> list[str]:
        cmd = [
            sys.executable,
            "-m",
            "whisper",
            str(media_path),
            "--model", model,
            "--language", language,
            "--output_format", "srt",
            "--output_dir", str(output_dir),
            "--fp16", "False",
        ]
        return cmd

    def _available(self) -> bool:
        """Whisper kurulu mu: yorumlayicida import edilebilir ya da
        verilen PYTHONPATH hedef dizininde paket var."""
        if _spec_available():
            return True
        pythonpath = (self._env or {}).get("PYTHONPATH", "")
        for entry in pythonpath.split(os.pathsep):
            if entry and (Path(entry) / "whisper").is_dir():
                return True
        return False

    async def _run_subprocess(self, cmd: list[str]) -> int:
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        # Whisper kucuk modellerde bile yavastir; uzun video icin bol
        # zaman taninir (is kuyrugu zaten sirali).
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), 14400.0)
        except TimeoutError as exc:
            # Bos mesajli "TimeoutError: " kayitlarini engelle (2026-10-23
            # canli olay:RRaenee videosu, kullanic hatayi hic goremedi).
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise TranscriptError(
                "whisper 4 saatte tamamlanamadi (zaman asimi); video cok "
                "uzun olabilir — sistem YouTube altyazisina dusecek"
            ) from exc
        if proc.returncode != 0:
            tail = stderr.decode("utf-8", "replace").strip()[-500:]
            if not tail:
                raise TranscriptError(
                    "whisper hata ciktisi yazmadan kapandi (genellikle "
                    "bellek yetersizligi); sistem YouTube altyazisina "
                    "dusecek"
                )
            raise TranscriptError(f"whisper basarisiz: {tail}")
        return proc.returncode

    async def transcribe(
        self,
        media_path: str | Path,
        output_dir: Path,
        *,
        model: str = "tiny",
        language: str = "tr",
    ) -> list[dict]:
        """Run Whisper and return parsed segments."""
        media = Path(media_path)
        if not media.is_file():
            raise TranscriptError(f"Medya dosyasi yok: {media}")
        output_dir.mkdir(parents=True, exist_ok=True)
        if not self._available():
            raise TranscriptError(
                "whisper kurulu degil; Ayarlar ekranindaki 'Whisper'i "
                "Indir ve Kur' dugmesiyle kurabilirsiniz."
            )
        cmd = self.build_command(
            media, output_dir, model=model, language=language
        )
        if self._runner is None:
            runner = self._run_subprocess
        else:
            runner = self._runner
        await runner(cmd)
        srt = output_dir / f"{media.stem}.srt"
        if not srt.is_file():
            raise TranscriptError("whisper cikti dosyasi olusturmadi.")
        text = await _read_text(srt)
        segments = parse_srt(text)
        if not segments:
            raise TranscriptError("whisper ciktisi bos/ayristirilamadi.")
        return segments


def _spec_available() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("whisper") is not None
    except Exception:  # noqa: BLE001
        return False


async def _read_text(path: Path) -> str:
    import asyncio

    return await asyncio.to_thread(
        path.read_text, encoding="utf-8", errors="replace"
    )
