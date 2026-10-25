"""Stüdyonun nabzı: kullanıcının gözü önünde olup biteni olay akışına döker.

Panelin "ruhu" buradan beslenir — biten işler (başarı/hata), yayın
olayları ve otomasyon değişimleri tek zamansal akışta birleşir. Olaylar
iki kaynaktan gelir:

- ``jobs`` tablosu: son biten işler (succeeded/failed) — başlık/kanal
  bağlamı PipelineViewService.job_context ile zenginleştirilir.
- ``audit_events`` tablosu: yayın ve otomasyon olayları (publish.public,
  automation.started, ...).

İmleç (cursor) ISO zaman damgasıdır; istemci son gördüğü ``now``
değerini bir sonraki ``since`` olarak verir. Saat kaymalarına karşı
istemci tarafında olay kimliğiyle (id) tekilleme yapılır.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import AuditEvent, Channel, Job
from app.services.pipeline_view import PipelineViewService

# Kuyruğun geriye baktığı pencere: panel yeni açıldığında son 24 saati
# gösterir; imleçli çağrılar yalnız yenileri alır.
LOOKBACK_DEFAULT = timedelta(hours=24)
EVENT_LIMIT = 50

# Denetim olaylarının ruh tonları (arayüz hap rengiyle eşleşir).
_AUDIT_TONES: dict[str, str] = {
    "publish.public": "ok",
    "publish.private": "run",
    "publish.done": "ok",
    "publish.rescheduled": "run",
    "publish.no_ready": "warn",
    "automation.started": "run",
    "automation.stopped": "warn",
    "automation.paused": "warn",
    "automation.error": "error",
    "automation.characters": "run",
    "media.cleaned": "run",
    "media.lost_file_sweep": "warn",
    "hype.fallback": "warn",
}

# Detayda gösterilecek kısa anahtarlar (duyarlı olmayan bağlam).
_DETAIL_KEYS = ("title", "note", "reason", "orientation", "visibility", "count")


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment
    except ValueError:
        return None


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


class PulseService:
    """Son olayları tek akışta birleştirir (okuma-yalnız, ucuz sorgular)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def recent(
        self,
        since: str | None = None,
        limit: int = EVENT_LIMIT,
    ) -> dict[str, Any]:
        since_moment = _parse_since(since)
        now = datetime.now(UTC)
        window_start = since_moment or (now - LOOKBACK_DEFAULT)
        limit = max(1, min(limit, EVENT_LIMIT))

        async with self._sessionmaker() as session:
            events: list[dict[str, Any]] = []
            events.extend(await self._job_events(session, window_start, now))
            events.extend(await self._audit_events(session, window_start))
            events.sort(key=lambda item: item["created_at"], reverse=True)
            return {
                "events": events[:limit],
                "now": _iso(now),
            }

    async def _job_events(
        self, session: AsyncSession, window_start: datetime, now: datetime
    ) -> list[dict[str, Any]]:
        """Son biten işler: başarı ve hata geri bildiriminin kaynağı."""
        jobs = list(
            (
                await session.execute(
                    sa.select(Job)
                    .where(
                        Job.status.in_(("succeeded", "failed")),
                        Job.finished_at.isnot(None),
                        Job.finished_at >= window_start,
                    )
                    .order_by(Job.finished_at.desc())
                    .limit(EVENT_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        if not jobs:
            return []
        context = await PipelineViewService(
            self._sessionmaker, self._settings
        ).job_context(jobs)
        events = []
        for job in jobs:
            ctx = context.get(job.id, {})
            finished = job.finished_at
            if finished is None:  # tip daraltma; sorgu koşulu garantiliyor
                continue
            events.append(
                {
                    "id": f"job:{job.id}",
                    "kind": "job_finished",
                    "event_type": f"job.{job.status}",
                    "tone": "ok" if job.status == "succeeded" else "error",
                    "title": ctx.get("title"),
                    "channel_id": ctx.get("channel_id"),
                    "channel_name": ctx.get("channel_name"),
                    "detail": {
                        "job_type": job.job_type,
                        "attempts": job.attempts,
                        "max_attempts": job.max_attempts,
                        "last_error": job.last_error,
                    },
                    "created_at": _iso(finished) or _iso(now),
                }
            )
        return events

    async def _audit_events(
        self, session: AsyncSession, window_start: datetime
    ) -> list[dict[str, Any]]:
        """Yayın/otomasyon denetim izi: kanal adıyla birlikte."""
        rows = (
            await session.execute(
                sa.select(AuditEvent, Channel.name)
                .outerjoin(Channel, AuditEvent.channel_id == Channel.id)
                .where(
                    AuditEvent.created_at >= window_start,
                    AuditEvent.event_type.notin_(("discovery.run", "ops.summary")),
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(EVENT_LIMIT)
            )
        ).all()
        events = []
        for event, channel_name in rows:
            detail = event.detail if isinstance(event.detail, dict) else {}
            safe_detail = {
                key: detail[key] for key in _DETAIL_KEYS if key in detail
            }
            events.append(
                {
                    "id": f"audit:{event.id}",
                    "kind": "audit",
                    "event_type": event.event_type,
                    "tone": _AUDIT_TONES.get(event.event_type, "run"),
                    "title": detail.get("title"),
                    "channel_id": event.channel_id,
                    "channel_name": channel_name,
                    "detail": safe_detail or None,
                    "created_at": _iso(event.created_at),
                }
            )
        return events
