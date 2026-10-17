"""Multi-frame webcam detection for vertical rendering (M8).

Frames are sampled from the clip window with OpenCV (in-process; the
headless wheel ships its own decoders) and faces are detected per
frame. Detections are clustered across frames by IoU: a webcam is a
box that keeps re-appearing, so the best cluster — highest detection
rate, then largest area — is the webcam region, and its detection rate
(with a size-jitter penalty) is the confidence.

Low confidence is not an error: callers route it to review instead of
rendering a wrong crop. `FaceDetector` is a protocol so a stronger
detector (e.g. YuNet) can replace Haar without touching the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import cv2

DEFAULT_SAMPLES_PER_SECOND = 1.0
DEFAULT_IOU_THRESHOLD = 0.3
DEFAULT_MIN_CONFIDENCE = 0.5
_JITTER_PENALTY_CAP = 0.5


@dataclass
class Detection:
    x: int
    y: int
    w: int
    h: int
    frame_index: int


@dataclass
class Cluster:
    boxes: list[Detection] = field(default_factory=list)
    frames_seen: int = 1  # kac kare orneklendi (guven paydasi)

    def frames_with_detection(self) -> int:
        return len({d.frame_index for d in self.boxes})

    @property
    def region(self) -> tuple[int, int, int, int]:
        """Element-wise median box: robust to single-frame outliers."""
        xs = sorted(d.x for d in self.boxes)
        ys = sorted(d.y for d in self.boxes)
        ws = sorted(d.w for d in self.boxes)
        hs = sorted(d.h for d in self.boxes)
        mid = len(self.boxes) // 2
        return (xs[mid], ys[mid], ws[mid], hs[mid])

    @property
    def size_jitter(self) -> float:
        """Relative size instability (0 = rock solid)."""
        if len(self.boxes) < 2:
            return 0.0
        ws = [d.w for d in self.boxes]
        hs = [d.h for d in self.boxes]
        mean = (sum(ws) + sum(hs)) / (len(ws) + len(hs))
        if mean <= 0:
            return 1.0
        var_w = sum((w - sum(ws) / len(ws)) ** 2 for w in ws) / len(ws)
        var_h = sum((h - sum(hs) / len(hs)) ** 2 for h in hs) / len(hs)
        return ((var_w**0.5) + (var_h**0.5)) / (2 * mean)

    @property
    def confidence(self) -> float:
        rate = self.frames_with_detection() / max(1, self.frames_seen)
        jitter_penalty = min(_JITTER_PENALTY_CAP, self.size_jitter)
        return round(max(0.0, rate * (1.0 - jitter_penalty)), 4)


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class FaceDetector(Protocol):
    def detect(self, frame_bgr) -> list[tuple[int, int, int, int]]:
        """Return face boxes (x, y, w, h) in frame pixel coords."""
        ...


class HaarFaceDetector:
    """Cascade face detector; ships with the opencv wheel."""

    def __init__(
        self,
        cascade_name: str = "haarcascade_frontalface_alt2.xml",
        *,
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_size: tuple[int, int] = (40, 40),
    ) -> None:
        path = cv2.data.haarcascades + cascade_name
        self._cascade = cv2.CascadeClassifier(path)
        if self._cascade.empty():
            raise RuntimeError(f"Haar cascade yuklenemedi: {cascade_name}")
        self._scale_factor = scale_factor
        self._min_neighbors = min_neighbors
        self._min_size = min_size

    def detect(self, frame_bgr) -> list[tuple[int, int, int, int]]:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=self._scale_factor,
            minNeighbors=self._min_neighbors,
            minSize=self._min_size,
        )
        if faces is None or len(faces) == 0:
            return []
        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]


def sample_frames(
    video_path: str | Path,
    start_seconds: float,
    end_seconds: float,
    samples_per_second: float = DEFAULT_SAMPLES_PER_SECOND,
) -> list[tuple[int, object]]:
    """Seek-read frames at the requested rate; returns
    (frame_index_from_zero, frame). Frame index counts samples, not
    video frames."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Video acilamadi: {video_path}")
    step = 1.0 / max(0.1, samples_per_second)
    samples: list[tuple[int, object]] = []
    try:
        index = 0
        t = start_seconds
        while t < end_seconds:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                samples.append((index, frame))
            index += 1
            t += step
    finally:
        cap.release()
    return samples


def cluster_detections(
    detections: list[Detection],
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
) -> list[Cluster]:
    """Greedy IoU clustering in frame order: each detection joins the
    best-matching existing cluster or starts a new one."""
    clusters: list[Cluster] = []
    for detection in detections:
        box = (detection.x, detection.y, detection.w, detection.h)
        best: Cluster | None = None
        best_score = iou_threshold
        for cluster in clusters:
            score = iou(box, cluster.region)
            if score >= best_score:
                best = cluster
                best_score = score
        if best is None:
            clusters.append(Cluster(boxes=[detection]))
        else:
            best.boxes.append(detection)
    return clusters


@dataclass
class WebcamResult:
    region: tuple[int, int, int, int] | None
    confidence: float
    frames_sampled: int
    frames_with_face: int
    reason: str | None = None


def detect_webcam_region(
    video_path: str | Path,
    start_seconds: float,
    end_seconds: float,
    detector: FaceDetector | None = None,
    samples_per_second: float = DEFAULT_SAMPLES_PER_SECOND,
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
) -> WebcamResult:
    """Best stable face cluster in the window = webcam region."""
    detector = detector or HaarFaceDetector()
    frames = sample_frames(
        video_path, start_seconds, end_seconds, samples_per_second
    )
    frames_sampled = len(frames)
    if not frames_sampled:
        return WebcamResult(None, 0.0, 0, 0, "ornek kare okunamadi")

    detections: list[Detection] = []
    for index, frame in frames:
        for x, y, w, h in detector.detect(frame):
            detections.append(Detection(x, y, w, h, index))

    frames_with_face = len({d.frame_index for d in detections})
    if not detections:
        return WebcamResult(
            None, 0.0, frames_sampled, 0, "yuz bulunamadi"
        )

    clusters = cluster_detections(detections, iou_threshold)
    for cluster in clusters:
        cluster.frames_seen = frames_sampled
    # En iyi kume: yakalama orani, sonra alan.
    best = max(
        clusters,
        key=lambda c: (c.frames_with_detection(), c.region[2] * c.region[3]),
    )
    confidence = best.confidence
    if best.frames_with_detection() < 2:
        return WebcamResult(
            best.region,
            confidence,
            frames_sampled,
            frames_with_face,
            "tek karede goruldu; guven dusuk",
        )
    return WebcamResult(
        best.region,
        confidence,
        frames_sampled,
        frames_with_face,
        None,
    )
