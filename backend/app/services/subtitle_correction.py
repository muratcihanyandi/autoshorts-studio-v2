"""Turkish subtitle correction through the LLM chain (M9).

The provider chain (ADR-011) receives numbered segments with strict
rules: fix Turkish spelling and punctuation, preserve names/numbers,
never merge or reorder, flag uncertain lines. The service never trusts
the response shape: segment count and index coverage are verified, and
timestamps are copied verbatim from the ORIGINAL transcript — the LLM
never sees or sets them, so corrections cannot silently alter timing.

The original transcripts row stays untouched; the corrected copy lives
in corrected_transcripts (one per media asset).
"""
from __future__ import annotations

import httpx
import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import CorrectedTranscript, MediaAsset, Transcript
from app.services.channel_service import record_event
from app.services.llm_service import LlmProviderService, LlmServiceError

CHUNK_SIZE = 20

MAX_TITLE_CHARS = 100
MAX_DESCRIPTION_CHARS = 5000


class CorrectedLine(BaseModel):
    """LLM sözleşmesi: tek satır düzeltme."""

    index: int = Field(ge=0)
    text: str
    uncertain: bool = False


class CorrectionResponse(BaseModel):
    segments: list[CorrectedLine]


PROMPT_HEADER = (
    "Asagida numarali Turkce altyazi satirlari var. Gorev:\n"
    "- Yazim ve noktalama hatalarini duzelt\n"
    "- Isimleri, sayilari ve anlamı ASLA degistirme\n"
    "- Satirlari birlestirme, bolme veya siralama\n"
    "- Emin olmadigin satiri uncertain=true isaretle\n"
    "Yaniti SADECE su JSON biciminde ver:\n"
    '{"segments": [{"index": 0, "text": "...", "uncertain": false}]}\n\n'
)


class SubtitleCorrectionError(Exception):
    """Correction failure with a user-facing Turkish message."""


class SubtitleCorrectionService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        llm: LlmProviderService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._llm = llm

    async def correct_transcript(
        self, media_asset_id: int, *, http: httpx.AsyncClient | None = None
    ) -> dict:
        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, media_asset_id)
            if asset is None:
                raise SubtitleCorrectionError("Medya varligi bulunamadi.")
            existing = (
                (
                    await session.execute(
                        sa.select(CorrectedTranscript).where(
                            CorrectedTranscript.media_asset_id == media_asset_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if existing is not None:
                return {"media_asset_id": media_asset_id, "skipped": True}
            transcript = (
                (
                    await session.execute(
                        sa.select(Transcript).where(
                            Transcript.media_asset_id == media_asset_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if transcript is None or not transcript.segments:
                raise SubtitleCorrectionError(
                    "Duzeltilecek transkript yok; once medya islemesi gerekir."
                )
            source_video_id = asset.source_video_id
            segments = [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in transcript.segments
            ]

        corrected: list[dict] = []
        provider_name = ""
        for offset in range(0, len(segments), CHUNK_SIZE):
            chunk = segments[offset : offset + CHUNK_SIZE]
            prompt = PROMPT_HEADER + self._format_chunk(chunk, offset)
            # Parca bazli yeniden deneme: dusunen/yavas saglayicilarda tek
            # parcanin gecersiz donmesi tum varligi basa sarmandan once
            # kendi basina tekrar denensin (is yeniden denemesiyle
            # basarili parcalar tekrar cagrilmaz).
            result = None
            last_error: LlmServiceError | None = None
            for attempt in range(3):
                try:
                    result = await self._llm.complete(
                        prompt, schema=CorrectionResponse, http=http
                    )
                    break
                except LlmServiceError as exc:
                    last_error = exc
            if result is None:
                assert last_error is not None
                raise SubtitleCorrectionError(str(last_error)) from last_error
            lines = self._validated(result.structured, len(chunk), offset)
            provider_name = result.provider_name
            for position, line in enumerate(lines):
                original = chunk[position]
                corrected.append(
                    {
                        "start": original["start"],
                        "end": original["end"],
                        "text": line.text.strip() or original["text"],
                        "uncertain": line.uncertain,
                    }
                )

        corrected_count = sum(
            1
            for original, new in zip(segments, corrected)
            if original["text"] != new["text"]
        )
        flagged_count = sum(1 for seg in corrected if seg["uncertain"])

        async with self._sessionmaker() as session:
            session.add(
                CorrectedTranscript(
                    media_asset_id=media_asset_id,
                    segments=corrected,
                    corrected_count=corrected_count,
                    flagged_count=flagged_count,
                    provider_name=provider_name,
                )
            )
            channel_id = await self._channel_of(session, source_video_id)
            record_event(
                session,
                channel_id,
                "subtitle.corrected",
                {
                    "media_asset_id": media_asset_id,
                    "segments": len(corrected),
                    "corrected": corrected_count,
                    "flagged": flagged_count,
                    "provider": provider_name,
                },
            )
            await session.commit()
        return {
            "media_asset_id": media_asset_id,
            "segments": len(corrected),
            "corrected": corrected_count,
            "flagged": flagged_count,
            "provider": provider_name,
        }

    # --- yardimcilar ---

    @staticmethod
    def _format_chunk(chunk: list[dict], offset: int) -> str:
        lines = [
            f"{offset + i}. {seg['text']}" for i, seg in enumerate(chunk)
        ]
        return "\n".join(lines)

    @staticmethod
    def _validated(
        structured, expected: int, offset: int
    ) -> list[CorrectedLine]:
        """Sekil sozlesmesi: tam kapsam, index dogrulugu, ayni sayi."""
        if not isinstance(structured, dict):
            raise SubtitleCorrectionError("Saglayici yaniti bozuk (dict degil).")
        response = CorrectionResponse.model_validate(structured)
        lines = response.segments
        if len(lines) != expected:
            raise SubtitleCorrectionError(
                f"Satir sayisi uyusmadi: {len(lines)} != {expected}."
            )
        indices = sorted(line.index for line in lines)
        if indices != list(range(offset, offset + expected)):
            raise SubtitleCorrectionError("Satir indeksleri eksik veya bozuk.")
        return lines

    @staticmethod
    async def _channel_of(session: AsyncSession, source_video_id: int) -> int | None:
        from app.models import SourceChannel, SourceVideo

        video = await session.get(SourceVideo, source_video_id)
        if video is None:
            return None
        source = await session.get(SourceChannel, video.source_channel_id)
        return source.channel_id if source else None
