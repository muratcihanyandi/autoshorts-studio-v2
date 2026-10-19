"""webcam_detect: multi-frame detection, clustering, confidence.

Real-detection tests run actual OpenCV on generated media: the face
stream fixture (public-domain NASA portrait composited over a dark
background with slight jitter) and the M7 synthetic color video (no
faces). Pure clustering math is tested on synthetic boxes.

M13: character-face validation tests use the same PD photo as BOTH
the character reference and the face inside the test frame.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.vertical_pipeline import (
    DEFAULT_CHARACTER_MATCH_THRESHOLD,
    apply_character_validation,
)
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

    def test_ffmpeg_fallback_extracts_frames(self, face_video):
        """OpenCV'in cozumleyemedigi codec (orn. AV1) yedegi: ffmpeg kare
        cikarma yolu kendi basina calismali — ayni oran, ayni boyut."""
        from app.services.webcam_detect import _sample_frames_ffmpeg

        frames = _sample_frames_ffmpeg(
            face_video, 0.0, 8.0, 1.0, ffmpeg_bin="ffmpeg"
        )
        assert 6 <= len(frames) <= 8  # fps filtresi kucuk kayma toleransi
        height, width = frames[0][1].shape[:2]
        assert (width, height) == (1280, 720)

    def test_missing_file_raises(self, tmp_path):
        import pytest

        with pytest.raises(RuntimeError):
            sample_frames(tmp_path / "yok.mp4", 0.0, 1.0)

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


@pytest.fixture(scope="module")
def charval_face_video(tmp_path_factory):
    return make_face_stream_video(
        tmp_path_factory.mktemp("charval") / "face_stream.mp4"
    )


@pytest.fixture(scope="module")
def pd_reference():
    import cv2

    from app.services.character_match import extract_reference

    photo = cv2.imread(
        str(Path(__file__).parent / "assets" / "face_pd.jpg")
    )
    reference = extract_reference(photo)
    assert reference is not None  # fixture on kosulu: fotografda yuz var
    return reference


class TestCharacterValidation:
    """M13: algilanan webcam bolgesi karakterin referans yuzuyle
    dogrulanir. PD yuz fotografi hem karakter fotografi hem karedeki
    yuz olarak kullanilir (ayni kisi -> gecer)."""

    def _frame_at(self, video, seconds: float):
        frames = sample_frames(video, seconds, seconds + 1.0)
        assert frames, "kare okunamadi"
        return frames[0][1]

    def test_pd_face_region_validates(
        self, charval_face_video, pd_reference
    ):
        # Kesfedilen tipik bolge + ayni kisinin referans yuzu -> gecer
        frame = self._frame_at(charval_face_video, 1.0)
        region, confidence, reason = apply_character_validation(
            (280, 155, 85, 85),
            0.8,
            frame,
            pd_reference,
            DEFAULT_CHARACTER_MATCH_THRESHOLD,
        )
        assert region is not None
        assert reason is None
        assert confidence == 0.8  # gecen bolge tespit guvenini korur

    def test_nonface_region_falls_to_review(self, pd_reference):
        # Yuz icerMEyen kare: benzerlik ve arama da basarisiz -> review
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            plain = make_test_media(Path(tmp) / "plain.mp4")
            frame = self._frame_at(plain, 2.0)
        region, confidence, reason = apply_character_validation(
            (280, 155, 85, 85),
            0.8,
            frame,
            pd_reference,
            DEFAULT_CHARACTER_MATCH_THRESHOLD,
        )
        assert region is None
        assert confidence < DEFAULT_CHARACTER_MATCH_THRESHOLD
        assert reason is not None and "karakter" in reason

    def test_wrong_region_rescued_by_search(
        self, charval_face_video, pd_reference
    ):
        # Yanlis bolge (arka plan) verildiginde sablon aramasi yuzun
        # yerini bulur ve bolgeyi duzeltir.
        frame = self._frame_at(charval_face_video, 1.0)
        region, confidence, reason = apply_character_validation(
            (900, 500, 100, 100),
            0.8,
            frame,
            pd_reference,
            DEFAULT_CHARACTER_MATCH_THRESHOLD,
        )
        assert region is not None
        assert reason is None
        # Kurtarilan bolge yuzun bilinen mahallesini kapsamali
        x, y, w, h = region
        assert x <= 280 and y <= 155
        assert x + w >= 365 and y + h >= 240

    def test_region_outside_frame_rejected(
        self, charval_face_video, pd_reference
    ):
        frame = self._frame_at(charval_face_video, 1.0)
        region, _, reason = apply_character_validation(
            (5000, 5000, 80, 80),
            0.8,
            frame,
            pd_reference,
            DEFAULT_CHARACTER_MATCH_THRESHOLD,
        )
        assert region is None
        assert reason is not None
