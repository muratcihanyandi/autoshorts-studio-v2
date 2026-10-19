"""media_analysis: silence/scene/energy measurement.

Parser functions are tested against crafted ffmpeg log text; the
real-media tests run actual ffmpeg on the synthetic sample (scene cuts
at 4s/8s, silence 0-2s and 10-12s, 12s total — see media_sample.py).
"""
from __future__ import annotations

import asyncio
import math
from array import array

import pytest

from app.services.media_analysis import (
    bytes_to_samples,
    intro_outro_from_silences,
    parse_scene_log,
    parse_silence_log,
    window_rms,
)
from tests.media_sample import (
    SCENE_CUTS,
    SILENCE_RUNS,
    TOTAL_SECONDS,
    make_test_media,
)

SILENCE_LOG = """
[muted @ 0x1] silence_start: 0
[muted @ 0x1] silence_end: 2.004 | silence_duration: 2.004
[muted @ 0x1] silence_start: 10.001
[muted @ 0x1] silence_end: 12 | silence_duration: 1.999
"""

SCENE_LOG = """
[Parsed_showinfo @ 0x2] n:   0 pts: 90000 pts_time:4 position:0
[Parsed_showinfo @ 0x2] n:   1 pts: 180000 pts_time:8 position:0
unrelated line without pts
"""


class TestParsers:
    def test_parse_silence_log_pairs(self):
        assert parse_silence_log(SILENCE_LOG) == [(0.0, 2.004), (10.001, 12.0)]

    def test_parse_silence_log_unpaired_start_ignored(self):
        assert parse_silence_log("silence_start: 5\n") == []
        assert parse_silence_log("no markers here") == []

    def test_parse_scene_log(self):
        assert parse_scene_log(SCENE_LOG) == [4.0, 8.0]
        assert parse_scene_log("nothing") == []

    def test_intro_outro_rules(self):
        duration = 12.0
        # bastaki ve sondaki sessizlik intro/outro olur
        assert intro_outro_from_silences([(0.0, 2.0), (10.0, 12.0)], duration) == (
            2.0,
            10.0,
        )
        # ortadaki sessizlik hicbirine sayilmaz
        assert intro_outro_from_silences([(5.0, 7.0)], duration) == (0.0, duration)
        # tum dosya sessiz: bozulma olmaz, tam aralik kalir
        assert intro_outro_from_silences([(0.0, 12.0)], duration) == (0.0, duration)
        # bos liste
        assert intro_outro_from_silences([], duration) == (0.0, duration)

    def test_window_rms(self):
        samples = array("h", [3, 4, 0, 0])
        assert window_rms(samples, 2) == pytest.approx(
            [math.sqrt((9 + 16) / 2), 0.0]
        )
        # kuyruk parcali pencere dusurulur
        assert window_rms(samples, 3) == pytest.approx(
            [math.sqrt((9 + 16 + 0) / 3)]
        )
        assert window_rms(samples, 0) == []

    def test_bytes_to_samples(self):
        samples = bytes_to_samples((3).to_bytes(2, "little") + (4).to_bytes(2, "little") + b"\xff")
        assert list(samples) == [3, 4]  # tek bayt kuyruk atilir


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return make_test_media(tmp_path_factory.mktemp("analysis") / "sample.mp4")


class TestRealAnalysis:
    def test_detect_silence_matches_synthetic(self, sample):
        from app.services.media_analysis import detect_silence

        async def scenario():
            return await detect_silence(
                "ffmpeg", sample, noise_db=-35.0, min_seconds=1.5
            )

        silences = asyncio.run(scenario())
        assert len(silences) == 2
        assert silences[0][0] == pytest.approx(SILENCE_RUNS[0][0], abs=0.5)
        assert silences[0][1] == pytest.approx(SILENCE_RUNS[0][1], abs=0.5)
        assert silences[1][0] == pytest.approx(SILENCE_RUNS[1][0], abs=0.5)
        assert silences[1][1] == pytest.approx(SILENCE_RUNS[1][1], abs=0.5)

    def test_detect_scene_changes_matches_synthetic(self, sample):
        from app.services.media_analysis import detect_scene_changes

        async def scenario():
            return await detect_scene_changes(
                "ffmpeg", sample, threshold=0.4
            )

        times = asyncio.run(scenario())
        assert len(times) == len(SCENE_CUTS)
        for detected, expected in zip(times, SCENE_CUTS, strict=True):
            assert detected == pytest.approx(expected, abs=0.5)

    def test_audio_rms_windows_separate_muted_regions(self, sample):
        from app.services.media_analysis import audio_rms_windows

        async def scenario():
            return await audio_rms_windows(
                "ffmpeg", sample, sample_rate=8000, window_seconds=1.0
            )

        levels = asyncio.run(scenario())
        # 12 saniye -> 12 tam pencere
        assert len(levels) == int(TOTAL_SECONDS)
        voiced = levels[2:10]  # 2-10s ton var
        muted = levels[0:2] + levels[10:12]  # bastaki/sondaki sessizlik
        assert max(voiced) > 1000
        assert max(muted) < max(voiced) / 5

    def test_intro_outro_from_real_silences(self, sample):
        from app.services.media_analysis import (
            detect_silence,
            intro_outro_from_silences,
        )

        async def scenario():
            silences = await detect_silence(
                "ffmpeg", sample, noise_db=-35.0, min_seconds=1.5
            )
            return intro_outro_from_silences(silences, TOTAL_SECONDS)

        intro_end, outro_start = asyncio.run(scenario())
        assert intro_end == pytest.approx(2.0, abs=0.5)
        assert outro_start == pytest.approx(10.0, abs=0.5)
