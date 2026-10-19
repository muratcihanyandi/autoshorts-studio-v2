"""Canlı boru hattı görünümü: Genel Bakış'ın 'canlı işler' panelini besler.

Her şey kalıcı DB durumundan türetilir: aktif işler (aşama, geçen süre,
indirme baytı), kuyruktaki işler ve son sonuçlar. Tahminler son
tamamlanan işlerin GERÇEK sürelerinden hesaplanır ve 'tahmini' olarak
etiketlenir — hiçbir sayı uydurulmaz, ortalama yoksa alan null kalır.

Job -> video/kanal eşlemesi payload JSON'undan Python tarafında yapılır;
sorgular PostgreSQL ve sqlite üzerinde aynı çalışır (testler sqlite).
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Channel, Job, MediaAsset, SourceChannel, SourceVideo

# Yatay medya isleme boru hattinin asamalari (media_pipeline.STAGES ile
# ayni sirada tutulmalidir; kopya kalmamasi icin import yerine burada
# tekrar yazildi cunku media_pipeline bu servise baglanmamali).
PIPELINE_STAGES = (
    "download",
    "inspect",
    "transcript",
    "analysis",
    "candidates",
)

# Tahmin hesabi icin geriye kac is/_varliga bakilir.
_AVG_JOB_SAMPLES = 10
_AVG_BYTES_SAMPLES = 5


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class PipelineViewService:
    """Aktif/kuyruk/son islerin operator görünümü (salt okunur)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def overview(self) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            running = (
                (
                    await session.execute(
                        sa.select(Job)
                        .where(Job.status == "running")
                        .order_by(Job.id.asc())
                        .limit(50)
                    )
                )
                .scalars()
                .all()
            )
            queued = (
                (
                    await session.execute(
                        sa.select(Job)
                        .where(Job.status == "queued")
                        .order_by(Job.priority.asc(), Job.run_at.asc(), Job.id.asc())
                        .limit(20)
                    )
                )
                .scalars()
                .all()
            )
            recent = (
                (
                    await session.execute(
                        sa.select(Job)
                        .where(Job.status.in_(("succeeded", "failed")))
                        .order_by(Job.id.desc())
                        .limit(30)
                    )
                )
                .scalars()
                .all()
            )
            context = await self._resolve_context(session, running, queued, recent)
            averages = await self._job_averages(session)
            expected_bytes = await self._expected_download_bytes(session)
            sources = await self._sources(session)

        active_cards = [
            self._active_card(job, context, averages, expected_bytes)
            for job in running
        ]
        queued_cards = [
            self._queued_card(job, context, position)
            for position, job in enumerate(queued, start=1)
        ]
        recent_cards = [
            self._recent_card(job, context) for job in recent[:8]
        ]
        return {
            "active": active_cards,
            "queued": queued_cards,
            "recent": recent_cards,
            "sources": sources,
            "now": _utcnow().isoformat(),
        }

    async def job_context(self, jobs: list[Job]) -> dict[int, dict[str, Any]]:
        """Is listesi -> video/kanal baglami. Isler API'sinin her satirini
        video basligiyla zenginlestirmek icin acik kapidir; ayni cozucu
        overview() de kullanir."""
        async with self._sessionmaker() as session:
            return await self._resolve_context(session, tuple(jobs))

    # --- baglam cozumu ---

    async def _resolve_context(
        self,
        session: AsyncSession,
        *job_groups: tuple[Job, ...],
    ) -> dict[int, dict[str, Any]]:
        """job_id -> {title, channel_name, channel_id, ribbon_color,
        source_video_id, asset_stage, asset_status} eslemesi."""
        jobs = [job for group in job_groups for job in group]
        video_ids: set[int] = set()
        channel_ids: set[int] = set()
        candidate_ids: set[int] = set()
        for job in jobs:
            payload = job.payload or {}
            sv = payload.get("source_video_id")
            if isinstance(sv, int):
                video_ids.add(sv)
            cid = payload.get("channel_id")
            if isinstance(cid, int):
                channel_ids.add(cid)
            cand = payload.get("clip_candidate_id")
            if isinstance(cand, int):
                candidate_ids.add(cand)

        # Aday -> video eslemesi (tek sorgu).
        if candidate_ids:
            from app.models import ClipCandidate

            rows = (
                (
                    await session.execute(
                        sa.select(ClipCandidate.id, ClipCandidate.source_video_id).where(
                            ClipCandidate.id.in_(candidate_ids)
                        )
                    )
                )
                .all()
            )
            for _cand_id, sv_id in rows:
                video_ids.add(sv_id)

        videos: dict[int, dict[str, Any]] = {}
        if video_ids:
            rows = (
                (
                    await session.execute(
                        sa.select(
                            SourceVideo.id,
                            SourceVideo.title,
                            SourceVideo.duration_seconds,
                            SourceChannel.channel_id,
                        )
                        .join(SourceChannel, SourceVideo.source_channel_id == SourceChannel.id)
                        .where(SourceVideo.id.in_(video_ids))
                    )
                )
                .all()
            )
            channels = await self._channels_by_id(session, {r[3] for r in rows})
            for vid, title, duration, cid in rows:
                channel = channels.get(cid)
                videos[vid] = {
                    "title": title,
                    "duration_seconds": duration,
                    "channel_id": cid,
                    "channel_name": channel["name"] if channel else None,
                    "ribbon_color": channel["ribbon_color"] if channel else None,
                }
                channel_ids.add(cid)

        # Video'suz ama kanalli isler (source_discover, publish_due, ...).
        for job in jobs:
            payload = job.payload or {}
            cid = payload.get("channel_id")
            if isinstance(cid, int):
                channel_ids.add(cid)
        channels_all = await self._channels_by_id(session, channel_ids)

        assets = await self._assets_by_video(session, video_ids)

        context: dict[int, dict[str, Any]] = {}
        for job in jobs:
            payload = job.payload or {}
            sv = payload.get("source_video_id") if isinstance(
                payload.get("source_video_id"), int
            ) else None
            video = videos.get(sv) if sv is not None else None
            cid = (video or {}).get("channel_id") or payload.get("channel_id")
            channel = channels_all.get(cid) if isinstance(cid, int) else None
            asset = assets.get(sv) if sv is not None else None
            context[job.id] = {
                "title": (video or {}).get("title"),
                "duration_seconds": (video or {}).get("duration_seconds"),
                "channel_id": cid if isinstance(cid, int) else None,
                "channel_name": (channel or {}).get("name") if channel else None,
                "ribbon_color": (channel or {}).get("ribbon_color") if channel else None,
                "source_video_id": sv,
                "asset_stage": asset.stage if asset else None,
                "asset_status": asset.status if asset else None,
            }
        return context

    @staticmethod
    async def _sources(session: AsyncSession) -> list[dict[str, Any]]:
        """Detay penceresinin kaynak listesi: yetkili kaynak kanallar,
        bagli olduklari yayin kanali ve izleme havuzundaki video sayisi
        (haric tutulanlar sayilmaz)."""
        rows = (
            (
                await session.execute(
                    sa.select(
                        SourceChannel.id,
                        SourceChannel.title,
                        SourceChannel.platform,
                        Channel.name,
                        Channel.ribbon_color,
                        sa.func.sum(
                            sa.case(
                                (SourceVideo.status != "excluded", 1),
                                else_=0,
                            )
                        ),
                    )
                    .join(Channel, SourceChannel.channel_id == Channel.id)
                    .outerjoin(
                        SourceVideo,
                        SourceVideo.source_channel_id == SourceChannel.id,
                    )
                    .where(SourceChannel.permission_status == "authorized")
                    .group_by(SourceChannel.id, Channel.id)
                    .order_by(Channel.name.asc(), SourceChannel.title.asc())
                )
            )
            .all()
        )
        return [
            {
                "id": source_id,
                "title": title,
                "platform": platform,
                "channel_name": channel_name,
                "ribbon_color": ribbon_color,
                "videos": int(videos or 0),
            }
            for source_id, title, platform, channel_name, ribbon_color, videos in rows
        ]

    @staticmethod
    async def _channels_by_id(
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
    async def _assets_by_video(
        session: AsyncSession, video_ids: set[int]
    ) -> dict[int, MediaAsset]:
        if not video_ids:
            return {}
        rows = (
            (
                await session.execute(
                    sa.select(MediaAsset).where(
                        MediaAsset.source_video_id.in_(video_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        return {asset.source_video_id: asset for asset in rows}

    # --- tahminler ---

    async def _job_averages(
        self, session: AsyncSession
    ) -> dict[str, float | None]:
        """Is tipi basina ortalama tamamlanma suresi (saniye, son N is)."""
        rows = (
            (
                await session.execute(
                    sa.select(Job)
                    .where(Job.status == "succeeded")
                    .order_by(Job.id.desc())
                    .limit(400)
                )
            )
            .scalars()
            .all()
        )
        buckets: dict[str, list[float]] = {}
        for job in rows:
            started = _as_utc(job.started_at)
            finished = _as_utc(job.finished_at)
            if started is None or finished is None:
                continue
            seconds = (finished - started).total_seconds()
            if seconds < 0:
                continue
            buckets.setdefault(job.job_type, []).append(seconds)
        return {
            job_type: sum(values[:_AVG_JOB_SAMPLES]) / len(values[:_AVG_JOB_SAMPLES])
            for job_type, values in buckets.items()
            if values
        }

    async def _expected_download_bytes(
        self, session: AsyncSession
    ) -> float | None:
        """Son islenen varliklarin ortalama boyutu: indirme tahmininin
        paydasidir. Veri yoksa tahmin yapilmaz (None)."""
        rows = (
            (
                await session.execute(
                    sa.select(MediaAsset.file_bytes)
                    .where(
                        MediaAsset.status == "processed",
                        MediaAsset.file_bytes > 0,
                    )
                    .order_by(MediaAsset.id.desc())
                    .limit(_AVG_BYTES_SAMPLES)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return None
        return float(sum(rows) / len(rows))

    # --- kart olusturma ---

    def _active_card(
        self,
        job: Job,
        context: dict[int, dict[str, Any]],
        averages: dict[str, float | None],
        expected_bytes: float | None,
    ) -> dict[str, Any]:
        ctx = context.get(job.id, {})
        stage = ctx.get("asset_stage") if job.job_type == "media_process" else None
        stage_index = (
            PIPELINE_STAGES.index(stage) if stage in PIPELINE_STAGES else None
        )
        started = _as_utc(job.started_at)
        elapsed = (
            round(( _utcnow() - started).total_seconds()) if started else None
        )
        average = averages.get(job.job_type)
        eta = None
        if average is not None and elapsed is not None:
            eta = max(0.0, round(average - elapsed))
        download = None
        if stage == "download" and ctx.get("source_video_id") is not None:
            part_bytes = self._part_bytes(ctx["source_video_id"])
            if part_bytes is not None:
                download = {
                    "bytes": part_bytes,
                    "expected_bytes": (
                        round(expected_bytes) if expected_bytes else None
                    ),
                }
        return {
            "job_id": job.id,
            "job_type": job.job_type,
            "source_video_id": ctx.get("source_video_id"),
            "title": ctx.get("title"),
            "channel_id": ctx.get("channel_id"),
            "channel_name": ctx.get("channel_name"),
            "ribbon_color": ctx.get("ribbon_color"),
            "stage": stage,
            "stage_index": stage_index,
            "stage_count": len(PIPELINE_STAGES),
            "elapsed_seconds": elapsed,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "eta_seconds": eta,
            "average_seconds": (
                round(average) if average is not None else None
            ),
            "download": download,
            "last_error": None,
        }

    def _queued_card(
        self, job: Job, context: dict[int, dict[str, Any]], position: int
    ) -> dict[str, Any]:
        ctx = context.get(job.id, {})
        return {
            "job_id": job.id,
            "job_type": job.job_type,
            "title": ctx.get("title"),
            "channel_name": ctx.get("channel_name"),
            "position": position,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
        }

    def _recent_card(
        self, job: Job, context: dict[int, dict[str, Any]]
    ) -> dict[str, Any]:
        ctx = context.get(job.id, {})
        started = _as_utc(job.started_at)
        finished = _as_utc(job.finished_at)
        duration = None
        if started is not None and finished is not None:
            duration = round((finished - started).total_seconds())
        error = job.last_error
        return {
            "job_id": job.id,
            "job_type": job.job_type,
            "title": ctx.get("title"),
            "channel_name": ctx.get("channel_name"),
            "status": job.status,
            "duration_seconds": duration,
            "error": error[:140] if error else None,
            "finished_at": (
                finished.isoformat() if finished else None
            ),
        }

    # --- indirme dosyasi olcumu ---

    def _part_bytes(self, source_video_id: int) -> int | None:
        """Downloads dizinindeki yarim indirme dosyasinin boyutu.
        Disk erisilemezse None: panel tahminsiz de calisir."""
        root = self._settings.media_root
        if not root:
            return None
        downloads = Path(root) / "downloads"
        try:
            parts = list(downloads.glob(f"{source_video_id}.*.part"))
        except OSError:
            return None
        if not parts:
            return None
        try:
            return max(p.stat().st_size for p in parts)
        except OSError:
            return None
