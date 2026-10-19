"""Central status/tag service: the single source of the operator-facing
job-state vocabulary.

The tags (#queued, #downloading, #processing, #done, #confirmed,
#shorts, #error) are never just UI labels — every tag is computed from
persistent, verifiable database state (source videos, media assets,
jobs, rendered clips) through this service, and the #confirmed terminal
transition happens only here so a source can never carry two
contradictory active states.

Expected flow for a horizontal source:

    #queued -> #downloading -> #processing -> #done -> #confirmed

- #done: the horizontal video completed the required analysis stages
  and is ready in the horizontal stock (kept, file preserved).
- #confirmed: Shorts extraction for this source is complete; it is
  never re-queued for analysis or Shorts production again.

#shorts marks a produced vertical clip that is ready in the Shorts
stock (no fixed upper limit, no auto-deletion).
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Channel,
    ChannelCharacter,
    ClipCandidate,
    Job,
    MediaAsset,
    PublishedVideo,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.channel_service import record_event
from app.services.source_orientation import produces_full_cut

TAG_QUEUED = "#queued"
TAG_DOWNLOADING = "#downloading"
TAG_PROCESSING = "#processing"
TAG_DONE = "#done"
TAG_CONFIRMED = "#confirmed"
TAG_SHORTS = "#shorts"
TAG_ERROR = "#error"

# Is turleri -> kanal eslemesi icin payload anahtarlari.
_VIDEO_PAYLOAD_KEYS = ("source_video_id",)
_CANDIDATE_PAYLOAD_KEYS = ("clip_candidate_id",)
_ASSET_PAYLOAD_KEYS = ("media_asset_id",)

# Motor aktivitesi anahtarlari (arayuz Turkce etiketi kendisi cevirir).
ACTIVITY_IDLE = "idle"
ACTIVITY_DISCOVERING = "discovering"
ACTIVITY_DOWNLOADING = "downloading"
ACTIVITY_TRANSCRIBING = "transcribing"
ACTIVITY_ANALYZING = "analyzing"
ACTIVITY_RENDERING = "rendering"
ACTIVITY_STOCK_READY = "stock_ready"
ACTIVITY_STOPPED = "stopped"


class StatusService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    # --- stok sayilari ---

    async def horizontal_stock_level(self, channel_id: int) -> int:
        """Ready horizontal stock: sources whose pipeline finished
        (#done) but whose Shorts production is not complete yet (not
        #confirmed). This is the number the stock target compares
        against; it shrinks as sources become #confirmed."""
        async with self._sessionmaker() as session:
            return int(
                (
                    await session.execute(
                        sa.select(sa.func.count())
                        .select_from(SourceVideo)
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        )
                        .join(MediaAsset, MediaAsset.source_video_id == SourceVideo.id)
                        .where(
                            SourceChannel.channel_id == channel_id,
                            SourceVideo.status == "processed",
                            MediaAsset.status == "processed",
                        )
                    )
                ).scalar()
                or 0
            )

    async def queued_horizontal_count(self, channel_id: int) -> int:
        """Horizontal videos waiting for their turn: planned sources
        without a finished (or in-flight beyond the queue) pipeline."""
        async with self._sessionmaker() as session:
            return int(
                (
                    await session.execute(
                        sa.select(sa.func.count())
                        .select_from(SourceVideo)
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        )
                        .outerjoin(
                            MediaAsset, MediaAsset.source_video_id == SourceVideo.id
                        )
                        .where(
                            SourceChannel.channel_id == channel_id,
                            SourceVideo.status == "planned",
                            sa.or_(
                                MediaAsset.id.is_(None),
                                MediaAsset.status == "failed",
                            ),
                        )
                    )
                ).scalar()
                or 0
            )

    async def shorts_count(self, channel_id: int) -> int:
        """Ready Shorts in the local stock (rendered vertical clips)."""
        return await self._rendered_count(channel_id, "vertical")

    async def full_cut_count(self, channel_id: int) -> int:
        return await self._rendered_count(channel_id, "horizontal")

    async def ready_clip_stock(self, channel_id: int) -> int:
        """Hazır video stoğu (Görev 2): render edilmiş ama henüz yüklenmemiş
        (PublishedVideo satırı olmayan) dikey shortlar + yatay tam kesitler.
        Üretim kapısı bu sayıya bakar — hedefe ulaşınca yeni kaynak
        indirilmez, videolar paylaşıldıkça stok azalır ve üretim sürer."""
        async with self._sessionmaker() as session:
            vertical = int(
                (
                    await session.execute(
                        sa.select(sa.func.count())
                        .select_from(ClipCandidate)
                        .join(
                            SourceVideo,
                            ClipCandidate.source_video_id == SourceVideo.id,
                        )
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        )
                        .join(
                            RenderedClip,
                            RenderedClip.clip_candidate_id == ClipCandidate.id,
                        )
                        .outerjoin(
                            PublishedVideo,
                            PublishedVideo.clip_candidate_id == ClipCandidate.id,
                        )
                        .where(
                            SourceChannel.channel_id == channel_id,
                            SourceChannel.permission_status == "authorized",
                            RenderedClip.status == "rendered",
                            RenderedClip.orientation == "vertical",
                            PublishedVideo.id.is_(None),
                        )
                    )
                ).scalar()
                or 0
            )
            horizontal = int(
                (
                    await session.execute(
                        sa.select(sa.func.count())
                        .select_from(RenderedClip)
                        .join(
                            SourceVideo,
                            RenderedClip.source_video_id == SourceVideo.id,
                        )
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        )
                        .outerjoin(
                            PublishedVideo,
                            sa.and_(
                                PublishedVideo.source_video_id == SourceVideo.id,
                                PublishedVideo.clip_candidate_id.is_(None),
                                PublishedVideo.orientation == "horizontal",
                            ),
                        )
                        .where(
                            SourceChannel.channel_id == channel_id,
                            SourceChannel.permission_status == "authorized",
                            RenderedClip.clip_candidate_id.is_(None),
                            RenderedClip.orientation == "horizontal",
                            RenderedClip.status == "rendered",
                            PublishedVideo.id.is_(None),
                        )
                    )
                ).scalar()
                or 0
            )
        return vertical + horizontal

    async def _rendered_count(self, channel_id: int, orientation: str) -> int:
        async with self._sessionmaker() as session:
            return int(
                (
                    await session.execute(
                        sa.select(sa.func.count())
                        .select_from(RenderedClip)
                        .join(
                            ClipCandidate,
                            RenderedClip.clip_candidate_id == ClipCandidate.id,
                        )
                        .join(
                            SourceVideo,
                            ClipCandidate.source_video_id == SourceVideo.id,
                        )
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        )
                        .where(
                            SourceChannel.channel_id == channel_id,
                            RenderedClip.status == "rendered",
                            RenderedClip.orientation == orientation,
                        )
                    )
                ).scalar()
                or 0
            )

    # --- kaynak video etiketi ---

    async def source_tag(self, source_video_id: int) -> str | None:
        """The operator-facing tag for one horizontal source video.

        Computed from the video row, its media asset, and the latest
        pipeline job — never from UI state. Returns None for excluded
        videos (they are not part of the flow).
        """
        async with self._sessionmaker() as session:
            video = await session.get(SourceVideo, source_video_id)
            if video is None or video.status == "excluded":
                return None
            if video.status == "confirmed":
                return TAG_CONFIRMED
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
            job = await self._latest_pipeline_job(session, source_video_id)

        if asset is not None and asset.status == "failed":
            return TAG_ERROR
        # Varlik islendiyse kaynak stokta hazirdir; eski bir basarisiz
        # is denemesi bunu golgeleyemez.
        if asset is not None and asset.status == "processed":
            return TAG_DONE
        if job is not None and job.status == "failed":
            return TAG_ERROR
        if job is not None and job.status in ("queued", "cancelling"):
            return TAG_QUEUED
        if job is not None and job.status == "running":
            if asset is not None and asset.stage == "download":
                return TAG_DOWNLOADING
            return TAG_PROCESSING
        if asset is not None and asset.status in (
            "downloading",
            "downloaded",
            "inspected",
            "transcribed",
            "analyzed",
        ):
            # Pipeline yarida kalmis ama is sirada: tekrar denenecek.
            return TAG_QUEUED
        return TAG_QUEUED

    @staticmethod
    async def _latest_pipeline_job(
        session: AsyncSession, source_video_id: int
    ) -> Job | None:
        """Newest media_process/hype_evaluate job for the video."""
        rows = (
            (
                await session.execute(
                    sa.select(Job)
                    .where(Job.job_type.in_(("media_process", "hype_evaluate")))
                    .order_by(Job.id.desc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        for job in rows:
            payload = job.payload or {}
            if payload.get("source_video_id") == source_video_id:
                return job
        return None

    # --- shorts etiketi ---

    @staticmethod
    def clip_tag(render: RenderedClip) -> str:
        if render.status == "rendered":
            return TAG_SHORTS
        if render.status == "failed":
            return TAG_ERROR
        return TAG_PROCESSING  # rendering

    # --- motor aktivitesi ---

    async def engine_activity(self, channel_id: int) -> str:
        """What the engine is actually doing for this channel right now,
        derived from live jobs and stock — never a frontend-only state."""
        jobs = await self._channel_jobs(channel_id)
        running = [j for j in jobs if j.status == "running"]
        for job in running:
            kind = job.job_type
            if kind == "source_discover":
                return ACTIVITY_DISCOVERING
            if kind == "media_process":
                stage = await self._asset_stage(
                    (job.payload or {}).get("source_video_id")
                )
                if stage == "download":
                    return ACTIVITY_DOWNLOADING
                if stage == "transcript":
                    return ACTIVITY_TRANSCRIBING
                return ACTIVITY_ANALYZING
            if kind == "hype_evaluate":
                return ACTIVITY_ANALYZING
            if kind in ("clip_render", "clip_render_full_cut"):
                return ACTIVITY_RENDERING
        if not jobs:
            if await self.horizontal_stock_level(channel_id) > 0:
                return ACTIVITY_STOCK_READY
            return ACTIVITY_IDLE
        return ACTIVITY_IDLE

    async def _asset_stage(self, source_video_id: Any) -> str | None:
        if not isinstance(source_video_id, int):
            return None
        async with self._sessionmaker() as session:
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
            return asset.stage if asset else None

    async def _channel_jobs(
        self, channel_id: int, statuses: tuple[str, ...] | None = None
    ) -> list[Job]:
        """Jobs in the given statuses that belong to the channel,
        resolved in Python from job payloads (works identically on
        PostgreSQL JSONB and sqlite JSON)."""
        wanted = statuses or ("queued", "running", "cancelling")
        async with self._sessionmaker() as session:
            jobs = (
                (
                    await session.execute(
                        sa.select(Job)
                        .where(Job.status.in_(wanted))
                        .order_by(Job.id.desc())
                        .limit(300)
                    )
                )
                .scalars()
                .all()
            )
            if not jobs:
                return []
            video_ids = set(
                (
                    await session.execute(
                        sa.select(SourceVideo.id).join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        ).where(SourceChannel.channel_id == channel_id)
                    )
                )
                .scalars()
                .all()
            )
            candidate_ids = set(
                (
                    await session.execute(
                        sa.select(ClipCandidate.id).join(
                            SourceVideo,
                            ClipCandidate.source_video_id == SourceVideo.id,
                        ).where(ClipCandidate.source_video_id.in_(video_ids or {0}))
                    )
                )
                .scalars()
                .all()
            )
            asset_ids = set(
                (
                    await session.execute(
                        sa.select(MediaAsset.id).where(
                            MediaAsset.source_video_id.in_(video_ids or {0})
                        )
                    )
                )
                .scalars()
                .all()
            )

        matched: list[Job] = []
        for job in jobs:
            payload = job.payload or {}
            if payload.get("channel_id") == channel_id:
                matched.append(job)
                continue
            if any(payload.get(k) in video_ids for k in _VIDEO_PAYLOAD_KEYS):
                matched.append(job)
                continue
            if any(payload.get(k) in candidate_ids for k in _CANDIDATE_PAYLOAD_KEYS):
                matched.append(job)
                continue
            if any(payload.get(k) in asset_ids for k in _ASSET_PAYLOAD_KEYS):
                matched.append(job)
        return matched

    # --- kanal ozeti (Genel Bakis satirlari) ---

    async def channel_status_row(self, channel: Channel) -> dict:
        """One Overview row: persistent automation state, live engine
        activity, stock/queue/shorts counts, and the last success/error
        from the channel's settled jobs."""
        async with self._sessionmaker() as session:
            profile_row = (
                (
                    await session.execute(
                        sa.text(
                            "SELECT automation_state, horizontal_stock_target "
                            "FROM publishing_profiles WHERE channel_id = :cid"
                        ),
                        {"cid": channel.id},
                    )
                )
                .first()
            )
            automation_state = profile_row[0] if profile_row else "stopped"
            stock_target = profile_row[1] if profile_row else 3

        settled = await self._channel_jobs(
            channel.id, statuses=("succeeded", "failed")
        )
        last_error = next((j for j in settled if j.status == "failed"), None)
        last_success = next((j for j in settled if j.status == "succeeded"), None)

        activity = await self.engine_activity(channel.id)
        if automation_state in ("stopped", "error"):
            activity = ACTIVITY_STOPPED
        return {
            "channel_id": channel.id,
            "name": channel.name,
            "handle": channel.handle,
            "status": channel.status.value if hasattr(channel.status, "value") else channel.status,
            "ribbon_color": channel.ribbon_color,
            "automation_state": automation_state,
            "engine_activity": activity,
            "horizontal_stock": await self.horizontal_stock_level(channel.id),
            "horizontal_stock_target": int(stock_target),
            "ready_stock": await self.ready_clip_stock(channel.id),
            "ready_stock_target": int(stock_target),
            "queued_horizontal": await self.queued_horizontal_count(channel.id),
            "shorts_ready": await self.shorts_count(channel.id),
            "full_cuts_ready": await self.full_cut_count(channel.id),
            "last_error": last_error.last_error if last_error else None,
            "last_error_at": (
                last_error.finished_at.isoformat()
                if last_error and last_error.finished_at
                else None
            ),
            "last_success_at": (
                last_success.finished_at.isoformat()
                if last_success and last_success.finished_at
                else None
            ),
        }

    # --- takip edilen karakterler ---

    async def followed_character_ids(self, channel_id: int) -> list[int]:
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        sa.select(ChannelCharacter.character_id)
                        .where(ChannelCharacter.channel_id == channel_id)
                        .order_by(ChannelCharacter.id)
                    )
                )
                .scalars()
                .all()
            )
            return list(rows)

    # --- #confirmed gecisi ---

    async def maybe_confirm_source(self, source_video_id: int) -> bool:
        """Mark a source #confirmed when its Shorts production is
        complete: every selected candidate rendered, plus (for reaction
        sources) the horizontal full cut. Called after render and hype
        jobs; idempotent and central — nothing else writes 'confirmed'.
        """
        async with self._sessionmaker() as session:
            video = await session.get(SourceVideo, source_video_id)
            if video is None or video.status != "processed":
                return False
            source = await session.get(SourceChannel, video.source_channel_id)
            if source is None:
                return False
            selected = (
                (
                    await session.execute(
                        sa.select(ClipCandidate.id)
                        .where(
                            ClipCandidate.source_video_id == source_video_id,
                            ClipCandidate.status == "selected",
                        )
                    )
                )
                .scalars()
                .all()
            )
            if selected:
                rendered = set(
                    (
                        (
                            await session.execute(
                                sa.select(RenderedClip.clip_candidate_id)
                                .where(
                                    RenderedClip.clip_candidate_id.in_(selected),
                                    RenderedClip.orientation == "vertical",
                                    RenderedClip.status == "rendered",
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                )
                shorts_done = set(selected).issubset(rendered)
            else:
                # Cikarilacak aday yok: uretim bitti sayilir.
                shorts_done = True
            full_cut_done = True
            if produces_full_cut(source):
                full_cut_done = (
                    (
                        await session.execute(
                            sa.select(sa.func.count())
                            .select_from(RenderedClip)
                            .where(
                                RenderedClip.source_video_id == source_video_id,
                                RenderedClip.clip_candidate_id.is_(None),
                                RenderedClip.orientation == "horizontal",
                                RenderedClip.status == "rendered",
                            )
                        )
                    ).scalar()
                    or 0
                ) > 0
            if not (shorts_done and full_cut_done):
                return False
            video.status = "confirmed"
            vertical_only = source.output_orientation == "vertical"
            record_event(
                session,
                source.channel_id,
                "source.confirmed",
                {
                    "source_video_id": source_video_id,
                    "selected_candidates": len(selected),
                },
            )
            await session.commit()
        if vertical_only:
            # Görev 2: dikey yönlü kaynakta Shorts üretimi bitti — yatay
            # kaynak dosyası diskten kalkar, stokta yalnız dikey klipler
            # kalır. DB kayıtları durur (denetim izi korunur).
            from app.services.media_cleanup import cleanup_vertical_source_files

            await cleanup_vertical_source_files(
                self._sessionmaker, self._settings, source_video_id=source_video_id
            )
        return True
