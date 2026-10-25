"""Medya kütüphanesi görünümü: kaynak videolar, üretilen klipler ve
stok özeti (salt okunur, sayfalanabilir).

Etiketler StatusService'in sözlüğüyle aynıdır (#queued, #downloading,
...) ama tek sayfalık listeleme için tek sorgu setinden Python
tarafında türetilir — video başına ek sorgu açılmaz.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Channel,
    ClipCandidate,
    ClipMetadata,
    Job,
    MediaAsset,
    PublishedVideo,
    PublishingProfile,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.publishing_schedule import (
    ScheduleError,
    next_due_time,
    slots_for_orientation,
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

# Ürün görünümündeki aşama şeridi: sıra, etiket ve asset.stage eşlemesi.
_STAGE_SPECS = (
    ("download", "İndirme"),
    ("inspect", "İnceleme"),
    ("transcript", "Altyazı"),
    ("analysis", "Analiz"),
    ("candidates", "Adaylar"),
)
_STAGE_KEYS = tuple(key for key, _ in _STAGE_SPECS)


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
        engine_selected_only: bool = False,
        ready_only: bool = False,
        excluded_only: bool = False,
    ) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            # Kuralin reddettigi (Hariç) videolar varsayilan listede
            # kalabalik yapmaz; yalnizca 'Haric' filtresi isteyince gelir.
            # active_only: yalnizca sisteme girmis videolar (asset'i olan,
            # onaylanmis veya su an islenen) — kesif havuzundaki hic
            # dokunulmamis satirlar listeyi doldurmaz.
            # engine_selected_only: Ürün görünümü; yalnızca motorun klip
            # seçtiği videolar ve o an işlenen tek kaynak görünür.
            # excluded_only: hariç paneli (2026-10-21 kalıcı çözüm) —
            # yalnızca dışlanan videolar; toplu geri alma listesi.
            if excluded_only:
                visible: list[Any] = [SourceVideo.status == "excluded"]
            else:
                visible = (
                    []
                    if include_excluded
                    else [SourceVideo.status != "excluded"]
                )
            active_video_ids = await self._active_pipeline_video_ids(session)
            if active_only:
                visible.append(
                    sa.or_(
                        MediaAsset.id.isnot(None),
                        SourceVideo.status == "confirmed",
                        SourceVideo.id.in_(active_video_ids),
                    )
                )
            if engine_selected_only:
                selected_exists = sa.exists(
                    sa.select(1)
                    .select_from(ClipCandidate)
                    .where(
                        ClipCandidate.source_video_id == SourceVideo.id,
                        ClipCandidate.status == "selected",
                    )
                )
                visible.append(
                    sa.or_(
                        selected_exists,
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
                        sa.select(SourceVideo, SourceChannel, MediaAsset)
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
            channel_ids = {
                source.channel_id for _, source, _ in video_rows
            }
            channels = await self._channels(session, channel_ids)
            video_ids = [video.id for video, _, _ in video_rows]
            latest_jobs = await self._latest_jobs_by_video(session, video_ids)
            selected_map = await self._selected_candidates(session, video_ids)
            full_cut_ids = await self._rendered_full_cuts(session, video_ids)
            current_source_id = (
                max(active_video_ids) if active_video_ids else None
            )
            from app.models import AppMeta

            from app.services.media_pipeline import DOWNLOAD_PROGRESS_KEY

            progress_row = await session.get(AppMeta, DOWNLOAD_PROGRESS_KEY)
            download_progress = (
                progress_row.value if progress_row is not None else {}
            )

            sources = [
                self._source_card(
                    video,
                    source,
                    asset,
                    channels,
                    latest_jobs,
                    selected_map.get(video.id, []),
                    video.id in full_cut_ids,
                    video.id == current_source_id,
                    download_progress,
                )
                for video, source, asset in video_rows
            ]

            clips, clips_total = await self._clips(session, ready_only=ready_only)
            summary = await self._summary(
                session, include_excluded, active_video_ids
            )

        return {
            "sources": sources,
            "sources_total": int(total),
            "current_source_id": current_source_id,
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
    async def _selected_candidates(
        session: AsyncSession, video_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        """Motorun seçtiği klip anları (render durumuyla birlikte)."""
        if not video_ids:
            return {}
        rows = (
            (
                await session.execute(
                    sa.select(ClipCandidate, RenderedClip)
                    .outerjoin(
                        RenderedClip,
                        sa.and_(
                            RenderedClip.clip_candidate_id == ClipCandidate.id,
                            RenderedClip.orientation == "vertical",
                        ),
                    )
                    .where(
                        ClipCandidate.source_video_id.in_(video_ids),
                        ClipCandidate.status == "selected",
                    )
                    .order_by(
                        ClipCandidate.source_video_id,
                        ClipCandidate.start_seconds,
                    )
                )
            )
            .all()
        )
        grouped: dict[int, list[dict[str, Any]]] = {}
        for candidate, render in rows:
            hype = (candidate.detail or {}).get("hype") or {}
            grouped.setdefault(candidate.source_video_id, []).append(
                {
                    "id": candidate.id,
                    "start_seconds": candidate.start_seconds,
                    "end_seconds": candidate.end_seconds,
                    "duration_seconds": candidate.duration_seconds,
                    "score": candidate.score,
                    "reason": candidate.reason,
                    "hype_confidence": hype.get("confidence"),
                    "hype_reason": hype.get("reason"),
                    "refined": bool(hype.get("refined")),
                    "render_id": render.id if render is not None else None,
                    "render_status": render.status if render is not None else None,
                }
            )
        return grouped

    @staticmethod
    async def _rendered_full_cuts(
        session: AsyncSession, video_ids: list[int]
    ) -> set[int]:
        if not video_ids:
            return set()
        rows = (
            (
                await session.execute(
                    sa.select(RenderedClip.source_video_id).where(
                        RenderedClip.source_video_id.in_(video_ids),
                        RenderedClip.clip_candidate_id.is_(None),
                        RenderedClip.orientation == "horizontal",
                        RenderedClip.status == "rendered",
                    )
                )
            )
            .scalars()
            .all()
        )
        return {int(value) for value in rows if value is not None}

    @staticmethod
    def _source_stages(
        asset: MediaAsset | None,
        selected_count: int,
        latest_job: Job | None,
        is_current: bool,
        download_percent: float | None = None,
        error_text: str | None = None,
    ) -> list[dict[str, str | None]]:
        """Beş boru hattı aşaması + klip seçimi; ürün şeridi için.
        İndirme sırasında download adımı yüzde detayı taşır; hatalı
        adım kısa hata metni taşır (tam metin kart üzerinde)."""
        states = {key: "pending" for key in _STAGE_KEYS}
        selection_state = "pending"
        if asset is not None:
            if asset.status == "processed":
                states = {key: "done" for key in _STAGE_KEYS}
                selection_state = "done" if selected_count else "skipped"
            else:
                index = (
                    _STAGE_KEYS.index(asset.stage)
                    if asset.stage in _STAGE_KEYS
                    else 0
                )
                for position, key in enumerate(_STAGE_KEYS):
                    if position < index:
                        states[key] = "done"
                    elif position == index:
                        states[key] = (
                            "failed" if asset.status == "failed" else "active"
                        )
                if latest_job is not None and latest_job.job_type == "hype_evaluate":
                    selection_state = (
                        "active" if latest_job.status == "running" else "pending"
                    )
        elif is_current:
            states["download"] = "active"
            if latest_job is not None and latest_job.status == "failed":
                states["download"] = "failed"
        short_error = None
        if error_text:
            short_error = error_text.strip()[:80] or None
        result = [
            {
                "key": key,
                "label": label,
                "state": states[key],
                "detail": (
                    f"%{download_percent:.0f}"
                    if key == "download"
                    and download_percent is not None
                    and states[key] == "active"
                    else short_error
                    if states[key] == "failed"
                    else None
                ),
            }
            for key, label in _STAGE_SPECS
        ]
        result.append(
            {"key": "selection", "label": "Klip seçimi", "state": selection_state, "detail": None}
        )
        return result

    @staticmethod
    def _source_card(
        video: SourceVideo,
        source: SourceChannel,
        asset: MediaAsset | None,
        channels: dict[int, dict[str, Any]],
        latest_jobs: dict[int, Job],
        selected: list[dict[str, Any]],
        full_cut_ready: bool,
        is_current: bool,
        download_progress: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        channel_id = source.channel_id
        channel = channels.get(channel_id) if channel_id is not None else None
        job = latest_jobs.get(video.id)
        # StatusService.source_tag ile ayni sozcukler, tek sorgu setinden.
        # Sürüyen iş, 'failed' işaretinden önce gelir: kaldığı yerden
        # sürdürülen video "İşleniyor" görünür, "Hata" değil.
        if video.status == "excluded":
            tag = "#excluded"
        elif video.status == "confirmed":
            tag = TAG_CONFIRMED
        elif job is not None and job.status == "running":
            if asset is not None and asset.stage == "download":
                tag = TAG_DOWNLOADING
            else:
                tag = TAG_PROCESSING
        elif asset is not None and asset.status == "failed":
            tag = TAG_ERROR
        elif asset is not None and asset.status == "processed":
            tag = TAG_DONE
        elif job is not None and job.status == "failed":
            tag = TAG_ERROR
        else:
            tag = TAG_QUEUED
        stage_label = (
            _ASSET_STAGE_LABEL.get(asset.status) if asset is not None else None
        )
        last_error = None
        if asset is not None and asset.last_error:
            last_error = asset.last_error
        elif job is not None and job.last_error and tag == TAG_ERROR:
            last_error = job.last_error
        return {
            "id": video.id,
            "title": video.title,
            "platform": source.platform,
            "youtube_video_id": video.youtube_video_id,
            "youtube_url": (
                f"https://www.youtube.com/watch?v={video.youtube_video_id}"
                if source.platform == "youtube" and video.youtube_video_id
                else None
            ),
            "source_channel_title": source.title,
            "source_channel_youtube_id": source.youtube_channel_id,
            "reaction_source": bool(source.reaction_source),
            "output_orientation": source.output_orientation,
            "filter_rules": source.filter_rules or {},
            "trim_start_seconds": source.trim_start_seconds,
            "trim_end_seconds": source.trim_end_seconds,
            # Otomatik intro/outro tespiti (2026-10-24): kullanici elle
            # ayarlamaz; analiz asamasinda hesaplanip render'da uygulanir.
            "auto_trim": (asset.analysis or {}).get("auto_trim")
            if asset is not None
            else None,
            "duration_seconds": video.duration_seconds,
            "tag": tag,
            "asset_stage": asset.stage if asset is not None else None,
            "asset_stage_label": stage_label,
            "asset_status": asset.status if asset is not None else None,
            "last_error": last_error,
            "file_bytes": asset.file_bytes if asset is not None else 0,
            "origin": asset.origin if asset is not None else None,
            "stages": LibraryViewService._source_stages(
                asset,
                len(selected),
                job,
                is_current,
                download_percent=(
                    download_progress.get("percent")
                    if download_progress
                    and asset is not None
                    and download_progress.get("media_asset_id") == asset.id
                    and asset.status == "downloading"
                    else None
                ),
                error_text=last_error,
            ),
            "selected_candidates": selected,
            "selected_count": len(selected),
            "full_cut_ready": full_cut_ready,
            "is_current": is_current,
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
    async def _latest_metadata(
        session: AsyncSession,
        candidate_ids: list[int],
        source_ids: list[int],
    ) -> dict[tuple[str, int], ClipMetadata]:
        conditions = []
        if candidate_ids:
            conditions.append(
                ClipMetadata.clip_candidate_id.in_(candidate_ids)
            )
        if source_ids:
            conditions.append(
                sa.and_(
                    ClipMetadata.source_video_id.in_(source_ids),
                    ClipMetadata.clip_candidate_id.is_(None),
                )
            )
        if not conditions:
            return {}
        rows = (
            (
                await session.execute(
                    sa.select(ClipMetadata)
                    .where(sa.or_(*conditions))
                    .order_by(ClipMetadata.revision.asc(), ClipMetadata.id.asc())
                )
            )
            .scalars()
            .all()
        )
        latest: dict[tuple[str, int], ClipMetadata] = {}
        for row in rows:
            if row.clip_candidate_id is not None:
                latest[("candidate", row.clip_candidate_id)] = row
            elif row.source_video_id is not None:
                latest[("source", row.source_video_id)] = row
        return latest

    @staticmethod
    async def _published_by_render(
        session: AsyncSession,
        candidate_ids: list[int],
        source_ids: list[int],
    ) -> dict[tuple[str, int, str], PublishedVideo]:
        conditions = []
        if candidate_ids:
            conditions.append(
                PublishedVideo.clip_candidate_id.in_(candidate_ids)
            )
        if source_ids:
            conditions.append(
                sa.and_(
                    PublishedVideo.source_video_id.in_(source_ids),
                    PublishedVideo.clip_candidate_id.is_(None),
                )
            )
        if not conditions:
            return {}
        rows = (
            (
                await session.execute(
                    sa.select(PublishedVideo)
                    .where(sa.or_(*conditions))
                    .order_by(PublishedVideo.id.asc())
                )
            )
            .scalars()
            .all()
        )
        mapped: dict[tuple[str, int, str], PublishedVideo] = {}
        for row in rows:
            if row.clip_candidate_id is not None:
                mapped[("candidate", row.clip_candidate_id, row.orientation)] = row
            elif row.source_video_id is not None:
                mapped[("source", row.source_video_id, row.orientation)] = row
        return mapped

    @staticmethod
    def _thumbnail_url(
        render: RenderedClip,
        video: SourceVideo | None,
        source: SourceChannel | None = None,
    ) -> str | None:
        if render.thumbnail_path:
            return f"/api/media/clips/{render.id}/thumbnail"
        if (
            video is not None
            and video.youtube_video_id
            and (source is None or source.platform == "youtube")
        ):
            return (
                f"https://i.ytimg.com/vi/"
                f"{video.youtube_video_id}/mqdefault.jpg"
            )
        return None

    @staticmethod
    async def _clips(
        session: AsyncSession, ready_only: bool = False
    ) -> tuple[list[dict], int]:
        total_query = sa.select(sa.func.count()).select_from(RenderedClip)
        statement_filter = RenderedClip.status != "removed"
        if ready_only:
            total_query = total_query.where(RenderedClip.status == "rendered")
        else:
            total_query = total_query.where(statement_filter)
        total = int((await session.execute(total_query)).scalar() or 0)

        statement = (
            sa.select(
                RenderedClip,
                ClipCandidate,
                SourceVideo,
                SourceChannel,
                Channel,
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
        if ready_only:
            statement = statement.where(RenderedClip.status == "rendered")
        else:
            # Kaldirilan klipler (mezartas) listede gorunmez.
            statement = statement.where(statement_filter)
        rows = (await session.execute(statement)).all()

        candidate_ids = [
            render.clip_candidate_id
            for render, candidate, _, _, _ in rows
            if candidate is not None and render.clip_candidate_id is not None
        ]
        source_ids = [
            video.id for _, candidate, video, _, _ in rows
            if candidate is None and video is not None
        ]
        metadata = await LibraryViewService._latest_metadata(
            session, candidate_ids, source_ids
        )
        published = await LibraryViewService._published_by_render(
            session, candidate_ids, source_ids
        )

        clips = []
        for render, candidate, video, source, channel in rows:
            if candidate is not None:
                meta = metadata.get(("candidate", candidate.id))
                published_row = published.get(
                    ("candidate", candidate.id, render.orientation)
                )
            elif video is not None:
                meta = metadata.get(("source", video.id))
                published_row = published.get(
                    ("source", video.id, render.orientation)
                )
            else:
                meta = None
                published_row = None
            hype = (
                ((candidate.detail or {}).get("hype") or {})
                if candidate is not None
                else {}
            )
            youtube_video_id = (
                published_row.youtube_video_id if published_row is not None else None
            )
            clips.append(
                {
                    "id": render.id,
                    "title": (
                        meta.title
                        if meta is not None
                        else video.title
                        if video is not None
                        else "Tam kesit"
                    ),
                    "candidate_reason": (
                        candidate.reason if candidate is not None else None
                    ),
                    "orientation": render.orientation,
                    "status": render.status,
                    "file_bytes": render.file_bytes,
                    "duration_seconds": render.duration_seconds,
                    "channel_id": channel.id if channel is not None else None,
                    "channel_name": channel.name if channel is not None else None,
                    "ribbon_color": channel.ribbon_color if channel is not None else None,
                    "created_at": (
                        render.created_at.isoformat() if render.created_at else None
                    ),
                    "thumbnail_url": LibraryViewService._thumbnail_url(
                        render, video, source
                    ),
                    "stream_url": (
                        f"/api/media/clips/{render.id}/stream"
                        if render.status == "rendered"
                        else None
                    ),
                    "metadata_status": meta.status if meta is not None else None,
                    "published_status": (
                        published_row.status
                        if published_row is not None
                        else "not_uploaded"
                    ),
                    "visibility": (
                        published_row.visibility
                        if published_row is not None
                        else None
                    ),
                    "youtube_video_id": youtube_video_id,
                    "youtube_url": (
                        f"https://www.youtube.com/watch?v={youtube_video_id}"
                        if youtube_video_id
                        else None
                    ),
                    # Kütüphane kartında detaya girmeden yayın planını
                    # göstermek için ek tarih alanları (madde 4, 2026-10-25).
                    "published_at": (
                        published_row.published_at.isoformat()
                        if published_row is not None and published_row.published_at
                        else None
                    ),
                    "public_at": (
                        published_row.public_at.isoformat()
                        if published_row is not None and published_row.public_at
                        else None
                    ),
                    "scheduled_at": (
                        published_row.scheduled_at.isoformat()
                        if published_row is not None and published_row.scheduled_at
                        else None
                    ),
                    "source_video_id": video.id if video is not None else None,
                    "source_youtube_video_id": (
                        video.youtube_video_id if video is not None else None
                    ),
                    "source_platform": (
                        source.platform if source is not None else None
                    ),
                    "source_channel_title": (
                        source.title if source is not None else None
                    ),
                    "start_seconds": (
                        candidate.start_seconds if candidate is not None else None
                    ),
                    "end_seconds": (
                        candidate.end_seconds if candidate is not None else None
                    ),
                    "hype_confidence": hype.get("confidence"),
                }
            )
        return clips, total

    async def clip_detail(self, render_id: int) -> dict[str, Any] | None:
        """Ürün detayı: oynatıcı, YouTube yayın planı, metaveri, filtreler."""
        async with self._sessionmaker() as session:
            render = await session.get(RenderedClip, render_id)
            if render is None:
                return None

            candidate = None
            if render.clip_candidate_id is not None:
                candidate = await session.get(
                    ClipCandidate, render.clip_candidate_id
                )
            video_id = (
                candidate.source_video_id
                if candidate is not None
                else render.source_video_id
            )
            video = (
                await session.get(SourceVideo, video_id)
                if video_id is not None
                else None
            )
            source = (
                await session.get(SourceChannel, video.source_channel_id)
                if video is not None
                else None
            )
            channel = (
                await session.get(Channel, source.channel_id)
                if source is not None
                else None
            )
            profile = None
            if channel is not None:
                profile = (
                    (
                        await session.execute(
                            sa.select(PublishingProfile).where(
                                PublishingProfile.channel_id == channel.id
                            )
                        )
                    )
                    .scalars()
                    .one_or_none()
                )

            metadata = None
            if candidate is not None:
                metadata = (
                    (
                        await session.execute(
                            sa.select(ClipMetadata)
                            .where(
                                ClipMetadata.clip_candidate_id == candidate.id
                            )
                            .order_by(ClipMetadata.revision.desc())
                            .limit(1)
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
            elif video is not None:
                metadata = (
                    (
                        await session.execute(
                            sa.select(ClipMetadata)
                            .where(
                                ClipMetadata.source_video_id == video.id,
                                ClipMetadata.clip_candidate_id.is_(None),
                            )
                            .order_by(ClipMetadata.revision.desc())
                            .limit(1)
                        )
                    )
                    .scalars()
                    .one_or_none()
                )

            published = None
            if candidate is not None:
                published = (
                    (
                        await session.execute(
                            sa.select(PublishedVideo).where(
                                PublishedVideo.clip_candidate_id == candidate.id,
                                PublishedVideo.orientation == render.orientation,
                            )
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
            elif video is not None:
                published = (
                    (
                        await session.execute(
                            sa.select(PublishedVideo).where(
                                PublishedVideo.source_video_id == video.id,
                                PublishedVideo.clip_candidate_id.is_(None),
                                PublishedVideo.orientation == render.orientation,
                            )
                        )
                    )
                    .scalars()
                    .one_or_none()
                )

            metadata_versions = 0
            today_count = 0
            last_published = None
            if channel is not None:
                if metadata is not None:
                    versions_query = (
                        sa.select(sa.func.count())
                        .select_from(ClipMetadata)
                        .where(
                            (
                                ClipMetadata.clip_candidate_id == candidate.id
                                if candidate is not None
                                else sa.and_(
                                    ClipMetadata.source_video_id == video.id,
                                    ClipMetadata.clip_candidate_id.is_(None),
                                )
                            )
                        )
                    )
                    metadata_versions = int(
                        (await session.execute(versions_query)).scalar() or 0
                    )
                today_start = datetime.now(UTC).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                today_count = int(
                    (
                        await session.execute(
                            sa.select(sa.func.count())
                            .select_from(PublishedVideo)
                            .where(
                                PublishedVideo.channel_id == channel.id,
                                PublishedVideo.orientation == render.orientation,
                                PublishedVideo.published_at >= today_start,
                            )
                        )
                    ).scalar()
                    or 0
                )
                last_published = (
                    await session.execute(
                        sa.select(sa.func.max(PublishedVideo.published_at)).where(
                            PublishedVideo.channel_id == channel.id,
                            PublishedVideo.orientation == render.orientation,
                        )
                    )
                ).scalar()
                if last_published is not None and last_published.tzinfo is None:
                    last_published = last_published.replace(tzinfo=UTC)

        filters = dict(source.filter_rules or {}) if source is not None else {}
        filters["reaction_source"] = (
            bool(source.reaction_source) if source is not None else False
        )
        filters["trim_start_seconds"] = (
            source.trim_start_seconds if source is not None else 0.0
        )
        filters["trim_end_seconds"] = (
            source.trim_end_seconds if source is not None else 0.0
        )

        timezone_name = (
            profile.timezone
            if profile is not None and profile.timezone
            else "Europe/Istanbul"
        )
        # Yon bazli saatler: shorts kendi prime time dilimlerinde cikar.
        try:
            orientation_slots = slots_for_orientation(
                profile.settings if profile is not None else None,
                render.orientation,
            )
            publish_times = [s.strftime("%H:%M") for s in orientation_slots]
        except ScheduleError:
            publish_times = []
        next_slot = None
        if (
            published is not None
            and published.scheduled_at is not None
            and published.visibility == "private"
        ):
            # Elle planlanmis klibin saati slot tahmininden oncelikli.
            moment = published.scheduled_at
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            next_slot = moment
        else:
            try:
                next_slot = next_due_time(
                    now_utc=datetime.now(UTC),
                    timezone_name=timezone_name,
                    publish_times=(
                        orientation_slots if publish_times else None
                    ),
                    last_published_at=last_published,
                )
            except ScheduleError:
                next_slot = None

        youtube_video_id = (
            published.youtube_video_id if published is not None else None
        )
        upload_status = published.status if published is not None else "not_uploaded"
        visibility = published.visibility if published is not None else None
        metadata_approved = metadata is not None and metadata.status == "approved"
        auto_approve = bool(
            profile and (profile.settings or {}).get("auto_approve_metadata")
        )
        automation_state = (
            profile.automation_state if profile is not None else "stopped"
        )
        daily_limit = (
            (
                profile.daily_clip_target
                if render.orientation == "vertical"
                else profile.daily_horizontal_limit
            )
            if profile is not None
            else 0
        )

        if upload_status == "verified" and visibility == "public":
            note = "Video YouTube'da herkese açık."
        elif upload_status in ("uploaded", "verified") and visibility == "private":
            note = (
                "Gizli yüklendi; planlanan yayın diliminde herkese açılacak."
            )
        elif upload_status == "failed":
            note = "Yükleme başarısız; kuyruk yeniden deneyecek."
        elif metadata_approved:
            note = "Metaveri onaylı; gizli yükleme kuyruğa alınabilir."
        elif metadata is not None:
            note = "Metaveri onay bekliyor; onaylanınca gizli yüklenir."
        else:
            note = "Henüz metaveri üretilmedi; önce içerik hazırlanmalı."
        if automation_state == "stopped":
            note += " Otomasyon durduruldu."
        elif automation_state == "paused":
            note += " Otomasyon duraklatıldı; yayın bekliyor."
        elif automation_state == "error":
            note += " Kanal hata durumunda; tekrar başlatılmalı."

        hype = (
            ((candidate.detail or {}).get("hype") or {})
            if candidate is not None
            else {}
        )

        return {
            "render": {
                "id": render.id,
                "orientation": render.orientation,
                "status": render.status,
                "duration_seconds": render.duration_seconds,
                "width": render.width,
                "height": render.height,
                "file_bytes": render.file_bytes,
                "created_at": (
                    render.created_at.isoformat() if render.created_at else None
                ),
                "stream_url": (
                    f"/api/media/clips/{render.id}/stream"
                    if render.status == "rendered"
                    else None
                ),
                "thumbnail_url": LibraryViewService._thumbnail_url(
                    render, video, source
                ),
                "validation": render.validation or {},
                "webcam_confidence": render.webcam_confidence,
                "layout": render.layout or {},
                "last_error": render.last_error,
            },
            "candidate": (
                {
                    "id": candidate.id,
                    "start_seconds": candidate.start_seconds,
                    "end_seconds": candidate.end_seconds,
                    "duration_seconds": candidate.duration_seconds,
                    "score": candidate.score,
                    "reason": candidate.reason,
                    "hype_confidence": hype.get("confidence"),
                    "hype_reason": hype.get("reason"),
                    "refined": bool(hype.get("refined")),
                }
                if candidate is not None
                else None
            ),
            "source": (
                {
                    "video_id": video.id,
                    "title": video.title,
                    "platform": source.platform if source is not None else None,
                    "youtube_video_id": video.youtube_video_id,
                    "youtube_url": (
                        f"https://www.youtube.com/watch?v={video.youtube_video_id}"
                        if source is not None
                        and source.platform == "youtube"
                        and video.youtube_video_id
                        else None
                    ),
                    "channel_title": source.title if source is not None else None,
                    "channel_youtube_id": (
                        source.youtube_channel_id if source is not None else None
                    ),
                    "published_at": (
                        video.published_at.isoformat()
                        if video.published_at
                        else None
                    ),
                    "duration_seconds": video.duration_seconds,
                    "reaction_source": (
                        bool(source.reaction_source) if source is not None else False
                    ),
                    "output_orientation": (
                        source.output_orientation if source is not None else None
                    ),
                }
                if video is not None
                else None
            ),
            "channel": (
                {
                    "id": channel.id,
                    "name": channel.name,
                    "ribbon_color": channel.ribbon_color,
                }
                if channel is not None
                else None
            ),
            "metadata": (
                {
                    "revision": metadata.revision,
                    "versions": metadata_versions,
                    "status": metadata.status,
                    "title": metadata.title,
                    "description": metadata.description,
                    "tags": list(metadata.tags or []),
                    "hook": metadata.hook,
                    "thumbnail_text": metadata.thumbnail_text,
                    "content_warning": metadata.content_warning,
                    "ai_disclosure": metadata.ai_disclosure,
                    "provider_name": metadata.provider_name,
                    "created_at": (
                        metadata.created_at.isoformat()
                        if metadata.created_at
                        else None
                    ),
                }
                if metadata is not None
                else None
            ),
            "publishing": {
                "upload_status": upload_status,
                "visibility": visibility,
                "youtube_video_id": youtube_video_id,
                "youtube_url": (
                    f"https://www.youtube.com/watch?v={youtube_video_id}"
                    if youtube_video_id
                    else None
                ),
                "published_at": (
                    published.published_at.isoformat()
                    if published is not None and published.published_at
                    else None
                ),
                "public_at": (
                    published.public_at.isoformat()
                    if published is not None and published.public_at
                    else None
                ),
                "next_slot": next_slot.isoformat() if next_slot else None,
                "timezone": timezone_name,
                "publish_times": publish_times,
                "scheduled_at": (
                    published.scheduled_at.isoformat()
                    if published is not None and published.scheduled_at
                    else None
                ),
                "automation_state": automation_state,
                "metadata_approved": metadata_approved,
                "auto_approve": auto_approve,
                "daily_limit": daily_limit,
                "today_count": today_count,
            },
            "filters": filters,
            "note": note,
        }

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
