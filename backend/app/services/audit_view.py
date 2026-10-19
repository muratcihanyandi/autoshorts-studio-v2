"""Günlükler görünümü: audit_events salt-okunur, sayfalanabilir akış.

Filtreler: kanal, olay kategorisi (event_type'in ilk noktaya kadar
kısmı: media, llm, oauth, ...) ve imleç (before_id) sayfalama.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import AuditEvent, Channel

DEFAULT_LIMIT = 80
MAX_LIMIT = 300


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
