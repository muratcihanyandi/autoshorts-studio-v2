"""media_probe: ffprobe inspection, integrity, hashing.

Runs the real ffprobe/ffmpeg binaries from PATH against generated
synthetic media (tests/media_sample.py) — the same tools the pipeline
uses on the Pi.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.media_probe import (
    InspectionData,
    MediaProbeError,
    integrity_ok,
    parse_probe,
    probe_media,
    sha256_file,
)
from tests.media_sample import make_test_media


class TestParseProbe:
    def test_maps_streams_and_format(self):
        raw = {
            "format": {"duration": "12.0", "format_name": "mov,mp4,m4a"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 320,
                    "height": 240,
                    "r_frame_rate": "30000/1001",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }
        data = parse_probe(raw)
        assert data.duration_seconds == 12.0
        assert (data.width, data.height) == (320, 240)
        assert data.fps == pytest.approx(29.97, abs=0.01)
        assert data.video_codec == "h264"
        assert data.audio_codec == "aac"
        assert data.has_audio is True
        assert data.format_name == "mov,mp4,m4a"

    def test_video_only_and_bad_values(self):
        raw = {
            "format": {"duration": "5.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 100,
                    "height": 50,
                    "r_frame_rate": "0/0",
                }
            ],
        }
        data = parse_probe(raw)
        assert data.has_audio is False
        assert data.audio_codec is None
        assert data.fps == 0.0

    def test_missing_duration_or_video_raises(self):
        with pytest.raises(MediaProbeError):
            parse_probe({"format": {}, "streams": []})
        with pytest.raises(MediaProbeError):
            parse_probe(
                {
                    "format": {"duration": "1.0"},
                    "streams": [{"codec_type": "audio", "codec_name": "aac"}],
                }
            )

    def test_integrity_rules(self):
        ok = InspectionData(
            duration_seconds=10.0,
            width=320,
            height=240,
            fps=15.0,
            video_codec="h264",
            audio_codec=None,
            has_audio=False,
            format_name=None,
        )
        assert integrity_ok(ok) is True
        assert integrity_ok(
            InspectionData(
                duration_seconds=0.0,
                width=320,
                height=240,
                fps=15.0,
                video_codec="h264",
                audio_codec=None,
                has_audio=False,
                format_name=None,
            )
        ) is False
        assert integrity_ok(
            InspectionData(
                duration_seconds=10.0,
                width=0,
                height=240,
                fps=15.0,
                video_codec="h264",
                audio_codec=None,
                has_audio=False,
                format_name=None,
            )
        ) is False


class TestRealProbe:
    def test_probe_generated_media(self, tmp_path):
        media = make_test_media(tmp_path / "sample.mp4")

        async def scenario():
            return await probe_media("ffprobe", media)

        data = asyncio.run(scenario())
        assert data.duration_seconds == pytest.approx(12.0, abs=0.5)
        assert (data.width, data.height) == (320, 240)
        assert data.fps == pytest.approx(15.0, abs=0.1)
        assert data.video_codec == "h264"
        assert data.has_audio is True
        assert integrity_ok(data) is True

    def test_corrupt_file_fails_probe(self, tmp_path):
        media = make_test_media(tmp_path / "sample.mp4")
        corrupt = tmp_path / "corrupt.mp4"
        corrupt.write_bytes(media.read_bytes()[: media.stat().st_size // 3])

        async def scenario():
            try:
                await probe_media("ffprobe", corrupt)
                return None
            except MediaProbeError as exc:
                return str(exc)

        message = asyncio.run(scenario())
        assert message is not None  # bozuk dosya Turkce hata ile reddedilir

    def test_missing_file_fails_probe(self, tmp_path):
        async def scenario():
            try:
                await probe_media("ffprobe", tmp_path / "yok.mp4")
                return None
            except MediaProbeError as exc:
                return str(exc)

        assert asyncio.run(scenario()) is not None

    def test_sha256_stable_and_size_aware(self, tmp_path):
        media = make_test_media(tmp_path / "sample.mp4")

        async def scenario():
            first = await sha256_file(media)
            second = await sha256_file(media)
            return first, second

        first, second = asyncio.run(scenario())
        assert first == second
        assert len(first) == 64

    def test_sha256_missing_file_raises(self, tmp_path):
        async def scenario():
            try:
                await sha256_file(tmp_path / "yok.mp4")
                return False
            except MediaProbeError:
                return True

        assert asyncio.run(scenario()) is True
