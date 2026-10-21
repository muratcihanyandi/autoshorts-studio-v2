"""Clip-candidate generation and content similarity (M7).

Pure scoring over the M7 analysis results: windows inside the usable
range (between intro and outro) are ranked by audio energy, scene
density, and transcript coverage, minus a penalty for overlapping
silence. The best non-overlapping windows become candidates.

Near-duplicate detection compares candidate transcript text against
the channel's existing candidates with word 3-gram Jaccard similarity,
so the same moment cut from different angles or re-uploads do not
reach the publish queue twice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class CandidateSpec:
    start_seconds: float
    end_seconds: float
    score: float
    detail: dict = field(default_factory=dict)
    reason: str | None = None

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 3)


def _normalize(values: list[float]) -> list[float]:
    peak = max(values) if values else 0.0
    if peak <= 0:
        return [0.0] * len(values)
    return [v / peak for v in values]


def _silence_overlap(
    start: float, end: float, silences: list[tuple[float, float]]
) -> float:
    """Fraction of [start, end] covered by silence runs."""
    if end <= start:
        return 0.0
    covered = 0.0
    for silence_start, silence_end in silences:
        overlap = min(end, silence_end) - max(start, silence_start)
        if overlap > 0:
            covered += overlap
    return covered / (end - start)


def _score_window(
    start: float,
    end: float,
    energy: list[float],
    scene_times: list[float],
    segments: list[dict],
    silences: list[tuple[float, float]],
) -> tuple[float, dict]:
    window = end - start
    window_energy = energy[int(start) : int(end)]
    mean_energy = sum(window_energy) / len(window_energy) if window_energy else 0.0
    scenes = sum(1 for t in scene_times if start <= t < end)
    scene_density = scenes / window if window > 0 else 0.0
    transcript_chars = sum(
        len(seg.get("text", ""))
        for seg in segments
        if seg.get("end", 0) > start and seg.get("start", 0) < end
    )
    coverage = min(1.0, transcript_chars / (window * 15)) if window > 0 else 0.0
    silence_fraction = _silence_overlap(start, end, silences)

    # Normalize etmeden ham degerlerle agirliklandir: enerji 0..32768,
    # sahne yogunlugu ve kapsam 0..1 oldugundan once 0..1'e cekilir.
    energy_score = min(1.0, mean_energy / 32768.0 * 4.0)
    score = (
        0.4 * energy_score
        + 0.3 * min(1.0, scene_density / 0.1)
        + 0.3 * coverage
        - 0.5 * silence_fraction
    )
    detail = {
        "mean_energy": round(mean_energy, 2),
        "scene_count": scenes,
        "transcript_chars": transcript_chars,
        "silence_fraction": round(silence_fraction, 3),
    }
    return round(max(0.0, score), 4), detail


def generate_candidates(
    duration: float,
    *,
    intro_end: float = 0.0,
    outro_start: float | None = None,
    silences: list[tuple[float, float]] | None = None,
    scene_changes: list[float] | None = None,
    energy_windows: list[float] | None = None,
    segments: list[dict] | None = None,
    clip_min_seconds: int = 20,
    clip_max_seconds: int = 90,
    max_candidates: int = 5,
    step_seconds: float = 5.0,
) -> list[CandidateSpec]:
    """Rank windows in the usable range; return non-overlapping top-K."""
    silences = silences or []
    scene_changes = scene_changes or []
    energy_windows = energy_windows or []
    segments = segments or []
    if outro_start is None:
        outro_start = duration
    usable_start = max(0.0, intro_end)
    usable_end = min(duration, outro_start)
    if usable_end - usable_start < clip_min_seconds:
        return []

    lengths = sorted(
        {
            clip_min_seconds,
            (clip_min_seconds + clip_max_seconds) // 2,
            clip_max_seconds,
        }
    )
    windows_by_length: dict[int, list[tuple[float, float, float, dict]]] = {}
    for length in lengths:
        if length > usable_end - usable_start:
            continue
        bucket = windows_by_length[length] = []
        start = usable_start
        while start + length <= usable_end:
            score, detail = _score_window(
                start,
                start + length,
                energy_windows,
                scene_changes,
                segments,
                silences,
            )
            bucket.append((start, start + length, score, detail))
            start += step_seconds

    # Uzunluk cesitliligi (kullanici istegi 2026-10-21): yogunluk
    # metrikleri kisa pencerelere dogal avantaj verdiginden tohum adaylar
    # hep en kisa uzunlukta cikiyordu ve klipler sabit 20 saniyeye
    # kilitleniyordu. Uzunluklar round-robin sirayla birer tohum verir;
    # nihai sureyi hype (LLM) anin dogasina gore belirler.
    ranked_by_length = {
        length: sorted(bucket, key=lambda w: (-w[2], w[0]))
        for length, bucket in windows_by_length.items()
    }

    def _overlaps(window: tuple[float, float, float, dict]) -> bool:
        return any(window[0] < c[1] and window[1] > c[0] for c in chosen)

    chosen: list[tuple[float, float, float, dict]] = []
    progressed = True
    while len(chosen) < max_candidates and progressed:
        progressed = False
        for length in sorted(ranked_by_length, reverse=True):
            if len(chosen) >= max_candidates:
                break
            bucket = ranked_by_length[length]
            while bucket:
                window = bucket.pop(0)
                if not _overlaps(window):
                    chosen.append(window)
                    progressed = True
                    break

    return [
        CandidateSpec(
            start_seconds=round(start, 3),
            end_seconds=round(end, 3),
            score=score,
            detail=detail,
            reason="puanlandi",
        )
        for start, end, score, detail in chosen
    ]


def _word_ngrams(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    if len(words) < n:
        # kisa metinler icin kelime kumesi (bigram yoksa unigram)
        return {(word,) for word in words}
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def ngram_jaccard(a: str, b: str, n: int = 3) -> float:
    """Word n-gram Jaccard similarity in [0, 1]."""
    grams_a = _word_ngrams(a, n)
    grams_b = _word_ngrams(b, n)
    if not grams_a or not grams_b:
        return 0.0
    return len(grams_a & grams_b) / len(grams_a | grams_b)


def find_near_duplicate(
    text: str,
    existing_texts: list[tuple[int, str]],
    *,
    threshold: float = 0.8,
) -> int | None:
    """Return the id of the first existing candidate near-duplicate to
    text, or None. `existing_texts` is a list of (candidate_id, text)."""
    for candidate_id, existing in existing_texts:
        if ngram_jaccard(text, existing) >= threshold:
            return candidate_id
    return None
