"""Otomatik intro/outro tespiti (2026-10-24 kullanici istegi).

Yatay tam kesit, kaynak videonun ACIKCA intro ve outro'su cikarilarak
paylasilir; bunu kullanici elle ayarlamaz. Tespit dort bagimsiz
sinyalin birlesimidir ve hicbiri tek basina icerik kesmez:

- **Konusma bosluklari** (whisper transkripti): videonun basinda/sonunda
  konusma yoksa orasi jenerik/bitis kartidir.
- **Sessizlik** (ffmpeg silencedetect): kenardan baslayan sessizlik
  blogu intro/outro'nun ses tarafidir.
- **Siyah kare** (ffmpeg blackdetect): gecis/bitis kartlarinda tipiktir.
- **Sahne kesmesi** (showinfo): konusmasiz blogun sinirinda sert bir
  kesme varsa jenerik -> icerik gecisi tam oradan alinir.

Emniyet kurallari: her taraf sure'nin en fazla %10'u (intro 90 sn,
outro 120 sn) kadar budanir, videonun en az %70'i ve en az 60 saniyesi
kalir. Sinyal yoksa budama 0'dir — yanlis kesmek, kesmemekten kotudur.

Saf fonksiyon :func:`detect_auto_trim` ffmpeg calistirmadan test
edilebilir; :func:`compute_auto_trim_for_asset` depodan veriyi okur,
kenar pencerelerinde blackdetect kosar ve sonucu asset.analysis'e yazar.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings

# Bir tarafin budayabilecegi ust sinirlar (kullanici istegi: intro/outro
# tipik olarak jenerik + bitis karti kadardir, video govdesi degil).
MAX_INTRO_SECONDS = 90.0
MAX_OUTRO_SECONDS = 120.0
MAX_INTRO_FRACTION = 0.10
MAX_OUTRO_FRACTION = 0.10
# Budamadan sonra kalan icerik: en az bu kadar olmali.
MIN_KEEP_FRACTION = 0.70
MIN_KEEP_SECONDS = 60.0
# Kenar taramasinda blackdetect penceresi.
EDGE_WINDOW_SECONDS = 150.0
# Konusmasiz blogun "jenerik" sayilmasi icin gereken en kisa sure.
MIN_SPEECH_GAP_SECONDS = 2.0
# Konusma sinirindaki sahne kesmesi eslesme toleransi.
SCENE_MATCH_TOLERANCE = 3.0

_BLACK_RE = re.compile(
    r"black_start:\s*(?P<start>\d+(?:\.\d+)?)\s+black_end:\s*(?P<end>\d+(?:\.\d+)?)"
)


def parse_black_log(log_text: str) -> list[tuple[float, float]]:
    """blackdetect satirlarini (start, end) ciftlerine cevir."""
    pairs: list[tuple[float, float]] = []
    for match in _BLACK_RE.finditer(log_text):
        start = float(match.group("start"))
        end = float(match.group("end"))
        if end > start:
            pairs.append((start, end))
    return pairs


async def detect_black_frames(
    ffmpeg_bin: str,
    path: str | Path,
    *,
    window_start: float = 0.0,
    window_seconds: float = EDGE_WINDOW_SECONDS,
    min_seconds: float = 0.3,
    pixel_threshold: float = 0.10,
    timeout: float = 180.0,
) -> list[tuple[float, float]]:
    """Kenar penceresinde siyah kare bloklari (mutlak saniye).

    Yalniz video cozumlenir (-an); tam dosya yerine kenar penceresi
    tarandigi icin Pi'de saniyeler surer.
    """
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-ss",
        f"{max(0.0, window_start):.3f}",
        "-t",
        f"{max(0.1, window_seconds):.3f}",
        "-i",
        str(path),
        "-an",
        "-vf",
        f"blackdetect=d={min_seconds}:pix_th={pixel_threshold}",
        "-f",
        "null",
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
        return []
    # blackdetect zamanlari pencereye gore gorecelidir; mutlak ana cevir.
    return [
        (start + window_start, end + window_start)
        for start, end in parse_black_log(stderr.decode("utf-8", "replace"))
    ]


@dataclass
class AutoTrim:
    """Tespit sonucu: budanacak saniyeler + kanit izi."""

    intro_seconds: float = 0.0
    outro_seconds: float = 0.0
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "intro_seconds": round(self.intro_seconds, 2),
            "outro_seconds": round(self.outro_seconds, 2),
            "evidence": self.evidence,
        }


def _leading_run(
    spans: list[tuple[float, float]], *, duration: float
) -> float | None:
    """0'dan baslayan (ya da 0.5 sn icinde baslayan) blogun bitisi."""
    best: float | None = None
    for start, end in spans:
        if start <= 0.5 and end < duration - 0.5:
            if best is None or end > best:
                best = end
    return best


def _trailing_run(
    spans: list[tuple[float, float]], *, duration: float
) -> float | None:
    """Videonun sonuna degen (ya da 0.5 sn kala biten) blogun basi."""
    best: float | None = None
    for start, end in spans:
        if end >= duration - 0.5 and start > 0.5:
            if best is None or start < best:
                best = start
    return best


def _scene_near(scenes: list[float], moment: float) -> float | None:
    """Verilen ana en yakin sahne kesmesi (tolerans icindeyse)."""
    if not scenes:
        return None
    nearest = min(scenes, key=lambda value: abs(value - moment))
    if abs(nearest - moment) <= SCENE_MATCH_TOLERANCE:
        return nearest
    return None


def _covered_by_spans(
    spans: list[tuple[float, float]], start: float, end: float
) -> float:
    """[start, end] araliginin ne kadari verilen bloklarla kapli."""
    covered = 0.0
    for span_start, span_end in spans:
        overlap = min(end, span_end) - max(start, span_start)
        if overlap > 0:
            covered += overlap
    return min(covered, max(0.0, end - start))


def detect_auto_trim(
    *,
    duration: float,
    silences: list[tuple[float, float]] | None = None,
    black_frames: list[tuple[float, float]] | None = None,
    scenes: list[float] | None = None,
    first_speech: float | None = None,
    last_speech: float | None = None,
) -> AutoTrim:
    """Kenar sinyallerinden intro/outro budamasini hesapla (saf fonksiyon).

    Her sinyal aday uretir; intro'da en buyuk, outro'da en kucuk aday
    kazanir. Sonuc emniyet sinirlarina kirpilir ve kanit sozlugune her
    adayin degeri yazilir (canli teshis icin).
    """
    silences = list(silences or [])
    black_frames = list(black_frames or [])
    scenes = list(scenes or [])
    if duration <= 0:
        return AutoTrim(evidence={"reason": "sure bilinmiyor"})

    cap_intro = min(MAX_INTRO_SECONDS, duration * MAX_INTRO_FRACTION)
    cap_outro = min(MAX_OUTRO_SECONDS, duration * MAX_OUTRO_FRACTION)
    evidence: dict = {"cap_intro": round(cap_intro, 2), "cap_outro": round(cap_outro, 2)}

    # --- intro adaylari ---
    intro_candidates: dict[str, float] = {}
    leading_silence = _leading_run(silences, duration=duration)
    if leading_silence is not None:
        intro_candidates["leading_silence"] = leading_silence
    leading_black = _leading_run(black_frames, duration=duration)
    if leading_black is not None:
        intro_candidates["leading_black"] = leading_black
    if first_speech is not None and first_speech >= MIN_SPEECH_GAP_SECONDS:
        cut = _scene_near(scenes, first_speech)
        covered = _covered_by_spans(silences, 0.0, first_speech)
        if cut is not None:
            intro_candidates["speech_start_scene_cut"] = cut
        elif covered >= (first_speech - 0.5) * 0.7:
            # Sessizlik agirlikli: sessizligin BITISI daha muhafazakar
            # sinirdir (konusmanin ilk hecesini kesme riski yok).
            intro_candidates["speech_start_silence"] = (
                leading_silence if leading_silence is not None else first_speech
            )
        elif leading_black is not None or leading_silence is not None:
            # Kenar sinyali varsa konusma basi guvenilir bir sinirdir.
            intro_candidates["speech_start_edge"] = first_speech
    intro = min(max(intro_candidates.values(), default=0.0), cap_intro)

    # --- outro adaylari ---
    outro_candidates: dict[str, float] = {}
    trailing_silence = _trailing_run(silences, duration=duration)
    if trailing_silence is not None:
        outro_candidates["trailing_silence"] = duration - trailing_silence
    trailing_black = _trailing_run(black_frames, duration=duration)
    if trailing_black is not None:
        outro_candidates["trailing_black"] = duration - trailing_black
    if last_speech is not None:
        gap = duration - last_speech
        if gap >= MIN_SPEECH_GAP_SECONDS:
            cut = _scene_near(scenes, last_speech)
            covered = _covered_by_spans(silences, last_speech, duration)
            if cut is not None:
                outro_candidates["speech_end_scene_cut"] = duration - cut
            elif covered >= (gap - 0.5) * 0.7:
                outro_candidates["speech_end_silence"] = gap
            elif trailing_black is not None or trailing_silence is not None:
                outro_candidates["speech_end_edge"] = gap
    outro = min(max(outro_candidates.values(), default=0.0), cap_outro)

    # --- emniyet: kalan icerik yeterli mi? ---
    # 60 sn alt siniri yalnizca uzun videolarda anlamlidir; kisa bir
    # videoda (ornegin 20 sn'lik test dosyasi) tum budamayi sifirlardi.
    keep_needed = max(
        min(MIN_KEEP_SECONDS, duration * 0.5), duration * MIN_KEEP_FRACTION
    )
    total = intro + outro
    if total > 0 and duration - total < keep_needed:
        allowed = max(0.0, duration - keep_needed)
        if total > 0 and allowed < total:
            scale = allowed / total
            evidence["clamped"] = True
            intro = round(intro * scale, 2)
            outro = round(outro * scale, 2)
    evidence["intro_candidates"] = {
        key: round(value, 2) for key, value in intro_candidates.items()
    }
    evidence["outro_candidates"] = {
        key: round(value, 2) for key, value in outro_candidates.items()
    }
    evidence["first_speech"] = None if first_speech is None else round(first_speech, 2)
    evidence["last_speech"] = None if last_speech is None else round(last_speech, 2)
    return AutoTrim(
        intro_seconds=round(intro, 2),
        outro_seconds=round(outro, 2),
        evidence=evidence,
    )


def _speech_bounds(segments: list[dict]) -> tuple[float | None, float | None]:
    """Transkript segmentlerinden ilk baslangic ve son bitis."""
    starts: list[float] = []
    ends: list[float] = []
    for segment in segments or []:
        try:
            start = float(segment.get("start"))
        except (TypeError, ValueError):
            start = None
        try:
            end = float(segment.get("end"))
        except (TypeError, ValueError):
            end = None
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)
    return (min(starts) if starts else None, max(ends) if ends else None)


async def compute_auto_trim_for_asset(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    asset_id: int,
) -> dict:
    """Asset icin otomatik budamayi hesapla ve analysis'e yaz.

    Depodaki sessizlik/sahne verisi + transkript kullanilir; yalniz
    kenar pencerelerinde blackdetect kosar. Hata durumunda asset
    analysis'i degismez ve bos sozluk doner (akisi durdurmaz).
    """
    from app.models import (
        CorrectedTranscript,
        MediaAsset,
        MediaInspection,
        Transcript,
    )

    async with sessionmaker() as session:
        asset = await session.get(MediaAsset, asset_id)
        if asset is None or not asset.file_path:
            return {}
        inspection = (
            (
                await session.execute(
                    sa.select(MediaInspection).where(
                        MediaInspection.media_asset_id == asset_id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if inspection is None:
            return {}
        analysis = dict(asset.analysis or {})
        silences = [
            (float(pair[0]), float(pair[1]))
            for pair in analysis.get("silences") or []
            if isinstance(pair, (list, tuple)) and len(pair) >= 2
        ]
        scenes = [float(value) for value in analysis.get("scene_changes") or []]
        corrected = (
            (
                await session.execute(
                    sa.select(CorrectedTranscript).where(
                        CorrectedTranscript.media_asset_id == asset_id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        segments: list[dict] = []
        if corrected is not None:
            segments = corrected.segments or []
        else:
            original = (
                (
                    await session.execute(
                        sa.select(Transcript).where(
                            Transcript.media_asset_id == asset_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if original is not None:
                segments = original.segments or []
        file_path = asset.file_path
        duration = float(inspection.duration_seconds or 0.0)

    first_speech, last_speech = _speech_bounds(segments)

    black_frames = list(analysis.get("black_frames") or [])
    if not black_frames:
        head = await detect_black_frames(
            settings.ffmpeg_bin,
            file_path,
            window_start=0.0,
            window_seconds=min(EDGE_WINDOW_SECONDS, max(1.0, duration)),
        )
        tail_start = max(0.0, duration - EDGE_WINDOW_SECONDS)
        tail = await detect_black_frames(
            settings.ffmpeg_bin,
            file_path,
            window_start=tail_start,
            window_seconds=min(EDGE_WINDOW_SECONDS, max(1.0, duration - tail_start)),
        )
        black_frames = [
            (float(pair[0]), float(pair[1])) for pair in (head + tail)
        ]

    trim = detect_auto_trim(
        duration=duration,
        silences=silences,
        black_frames=black_frames,
        scenes=scenes,
        first_speech=first_speech,
        last_speech=last_speech,
    )
    result = trim.as_dict()

    async with sessionmaker() as session:
        asset = await session.get(MediaAsset, asset_id)
        if asset is None:
            return {}
        updated = dict(asset.analysis or {})
        updated["black_frames"] = [list(pair) for pair in black_frames]
        updated["auto_trim"] = result
        asset.analysis = updated
        await session.commit()
    return result
