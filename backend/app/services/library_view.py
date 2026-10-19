"""Medya kütüphanesi görünümü: kaynak videolar, üretilen klipler ve
stok özeti (salt okunur, sayfalanabilir).

Etiketler StatusService'in sözlüğüyle aynıdır (#queued, #downloading,
...) ama tek sayfalık listeleme için tek sorgu setinden Python
tarafında türetilir — video başına ek sorgu açılmaz.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Channel,
    ClipCandidate,
    Job,
    MediaAsset,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)

TAG_QUEUED = "#queued"
TAG_DOWNLOADING = "#downloading"
TAG_PROCESSING = "#processing"
TAG_DONE = "#done"
TAG_CONFIRMED = "#confirmed"
TAG_SHORTS = "#shorts"
TAG_ERROR = "#error"

# Incelenen asama etiketi: asset.status -> operator sozlugu.
_ASSET_STAGE_LABEL = {
    "downloading": "indiriliyor",
    "downloaded": "indi",
    "inspected": "incelendi",
    "transcribed": "yazildi",
    "analyzed": "analiz",
}


class LibraryViewService:
    """Kütüphane ekranının tüm verisi."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def media_library(
        self,
        limit: int = 60,
        offset: int = 0,
        include_excluded: bool = False,
        active_only: bool = False,
    ) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            # Kuralin reddettigi (Hariç) videolar varsayilan listede
            # kalabalik yapmaz; yalnizca 'Haric' filtresi isteyince gelir.
            # active_only: yalnizca sisteme girmis videolar (asset'i olan,
            # onaylanmis veya su an islenen) — kesif havuzundaki hic
            # dokunulmamis satirlar listeyi doldurmaz.
            active_video_ids = await self._active_pipeline_video_ids(session)
            visible: list[Any] = (
                [] if include_excluded else [SourceVideo.status != "excluded"]
            )
            if active_only:
                visible.append(
                    sa.or_(
                        MediaAsset.id.isnot(None),
                        SourceVideo.status == "confirmed",
                        SourceVideo.id.in_(active_video_ids),
                    )
                )
            total = (
                (
                    await session.execute(
                        sa.select(sa.func.count())
                        .select_from(SourceVideo)
                        .outerjoin(
                            MediaAsset,
                            MediaAsset.source_video_id == SourceVideo.id,
                        )
                        .where(*visible)
                    )
                ).scalar()
                or 0
            )
            video_rows = (
                (
                    await session.execute(
                        sa.select(
                            SourceVideo,
                            SourceChannel.channel_id,
                            MediaAsset,
                        )
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        )
                        .outerjoin(
                            MediaAsset, MediaAsset.source_video_id == SourceVideo.id
                        )
                        .where(*visible)
                        .order_by(SourceVideo.id.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                )
                .all()
            )
            channel_ids = {row[1] for row in video_rows if row[1] is not None}
            channels = await self._channels(session, channel_ids)
            latest_jobs = await self._latest_jobs_by_video(
                session, [row[0].id for row in video_rows]
            )

            sources = [
                self._source_card(video, channel_id, asset, channels, latest_jobs)
                for video, channel_id, asset in video_rows
            ]

            clips, clips_total = await self._clips(session)
            summary = await self._summary(
                session, include_excluded, active_video_ids
            )

        return {
            "sources": sources,
            "sources_total": int(total),
            "clips": clips,
            "clips_total": clips_total,
            "summary": summary,
        }

    @staticmethod
    async def _active_pipeline_video_ids(
        session: AsyncSession,
    ) -> set[int]:
        """Su an kosan medya islerine bagli video id'leri. Asset henuz
        olusmamis olsa da islenmeye baslamis bir video 'girmis' sayilir;
        listede kaybolmamasi icin active_only kapsamina eklenir."""
        jobs = (
            (
                await session.execute(
                    sa.select(Job)
                    .where(
                        Job.status == "running",
                        Job.job_type.in_(("media_process", "hype_evaluate")),
                    )
                    .order_by(Job.id.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        ids: set[int] = set()
        for job in jobs:
            sv = (job.payload or {}).get("source_video_id")
            if isinstance(sv, int):
                ids.add(sv)
        return ids

    @staticmethod
    async def _channels(
        session: AsyncSession, channel_ids: set[int]
    ) -> dict[int, dict[str, Any]]:
        if not channel_ids:
            return {}
        rows = (
            (
                await session.execute(
                    sa.select(Channel.id, Channel.name, Channel.ribbon_color).where(
                        Channel.id.in_(channel_ids)
                    )
                )
            )
            .all()
        )
        return {r[0]: {"name": r[1], "ribbon_color": r[2]} for r in rows}

    @staticmethod
    async def _latest_jobs_by_video(
        session: AsyncSession, video_ids: list[int]
    ) -> dict[int, Job]:
        """Video basina en guncel boru hatti isi (status sozlugu icin)."""
        if not video_ids:
            return {}
        jobs = (
            (
                await session.execute(
                    sa.select(Job)
                    .where(Job.job_type.in_(("media_process", "hype_evaluate")))
                    .order_by(Job.id.desc())
                    .limit(400)
                )
            )
            .scalars()
            .all()
        )
        wanted = set(video_ids)
        latest: dict[int, Job] = {}
        for job in jobs:
            sv = (job.payload or {}).get("source_video_id")
            if isinstance(sv, int) and sv in wanted and sv not in latest:
                latest[sv] = job
        return latest

    @staticmethod
    def _source_card(
        video: SourceVideo,
        channel_id: int | None,
        asset: MediaAsset | None,
        channels: dict[int, dict[str, Any]],
        latest_jobs: dict[int, Job],
    ) -> dict[str, Any]:
        channel = channels.get(channel_id) if channel_id is not None else None
        job = latest_jobs.get(video.id)
        # StatusService.source_tag ile ayni sozcukler, tek sorgu setinden.
        if video.status == "excluded":
            tag = "#excluded"
        elif video.status == "confirmed":
            tag = TAG_CONFIRMED
        elif asset is not None and asset.status == "failed":
            tag = TAG_ERROR
        elif asset is not None and asset.status == "processed":
            tag = TAG_DONE
        elif job is not None and job.status == "running":
            if asset is not None and asset.stage == "download":
                tag = TAG_DOWNLOADING
            else:
                tag = TAG_PROCESSING
        elif job is not None and job.status == "failed":
            tag = TAG_ERROR
        else:
            tag = TAG_QUEUED
        stage_label = (
            _ASSET_STAGE_LABEL.get(asset.status) if asset is not None else None
        )
        return {
            "id": video.id,
            "title": video.title,
            "youtube_video_id": video.youtube_video_id,
            "duration_seconds": video.duration_seconds,
            "tag": tag,
            "asset_stage": asset.stage if asset is not None else None,
            "asset_stage_label": stage_label,
            "asset_status": asset.status if asset is not None else None,
            "file_bytes": asset.file_bytes if asset is not None else 0,
            "origin": asset.origin if asset is not None else None,
            "channel_id": channel_id,
            "channel_name": channel["name"] if channel else None,
            "ribbon_color": channel["ribbon_color"] if channel else None,
            "published_at": (
                video.published_at.isoformat() if video.published_at else None
            ),
            "updated_at": (
                asset.updated_at.isoformat()
                if asset is not None and asset.updated_at
                else video.updated_at.isoformat() if video.updated_at else None
            ),
        }

    @staticmethod
    async def _clips(session: AsyncSession) -> tuple[list[dict], int]:
        total = (
            (
                await session.execute(
                    sa.select(sa.func.count()).select_from(RenderedClip)
                )
            ).scalar()
            or 0
        )
        rows = (
            (
                await session.execute(
                    sa.select(
                        RenderedClip,
                        ClipCandidate,
                        SourceVideo.title,
                        Channel.name,
                        Channel.ribbon_color,
                        Channel.id,
                    )
                    .outerjoin(
                        ClipCandidate,
                        RenderedClip.clip_candidate_id == ClipCandidate.id,
                    )
                    .outerjoin(
                        SourceVideo,
                        sa.or_(
                            ClipCandidate.source_video_id == SourceVideo.id,
                            RenderedClip.source_video_id == SourceVideo.id,
                        ),
                    )
                    .outerjoin(
                        SourceChannel, SourceVideo.source_channel_id == SourceChannel.id
                    )
                    .outerjoin(Channel, SourceChannel.channel_id == Channel.id)
                    .order_by(RenderedClip.id.desc())
                    .limit(60)
                )
            )
            .all()
        )
        clips = []
        for render, candidate, title, name, ribbon, cid in rows:
            clips.append(
                {
                    "id": render.id,
                    "title": title,
                    "candidate_reason": (
                        candidate.reason if candidate is not None else None
                    ),
                    "orientation": render.orientation,
                    "status": render.status,
                    "file_bytes": render.file_bytes,
                    "duration_seconds": render.duration_seconds,
                    "channel_id": cid,
                    "channel_name": name,
                    "ribbon_color": ribbon,
                    "created_at": (
                        render.created_at.isoformat() if render.created_at else None
                    ),
                }
            )
        return clips, int(total)

    @staticmethod
    async def _summary(
        session: AsyncSession,
        include_excluded: bool = False,
        active_video_ids: set[int] | None = None,
    ) -> dict[str, int]:
        async def _count(statement: Any) -> int:
            return int((await session.execute(statement)).scalar() or 0)

        processed = await _count(
            sa.select(sa.func.count())
            .select_from(MediaAsset)
            .where(MediaAsset.status == "processed")
        )
        failed = await _count(
            sa.select(sa.func.count())
            .select_from(MediaAsset)
            .where(MediaAsset.status == "failed")
        )
        shorts = await _count(
            sa.select(sa.func.count())
            .select_from(RenderedClip)
            .where(
                RenderedClip.status == "rendered",
                RenderedClip.orientation == "vertical",
            )
        )
        full_cuts = await _count(
            sa.select(sa.func.count())
            .select_from(RenderedClip)
            .where(
                RenderedClip.status == "rendered",
                RenderedClip.orientation == "horizontal",
            )
        )
        # Kesif havuzu her zaman haric tutulanlar disindaki toplamdir;
        # 'sources_total' ise istenen gorunumun (haric dahil) sayisidir.
        pool_total = await _count(
            sa.select(sa.func.count()).select_from(SourceVideo).where(
                SourceVideo.status != "excluded"
            )
        )
        sources = await _count(
            sa.select(sa.func.count())
            .select_from(SourceVideo)
            .where(
                *(
                    []
                    if include_excluded
                    else [SourceVideo.status != "excluded"]
                )
            )
        )
        entered = await _count(
            sa.select(sa.func.count())
            .select_from(SourceVideo)
            .outerjoin(
                MediaAsset, MediaAsset.source_video_id == SourceVideo.id
            )
            .where(
                SourceVideo.status != "excluded",
                sa.or_(
                    MediaAsset.id.isnot(None),
                    SourceVideo.status == "confirmed",
                    SourceVideo.id.in_(active_video_ids or set()),
                ),
            )
        )
        return {
            "sources_total": sources,
            "entered": entered,
            "queued_pool": max(0, pool_total - entered),
            "processed": processed,
            "failed": failed,
            "shorts_ready": shorts,
            "full_cuts_ready": full_cuts,
        }
