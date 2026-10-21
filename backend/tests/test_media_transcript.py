"""media_transcript: VTT/SRT parsing, sidecar lookup, range extraction."""
from __future__ import annotations

from app.services.media_transcript import (
    find_sidecar,
    parse_sidecar_text,
    parse_srt,
    parse_vtt,
    transcript_text_in_range,
)

VTT_SAMPLE = """WEBVTT

00:00:00.500 --> 00:00:02.000
Merhaba dunya

00:00:02.000 --> 00:00:04.500 position:50%
Ikinci satir
devam ediyor

00:00:05.000 --> 00:00:04.000
ters zaman damgasi atlanir

NOT-BIR-CUE
duz metin blogu

01:02:03.250 --> 01:02:05.000
saatlik damga
"""

SRT_SAMPLE = """1
00:00:01,000 --> 00:00:03,000
SRT ilk cumle

2
00:00:03,500 --> 00:00:06,000
SRT ikinci cumle

bozuk blok
00:00:99,000 --> 00:00:99,000
gecersiz damga
"""


class TestParsers:
    def test_parse_vtt(self):
        segments = parse_vtt(VTT_SAMPLE)
        assert len(segments) == 3
        assert segments[0] == {
            "start": 0.5,
            "end": 2.0,
            "text": "Merhaba dunya",
        }
        # Cogul satirlar birlesir; cue ayarlari (position) yok sayilir.
        assert segments[1]["text"] == "Ikinci satir devam ediyor"
        assert segments[1]["end"] == 4.5
        # ters damga ve cue olmayan blok atlandi
        assert all(s["end"] > s["start"] for s in segments)
        # 01:02:03.250 -> 1 saat 2 dakika 3.25 saniye
        assert segments[2]["start"] == 1 * 3600 + 2 * 60 + 3.25

    def test_parse_srt(self):
        segments = parse_srt(SRT_SAMPLE)
        assert len(segments) == 2
        assert segments[0]["start"] == 1.0
        assert segments[0]["end"] == 3.0
        assert segments[0]["text"] == "SRT ilk cumle"
        assert segments[1]["start"] == 3.5

    def test_dispatch_by_marker(self):
        assert parse_sidecar_text(VTT_SAMPLE)[0]["start"] == 0.5
        assert parse_sidecar_text(SRT_SAMPLE)[0]["start"] == 1.0

    def test_empty_and_garbage_input(self):
        assert parse_vtt("") == []
        assert parse_srt("rastgele metin\n--\nbaska") == []
        assert parse_sidecar_text("WEBVTT\n") == []


class TestSidecarAndRange:
    def test_find_sidecar_prefers_vtt(self, tmp_path):
        media = tmp_path / "7.mp4"
        media.write_bytes(b"x")
        assert find_sidecar(media) is None
        srt = tmp_path / "7.srt"
        srt.write_text(SRT_SAMPLE, encoding="utf-8")
        found = find_sidecar(media)
        assert found is not None and found.suffix == ".srt"
        vtt = tmp_path / "7.vtt"
        vtt.write_text(VTT_SAMPLE, encoding="utf-8")
        found = find_sidecar(media)
        assert found is not None and found.suffix == ".vtt"

    def test_find_sidecar_language_suffix(self, tmp_path):
        # yt-dlp '<id>.tr.vtt' adlandirmasi da bulunmalidir
        media = tmp_path / "1.mp4"
        media.write_bytes(b"x")
        assert find_sidecar(media) is None
        lang = tmp_path / "1.tr.vtt"
        lang.write_text(VTT_SAMPLE, encoding="utf-8")
        found = find_sidecar(media)
        assert found is not None and found.name == "1.tr.vtt"

    def test_range_extraction_overlaps(self):
        segments = parse_vtt(VTT_SAMPLE)
        # [0.0, 2.5) -> ilk cue + ikinci cueyle kesisim
        text = transcript_text_in_range(segments, 0.0, 2.5)
        assert "Merhaba" in text and "Ikinci" in text
        # tamamen disinda
        assert transcript_text_in_range(segments, 10.0, 20.0) == ""
        # tek cue araligi
        only_second = transcript_text_in_range(segments, 4.0, 4.4)
        assert only_second == "Ikinci satir devam ediyor"


class TestYouTubeAutoCaptionCleanup:
    """2026-10-21 canlı olay: yt-dlp --write-auto-subs ile inen YouTube
    otomatik altyazıları kelime zamanlaması etiketleri
    ('<00:00:08.040><c> almaya</c>') ve HTML varlıkları taşır; temizlenmezse
    altyazı klipte zaman damgalarıyla birlikte görünür. Ayrıca 'kayan'
    cue'larda ilk satır önceki cue'nun tekrarıdır."""

    AUTO_VTT = """WEBVTT

00:00:07.670 --> 00:00:07.680
Bilgisayarına, bazen internetin

00:00:07.680 --> 00:00:09.950
Bilgisayarına, bazen internetin &gt;&gt; 360<00:00:08.040><c> almaya</c><00:00:08.280><c> koş.</c>

00:00:09.950 --> 00:00:12.000
360 almaya koş. PlayStation 5 &amp; kırıldı
"""

    def test_word_timing_tags_stripped(self):
        segments = parse_vtt(self.AUTO_VTT)
        texts = " ".join(seg["text"] for seg in segments)
        # Zaman damgaları ve etiketler metinde görünmez.
        assert "00:00:08" not in texts
        assert "<c>" not in texts and "<" not in texts
        assert "&gt;" not in texts and "&amp;" not in texts
        # Asil kelimeler kalir.
        assert "almaya" in texts and "koş" in texts
        assert "PlayStation 5" in texts

    def test_rolling_repeat_line_dropped(self):
        segments = parse_vtt(self.AUTO_VTT)
        # Ikinci cue'nun ilk satiri onceki cue'nun tekrariydi; altyazida
        # cumle iki kez görünmemeli.
        assert segments[1]["text"].startswith("Bilgisayarına")
        assert segments[1]["text"].count("Bilgisayarına") == 1

    def test_srt_entities_cleaned(self):
        segments = parse_srt(
            "1\n00:00:01,000 --> 00:00:03,000\n"
            "Merhaba &amp; hos &lt;geldin&gt;\n"
        )
        assert segments[0]["text"] == "Merhaba & hos <geldin>"

    def test_speaker_marker_dropped(self):
        segments = parse_vtt(
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
            "&gt;&gt; Konusmaci degisti\n"
        )
        assert segments[0]["text"] == "Konusmaci degisti"
