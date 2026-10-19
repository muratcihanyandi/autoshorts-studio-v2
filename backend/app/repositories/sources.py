"""Source channel data access (repository layer)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SourceChannel, SourceVideo
from app.schemas_sources import SourceCreate


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_channel(self, channel_id: int) -> list[SourceChannel]:
        result = await self._session.execute(
            select(SourceChannel)
            .where(SourceChannel.channel_id == channel_id)
            .order_by(SourceChannel.created_at, SourceChannel.id)
        )
        return list(result.scalars().all())

    async def get(self, source_id: int) -> SourceChannel | None:
        return await self._session.get(SourceChannel, source_id)

    async def get_for_channel(
        self, channel_id: int, youtube_channel_id: str
    ) -> SourceChannel | None:
        result = await self._session.execute(
            select(SourceChannel).where(
                SourceChannel.channel_id == channel_id,
                SourceChannel.youtube_channel_id == youtube_channel_id,
            )
        )
        return result.scalars().one_or_none()

    async def create(
        self, channel_id: int, data: SourceCreate
    ) -> SourceChannel:
        source = SourceChannel(
            channel_id=channel_id,
            youtube_channel_id=data.youtube_channel_id,
            title=data.title,
            platform=data.platform,
            character_id=data.character_id,
            reaction_source=data.reaction_source,
            trim_start_seconds=data.trim_start_seconds,
            trim_end_seconds=data.trim_end_seconds,
            filter_rules=data.filter_rules or {},
        )
        self._session.add(source)
        await self._session.flush()
        return source

    async def delete(self, source: SourceChannel) -> None:
        await self._session.delete(source)
        await self._session.flush()

    async def count_authorized(self, channel_id: int | None = None) -> int:
        query = (
            select(func.count())
            .select_from(SourceChannel)
            .where(SourceChannel.permission_status == "authorized")
        )
        if channel_id is not None:
            query = query.where(SourceChannel.channel_id == channel_id)
        result = await self._session.execute(query)
        return result.scalar_one()

    # --- M13: manuel VOD ice aktarimi ---

    async def get_video(
        self, source_id: int, video_key: str
    ) -> SourceVideo | None:
        result = await self._session.execute(
            select(SourceVideo).where(
                SourceVideo.source_channel_id == source_id,
                SourceVideo.youtube_video_id == video_key,
            )
        )
        return result.scalars().one_or_none()

    async def create_video(
        self, source_id: int, video_key: str, title: str
    ) -> SourceVideo:
        video = SourceVideo(
            source_channel_id=source_id,
            youtube_video_id=video_key,
            title=title,
            status="planned",
        )
        self._session.add(video)
        await self._session.flush()
        return video
