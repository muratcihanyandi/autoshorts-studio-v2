"""webcam_detect: multi-frame detection, clustering, confidence.

Real-detection tests run actual OpenCV on generated media: the face
stream fixture (public-domain NASA portrait composited over a dark
background with slight jitter) and the M7 synthetic color video (no
faces). Pure clustering math is tested on synthetic boxes.
"""
from __future__ import annotations

import pytest

from app.services.webcam_detect import (
    Cluster,
    Detection,
    HaarFaceDetector,
    cluster_detections,
    detect_webcam_region,
    iou,
    sample_frames,
)
from tests.media_sample import make_face_stream_video, make_test_media


class TestPureLogic:
    def test_iou(self):
        a = (0, 0, 100, 100)
        assert iou(a, a) == pytest.approx(1.0)
        assert iou(a, (100, 0, 100, 100)) == pytest.approx(0.0)
        assert 0.0 < iou(a, (50, 0, 100, 100)) < 1.0

    def test_cluster_stable_region_wins_over_noise(self):
        # 6 karede kararli yuz + tek karelik rastgele gurultu
        detections = [
            Detection(100, 100, 80, 80, frame)
            for frame in range(6)
        ] + [Detection(100, 102, 78, 79, 5)] + [
            Detection(600, 500, 40, 40, 2)  # gurultu
        ]
        clusters = cluster_detections(detections)
        assert len(clusters) == 2
        best = max(
            clusters, key=lambda c: (c.frames_with_detection(), c.region[2])
        )
        assert best.frames_with_detection() == 6
        region = best.region
        assert 95 <= region[0] <= 105
        assert 80 <= region[2] <= 85

    def test_cluster_confidence_penalizes_jitter(self):
        steady = Cluster(
            boxes=[Detection(50, 50, 100, 100, i) for i in range(10)],
            frames_seen=10,
        )
        jumpy = Cluster(
            boxes=[
                Detection(50, 50, 100 if i % 2 == 0 else 40, 100, i)
                for i in range(10)
            ],
            frames_seen=10,
        )
        assert steady.confidence == pytest.approx(1.0)
        assert jumpy.confidence < steady.confidence
        assert jumpy.confidence > 0.0

    def test_single_frame_cluster_is_low_confidence(self):
        lonely = Cluster(boxes=[Detection(10, 10, 50, 50, 0)], frames_seen=8)
        assert lonely.confidence < 0.2


class TestRealDetection:
    @pytest.fixture(scope="module")
    def face_video(self, tmp_path_factory):
        return make_face_stream_video(
            tmp_path_factory.mktemp("webcam") / "face_stream.mp4"
        )

    def test_haar_detector_loads(self):
        detector = HaarFaceDetector()
        frame = __import__("cv2").imread(
            str(__import__("pathlib").Path(__file__).parent / "assets" / "face_pd.jpg")
        )
        faces = detector.detect(frame)
        assert len(faces) == 1
        x, y, w, h = faces[0]
        assert 300 < x < 450 and 100 < y < 250 and 100 < w < 180

    def test_sample_frames_returns_requested_rate(self, face_video):
        frames = sample_frames(face_video, 0.0, 8.0, samples_per_second=1.0)
        assert len(frames) == 8
        height, width = frames[0][1].shape[:2]
        assert (width, height) == (1280, 720)

    def test_detect_webcam_region_on_face_video(self, face_video):
        result = detect_webcam_region(face_video, 0.0, 8.0)
        # Cogunluk karede yuz var: guven yuksek, bolge yuzun civarinda.
        assert result.frames_sampled == 8
        assert result.frames_with_face >= 6
        assert result.confidence >= 0.5
        assert result.region is not None
        x, y, w, h = result.region
        assert 250 <= x <= 310
        assert 130 <= y <= 175
        assert 70 <= w <= 100
        assert 70 <= h <= 100

    def test_no_face_video_gives_zero_confidence(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            plain = make_test_media(Path(tmp) / "plain.mp4")
            result = detect_webcam_region(plain, 0.0, 12.0)
        assert result.region is None
        assert result.confidence == 0.0
        assert result.frames_with_face == 0
        assert result.reason is not None

    def test_detection_uses_only_requested_window(self, face_video):
        # Ilk 2 saniye: ayni sonucu vermeli (bolge pencere disina tasamaz)
        result = detect_webcam_region(face_video, 1.0, 4.0)
        assert result.region is not None
        x, y, w, h = result.region
        assert 250 <= x <= 310 and 130 <= y <= 175


class TestMultiSeedDetection:
    """Kullanici odağı: webcam tespiti farkli hareket genliklerinde de
    guvenilir olmali (M12 agir test)."""

    @pytest.mark.parametrize("jx,jy", [(0, 0), (6, 5), (14, 11)])
    def test_detection_across_jitter_levels(self, tmp_path_factory, jx, jy):
        video = make_face_stream_video(
            tmp_path_factory.mktemp(f"jit{jx}") / f"face_{jx}_{jy}.mp4",
            jitter_x=jx,
            jitter_y=jy,
        )
        result = detect_webcam_region(video, 0.0, 8.0)
        assert result.region is not None
        assert result.confidence >= 0.5, (
            f"jitter=({jx},{jy}) guven dustu: {result.confidence}"
        )
        x, y, w, h = result.region
        # Bolge yuzun bilinen mahallesinde kalmali.
        assert 240 <= x <= 320
        assert 120 <= y <= 190
        assert 65 <= w <= 105
        assert 65 <= h <= 105

    def test_detection_at_higher_sampling_rate(self, tmp_path_factory):
        """2 fps ornekleme ayni bolgeyi daha cok kareyle bulmali."""
        video = make_face_stream_video(
            tmp_path_factory.mktemp("hi") / "face_hi.mp4"
        )
        result = detect_webcam_region(
            video, 0.0, 8.0, samples_per_second=2.0
        )
        assert result.frames_sampled == 16
        assert result.region is not None
        assert result.confidence >= 0.5
