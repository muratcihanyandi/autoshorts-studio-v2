"""Günlükler görünümü: audit_events salt-okunur, sayfalanabilir akış.

Filtreler: kanal, olay kategorisi (event_type'in ilk noktaya kadar
kısmı: media, llm, oauth, ...) ve imleç (before_id) sayfalama.

Ayrıca birleşik hata akışı (errors): başarısız işler, başarısız medya
varlıkları ve başarısız yükleme satırları — tam hata metniyle. Olay
günlüğündeki kalabalıktan bağımsız, operatörün asıl soruna inmesi
içindir (2026-10-23 kullanıcı isteği: "hatayı net göremiyorum").
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import AuditEvent, Channel, Job, MediaAsset, PublishedVideo

DEFAULT_LIMIT = 80
MAX_LIMIT = 300
ERRORS_LIMIT = 60


def event_category(event_type: str) -> str:
    """'media.download' -> 'media'; noktasız tipler oldugu gibi kalir."""
    return event_type.split(".", 1)[0] if "." in event_type else event_type


class AuditViewService:
    """Günlükler ekranının verisi: olay sayfası + filtre seçenekleri."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def page(
        self,
        limit: int = DEFAULT_LIMIT,
        before_id: int | None = None,
        channel_id: int | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, MAX_LIMIT))
        async with self._sessionmaker() as session:
            statement = (
                sa.select(AuditEvent, Channel.name, Channel.ribbon_color)
                .outerjoin(Channel, AuditEvent.channel_id == Channel.id)
                .order_by(AuditEvent.id.desc())
                .limit(limit + 1)
            )
            if before_id is not None:
                statement = statement.where(AuditEvent.id < before_id)
            if channel_id is not None:
                statement = statement.where(AuditEvent.channel_id == channel_id)
            if category:
                # LIKE kalibinda % ve _ anlamli: escape edilir.
                escaped = category.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
                statement = statement.where(
                    sa.or_(
                        AuditEvent.event_type.like(f"{escaped}.%", escape="\\"),
                        AuditEvent.event_type == category,
                    )
                )
            rows = (await session.execute(statement)).all()

            has_more = len(rows) > limit
            rows = rows[:limit]

            entries: list[dict[str, Any]] = []
            for event, channel_name, ribbon in rows:
                entries.append(
                    {
                        "id": event.id,
                        "ts": (
                            event.created_at.isoformat()
                            if event.created_at
                            else None
                        ),
                        "channel_id": event.channel_id,
                        "channel_name": channel_name,
                        "ribbon_color": ribbon,
                        "event_type": event.event_type,
                        "category": event_category(event.event_type),
                        "detail": event.detail,
                    }
                )

            categories = await self._categories(session)
            channels = await self._channels(session)

        return {
            "entries": entries,
            "has_more": has_more,
            "categories": categories,
            "channels": channels,
        }

    @staticmethod
    async def _categories(session: AsyncSession) -> list[str]:
        rows = (
            (
                await session.execute(
                    sa.select(AuditEvent.event_type).distinct().limit(200)
                )
            )
            .scalars()
            .all()
        )
        return sorted({event_category(r) for r in rows})

    # --- birlesik hata akisi ---

    JOB_TYPE_LABELS = {
        "media_process": "Video işleme",
        "clip_render": "Klip render",
        "clip_render_full_cut": "Yatay tam kesit render",
        "metadata_generate": "Metaveri üretimi",
        "hype_evaluate": "Hype değerlendirmesi",
        "publish_clip": "Klip yükleme",
        "publish_full_cut": "Tam kesit yükleme",
        "publish_due": "Planlı yayın",
        "source_discover": "Kaynak keşfi",
        "subtitle_correct": "Altyazı düzeltme",
        "ops_summary": "Günlük özet",
    }

    async def errors(self, limit: int = ERRORS_LIMIT) -> dict[str, Any]:
        """Son başarısızlıklar: işler, medya varlıkları, yükleme satırları.

        Her kayıt tam hata metnini, hangi videoda olduğunu ve operatörün
        düzeltme yolunu taşır (iş yeniden deneme / video devam ettirme)."""
        limit = max(1, min(limit, 200))
        async with self._sessionmaker() as session:
            jobs = (
                (
                    await session.execute(
                        sa.select(Job)
                        .where(Job.status == "failed")
                        .order_by(Job.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            assets = (
                (
                    await session.execute(
                        sa.select(MediaAsset)
                        .where(MediaAsset.status == "failed")
                        .order_by(MediaAsset.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            uploads = (
                (
                    await session.execute(
                        sa.select(PublishedVideo)
                        .where(PublishedVideo.status == "failed")
                        .order_by(PublishedVideo.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )

            # Video basligi + kanal baglami (basarisizliklarin sahibi).
            from app.models import ClipCandidate, SourceChannel, SourceVideo

            video_ids: set[int] = set()
            candidate_ids: set[int] = set()
            for job in jobs:
                payload = job.payload or {}
                sv = payload.get("source_video_id")
                if isinstance(sv, int):
                    video_ids.add(sv)
                cand = payload.get("clip_candidate_id")
                if isinstance(cand, int):
                    candidate_ids.add(cand)
            for asset in assets:
                video_ids.add(asset.source_video_id)
            for row in uploads:
                if row.source_video_id is not None:
                    video_ids.add(row.source_video_id)
                if row.clip_candidate_id is not None:
                    candidate_ids.add(row.clip_candidate_id)
            if candidate_ids:
                rows = (
                    (
                        await session.execute(
                            sa.select(
                                ClipCandidate.id,
                                ClipCandidate.source_video_id,
                            ).where(ClipCandidate.id.in_(candidate_ids))
                        )
                    )
                    .all()
                )
                for _cand, sv in rows:
                    video_ids.add(sv)
            titles: dict[int, str] = {}
            channels: dict[int, tuple[str, str | None]] = {}
            if video_ids:
                rows = (
                    (
                        await session.execute(
                            sa.select(
                                SourceVideo.id,
                                SourceVideo.title,
                                Channel.id,
                                Channel.name,
                                Channel.ribbon_color,
                            )
                            .join(
                                SourceChannel,
                                SourceVideo.source_channel_id
                                == SourceChannel.id,
                            )
                            .outerjoin(
                                Channel, SourceChannel.channel_id == Channel.id
                            )
                            .where(SourceVideo.id.in_(video_ids))
                        )
                    )
                    .all()
                )
                for vid, title, cid, cname, ribbon in rows:
                    titles[vid] = title
                    if cid is not None:
                        channels[vid] = (cname, ribbon)

            def _context(payload_or_video: dict | int):
                vid = None
                if isinstance(payload_or_video, int):
                    vid = payload_or_video
                else:
                    sv = payload_or_video.get("source_video_id")
                    if isinstance(sv, int):
                        vid = sv
                channel = channels.get(vid) if vid is not None else None
                return {
                    "title": titles.get(vid) if vid is not None else None,
                    "source_video_id": vid,
                    "channel_name": channel[0] if channel else None,
                    "ribbon_color": channel[1] if channel else None,
                }

            items: list[dict[str, Any]] = []
            for job in jobs:
                ctx = _context(job.payload or {})
                items.append(
                    {
                        "kind": "job",
                        "id": job.id,
                        "ts": (
                            (job.finished_at or job.updated_at).isoformat()
                            if (job.finished_at or job.updated_at)
                            else None
                        ),
                        "what": self.JOB_TYPE_LABELS.get(
                            job.job_type, job.job_type
                        ),
                        "error": job.last_error,
                        "attempts": job.attempts,
                        "max_attempts": job.max_attempts,
                        "retry_job_id": job.id,
                        "stage": None,
                        "resume_video_id": None,
                        **ctx,
                    }
                )
            for asset in assets:
                ctx = _context(asset.source_video_id)
                items.append(
                    {
                        "kind": "asset",
                        "id": asset.id,
                        "ts": (
                            asset.updated_at.isoformat()
                            if asset.updated_at
                            else None
                        ),
                        "what": "Video işleme",
                        "error": asset.last_error,
                        "attempts": None,
                        "max_attempts": None,
                        "retry_job_id": None,
                        "stage": asset.stage,
                        "resume_video_id": asset.source_video_id,
                        **ctx,
                    }
                )
            for row in uploads:
                vid = (
                    row.source_video_id
                    if row.source_video_id is not None
                    else None
                )
                if vid is None and row.clip_candidate_id is not None:
                    cand = await session.get(
                        ClipCandidate, row.clip_candidate_id
                    )
                    vid = cand.source_video_id if cand else None
                ctx = _context(vid if vid is not None else {})
                items.append(
                    {
                        "kind": "upload",
                        "id": row.id,
                        "ts": (
                            row.updated_at.isoformat()
                            if row.updated_at
                            else None
                        ),
                        "what": "YouTube yükleme",
                        "error": row.last_error,
                        "attempts": None,
                        "max_attempts": None,
                        "retry_job_id": None,
                        "stage": None,
                        "resume_video_id": None,
                        **ctx,
                    }
                )
            items = [i for i in items if i["error"]]
            items.sort(key=lambda i: i["ts"] or "", reverse=True)
            return {"errors": items[:limit], "total": len(items)}

    @staticmethod
    async def _channels(session: AsyncSession) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    sa.select(Channel.id, Channel.name, Channel.ribbon_color).order_by(
                        Channel.id
                    )
                )
            )
            .all()
        )
        return [
            {"id": r[0], "name": r[1], "ribbon_color": r[2]} for r in rows
        ]
