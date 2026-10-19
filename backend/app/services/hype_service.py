"""LLM hype-point evaluation (Start/Stop era, spec section 8).

The pure-code candidate scorer (M7 clip_candidates) proposes windows
from audio energy, scene density and transcript coverage. This service
is the judgment layer on top: for each candidate the LLM sees the
timestamped transcript WITH surrounding context, the audio-analysis
summary, the video's duration and the channel's duration rules, and
returns refined start/end times, a reason and a confidence score as
structured JSON.

The rules that matter here:

- A clip must NOT start or end in the middle of the excitement: the
  build-up, the sentence start and the reaction landing stay inside.
  Boundaries snap to transcript segment edges so sentences are never
  cut in half (only when the snap keeps the clip within min/max
  duration).
- LLM-proposed times are validated (video bounds, min/max duration,
  monotonic) before anything reaches FFmpeg; invalid proposals fall
  back to the code-scored window.
- +18 detection and AI-use detection are independent judgments made
  later in metadata — a loud or AI-edited moment is not inherently
  adult content.
- Without a working LLM the service falls back to selecting the top
  candidates by their code score (audited), so the pipeline never
  stalls on provider outages.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Channel,
    Character,
    ClipCandidate,
    CorrectedTranscript,
    MediaAsset,
    MediaInspection,
    PublishingProfile,
    SourceChannel,
    SourceVideo,
    Transcript,
)
from app.services.channel_service import record_event
from app.services.llm_service import LlmProviderService, LlmServiceError
from app.services.media_transcript import transcript_text_in_range

logger = logging.getLogger(__name__)

# Cevap oncesi/sonrasi baglam penceresi (saniye).
CONTEXT_SECONDS = 20.0

DEFAULT_HYPE_SYSTEM_PROMPT = (
    "Sen bir kisa video kurgu uzmanisin. Verilen aday klip bolgelerini "
    "degerlendirip en iyi baslangic/bitis zamanlarini belirle.\n"
    "- Klip heyecanli anin TAM ORTASINDA baslamamali: hazirlik kismini, "
    "cumlenin baslangicini ve reaksiyonun olusmasini icine al.\n"
    "- Klip reaksiyon tamamlanmadan bitmemeli; hype ani (tepki/heyecan) "
    "biter BITMEZ bitir — olayin dogal kapanisini kesme.\n"
    "- Klip suresi ESNEKTIR: anin dogasina gore 20 saniye ile 3 dakika "
    "arasinda secilebilir; sureyi doldurmak icin anin sonunu budama.\n"
    "- Ses analizi yaniltici olabilir (muzik, oyun efektleri); transkript "
    "baglamina oncelik ver.\n"
    "- Kesin olmayan bilgileri kesin gibi one surme; guven puanini "
    "dusurerek belirt.\n"
    "- Yaniti yalnizca istenen JSON biciminde ver."
)


class HypeEvaluationItem(BaseModel):
    """LLM sözleşmesi: aday başına rafine zamanlar + gerekçe + güven."""

    candidate_id: int
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    reason: str = Field(default="", max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)


class HypeEvaluationResponse(BaseModel):
    evaluations: list[HypeEvaluationItem] = Field(default_factory=list)


PROMPT_TEMPLATE = (
    "Asagida bir yatay video ve bu videodan kesilmis aday klip "
    "bolgeleri var. Her aday icin en iyi baslangic/bitis zamanlarini "
    "belirle.\n\n"
    "Video toplam suresi: {duration:.1f} saniye\n"
    "Klip sure araligi: en az {min_seconds}, en cok {max_seconds} saniye. "
    "Sure esnektir — anin dogal suresine gore 20 saniyeden 1-2 dakikaya "
    "kadar sec; sureyi doldurmak icin anin sonunu BUDAMA.\n\n"
    "Adaylar:\n{candidates}\n\n"
    "Yaniti SADECE su JSON biciminde ver:\n"
    '{{"evaluations": [{{"candidate_id": 1, "start_seconds": 12.5, '
    '"end_seconds": 48.0, "reason": "kisa gerekce", "confidence": 0.8}}]}}\n'
    "Kurallar: start_seconds < end_seconds olmali; zamanlar video "
    "sinirlari icinde kalmali; heyecanli anin ortasindan kesme; hype ani "
    "(tepki/heyecan) tamamlanmadan klip BITMEMELI, olay biter bitmez "
    "bitir."
)


class HypeError(Exception):
    """Hype evaluation failure with a user-facing Turkish message."""


def _energy_stats(energy_windows: list[float], start: float, end: float) -> dict:
    """RMS pencere ozetleri aday araligi icin (LLM baglami)."""
    if not energy_windows:
        return {"mean": None, "max": None, "spikes": 0}
    lo = max(0, int(start))
    hi = max(lo + 1, int(end))
    window = energy_windows[lo:hi]
    if not window:
        return {"mean": None, "max": None, "spikes": 0}
    mean = sum(window) / len(window)
    peak = max(window)
    spikes = sum(1 for v in window if v > mean * 1.8)
    return {"mean": round(mean, 2), "max": round(peak, 2), "spikes": spikes}


def snap_to_segments(
    start: float,
    end: float,
    segments: list[dict],
    *,
    duration: float,
    min_seconds: float,
    max_seconds: float,
) -> tuple[float, float]:
    """Align clip boundaries to transcript segment edges so a sentence
    is never cut in half. A snap is applied only when the resulting
    duration stays within [min_seconds, max_seconds] and video bounds —
    otherwise the proposed boundary is kept (already validated)."""
    if not segments:
        return start, end

    def seg_start(s: dict) -> float:
        return float(s.get("start", 0.0))

    def seg_end(s: dict) -> float:
        return float(s.get("end", 0.0))

    new_start, new_end = start, end
    # Baslangic bir segmentin ortasindaysa o segmentin basina cek.
    for seg in segments:
        s0, s1 = seg_start(seg), seg_end(seg)
        if s0 < start < s1 and s0 >= 0:
            if end - s0 <= max_seconds and end - s0 >= min_seconds:
                new_start = s0
            break
    # Bitis bir segmentin ortasindaysa o segmentin sonuna cek.
    for seg in segments:
        s0, s1 = seg_start(seg), seg_end(seg)
        if s0 < end < s1 and s1 <= duration:
            if s1 - new_start <= max_seconds and s1 - new_start >= min_seconds:
                new_end = s1
            break
    return new_start, new_end


def validate_window(
    start: float,
    end: float,
    duration: float,
    *,
    min_seconds: float,
    max_seconds: float,
) -> tuple[float, float] | None:
    """Validate + clamp an LLM-proposed window. Returns None when the
    proposal cannot be repaired into a valid window."""
    if not (0 <= start < end) or end > duration + 0.5:
        return None
    start = max(0.0, start)
    end = min(end, duration)
    length = end - start
    if length <= 0:
        return None
    if length < min_seconds:
        end = min(duration, start + min_seconds)
        if end - start < min_seconds:
            start = max(0.0, end - min_seconds)
    elif length > max_seconds:
        # Gorev 3: hype aninin SONU korunur. Sure asil siniri asarsa
        # baslangic one cekilir; bitis (olayin dogal kapanisi) budanmaz.
        start = max(0.0, end - max_seconds)
    if not (0 <= start < end <= duration):
        return None
    return start, end


class HypeService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        llm: LlmProviderService,
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._llm = llm
        self._settings = settings

    async def evaluate_source(
        self,
        source_video_id: int,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Evaluate all pending candidates of one source video, refine
        their windows, select the top non-overlapping set and mark it
        'selected' for the render feed. Idempotent: a video with an
        existing selection is skipped."""
        from app.services.status_service import StatusService

        context = await self._load(source_video_id)
        if context is None:
            raise HypeError("Kaynak video bulunamadi veya islemesi bitmedi.")
        candidates = context["candidates"]
        if not candidates:
            # Cikarilacak aday yok: uretim tamamlandi sayilir.
            confirmed = await StatusService(
                self._sessionmaker, self._settings
            ).maybe_confirm_source(source_video_id)
            return {
                "source_video_id": source_video_id,
                "selected": 0,
                "confirmed": confirmed,
            }

        top_limit = max(1, self._settings.shorts_per_video)
        evaluations: dict[int, HypeEvaluationItem] = {}
        try:
            evaluations = await self._evaluate_with_llm(context, http=http)
            refined = self._apply_evaluations(context, evaluations)
            fallback = False
        except LlmServiceError as exc:
            logger.warning("hype LLM degerlendirmesi basarisiz: %s", exc)
            await self._audit_fallback(context["channel_id"], source_video_id, str(exc))
            refined = {c.id: (c.start_seconds, c.end_seconds) for c in candidates}
            fallback = True

        selected = self._select(context, refined, top_limit)
        await self._persist(
            source_video_id, context, refined, selected, evaluations, fallback
        )
        confirmed = await StatusService(
            self._sessionmaker, self._settings
        ).maybe_confirm_source(source_video_id)
        return {
            "source_video_id": source_video_id,
            "selected": len(selected),
            "fallback": fallback,
            "confirmed": confirmed,
        }

    # --- yukleme ---

    async def _load(self, source_video_id: int) -> dict | None:
        async with self._sessionmaker() as session:
            video = await session.get(SourceVideo, source_video_id)
            if video is None:
                return None
            source = await session.get(SourceChannel, video.source_channel_id)
            if source is None:
                return None
            asset = (
                (
                    await session.execute(
                        sa.select(MediaAsset).where(
                            MediaAsset.source_video_id == source_video_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if asset is None or asset.status != "processed":
                return None
            # Idempotency: secilmis aday varsa yeniden degerlendirme.
            selected_any = (
                (
                    await session.execute(
                        sa.select(sa.func.count())
                        .select_from(ClipCandidate)
                        .where(
                            ClipCandidate.source_video_id == source_video_id,
                            ClipCandidate.status == "selected",
                        )
                    )
                ).scalar()
                or 0
            ) > 0
            if selected_any:
                return None
            inspection = (
                (
                    await session.execute(
                        sa.select(MediaInspection).where(
                            MediaInspection.media_asset_id == asset.id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            segments = await self._segments_for(session, asset.id)
            candidates = list(
                (
                    await session.execute(
                        sa.select(ClipCandidate)
                        .where(
                            ClipCandidate.source_video_id == source_video_id,
                            ClipCandidate.status == "candidate",
                        )
                        .order_by(ClipCandidate.score.desc())
                    )
                )
                .scalars()
                .all()
            )
            profile = (
                (
                    await session.execute(
                        sa.select(PublishingProfile).where(
                            PublishingProfile.channel_id == source.channel_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            character_prompt = None
            if source.character_id is not None:
                character = await session.get(Character, source.character_id)
                if character is not None:
                    character_prompt = character.system_prompt
            channel_prompt = (
                profile.channel_system_prompt if profile is not None else None
            )

        return {
            "video": video,
            "source": source,
            "channel_id": source.channel_id,
            "duration": (
                inspection.duration_seconds if inspection is not None else 0.0
            ),
            "segments": segments,
            "analysis": asset.analysis or {},
            "candidates": candidates,
            "character_prompt": character_prompt,
            "channel_prompt": channel_prompt,
        }

    @staticmethod
    async def _segments_for(
        session: AsyncSession, media_asset_id: int
    ) -> list[dict]:
        corrected = (
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
        if corrected is not None:
            return list(corrected.segments)
        original = (
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
        return list(original.segments) if original is not None else []

    # --- LLM degerlendirmesi ---

    async def _system_prompt(self, context: dict) -> str:
        for prompt in (context["character_prompt"], context["channel_prompt"]):
            if prompt and prompt.strip():
                return prompt.strip()
        if self._settings.metadata_system_prompt.strip():
            return self._settings.metadata_system_prompt.strip()
        return DEFAULT_HYPE_SYSTEM_PROMPT

    def _candidate_block(self, context: dict, candidate: ClipCandidate) -> str:
        segments = context["segments"]
        start, end = candidate.start_seconds, candidate.end_seconds
        window_text = transcript_text_in_range(segments, start, end) or "(konuşma yok)"
        before = transcript_text_in_range(
            segments, max(0.0, start - CONTEXT_SECONDS), start
        )
        after = transcript_text_in_range(
            segments,
            end,
            min(context["duration"], end + CONTEXT_SECONDS),
        )
        energy = _energy_stats(
            list(context["analysis"].get("energy_windows", [])), start, end
        )
        lines = [
            f"aday {candidate.id}: {start:.1f}-{end:.1f} sn "
            f"(sure {end - start:.1f})",
            f"  ses analizi: ortalama RMS {energy['mean']}, tepe {energy['max']}, "
            f"ani yukselis {energy['spikes']}",
        ]
        if before:
            lines.append(f"  onceki baglam: {before[:400]}")
        lines.append(f"  transkript: {window_text[:1200]}")
        if after:
            lines.append(f"  sonraki baglam: {after[:400]}")
        return "\n".join(lines)

    async def _evaluate_with_llm(
        self, context: dict, *, http: httpx.AsyncClient | None
    ) -> dict[int, HypeEvaluationItem]:
        prompt = PROMPT_TEMPLATE.format(
            duration=context["duration"],
            min_seconds=self._settings.clip_min_seconds,
            max_seconds=self._settings.clip_max_seconds,
            candidates="\n\n".join(
                self._candidate_block(context, c) for c in context["candidates"]
            ),
        )
        result = await self._llm.complete(
            prompt,
            schema=HypeEvaluationResponse,
            http=http,
            system_prompt=await self._system_prompt(context),
        )
        response = HypeEvaluationResponse.model_validate(result.structured)
        by_id = {item.candidate_id: item for item in response.evaluations}
        return {
            c.id: by_id[c.id]
            for c in context["candidates"]
            if c.id in by_id
        }

    def _apply_evaluations(
        self, context: dict, evaluations: dict[int, HypeEvaluationItem]
    ) -> dict[int, tuple[float, float]]:
        """Validate every LLM window; invalid ones keep the original
        code-scored window. Valid ones additionally snap to sentence
        boundaries."""
        refined: dict[int, tuple[float, float]] = {}
        for candidate in context["candidates"]:
            item = evaluations.get(candidate.id)
            fallback_window = (candidate.start_seconds, candidate.end_seconds)
            if item is None:
                refined[candidate.id] = fallback_window
                continue
            window = validate_window(
                item.start_seconds,
                item.end_seconds,
                context["duration"],
                min_seconds=self._settings.clip_min_seconds,
                max_seconds=self._settings.clip_max_seconds,
            )
            if window is None:
                refined[candidate.id] = fallback_window
                continue
            refined[candidate.id] = snap_to_segments(
                window[0],
                window[1],
                context["segments"],
                duration=context["duration"],
                min_seconds=self._settings.clip_min_seconds,
                max_seconds=self._settings.clip_max_seconds,
            )
        return refined

    @staticmethod
    def _select(
        context: dict,
        refined: dict[int, tuple[float, float]],
        top_limit: int,
    ) -> list[int]:
        """Top non-overlapping candidates by score; overlapping rest stay
        unselected so the same moment is not re-cut repeatedly."""
        ordered = sorted(
            context["candidates"], key=lambda c: c.score, reverse=True
        )
        chosen: list[int] = []
        ranges: list[tuple[float, float]] = []
        for candidate in ordered:
            start, end = refined.get(
                candidate.id, (candidate.start_seconds, candidate.end_seconds)
            )
            if any(start < e and end > s for s, e in ranges):
                continue
            chosen.append(candidate.id)
            ranges.append((start, end))
            if len(chosen) >= top_limit:
                break
        return chosen

    # --- kaliclilik ---

    async def _persist(
        self,
        source_video_id: int,
        context: dict,
        refined: dict[int, tuple[float, float]],
        selected: list[int],
        evaluations: dict[int, HypeEvaluationItem],
        fallback: bool,
    ) -> None:
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        sa.select(ClipCandidate).where(
                            ClipCandidate.source_video_id == source_video_id,
                            ClipCandidate.status == "candidate",
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                detail = dict(row.detail or {})
                hype: dict[str, Any] = {"fallback": fallback}
                if row.id in selected:
                    start, end = refined.get(
                        row.id, (row.start_seconds, row.end_seconds)
                    )
                    row.start_seconds = start
                    row.end_seconds = end
                    row.duration_seconds = end - start
                    row.status = "selected"
                    item = evaluations.get(row.id)
                    if item is not None:
                        hype.update(
                            {
                                "confidence": item.confidence,
                                "reason": item.reason,
                            }
                        )
                    hype["refined"] = not fallback
                detail["hype"] = hype
                row.detail = detail
            record_event(
                session,
                context["channel_id"],
                "hype.evaluated",
                {
                    "source_video_id": source_video_id,
                    "selected": len(selected),
                    "fallback": fallback,
                },
            )
            await session.commit()

    async def _audit_fallback(
        self, channel_id: int, source_video_id: int, reason: str
    ) -> None:
        async with self._sessionmaker() as session:
            record_event(
                session,
                channel_id,
                "hype.fallback",
                {"source_video_id": source_video_id, "reason": reason[:300]},
            )
            await session.commit()
