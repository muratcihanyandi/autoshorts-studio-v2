"""character_match: reference extraction, similarity, region search.

Synthetic deterministic images: a distinctive colored pattern acts as
the "face"; the same pattern pasted into a larger frame must score
high and be located by search_region, while unrelated noise stays low.
The committed PD face fixture exercises the Haar-based extraction.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.character_match import (
    extract_reference,
    search_region,
    similarity,
)

FACE_IMAGE = Path(__file__).parent / "assets" / "face_pd.jpg"


def _pattern(size: int = 120) -> np.ndarray:
    """Distinctive reference "face": two dominant colors + rich corners.

    A two-peak color histogram (unlike uniform noise, which matches
    everything) and many stable ORB corners from the shape edges.
    """
    block = np.zeros((size, size, 3), dtype=np.uint8)
    half = size // 2
    block[:, :half] = (255, 60, 10)  # mavi yari (BGR)
    block[:, half:] = (0, 200, 230)  # turuncu yari
    cv2.circle(block, (half // 2, half // 2), size // 6, (250, 250, 250), -1)
    cv2.circle(
        block, (half + half // 2, half + half // 2), size // 8, (30, 30, 200), -1
    )
    cv2.rectangle(
        block,
        (half - size // 10, size - size // 5),
        (half + size // 10, size),
        (60, 220, 60),
        -1,
    )
    # Kose zengini doku: sabit konumlu kucuk sekiller (ORB anahtarlari)
    cell = max(4, size // 15)
    for row in range(3):
        for col in range(4):
            cx = size // 2 + (col - 2) * cell * 2 + cell
            cy = size // 4 + row * cell
            if 0 <= cx < size and 0 <= cy < size:
                cv2.rectangle(
                    block,
                    (cx, cy),
                    (min(cx + cell, size - 1), min(cy + cell, size - 1)),
                    (200, 200, 250) if (row + col) % 2 else (50, 80, 120),
                    -1,
                )
    return block


def _noise(size: int = 120, seed: int = 99) -> np.ndarray:
    """Unrelated content: flat-histogram uniform noise."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)


def _paste(
    frame_w: int, frame_h: int, block: np.ndarray, x: int, y: int
) -> np.ndarray:
    frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
    frame[:, :] = (40, 50, 60)
    h, w = block.shape[:2]
    frame[y : y + h, x : x + w] = block
    return frame


class TestExtractReference:
    def test_largest_face_with_padding(self):
        photo = cv2.imread(str(FACE_IMAGE))
        reference = extract_reference(photo)
        assert reference is not None
        photo_h, photo_w = photo.shape[:2]
        ref_h, ref_w = reference.shape[:2]
        assert 0 < ref_w <= photo_w and 0 < ref_h <= photo_h

    def test_no_face_returns_none(self):
        assert extract_reference(_noise(seed=1)) is None
        assert extract_reference(None) is None


class TestSimilarity:
    def test_same_pattern_scores_high(self):
        reference = _pattern()
        # Ayni desen, farkli boyutta kirpilmis bolge (olcek bagimsizligi)
        big = cv2.resize(reference, (240, 240), interpolation=cv2.INTER_AREA)
        region = big[30:150, 60:180]
        score = similarity(region, reference)
        assert score >= 0.5, f"ayni desen benzerligi dustu: {score}"

    def test_unrelated_noise_scores_low(self):
        reference = _pattern()
        score = similarity(_noise(seed=99), reference)
        assert score <= 0.35, f"ilgisiz gurultu benzerligi yuksek: {score}"

    def test_invalid_inputs_score_zero(self):
        reference = _pattern()
        assert similarity(None, reference) == 0.0
        assert similarity(reference, None) == 0.0
        empty = np.zeros((0, 0, 3), dtype=np.uint8)
        assert similarity(empty, reference) == 0.0

    def test_deterministic(self):
        reference = _pattern()
        assert similarity(_pattern(), reference) == similarity(
            _pattern(), reference
        )


class TestSearchRegion:
    def test_finds_pasted_pattern_location(self):
        reference = _pattern(size=100)
        scaled = cv2.resize(
            reference, (150, 150), interpolation=cv2.INTER_AREA
        )
        frame = _paste(800, 600, scaled, x=300, y=200)
        found = search_region(frame, reference)
        assert found is not None
        x, y, w, h, score = found
        assert score >= 0.5
        # Merkez bilinen yerde (pencere ~10% pay icerdigi icin toleransli)
        assert abs((x + w / 2) - (300 + 75)) <= 30
        assert abs((y + h / 2) - (200 + 75)) <= 30
        # Boyut ~150x150 + %10 pay
        assert 130 <= w <= 200
        assert 130 <= h <= 200

    def test_frame_smaller_than_min_scale_returns_none(self):
        reference = _pattern(size=400)
        small_frame = _noise(size=60, seed=5)
        assert search_region(small_frame, reference) is None

    def test_invalid_inputs_return_none(self):
        reference = _pattern()
        assert search_region(None, reference) is None
        assert search_region(_paste(200, 200, reference, 0, 0), None) is None

    @pytest.mark.parametrize("scale", [0.5, 1.0, 1.5])
    def test_finds_pattern_across_scales(self, scale):
        reference = _pattern(size=100)
        size = int(100 * scale)
        scaled = cv2.resize(
            reference, (size, size), interpolation=cv2.INTER_AREA
        )
        frame = _paste(640, 480, scaled, x=120, y=90)
        found = search_region(frame, reference)
        assert found is not None
        x, y, w, h, score = found
        assert score >= 0.5
        assert abs((x + w / 2) - (120 + size / 2)) <= 35
        assert abs((y + h / 2) - (90 + size / 2)) <= 35
