"""Source discovery: poll authorized sources, record new videos once.

Duplicate prevention is structural: source_videos carries a unique
(source_channel_id, youtube_video_id) constraint and discovery inserts
only ids it has not seen, so repeated polling never duplicates records
or downstream jobs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import SourceChannel, SourceVideo
from app.services.channel_service import record_event
from app.services.youtube_client import (
    QuotaTracker,
    YouTubeDataClient,
    YouTubeQuotaExceeded,
)


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # YouTube sends ISO-8601 with 'Z'.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class DiscoveryService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._client = YouTubeDataClient(
            settings, QuotaTracker(sessionmaker, settings.daily_quota_units)
        )

    async def _authorized_sources(
        self, session: AsyncSession, channel_id: int
    ) -> list[SourceChannel]:
        result = await session.execute(
            select(SourceChannel)
            .where(
                SourceChannel.channel_id == channel_id,
                SourceChannel.permission_status == "authorized",
            )
            .order_by(SourceChannel.id)
        )
        return list(result.scalars().all())

    async def discover_for_channel(self, channel_id: int) -> dict[str, Any]:
        """Poll every authorized source of the channel; return counters."""
        self._client.require_configured()
        new_videos = 0
        sources_checked = 0
        quota_blocked = False

        async with self._sessionmaker() as session:
            sources = await self._authorized_sources(session, channel_id)

            for source in sources:
                try:
                    uploads_playlist = await self._client.get_uploads_playlist_id(
                        source.youtube_channel_id
                    )
                    if uploads_playlist is None:
                        continue
                    videos = await self._client.list_upload_videos(uploads_playlist)
                except YouTubeQuotaExceeded:
                    quota_blocked = True
                    break

                sources_checked += 1
                known_ids = set(
                    (
                        await session.execute(
                            select(SourceVideo.youtube_video_id).where(
                                SourceVideo.source_channel_id == source.id
                            )
                        )
                    ).scalars().all()
                )
                for video in videos:
                    if video["video_id"] in known_ids:
                        continue
                    session.add(
                        SourceVideo(
                            source_channel_id=source.id,
                            youtube_video_id=video["video_id"],
                            title=video["title"],
                            published_at=_parse_published(video["published_at"]),
                        )
                    )
                    known_ids.add(video["video_id"])
                    new_videos += 1

            record_event(
                session,
                channel_id,
                "discovery.run",
                {
                    "sources_checked": sources_checked,
                    "new_videos": new_videos,
                    "quota_blocked": quota_blocked,
                },
            )
            await session.commit()

        return {
            "sources_checked": sources_checked,
            "new_videos": new_videos,
            "quota_blocked": quota_blocked,
        }

    async def list_videos(self, channel_id: int) -> list[SourceVideo]:
        """Discovered videos across all sources of a studio channel."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(SourceVideo)
                .join(SourceChannel, SourceVideo.source_channel_id == SourceChannel.id)
                .where(SourceChannel.channel_id == channel_id)
                .order_by(SourceVideo.discovered_at, SourceVideo.id)
            )
            return list(result.scalars().all())
