"""Character face matching against a stored reference (M13).

The reference face comes from the character's uploaded photo (largest
Haar face, padded). `similarity` blends an HSV histogram correlation
with normalized ORB feature matches, so a cropped region of the same
person scores high at a different scale/encoding while unrelated
content stays low. `search_region` proposes where the character's face
sits in a full frame via multi-scale template matching — the fallback
when webcam detection points at the wrong face.

All functions are deterministic: fixed parameters, no RNG.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.services.webcam_detect import HaarFaceDetector

# Referans yuz kirpmasinda yuzun her yanina eklenen pay (yuz boyutunun %20'si).
REFERENCE_PADDING = 0.2
# Benzerlik harmani: HSV histogram korrelasyonu ile ORB eslesme orani.
HIST_WEIGHT = 0.5
# Lowe oran testi esigi (ORB knn eslesmelerinde).
RATIO_TEST_THRESHOLD = 0.75
# Arama olcekleri: referans kirpma karede kucuk ya da buyuk olabilir.
SEARCH_SCALES = (2.0, 1.5, 1.0, 0.75, 0.5, 0.35, 0.25)
# Bulunan en iyi pencerenin her yana genisletme payi.
SEARCH_PADDING = 0.10

_HIST_BINS = (16, 16)
_HIST_RANGES = [0, 180, 0, 256]
_ORB_FEATURES = 64


def extract_reference(photo_bgr) -> np.ndarray | None:
    """Largest face crop (Haar) with 20% padding; None when no face.

    The crop stays inside the photo bounds; a copy is returned so the
    caller owns the buffer.
    """
    if photo_bgr is None or getattr(photo_bgr, "size", 0) == 0:
        return None
    faces = HaarFaceDetector().detect(photo_bgr)
    if not faces:
        return None
    x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
    img_h, img_w = photo_bgr.shape[:2]
    pad_x = int(round(w * REFERENCE_PADDING))
    pad_y = int(round(h * REFERENCE_PADDING))
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(img_w, x + w + pad_x)
    y1 = min(img_h, y + h + pad_y)
    if x1 <= x0 or y1 <= y0:
        return None
    return np.ascontiguousarray(photo_bgr[y0:y1, x0:x1])


def _hsv_correlation(a_bgr, b_bgr) -> float:
    """HSV (H,S) histogram correlation, clamped to [0, 1]."""
    a_hsv = cv2.cvtColor(a_bgr, cv2.COLOR_BGR2HSV)
    b_hsv = cv2.cvtColor(b_bgr, cv2.COLOR_BGR2HSV)
    hist_a = cv2.calcHist(
        [a_hsv], [0, 1], None, list(_HIST_BINS), _HIST_RANGES
    )
    hist_b = cv2.calcHist(
        [b_hsv], [0, 1], None, list(_HIST_BINS), _HIST_RANGES
    )
    score = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
    return float(min(1.0, max(0.0, score)))


def _orb_match_ratio(a_bgr, b_bgr) -> float:
    """Good ORB matches / smaller keypoint count, in [0, 1].

    Both images are compared in grayscale at the reference's scale; the
    ratio-test-normalized count is 0 when either side has too few
    keypoints to match meaningfully.
    """
    orb = cv2.ORB_create(nfeatures=_ORB_FEATURES)
    gray_a = cv2.cvtColor(a_bgr, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(b_bgr, cv2.COLOR_BGR2GRAY)
    kp_a, des_a = orb.detectAndCompute(gray_a, None)
    kp_b, des_b = orb.detectAndCompute(gray_b, None)
    if des_a is None or des_b is None:
        return 0.0
    if len(kp_a) < 2 or len(kp_b) < 2:
        return 0.0
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = matcher.knnMatch(des_a, des_b, k=2)
    good = 0
    for pair in matches:
        if len(pair) < 2:
            continue
        first, second = pair
        if first.distance < RATIO_TEST_THRESHOLD * second.distance:
            good += 1
    denominator = max(1, min(len(kp_a), len(kp_b)))
    return float(min(1.0, good / denominator))


def similarity(region_bgr, ref_bgr) -> float:
    """Blend of HSV histogram correlation and normalized ORB matches.

    The region is rescaled to the reference's dimensions first so both
    signals are scale-comparable. Deterministic; [0, 1].
    """
    if region_bgr is None or ref_bgr is None:
        return 0.0
    if getattr(region_bgr, "size", 0) == 0 or getattr(ref_bgr, "size", 0) == 0:
        return 0.0
    ref_h, ref_w = ref_bgr.shape[:2]
    if ref_h <= 0 or ref_w <= 0:
        return 0.0
    region = region_bgr
    if region_bgr.shape[:2] != (ref_h, ref_w):
        region = cv2.resize(
            region_bgr, (ref_w, ref_h), interpolation=cv2.INTER_AREA
        )
    hist_score = _hsv_correlation(region, ref_bgr)
    orb_score = _orb_match_ratio(region, ref_bgr)
    blended = HIST_WEIGHT * hist_score + (1.0 - HIST_WEIGHT) * orb_score
    return round(float(min(1.0, max(0.0, blended))), 4)


def search_region(
    frame_bgr, ref_bgr
) -> tuple[int, int, int, int, float] | None:
    """Multi-scale template search of the reference over the frame.

    Returns the best window (x, y, w, h, score) padded ~10% on each
    side and clamped to the frame; None when the frame is smaller than
    the template at every scale. Matching runs on grayscale with
    TM_CCOEFF_NORMED; the score is clamped to [0, 1].
    """
    if frame_bgr is None or ref_bgr is None:
        return None
    frame_h, frame_w = frame_bgr.shape[:2]
    ref_h, ref_w = ref_bgr.shape[:2]
    if frame_h <= 0 or frame_w <= 0 or ref_h <= 0 or ref_w <= 0:
        return None
    frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    best: tuple[int, int, int, int, float] | None = None
    for scale in SEARCH_SCALES:
        tw = int(round(ref_w * scale))
        th = int(round(ref_h * scale))
        if tw <= 0 or th <= 0 or tw > frame_w or th > frame_h:
            continue
        template = cv2.resize(
            ref_bgr, (tw, th), interpolation=cv2.INTER_AREA
        )
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(
            frame_gray, template_gray, cv2.TM_CCOEFF_NORMED
        )
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        score = float(min(1.0, max(0.0, max_val)))
        if best is None or score > best[4]:
            best = (max_loc[0], max_loc[1], tw, th, score)
    if best is None:
        return None

    x, y, w, h, score = best
    pad_x = int(round(w * SEARCH_PADDING))
    pad_y = int(round(h * SEARCH_PADDING))
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(frame_w, x + w + pad_x)
    y1 = min(frame_h, y + h + pad_y)
    return (x0, y0, x1 - x0, y1 - y0, round(score, 4))
