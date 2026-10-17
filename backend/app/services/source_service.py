"""Source channel service: registration + rights records + audit trail.

A source channel is only eligible for monitoring while its permission
status is 'authorized'; authorization is an explicit user act recorded
with a timestamp (rights record).
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import SourceChannel
from app.repositories.sources import SourceRepository
from app.schemas_sources import SourceCreate, SourceUpdate
from app.services.channel_service import record_event


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SourceServiceError(Exception):
    """Business rule failure with a user-facing Turkish message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class SourceService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_sources(self, channel_id: int) -> list[SourceChannel]:
        async with self._sessionmaker() as session:
            return await SourceRepository(session).list_for_channel(channel_id)

    async def get_source(self, source_id: int) -> SourceChannel | None:
        async with self._sessionmaker() as session:
            return await SourceRepository(session).get(source_id)

    async def add_source(
        self, channel_id: int, data: SourceCreate
    ) -> SourceChannel:
        async with self._sessionmaker() as session:
            repo = SourceRepository(session)
            existing = await repo.get_for_channel(
                channel_id, data.youtube_channel_id
            )
            if existing is not None:
                raise SourceServiceError(
                    "Bu kaynak kanal bu stüdyo kanalına zaten kayıtlı.",
                    status_code=409,
                )
            source = await repo.create(channel_id, data)
            record_event(
                session,
                channel_id,
                "source.added",
                {"youtube_channel_id": data.youtube_channel_id},
            )
            await session.commit()
            await session.refresh(source)
            return source

    async def update_source(
        self, source_id: int, data: SourceUpdate
    ) -> SourceChannel | None:
        async with self._sessionmaker() as session:
            repo = SourceRepository(session)
            source = await repo.get(source_id)
            if source is None:
                return None

            changes = data.model_dump(exclude_unset=True)
            title_changed = "title" in changes
            if title_changed:
                source.title = changes["title"]
            if "filter_rules" in changes:
                source.filter_rules = changes["filter_rules"] or {}

            new_permission = changes.get("permission_status")
            permission_changed = (
                new_permission is not None
                and source.permission_status != new_permission
            )
            if permission_changed:
                source.permission_status = new_permission
                source.authorized_at = (
                    _utcnow() if new_permission == "authorized" else None
                )
                record_event(
                    session,
                    source.channel_id,
                    f"source.{new_permission}",
                    {
                        "source_id": source_id,
                        "youtube_channel_id": source.youtube_channel_id,
                    },
                )

            if not title_changed and not permission_changed:
                # Aynı duruma geçiş hak kaydı yazmaz (idempotent).
                return source

            await session.commit()
            await session.refresh(source)
            return source

    async def delete_source(self, source_id: int) -> bool:
        async with self._sessionmaker() as session:
            repo = SourceRepository(session)
            source = await repo.get(source_id)
            if source is None:
                return False
            channel_id = source.channel_id
            youtube_id = source.youtube_channel_id
            await repo.delete(source)
            record_event(
                session,
                channel_id,
                "source.removed",
                {"source_id": source_id, "youtube_channel_id": youtube_id},
            )
            await session.commit()
            return True

    async def count_authorized(self, channel_id: int | None = None) -> int:
        async with self._sessionmaker() as session:
            return await SourceRepository(session).count_authorized(channel_id)
