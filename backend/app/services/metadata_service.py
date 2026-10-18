"""Clip metadata generation and channel templates (M9, M13).

The LLM proposes a short title, a hook, a summary, thumbnail text, and
tags from the clip's transcript window; the channel template patterns
shape the final metadata. Validation enforces YouTube limits (title <=
100, description <= 5000, tags <= 30 x 50 chars, hook <= 120,
thumbnail_text <= 80) — invalid output is rejected, never stored.
Revisions are append-only per clip candidate.

M13: the LLM system prompt resolves character.system_prompt (via the
candidate's source channel) -> settings.metadata_system_prompt
(effective settings, DB overrides env) -> built-in default. Horizontal
full cuts (candidate NULL, source_video set) carry their own
revision chain, one per source video (code-guarded).
"""
from __future__ import annotations

import re

import httpx
import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Channel,
    Character,
    ClipCandidate,
    ClipMetadata,
    CorrectedTranscript,
    MediaAsset,
    MetadataTemplate,
    SourceChannel,
    SourceVideo,
    Transcript,
)
from app.services.channel_service import record_event
from app.services.llm_service import LlmProviderService, LlmServiceError
from app.services.media_transcript import transcript_text_in_range

MAX_TITLE_CHARS = 100
MAX_DESCRIPTION_CHARS = 5000
MAX_TAGS = 30
MAX_TAG_CHARS = 50
MIN_TITLE_CHARS = 5
MIN_DESCRIPTION_CHARS = 20
MAX_HOOK_CHARS = 120
MAX_THUMBNAIL_TEXT_CHARS = 80

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

DEFAULT_TITLE_PATTERN = "{title}"
DEFAULT_DESCRIPTION_PATTERN = "{summary}"

# Yerlesik varsayilan sistem promptu (M13 zincirinin son halkasi).
DEFAULT_SYSTEM_PROMPT = (
    "Sen bir YouTube Shorts metaveri uzmanisin. Gorevin, verilen "
    "transkriptten viral olabilecek short-form icerik metaverisi "
    "uretmek.\n"
    "- Basliklar kisa, merak uyandiran ve Turkce olmali; buyuk harf "
    "bombardimi ve abartili iddialar YASAK.\n"
    "- Hook, videonun ilk 3 saniyesinde izleyiciyi tutacak bicimde "
    "yazilmali.\n"
    "- Etiketler SEO odakli ve icerikle ilgili olmali; alakasiz etiket "
    "EKLEME.\n"
    "- Icerikte olmayan bilgi, yanlis iddia veya clickbait URETME; "
    "sadelik ve dogruluk onceliklidir."
)


class MetadataError(Exception):
    """Metadata failure with a user-facing Turkish message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class MetadataProposal(BaseModel):
    """LLM sözleşmesi: kısa başlık, kanca, özet, etiketler, kapak metni."""

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    summary: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    hook: str = Field(default="", max_length=MAX_HOOK_CHARS)
    thumbnail_text: str = Field(default="", max_length=MAX_THUMBNAIL_TEXT_CHARS)


PROMPT = (
    "Asagida {kind} transkript bolumu ve kaynak video basligi var.\n"
    "Buna gore YouTube icin metaveri oner:\n"
    "- title: en fazla 90 karakter, dikkat cekici, Turkce, buyuk harf "
    "bombardimi YOK\n"
    "- summary: 2-4 cumlelik aciklama\n"
    "- tags: en fazla 8 etiket, her biri tek kelime veya kisa ifade\n"
    "- hook: ilk 3 saniyede izleyiciyi yakalayan kanca metni, en fazla "
    "120 karakter\n"
    "- thumbnail_text: kapak goruntusune yazilacak kisa vurucu metin, "
    "en fazla 80 karakter\n"
    'Yaniti SADECE su JSON biciminde ver: {{"title": "...", "summary": '
    '"...", "tags": ["..."], "hook": "...", "thumbnail_text": "..."}}\n\n'
    "Kaynak baslik: {video_title}\n\nTranskript:\n{transcript}"
)


def validate_metadata(
    title: str,
    description: str,
    tags: list[str],
    hook: str = "",
    thumbnail_text: str = "",
) -> list[str]:
    """Return a list of Turkish problems; empty means valid."""
    problems: list[str] = []
    if not (MIN_TITLE_CHARS <= len(title) <= MAX_TITLE_CHARS):
        problems.append(
            f"baslik {len(title)} karakter; {MIN_TITLE_CHARS}-{MAX_TITLE_CHARS} arasi olmali"
        )
    if not (MIN_DESCRIPTION_CHARS <= len(description) <= MAX_DESCRIPTION_CHARS):
        problems.append(
            f"aciklama {len(description)} karakter; "
            f"{MIN_DESCRIPTION_CHARS}-{MAX_DESCRIPTION_CHARS} arasi olmali"
        )
    if len(tags) > MAX_TAGS:
        problems.append(f"en fazla {MAX_TAGS} etiket")
    for tag in tags:
        if not tag or len(tag) > MAX_TAG_CHARS:
            problems.append(f"gecersiz etiket: {tag!r}")
    if len(hook) > MAX_HOOK_CHARS:
        problems.append(
            f"hook {len(hook)} karakter; en fazla {MAX_HOOK_CHARS} olmali"
        )
    if len(thumbnail_text) > MAX_THUMBNAIL_TEXT_CHARS:
        problems.append(
            f"thumbnail_text {len(thumbnail_text)} karakter; en fazla "
            f"{MAX_THUMBNAIL_TEXT_CHARS} olmali"
        )
    return problems


def apply_pattern(pattern: str, values: dict[str, str]) -> str:
    """Replace known {placeholders}; unknown ones stay literal."""

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    return _PLACEHOLDER.sub(_sub, pattern)


class MetadataService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        llm: LlmProviderService,
        settings: Settings | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._llm = llm
        # None: yalnizca sablon islemleri yapan cagiricilar icin (eski
        # davranis); genel prompt zinciri o zaman yerlesik varsayilana
        # duser (karakter promptu yine gecerlidir).
        self._settings = settings

    # --- sablonlar ---

    async def get_template(self, channel_id: int) -> MetadataTemplate:
        async with self._sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        sa.select(MetadataTemplate).where(
                            MetadataTemplate.channel_id == channel_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if row is None:
                row = MetadataTemplate(channel_id=channel_id)
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return row

    async def set_template(
        self,
        channel_id: int,
        *,
        title_pattern: str | None = None,
        description_pattern: str | None = None,
        base_tags: list[str] | None = None,
    ) -> MetadataTemplate:
        if title_pattern is not None and "{title}" not in title_pattern:
            raise MetadataError("Baslik sablonu {title} icermeli.")
        if (
            description_pattern is not None
            and "{summary}" not in description_pattern
        ):
            raise MetadataError("Aciklama sablonu {summary} icermeli.")
        if base_tags is not None and len(base_tags) > MAX_TAGS:
            raise MetadataError(f"En fazla {MAX_TAGS} sablon etiketi.")
        template = await self.get_template(channel_id)
        async with self._sessionmaker() as session:
            row = await session.get(MetadataTemplate, template.id)
            if title_pattern is not None:
                row.title_pattern = title_pattern
            if description_pattern is not None:
                row.description_pattern = description_pattern
            if base_tags is not None:
                row.base_tags = base_tags
            await session.commit()
            await session.refresh(row)
            return row

    # --- uretim ---

    async def _system_prompt(self, context: dict) -> str:
        """M13 zinciri: karakter -> global (efektif) -> yerlesik."""
        character_prompt = (context.get("character_system_prompt") or "").strip()
        if character_prompt:
            return character_prompt
        if self._settings is not None:
            from app.services.settings_service import SettingsService

            effective = await SettingsService(
                self._sessionmaker, self._settings
            ).effective_settings()
            global_prompt = (
                effective.metadata_system_prompt or ""
            ).strip()
            if global_prompt:
                return global_prompt
        return DEFAULT_SYSTEM_PROMPT

    async def generate(
        self,
        clip_candidate_id: int,
        *,
        regenerate: bool = False,
        http: httpx.AsyncClient | None = None,
    ) -> dict:
        async with self._sessionmaker() as session:
            candidate = await session.get(ClipCandidate, clip_candidate_id)
            if candidate is None:
                raise MetadataError("Klip adayi bulunamadi.")
            existing = (
                (
                    await session.execute(
                        sa.select(ClipMetadata)
                        .where(
                            ClipMetadata.clip_candidate_id == clip_candidate_id
                        )
                        .order_by(ClipMetadata.revision.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .one_or_none()
            )
            if existing is not None and not regenerate:
                return {"clip_candidate_id": clip_candidate_id, "skipped": True}
            context = await self._context(session, candidate)

        system_prompt = await self._system_prompt(context)
        prompt = PROMPT.format(
            kind="bir kisa videonun",
            video_title=context["video_title"],
            transcript=context["transcript"],
        )
        try:
            result = await self._llm.complete(
                prompt,
                schema=MetadataProposal,
                http=http,
                system_prompt=system_prompt,
            )
        except LlmServiceError as exc:
            raise MetadataError(str(exc)) from exc
        proposal = MetadataProposal.model_validate(result.structured)

        title = apply_pattern(
            context["title_pattern"],
            {"title": proposal.title, "channel": context["channel_name"]},
        )
        description = apply_pattern(
            context["description_pattern"],
            {"summary": proposal.summary, "channel": context["channel_name"]},
        )
        tags = dedupe_tags(list(context["base_tags"]) + list(proposal.tags))

        problems = validate_metadata(
            title,
            description,
            tags,
            hook=proposal.hook,
            thumbnail_text=proposal.thumbnail_text,
        )
        if problems:
            raise MetadataError(
                "Metaveri gecersiz: " + "; ".join(problems)
            )

        revision = (existing.revision + 1) if existing else 1
        async with self._sessionmaker() as session:
            session.add(
                ClipMetadata(
                    clip_candidate_id=clip_candidate_id,
                    revision=revision,
                    title=title,
                    description=description,
                    tags=tags,
                    hook=proposal.hook,
                    thumbnail_text=proposal.thumbnail_text,
                    provider_name=result.provider_name,
                )
            )
            record_event(
                session,
                context["channel_id"],
                "metadata.generated",
                {
                    "clip_candidate_id": clip_candidate_id,
                    "revision": revision,
                    "provider": result.provider_name,
                },
            )
            await session.commit()
        return {
            "clip_candidate_id": clip_candidate_id,
            "revision": revision,
            "title": title,
            "tags": len(tags),
        }

    async def generate_full_cut(
        self,
        source_video_id: int,
        *,
        regenerate: bool = False,
        http: httpx.AsyncClient | None = None,
    ) -> dict:
        """Yatay tam kesit metaverisi (M13): aday NULL, video dolu.

        Revizyon zinciri kaynak basina tektir (kod guvenligi); yalnizca
        reaksiyon kaynaklarinda uretilir.
        """
        async with self._sessionmaker() as session:
            video = await session.get(SourceVideo, source_video_id)
            if video is None:
                raise MetadataError("Kaynak video bulunamadi.")
            source = await session.get(
                SourceChannel, video.source_channel_id
            )
            if source is None:
                raise MetadataError("Kaynak kanal bulunamadi.")
            if not source.reaction_source:
                raise MetadataError(
                    "Yatay tam kesit metaverisi yalnizca reaksiyon "
                    "kaynaklarinda uretilir."
                )
            existing = (
                (
                    await session.execute(
                        sa.select(ClipMetadata)
                        .where(
                            ClipMetadata.source_video_id == source_video_id,
                            ClipMetadata.clip_candidate_id.is_(None),
                        )
                        .order_by(ClipMetadata.revision.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .one_or_none()
            )
            if existing is not None and not regenerate:
                return {"source_video_id": source_video_id, "skipped": True}
            context = await self._full_cut_context(session, video, source)

        system_prompt = await self._system_prompt(context)
        prompt = PROMPT.format(
            kind="bir reaksiyon videosunun tam kesitinin",
            video_title=context["video_title"],
            transcript=context["transcript"],
        )
        try:
            result = await self._llm.complete(
                prompt,
                schema=MetadataProposal,
                http=http,
                system_prompt=system_prompt,
            )
        except LlmServiceError as exc:
            raise MetadataError(str(exc)) from exc
        proposal = MetadataProposal.model_validate(result.structured)

        title = apply_pattern(
            context["title_pattern"],
            {"title": proposal.title, "channel": context["channel_name"]},
        )
        description = apply_pattern(
            context["description_pattern"],
            {"summary": proposal.summary, "channel": context["channel_name"]},
        )
        tags = dedupe_tags(list(context["base_tags"]) + list(proposal.tags))

        problems = validate_metadata(
            title,
            description,
            tags,
            hook=proposal.hook,
            thumbnail_text=proposal.thumbnail_text,
        )
        if problems:
            raise MetadataError(
                "Metaveri gecersiz: " + "; ".join(problems)
            )

        revision = (existing.revision + 1) if existing else 1
        async with self._sessionmaker() as session:
            session.add(
                ClipMetadata(
                    clip_candidate_id=None,
                    source_video_id=source_video_id,
                    revision=revision,
                    title=title,
                    description=description,
                    tags=tags,
                    hook=proposal.hook,
                    thumbnail_text=proposal.thumbnail_text,
                    provider_name=result.provider_name,
                )
            )
            record_event(
                session,
                context["channel_id"],
                "metadata.generated",
                {
                    "source_video_id": source_video_id,
                    "revision": revision,
                    "provider": result.provider_name,
                    "orientation": "horizontal",
                },
            )
            await session.commit()
        return {
            "source_video_id": source_video_id,
            "revision": revision,
            "title": title,
            "tags": len(tags),
        }

    async def latest(self, clip_candidate_id: int) -> ClipMetadata | None:
        async with self._sessionmaker() as session:
            return (
                (
                    await session.execute(
                        sa.select(ClipMetadata)
                        .where(
                            ClipMetadata.clip_candidate_id == clip_candidate_id
                        )
                        .order_by(ClipMetadata.revision.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .one_or_none()
            )

    # --- yardimcilar ---

    @staticmethod
    async def _character_system_prompt(
        session: AsyncSession, source: SourceChannel
    ) -> str | None:
        """Kaynaga bagli karakterin sistem promptu (yoksa None)."""
        if source.character_id is None:
            return None
        character = await session.get(Character, source.character_id)
        if character is None or not character.system_prompt:
            return None
        return character.system_prompt.strip()

    @staticmethod
    async def _context(session: AsyncSession, candidate: ClipCandidate) -> dict:
        video = await session.get(SourceVideo, candidate.source_video_id)
        source = await session.get(SourceChannel, video.source_channel_id)
        channel = await session.get(Channel, source.channel_id)
        asset = (
            (
                await session.execute(
                    sa.select(MediaAsset).where(
                        MediaAsset.source_video_id == video.id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        segments: list[dict] = []
        if asset is not None:
            corrected = (
                (
                    await session.execute(
                        sa.select(CorrectedTranscript).where(
                            CorrectedTranscript.media_asset_id == asset.id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if corrected is not None:
                segments = corrected.segments
            else:
                original = (
                    (
                        await session.execute(
                            sa.select(Transcript).where(
                                Transcript.media_asset_id == asset.id
                            )
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
                if original is not None:
                    segments = original.segments
        window_text = transcript_text_in_range(
            segments, candidate.start_seconds, candidate.end_seconds
        )
        template = (
            (
                await session.execute(
                    sa.select(MetadataTemplate).where(
                        MetadataTemplate.channel_id == channel.id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        return {
            "video_title": video.title,
            "channel_name": channel.name,
            "channel_id": channel.id,
            "transcript": window_text or "(transkript yok)",
            "title_pattern": (
                template.title_pattern if template else DEFAULT_TITLE_PATTERN
            ),
            "description_pattern": (
                template.description_pattern
                if template
                else DEFAULT_DESCRIPTION_PATTERN
            ),
            "base_tags": list(template.base_tags) if template else [],
            "character_system_prompt": await MetadataService._character_system_prompt(
                session, source
            ),
        }

    @staticmethod
    async def _full_cut_context(
        session: AsyncSession, video: SourceVideo, source: SourceChannel
    ) -> dict:
        """Yatay tam kesit baglami: videonun TAM transkripti."""
        channel = await session.get(Channel, source.channel_id)
        asset = (
            (
                await session.execute(
                    sa.select(MediaAsset).where(
                        MediaAsset.source_video_id == video.id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        segments: list[dict] = []
        if asset is not None:
            corrected = (
                (
                    await session.execute(
                        sa.select(CorrectedTranscript).where(
                            CorrectedTranscript.media_asset_id == asset.id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if corrected is not None:
                segments = corrected.segments
            else:
                original = (
                    (
                        await session.execute(
                            sa.select(Transcript).where(
                                Transcript.media_asset_id == asset.id
                            )
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
                if original is not None:
                    segments = original.segments
        full_text = " ".join(
            str(seg.get("text", "")) for seg in segments
        ).strip()
        template = (
            (
                await session.execute(
                    sa.select(MetadataTemplate).where(
                        MetadataTemplate.channel_id == channel.id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        return {
            "video_title": video.title,
            "channel_name": channel.name,
            "channel_id": channel.id,
            "transcript": full_text or "(transkript yok)",
            "title_pattern": (
                template.title_pattern if template else DEFAULT_TITLE_PATTERN
            ),
            "description_pattern": (
                template.description_pattern
                if template
                else DEFAULT_DESCRIPTION_PATTERN
            ),
            "base_tags": list(template.base_tags) if template else [],
            "character_system_prompt": await MetadataService._character_system_prompt(
                session, source
            ),
        }


def dedupe_tags(tags: list[str]) -> list[str]:
    """Order-preserving dedupe + trim + empty drop."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        cleaned = tag.strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            result.append(cleaned)
    return result[:MAX_TAGS]
