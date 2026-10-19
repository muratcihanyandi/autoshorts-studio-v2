"""Channel data access (repository layer)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChannelStatus
from app.schemas import ChannelCreate, ChannelUpdate


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[Channel]:
        result = await self._session.execute(
            select(Channel).order_by(Channel.created_at, Channel.id)
        )
        return list(result.scalars().all())

    async def get(self, channel_id: int) -> Channel | None:
        return await self._session.get(Channel, channel_id)

    async def get_by_youtube_id(self, youtube_channel_id: str) -> Channel | None:
        result = await self._session.execute(
            select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)
        )
        return result.scalars().one_or_none()

    async def create(self, data: ChannelCreate) -> Channel:
        channel = Channel(
            name=data.name,
            handle=data.handle,
            ribbon_color=data.ribbon_color,
            notes=data.notes,
        )
        self._session.add(channel)
        await self._session.flush()
        return channel

    async def update(self, channel: Channel, data: ChannelUpdate) -> Channel:
        changes = data.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(channel, field, value)
        await self._session.flush()
        return channel

    async def delete(self, channel: Channel) -> None:
        await self._session.delete(channel)
        await self._session.flush()

    async def count_connected(self) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Channel)
            .where(Channel.status == ChannelStatus.connected)
        )
        return result.scalar_one()
