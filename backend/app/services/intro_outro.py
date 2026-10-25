"""Otomatik intro/outro tespiti (2026-10-24 kullanici istegi).

Yatay tam kesit, kaynak videonun ACIKCA intro ve outro'su cikarilarak
paylasilir; bunu kullanici elle ayarlamaz. Tespit bagimsiz sinyallerin
birlesimidir ve hicbiri tek basina govdeyi kesmez:

- **Kanal ici tekrar eden bumper** (en guclu sinyal): ayni kanalin
  videolari genelde AYNI intro/outro jenerigini tasir. Videolarin
  basindan/sonundan alinan kaba ses parmak izleri karsilastirilir;
  birebir ortak olan onek/sonek kadar saniye budanir. Canli olcum
  (2026-10-24): kanal videolarinin ilk 3.5 sn'si RMS olarak ayni cikti —
  ortak intro bumper'i.
- **Konusma bosluklari** (whisper transkripti): videonun basinda/sonunda
  konusma yoksa orasi jenerik/bitis kartidir.
- **Sessizlik** (ffmpeg silencedetect): kenara yakin sessizlik blogu
  intro/outro'nun ses tarafidir.
- **Siyah kare** (ffmpeg blackdetect): gecis/bitis kartlarinda tipiktir.
- **Sahne kesmesi** (showinfo): konusmasiz blogun sinirinda sert bir
  kesme varsa jenerik -> icerik gecisi tam oradan alinir.

Emniyet kurallari: her taraf sure'nin en fazla %10'u (intro 90 sn,
outro 120 sn) kadar budanir, videonun en az %70'i kalir. Sinyal yoksa
budama 0'dir — yanlis kesmek, kesmemekten kotudur.

Saf fonksiyon :func:`detect_auto_trim` ffmpeg calistirmadan test
edilebilir; :func:`compute_auto_trim_for_asset` depodan veriyi okur,
kenar pencerelerinde blackdetect + ses parmak izi kosar ve sonucu
asset.analysis'e yazar.
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
# Gevsek kural: kenarda bu kadar uzun konusma boslugu varsa ve boslugun
# en az bu kadari sessizse orasi jenerik/bitis kartidir. Canli olcum
# (2026-10-24): bu kanalda outro MUZIKLI, son saniyelerde konusma yok ama
# sessizlik blogu dosya sonuna degmiyor — siki kural kaciriyordu.
RELAXED_GAP_SECONDS = 5.0
RELAXED_COVERAGE = 0.30
# Gevsek kuralin gorsel guvencesi: jenerik/bitis karti STATIKTIR. Canli
# olcum (2026-10-24): video 950'nin son 30 sn'sinde 0 sahne kesmesi vardi,
# govdesinde 30 sn'de 6 kesme. Bu kapidan gecmeyen (hareketli) kuyruk
# icerik sayilir ve kesilmez.
RELAXED_MAX_TAIL_SCENES = 1
# Konusma sinirindaki sahne kesmesi eslesme toleransi.
SCENE_MATCH_TOLERANCE = 3.0
# Kanal ici bumper karsilastirmasi: kenar penceresi, RMS penceresi ve
# eslesme toleranslari. Ayni jenerik ayni sesten geldigi icin RMS
# degerleri neredeyse birebir esit cikar (canli olcum: 2194.5 vs 2194.5).
FINGERPRINT_EDGE_SECONDS = 40.0
FINGERPRINT_WINDOW_SECONDS = 0.25
FINGERPRINT_REL_TOLERANCE = 0.25
FINGERPRINT_ABS_TOLERANCE = 120.0
MIN_BUMPER_SECONDS = 1.5
# Ortak bolgenin "jenerik" sayilmasi icin gereken en kucuk ortalama ses
# seviyesi: iki video birlikte sessiz basliyorsa bu bir bumper DEGILDIR
# (sessizlik sinyali onu zaten kapsar).
MIN_BUMPER_RMS = 250.0
# Bumper dogrulamasi icin en az bu kadar BASKA video ile eslesme gerekir.
MIN_BUMPER_WITNESSES = 2
# Tek bir tanikla kabul icin gereken cok siki eslesme.
STRICT_BUMPER_REL_TOLERANCE = 0.08
# Enerji pencerelerinden "sessiz kenar" esigi (0..32768 RMS). Sona kadar
# suren sessizlikte silencedetect silence_end uretmez (dosya biter), bu
# yuzden kenar sessizligi enerji pencerelerinden de okunur.
MIN_QUIET_RMS = 200.0

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


# --- kanal ici bumper (tekrar eden jenerik) tespiti ---

_SAMPLE_RATE = 8000
_SAMPLE_BYTES = 2  # s16le mono


def rms_vector(pcm: bytes, *, window_seconds: float = FINGERPRINT_WINDOW_SECONDS) -> list[float]:
    """s16le mono PCM'i pencerelere bolup RMS vektorune cevir (saf)."""
    step = max(1, int(_SAMPLE_RATE * window_seconds)) * _SAMPLE_BYTES
    values: list[float] = []
    for offset in range(0, len(pcm) - step + 1, step):
        chunk = pcm[offset : offset + step]
        total = 0
        count = len(chunk) // _SAMPLE_BYTES
        if not count:
            continue
        for index in range(0, count * _SAMPLE_BYTES, _SAMPLE_BYTES):
            sample = int.from_bytes(
                chunk[index : index + _SAMPLE_BYTES], "little", signed=True
            )
            total += sample * sample
        values.append((total / count) ** 0.5)
    return values


async def _decode_edge_pcm(
    ffmpeg_bin: str,
    path: str | Path,
    *,
    head: bool,
    edge_seconds: float = FINGERPRINT_EDGE_SECONDS,
    timeout: float = 120.0,
) -> bytes:
    """Kenar penceresinin sesini ham PCM olarak coz (video cozulmez)."""
    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error"]
    if head:
        cmd += ["-t", f"{edge_seconds:.3f}"]
    else:
        cmd += ["-sseof", f"-{edge_seconds:.3f}"]
    cmd += [
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(_SAMPLE_RATE),
        "-f",
        "s16le",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return b""
    return stdout or b""


async def edge_fingerprint(
    ffmpeg_bin: str,
    path: str | Path,
    *,
    edge_seconds: float = FINGERPRINT_EDGE_SECONDS,
    duration: float | None = None,
) -> dict:
    """Videonun bas/son ses parmak izi (RMS vektoru).

    Kanal ici tekrar eden intro/outro jenerigini bulmak icin kullanilir:
    ayni jenerik ayni ses oldugu icin RMS degerleri neredeyse birebir
    esit cikar (canli olcum: 2194.5 vs 2194.5).

    Pencere videonun en fazla ceyregi olur: kisa videoda bas ve son
    pencereler ayni sese denk gelip kendisiyle eslesirdi.
    """
    window = edge_seconds
    if duration and duration > 0:
        window = min(window, duration / 4.0)
    window = max(2.0, window)
    head_pcm = await _decode_edge_pcm(
        ffmpeg_bin, path, head=True, edge_seconds=window
    )
    tail_pcm = await _decode_edge_pcm(
        ffmpeg_bin, path, head=False, edge_seconds=window
    )
    return {
        "window": FINGERPRINT_WINDOW_SECONDS,
        "edge_seconds": round(window, 2),
        "head": [round(v, 1) for v in rms_vector(head_pcm)],
        "tail": [round(v, 1) for v in rms_vector(tail_pcm)],
    }


def _values_match(left: float, right: float, *, rel_tolerance: float) -> bool:
    return abs(left - right) <= max(
        FINGERPRINT_ABS_TOLERANCE, rel_tolerance * max(left, right)
    )


def _match_run(
    left: list[float],
    right: list[float],
    *,
    window_seconds: float,
    rel_tolerance: float,
) -> float:
    """Bastan itibaren eslesen pencerelerin suresi.

    Iki taraf da SESSIZ olan pencereler zinciri kesmez (jenerigin
    basindaki kisa sessizlik normaldir) ama tek basina bumper sayilmaz:
    en az MIN_BUMPER_SECONDS kadar SESLI eslesme sart. Boylece "iki video
    birlikte sessiz basliyor" durumu bumper olarak algilanmaz.
    """
    matched = 0
    loud_matched = 0
    for first, second in zip(left, right):
        if not _values_match(first, second, rel_tolerance=rel_tolerance):
            break
        matched += 1
        if max(first, second) > MIN_BUMPER_RMS:
            loud_matched += 1
    if loud_matched * window_seconds < MIN_BUMPER_SECONDS:
        return 0.0
    return matched * window_seconds


def shared_prefix_seconds(
    left: list[float],
    right: list[float],
    *,
    window_seconds: float = FINGERPRINT_WINDOW_SECONDS,
    rel_tolerance: float = FINGERPRINT_REL_TOLERANCE,
) -> float:
    """Iki videonun basindan itibaren birebir ayni olan ses suresi."""
    return _match_run(
        left,
        right,
        window_seconds=window_seconds,
        rel_tolerance=rel_tolerance,
    )


def shared_suffix_seconds(
    left: list[float],
    right: list[float],
    *,
    window_seconds: float = FINGERPRINT_WINDOW_SECONDS,
    rel_tolerance: float = FINGERPRINT_REL_TOLERANCE,
) -> float:
    """Iki videonun sonundan geriye birebir ayni olan ses suresi."""
    return _match_run(
        list(reversed(left)),
        list(reversed(right)),
        window_seconds=window_seconds,
        rel_tolerance=rel_tolerance,
    )


def consensus_bumper(
    comparisons: list[tuple[float, float]],
) -> tuple[float, float]:
    """Tanik ciftlerinden (intro, outro) ortak bumper sureleri.

    `comparisons` her tanik video icin (shared_prefix, shared_suffix)
    ciftleridir. Bir taraf ancak yeterli tanik ayni fikirde ise kabul
    edilir: en az MIN_BUMPER_WITNESSES tanik ya da tek tanikta cok siki
    eslesme. Donen deger medyandir (aykiri tanik sureyi bozmasin).
    """
    def _side(values: list[float]) -> float:
        positive = [value for value in values if value > 0]
        if not positive:
            return 0.0
        if len(positive) >= MIN_BUMPER_WITNESSES:
            positive.sort()
            # Alt medyan: muhafazakar taraf (daha az kesmek).
            return positive[(len(positive) - 1) // 2]
        return 0.0

    intros = [pair[0] for pair in comparisons]
    outros = [pair[1] for pair in comparisons]
    return _side(intros), _side(outros)


def bumper_from_witnesses(
    own: dict,
    witnesses: list[dict],
) -> tuple[float, float, list[tuple[float, float]]]:
    """Kendi parmak izini tanik parmak izleriyle karsilastir.

    Hem normal toleransla hem cok siki toleransla karsilastirilir; siki
    eslesme tek tanikla kabul edilir (ayni jenerik neredeyse birebir
    ayni ses oldugu icin bu guvenli). (intro, outro, kanit) doner.
    """
    window = float(own.get("window") or FINGERPRINT_WINDOW_SECONDS)
    own_head = [float(v) for v in own.get("head") or []]
    own_tail = [float(v) for v in own.get("tail") or []]
    normal: list[tuple[float, float]] = []
    strict: list[tuple[float, float]] = []
    for witness in witnesses:
        w_head = [float(v) for v in witness.get("head") or []]
        w_tail = [float(v) for v in witness.get("tail") or []]
        if not w_head or not w_tail:
            continue
        normal.append(
            (
                shared_prefix_seconds(own_head, w_head, window_seconds=window),
                shared_suffix_seconds(own_tail, w_tail, window_seconds=window),
            )
        )
        strict.append(
            (
                shared_prefix_seconds(
                    own_head,
                    w_head,
                    window_seconds=window,
                    rel_tolerance=STRICT_BUMPER_REL_TOLERANCE,
                ),
                shared_suffix_seconds(
                    own_tail,
                    w_tail,
                    window_seconds=window,
                    rel_tolerance=STRICT_BUMPER_REL_TOLERANCE,
                ),
            )
        )
    intro, outro = consensus_bumper(normal)
    if intro <= 0.0 or outro <= 0.0:
        strict_intro, strict_outro = consensus_bumper(strict)
        intro = max(intro, strict_intro)
        outro = max(outro, strict_outro)
    return intro, outro, normal + strict


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


def _quiet_edge_seconds(
    energy: list[float], *, head: bool, threshold: float = MIN_QUIET_RMS
) -> float:
    """Enerji pencerelerinden sessiz kenar suresi (saniye).

    Sona kadar suren sessizlikte silencedetect `silence_end` uretmez
    (dosya biter) — canli olcum (2026-10-24): uc videonun sonu sessizdi
    ama hicbir sessizlik blogu kaydedilmemisti. Bu yuzden kenar
    sessizligi 1 sn'lik RMS pencerelerinden de okunur.
    """
    count = 0
    values = energy if head else list(reversed(energy))
    for value in values:
        if value > threshold:
            break
        count += 1
    # 1 sn pencereler; tek pencere gurultu olabilir.
    return float(count) if count >= 2 else 0.0


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


def _scenes_in(scenes: list[float], start: float, end: float) -> int:
    """[start, end] araligindaki sahne kesmesi sayisi."""
    return sum(1 for value in scenes if start <= value <= end)


def detect_auto_trim(
    *,
    duration: float,
    silences: list[tuple[float, float]] | None = None,
    black_frames: list[tuple[float, float]] | None = None,
    scenes: list[float] | None = None,
    first_speech: float | None = None,
    last_speech: float | None = None,
    shared_intro: float = 0.0,
    shared_outro: float = 0.0,
    energy: list[float] | None = None,
) -> AutoTrim:
    """Kenar sinyallerinden intro/outro budamasini hesapla (saf fonksiyon).

    Her sinyal aday uretir; intro'da en buyuk aday kazanir. Kanal ici
    tekrar eden bumper (shared_intro/shared_outro) diger sinyallerin
    ustundedir: ayni jenerik kanitlanmis demektir. Sonuc emniyet
    sinirlarina kirpilir ve kanit sozlugune her adayin degeri yazilir
    (canli teshis icin).
    """
    silences = list(silences or [])
    black_frames = list(black_frames or [])
    scenes = list(scenes or [])
    energy_windows = list(energy or [])
    if duration <= 0:
        return AutoTrim(evidence={"reason": "sure bilinmiyor"})

    cap_intro = min(MAX_INTRO_SECONDS, duration * MAX_INTRO_FRACTION)
    cap_outro = min(MAX_OUTRO_SECONDS, duration * MAX_OUTRO_FRACTION)
    evidence: dict = {"cap_intro": round(cap_intro, 2), "cap_outro": round(cap_outro, 2)}

    # --- intro adaylari ---
    intro_candidates: dict[str, float] = {}
    if shared_intro > 0.0:
        # Kanal ici tekrar eden bumper: diger sinyallerden ustun.
        intro_candidates["shared_bumper"] = shared_intro
    leading_silence = _leading_run(silences, duration=duration)
    if leading_silence is not None:
        intro_candidates["leading_silence"] = leading_silence
    leading_black = _leading_run(black_frames, duration=duration)
    if leading_black is not None:
        intro_candidates["leading_black"] = leading_black
    # Sona/başa kadar süren sessizlikte silencedetect kapanış üretmez;
    # enerji pencereleri bu boşluğu doldurur.
    if energy_windows:
        quiet_head = _quiet_edge_seconds(energy_windows, head=True)
        if quiet_head > 0.0:
            intro_candidates["leading_quiet"] = quiet_head
    if first_speech is not None and first_speech >= MIN_SPEECH_GAP_SECONDS:
        cut = _scene_near(scenes, first_speech)
        covered = _covered_by_spans(silences, 0.0, first_speech)
        if cut is not None:
            intro_candidates["speech_start_scene_cut"] = cut
        elif covered >= (first_speech - 0.5) * 0.7:
            # Sessizlik agirlikli: sessizligin BITISI daha muhafazakar
            # sinirdir (konusmanin ilk heceyi kesme riski yok).
            intro_candidates["speech_start_silence"] = (
                leading_silence if leading_silence is not None else first_speech
            )
        elif leading_black is not None or leading_silence is not None:
            # Kenar sinyali varsa konusma basi guvenilir bir sinirdir.
            intro_candidates["speech_start_edge"] = first_speech
        elif (
            first_speech >= RELAXED_GAP_SECONDS
            and covered >= first_speech * RELAXED_COVERAGE
            and _scenes_in(scenes, 0.0, first_speech) <= RELAXED_MAX_TAIL_SCENES
        ):
            # Muzikli/kisa jenerik: konusma yok, kenar sessizligi kismi ve
            # gorsel STATIK (jenerik/logo karti). Kesim SESSIZLIGIN
            # bitisidir; konusmanin ilk hecesine dokunulmaz.
            intro_candidates["speech_start_relaxed"] = (
                leading_silence if leading_silence is not None else first_speech
            )
    intro = min(max(intro_candidates.values(), default=0.0), cap_intro)

    # --- outro adaylari ---
    outro_candidates: dict[str, float] = {}
    if shared_outro > 0.0:
        outro_candidates["shared_bumper"] = shared_outro
    trailing_silence = _trailing_run(silences, duration=duration)
    if trailing_silence is not None:
        outro_candidates["trailing_silence"] = duration - trailing_silence
    if energy_windows:
        quiet_tail = _quiet_edge_seconds(energy_windows, head=False)
        if quiet_tail > 0.0:
            outro_candidates["trailing_quiet"] = quiet_tail
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
            elif (
                gap >= RELAXED_GAP_SECONDS
                and covered >= gap * RELAXED_COVERAGE
                and _scenes_in(scenes, last_speech, duration)
                <= RELAXED_MAX_TAIL_SCENES
            ):
                # Muzikli bitis karti: konusma yok, kenar sessizligi kismi
                # ve kuyruk gorsel olarak STATIK (jenerik).
                outro_candidates["speech_end_relaxed"] = gap
            elif _scenes_in(scenes, last_speech, duration) == 0 and gap >= 3.0:
                # Hic sahne degismeyen kuyruk: gorsel olarak tek kare
                # (bitis karti). Konusma bitiminden sonra kesilir.
                outro_candidates["speech_end_static_tail"] = gap
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
    evidence["shared_intro"] = round(shared_intro, 2)
    evidence["shared_outro"] = round(shared_outro, 2)
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
        # Kanal ici bumper taniklari: ayni kanalin diger videolarinin
        # parmak izleri (kendisi haric). En fazla 8 tanik kullanilir.
        from app.models import SourceChannel, SourceVideo

        channel_id = (
            await session.execute(
                sa.select(SourceChannel.channel_id)
                .join(SourceVideo, SourceVideo.source_channel_id == SourceChannel.id)
                .where(SourceVideo.id == asset.source_video_id)
            )
        ).scalar_one_or_none()
        witness_fingerprints: list[dict] = []
        if channel_id is not None:
            rows = (
                (
                    await session.execute(
                        sa.select(MediaAsset.analysis)
                        .join(SourceVideo, MediaAsset.source_video_id == SourceVideo.id)
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        )
                        .where(
                            SourceChannel.channel_id == channel_id,
                            MediaAsset.id != asset_id,
                            SourceVideo.id != asset.source_video_id,
                        )
                        .order_by(MediaAsset.id.desc())
                        .limit(40)
                    )
                )
                .scalars()
                .all()
            )
            for raw in rows:
                if not raw:
                    continue
                candidate = (raw or {}).get("edge_fingerprint")
                if candidate:
                    witness_fingerprints.append(candidate)
                if len(witness_fingerprints) >= 8:
                    break

    first_speech, last_speech = _speech_bounds(segments)

    fingerprint = analysis.get("edge_fingerprint")
    if not fingerprint:
        fingerprint = await edge_fingerprint(settings.ffmpeg_bin, file_path)
    shared_intro, shared_outro, bumper_evidence = bumper_from_witnesses(
        fingerprint, witness_fingerprints
    )

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
        shared_intro=shared_intro,
        shared_outro=shared_outro,
        energy=analysis.get("energy_windows") or [],
    )
    result = trim.as_dict()
    result["evidence"]["bumper_witnesses"] = len(witness_fingerprints)
    result["evidence"]["bumper_matches"] = [
        [round(a, 2), round(b, 2)] for a, b in bumper_evidence[:6]
    ]

    async with sessionmaker() as session:
        asset = await session.get(MediaAsset, asset_id)
        if asset is None:
            return {}
        updated = dict(asset.analysis or {})
        updated["black_frames"] = [list(pair) for pair in black_frames]
        updated["edge_fingerprint"] = fingerprint
        updated["auto_trim"] = result
        asset.analysis = updated
        await session.commit()
    return result
