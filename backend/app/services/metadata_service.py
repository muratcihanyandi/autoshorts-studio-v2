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
    """LLM sözleşmesi: kısa başlık, kanca, özet, etiketler, kapak metni
    ve içerik bildirimi kararları (auto modunda)."""

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    summary: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    hook: str = Field("", max_length=MAX_HOOK_CHARS)
    thumbnail_text: str = Field("", max_length=MAX_THUMBNAIL_TEXT_CHARS)
    # Iki bildirim BIRBIRINDEN BAGIMSIZ kararlar: yapay zekâ ile
    # duzenlenmis olmak tek basina +18 demek degil.
    content_warning: bool = Field(default=False)
    ai_disclosure: bool = Field(default=False)


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
    "- content_warning: icerik yetiskinlere uygun degilse true (siddet, "
    "acik konusma veya benzeri yogunsa); belirsizse false\n"
    "- ai_disclosure: icerik anlamli bicimde yapay zeka ile uretilmis "
    "veya degistirilmisse true (sentetik ses/goruntu); altyazi "
    "duzeltmesi veya montaj tek basina true yapmak icin yeterli DEGIL; "
    "belirsizse false\n"
    "Icerikte olmayan bilgi, yanlis iddia veya clickbait URETME; iki "
    "bildirim karari birbirinden bagimsizdir.\n"
    'Yaniti SADECE su JSON biciminde ver: {{"title": "...", "summary": '
    '"...", "tags": ["..."], "hook": "...", "thumbnail_text": "...", '
    '"content_warning": false, "ai_disclosure": false}}\n\n'
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


def fallback_title(video_title: str) -> str:
    """Deterministic title for channels with title generation off."""
    base = (video_title or "").strip() or "Kisa video"
    if len(base) < MIN_TITLE_CHARS:
        base = f"{base} - kisa video"
    return base[:MAX_TITLE_CHARS]


def fallback_description(video_title: str, transcript_text: str) -> str:
    """Deterministic description for channels with generation off."""
    text = (transcript_text or "").strip()
    if len(text) >= MIN_DESCRIPTION_CHARS:
        return text[:300]
    base = f"Bu kisa video '{video_title or 'kaynak'}' kaynagindan kesilmistir."
    return base[:MAX_DESCRIPTION_CHARS]


def resolve_notification(mode: str, llm_value: bool) -> bool:
    """auto/on/off karar: 'on' dogrudan acik, 'off' dogrudan kapali,
    'auto' LLM karari (LLM cagrisi yoksa guvenli varsayilan false)."""
    if mode == "on":
        return True
    if mode == "off":
        return False
    return bool(llm_value)


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
        """Prompt zinciri: karakter -> kanal -> global (efektif) -> yerlesik."""
        character_prompt = (context.get("character_system_prompt") or "").strip()
        if character_prompt:
            return character_prompt
        channel_prompt = (context.get("channel_system_prompt") or "").strip()
        if channel_prompt:
            return channel_prompt
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

    def _modes(self, context: dict) -> dict[str, str]:
        """Kanal ayarlarindaki auto/on/off modlari (varsayilan 'auto')."""
        modes = context.get("modes") or {}
        return {
            key: modes.get(key, "auto")
            for key in (
                "title_mode",
                "description_mode",
                "tags_mode",
                "content_warning_mode",
                "ai_disclosure_mode",
            )
        }

    def _compose(
        self, proposal: MetadataProposal | None, context: dict
    ) -> dict:
        """Modlara gore nihai metaveri: 'off' alanlari deterministik
        degere duser, bildirimler auto/on/off kararindan gecer."""
        modes = self._modes(context)
        if modes["title_mode"] == "off" or proposal is None:
            title_raw = fallback_title(context["video_title"])
        else:
            title_raw = proposal.title
        if modes["description_mode"] == "off" or proposal is None:
            summary_raw = fallback_description(
                context["video_title"], context["transcript"]
            )
        else:
            summary_raw = proposal.summary
        if modes["tags_mode"] == "off" or proposal is None:
            proposed_tags: list[str] = []
        else:
            proposed_tags = list(proposal.tags)

        title = apply_pattern(
            context["title_pattern"],
            {"title": title_raw, "channel": context["channel_name"]},
        )
        description = apply_pattern(
            context["description_pattern"],
            {"summary": summary_raw, "channel": context["channel_name"]},
        )
        tags = dedupe_tags(list(context["base_tags"]) + proposed_tags)
        content_warning = resolve_notification(
            modes["content_warning_mode"],
            proposal.content_warning if proposal is not None else False,
        )
        ai_disclosure = resolve_notification(
            modes["ai_disclosure_mode"],
            proposal.ai_disclosure if proposal is not None else False,
        )
        hook = proposal.hook if proposal is not None else ""
        thumbnail_text = proposal.thumbnail_text if proposal is not None else ""
        problems = validate_metadata(
            title,
            description,
            tags,
            hook=hook,
            thumbnail_text=thumbnail_text,
        )
        return {
            "title": title,
            "description": description,
            "tags": tags,
            "content_warning": content_warning,
            "ai_disclosure": ai_disclosure,
            "hook": hook,
            "thumbnail_text": thumbnail_text,
            "problems": problems,
        }

    def _llm_needed(self, modes: dict[str, str]) -> bool:
        return any(
            (
                modes["title_mode"] != "off",
                modes["description_mode"] != "off",
                modes["tags_mode"] != "off",
                modes["content_warning_mode"] == "auto",
                modes["ai_disclosure_mode"] == "auto",
            )
        )

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
        modes = self._modes(context)
        proposal: MetadataProposal | None = None
        provider_name = ""
        if self._llm_needed(modes):
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
            provider_name = result.provider_name

        composed = self._compose(proposal, context)
        if composed["problems"]:
            raise MetadataError(
                "Metaveri gecersiz: " + "; ".join(composed["problems"])
            )

        revision = (existing.revision + 1) if existing else 1
        async with self._sessionmaker() as session:
            session.add(
                ClipMetadata(
                    clip_candidate_id=clip_candidate_id,
                    revision=revision,
                    title=composed["title"],
                    description=composed["description"],
                    tags=composed["tags"],
                    hook=composed["hook"],
                    thumbnail_text=composed["thumbnail_text"],
                    content_warning=composed["content_warning"],
                    ai_disclosure=composed["ai_disclosure"],
                    provider_name=provider_name,
                )
            )
            record_event(
                session,
                context["channel_id"],
                "metadata.generated",
                {
                    "clip_candidate_id": clip_candidate_id,
                    "revision": revision,
                    "provider": provider_name,
                },
            )
            await session.commit()
        return {
            "clip_candidate_id": clip_candidate_id,
            "revision": revision,
            "title": composed["title"],
            "tags": len(composed["tags"]),
            "content_warning": composed["content_warning"],
            "ai_disclosure": composed["ai_disclosure"],
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
        modes = self._modes(context)
        proposal: MetadataProposal | None = None
        provider_name = ""
        if self._llm_needed(modes):
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
            provider_name = result.provider_name

        composed = self._compose(proposal, context)
        if composed["problems"]:
            raise MetadataError(
                "Metaveri gecersiz: " + "; ".join(composed["problems"])
            )

        revision = (existing.revision + 1) if existing else 1
        async with self._sessionmaker() as session:
            session.add(
                ClipMetadata(
                    clip_candidate_id=None,
                    source_video_id=source_video_id,
                    revision=revision,
                    title=composed["title"],
                    description=composed["description"],
                    tags=composed["tags"],
                    hook=composed["hook"],
                    thumbnail_text=composed["thumbnail_text"],
                    content_warning=composed["content_warning"],
                    ai_disclosure=composed["ai_disclosure"],
                    provider_name=provider_name,
                )
            )
            record_event(
                session,
                context["channel_id"],
                "metadata.generated",
                {
                    "source_video_id": source_video_id,
                    "revision": revision,
                    "provider": provider_name,
                    "orientation": "horizontal",
                },
            )
            await session.commit()
        return {
            "source_video_id": source_video_id,
            "revision": revision,
            "title": composed["title"],
            "tags": len(composed["tags"]),
            "content_warning": composed["content_warning"],
            "ai_disclosure": composed["ai_disclosure"],
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
    async def _profile_modes(
        session: AsyncSession, channel_id: int
    ) -> tuple[dict[str, str], str | None]:
        """Kanalin auto/on/off modlari ve kanal sistem promptu."""
        from app.models import PublishingProfile

        profile = (
            (
                await session.execute(
                    sa.select(PublishingProfile).where(
                        PublishingProfile.channel_id == channel_id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if profile is None:
            return {}, None
        return (
            {
                "title_mode": profile.title_mode,
                "description_mode": profile.description_mode,
                "tags_mode": profile.tags_mode,
                "content_warning_mode": profile.content_warning_mode,
                "ai_disclosure_mode": profile.ai_disclosure_mode,
            },
            profile.channel_system_prompt,
        )

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
        modes, channel_prompt = await MetadataService._profile_modes(
            session, channel.id
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
            "channel_system_prompt": channel_prompt,
            "modes": modes,
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
        modes, channel_prompt = await MetadataService._profile_modes(
            session, channel.id
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
            "channel_system_prompt": channel_prompt,
            "modes": modes,
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
