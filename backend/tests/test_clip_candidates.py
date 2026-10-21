"""clip_candidates: window scoring, non-overlap, similarity checks."""
from __future__ import annotations

from app.services.clip_candidates import (
    CandidateSpec,
    find_near_duplicate,
    generate_candidates,
    ngram_jaccard,
)

# 12s sentetik ornek uzerinden gercekci analiz verisi:
# sessizlik 0-2 ve 10-12, sahne kesimleri 4/8, enerji sesli bolgede yuksek.
ENERGY = [0.0, 0.0] + [13000.0] * 8 + [0.0, 0.0]
SILENCES = [(0.0, 2.0), (10.0, 12.0)]
SCENES = [4.0, 8.0]
SEGMENTS = [
    {"start": 2.0, "end": 10.0, "text": "konusan bir video icerigi burada"}
]


class TestGenerateCandidates:
    def test_short_media_yields_nothing(self):
        # 12s medya, 20s minimum klip -> kullanilabilir aralik yetmez
        assert (
            generate_candidates(
                12.0,
                intro_end=2.0,
                outro_start=10.0,
                silences=SILENCES,
                scene_changes=SCENES,
                energy_windows=ENERGY,
                segments=SEGMENTS,
            )
            == []
        )

    def test_long_media_produces_valid_nonoverlapping_candidates(self):
        duration = 120.0
        energy = [13000.0] * 120
        scenes = [float(t) for t in range(20, 120, 15)]
        candidates = generate_candidates(
            duration,
            intro_end=0.0,
            outro_start=None,
            silences=[],
            scene_changes=scenes,
            energy_windows=energy,
            segments=[],
            clip_min_seconds=20,
            clip_max_seconds=45,
            max_candidates=4,
        )
        assert 1 <= len(candidates) <= 4
        for candidate in candidates:
            # ROADMAP kabul kriteri: zaman damgalari gecerli
            assert 0 <= candidate.start_seconds < candidate.end_seconds <= duration
            assert 20 <= candidate.duration_seconds <= 45
            assert candidate.score >= 0.0
        # cakisma yok
        ordered = sorted(candidates, key=lambda c: c.start_seconds)
        for first, second in zip(ordered, ordered[1:]):
            assert first.end_seconds <= second.start_seconds

    def test_intro_outro_bounds_respected(self):
        duration = 120.0
        energy = [13000.0] * 120
        candidates = generate_candidates(
            duration,
            intro_end=10.0,
            outro_start=110.0,
            silences=[(0.0, 10.0), (110.0, 120.0)],
            scene_changes=[],
            energy_windows=energy,
            segments=[],
        )
        assert candidates
        for candidate in candidates:
            assert candidate.start_seconds >= 10.0
            assert candidate.end_seconds <= 110.0

    def test_silent_windows_score_lower(self):
        duration = 120.0
        loud = generate_candidates(
            duration,
            energy_windows=[13000.0] * 120,
            scene_changes=[],
            segments=[],
        )
        quiet = generate_candidates(
            duration,
            energy_windows=[10.0] * 120,
            scene_changes=[],
            segments=[],
        )
        assert loud[0].score > quiet[0].score

    def test_ranking_prefers_higher_scores(self):
        duration = 120.0
        # ilk yari sessiz, ikinci yari sesli
        energy = [0.0] * 60 + [13000.0] * 60
        candidates = generate_candidates(
            duration,
            energy_windows=energy,
            scene_changes=[],
            segments=[],
            clip_min_seconds=20,
            clip_max_seconds=20,
            max_candidates=3,
        )
        assert candidates
        best = candidates[0]
        assert best.start_seconds >= 55.0  # en iyi pencere sesli yarida
        scores = [c.score for c in candidates]
        assert scores == sorted(scores, reverse=True)


class TestSimilarity:
    def test_jaccard_identical_and_unrelated(self):
        text = "bugun size cok onemli bir konudan bahsedecegim ve bu konu cok ilginc"
        assert ngram_jaccard(text, text) == 1.0
        assert ngram_jaccard(text, "hava durumu yaradan icin yagisli gecicek") < 0.2

    def test_near_duplicate_word_variations(self):
        original = (
            "bugun kanalda cok onemli bir duyuru yapacagiz hepimiz icin buyuk bir gelisme var"
        )
        slightly_reworded = (
            "bugun kanalda cok onemli bir duyuru yapiyoruz hepimiz icin buyuk bir gelisme goruyoruz"
        )
        assert ngram_jaccard(original, slightly_reworded) >= 0.4
        assert find_near_duplicate(
            slightly_reworded, [(11, original)], threshold=0.4
        ) == 11

    def test_find_near_duplicate_returns_none_when_distinct(self):
        text = "tarlaya ekilen bugday suresi geldiysen hasat zamani gelir"
        others = [
            (1, "sanayi devrimi avrupa tarihini tamamen degistirdi"),
            (2, "cay demlemenin puf noktalari nelerdir anlatiyorum"),
        ]
        assert find_near_duplicate(text, others, threshold=0.2) is None

    def test_empty_texts_never_match(self):
        assert ngram_jaccard("", "bir seyler") == 0.0
        assert find_near_duplicate("", [(5, "dolu metin")]) is None


class TestCandidateSpec:
    def test_duration_property(self):
        spec = CandidateSpec(start_seconds=5.0, end_seconds=25.0, score=0.5)
        assert spec.duration_seconds == 20.0


class TestLengthDiversity:
    def test_seed_candidates_include_every_window_length(self):
        """Uzunluk çeşitliliği (kullanıcı isteği 2026-10-21): yoğunluk
        metrikleri kısa pencereyi ödüllendirip tohumları sabit 20 sn'ye
        kilitliyordu. Aday listesi her uzunluktan (20/100/180) gelmek
        zorundadır; nihai süreyi hype (LLM) anın doğasına göre belirler."""

        def run(max_candidates: int = 5):
            return generate_candidates(
                600.0,
                silences=[],
                scene_changes=[],
                energy_windows=[20000.0] * 600,
                segments=[],
                clip_min_seconds=20,
                clip_max_seconds=180,
                max_candidates=max_candidates,
            )

        durations = {c.duration_seconds for c in run()}
        assert 180.0 in durations  # en uzun tohum mutlaka seçilir
        assert 100.0 in durations
        assert 20.0 in durations
        # Kısıtlı kota: yine en uzun pencere önce gelir.
        only_two = [c.duration_seconds for c in run(max_candidates=2)]
        assert 180.0 in only_two
