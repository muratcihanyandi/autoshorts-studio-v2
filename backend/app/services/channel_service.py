"""Channel service: business rules + audit trail.

Every state-changing operation writes an audit event. OAuth token
handling lives with the OAuth service; this layer never touches token
material.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditEvent, Channel, ChannelStatus, PublishingProfile
from app.repositories.channels import ChannelRepository
from app.schemas import ChannelCreate, ChannelUpdate


def record_event(
    session: AsyncSession,
    channel_id: int | None,
    event_type: str,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(channel_id=channel_id, event_type=event_type, detail=detail)
    session.add(event)
    return event


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ChannelService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_channels(self) -> list[Channel]:
        async with self._sessionmaker() as session:
            return await ChannelRepository(session).list()

    async def count_owned_channels(self, user_id: int) -> int:
        """Kullanicinin sahip oldugu kanal sayisi (free plan limiti)."""
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(Channel.id).where(Channel.owner_user_id == user_id)
            )
            return len(rows.all())

    async def count_connected(self) -> int:
        async with self._sessionmaker() as session:
            return await ChannelRepository(session).count_connected()

    async def get_channel(self, channel_id: int) -> Channel | None:
        async with self._sessionmaker() as session:
            return await ChannelRepository(session).get(channel_id)

    async def create_channel(
        self, data: ChannelCreate, owner_user_id: int | None = None
    ) -> Channel:
        async with self._sessionmaker() as session:
            repo = ChannelRepository(session)
            channel = await repo.create(data)
            # Hesap izolasyonu (madde 6): kanalı oluşturan hesaba bagla.
            channel.owner_user_id = owner_user_id
            # Her kanal kendi yayın profiliyle doğar (kanal bazlı ayarlar).
            session.add(PublishingProfile(channel_id=channel.id))
            record_event(session, channel.id, "channel.created", {"name": data.name})
            await session.commit()
            await session.refresh(channel)
            return channel

    async def update_channel(self, channel_id: int, data: ChannelUpdate) -> Channel | None:
        async with self._sessionmaker() as session:
            repo = ChannelRepository(session)
            channel = await repo.get(channel_id)
            if channel is None:
                return None
            changes = data.model_dump(exclude_unset=True)
            await repo.update(channel, data)
            record_event(
                session, channel.id, "channel.updated", {"fields": sorted(changes)}
            )
            await session.commit()
            await session.refresh(channel)
            return channel

    async def delete_channel(self, channel_id: int) -> bool:
        async with self._sessionmaker() as session:
            repo = ChannelRepository(session)
            channel = await repo.get(channel_id)
            if channel is None:
                return False
            name = channel.name
            # Olay, kanal satırı silinmeden önce yazılmalı (FK); kanal
            # silinince audit_events.channel_id ON DELETE SET NULL ile korunur.
            record_event(session, channel_id, "channel.deleted", {"name": name})
            await session.flush()
            await repo.delete(channel)
            await session.commit()
            return True

    async def disconnect_channel(self, channel_id: int) -> Channel | None:
        """Mark disconnected and drop the credential row (token material goes)."""
        from sqlalchemy import delete

        from app.models import OAuthCredential

        async with self._sessionmaker() as session:
            repo = ChannelRepository(session)
            channel = await repo.get(channel_id)
            if channel is None:
                return None
            channel.status = ChannelStatus.disconnected
            channel.last_disconnected_at = _utcnow()
            await session.execute(
                delete(OAuthCredential).where(OAuthCredential.channel_id == channel_id)
            )
            record_event(session, channel_id, "channel.disconnected")
            await session.commit()
            await session.refresh(channel)
            return channel
