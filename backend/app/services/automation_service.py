"""End-to-end automation service (M11).

Connects the stages the worker already runs and adds the publish-time
decision logic: daily targets, stock levels, pause/resume. Publishing
never fabricates content — an empty stock publishes nothing and says
so; a met daily target waits for the next slot; a paused channel is
skipped entirely. Operational summaries land in the append-only audit
trail so the studio's day is reconstructable.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Channel,
    ClipCandidate,
    PublishedVideo,
    PublishingProfile,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.channel_service import record_event
from app.services.publishing_service import PublishingService
from app.services.publishing_schedule import ScheduleError


class AutomationError(Exception):
    """Automation failure with a user-facing Turkish message."""


class AutomationService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._publishing = PublishingService(sessionmaker, settings)

    async def profile(self, channel_id: int) -> PublishingProfile:
        """Get-or-create the channel's publishing profile."""
        async with self._sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        sa.select(PublishingProfile).where(
                            PublishingProfile.channel_id == channel_id
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if row is None:
                row = PublishingProfile(channel_id=channel_id)
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return row

    async def stock_level(self, channel_id: int) -> int:
        """Ready unpublished clips: rendered, rights-authorized, not
        published. Empty stock must never trigger unsafe publication."""
        return (
            await self._count(
                sa.select(sa.func.count())
                .select_from(ClipCandidate)
                .join(
                    SourceVideo,
                    ClipCandidate.source_video_id == SourceVideo.id,
                )
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .join(
                    RenderedClip,
                    RenderedClip.clip_candidate_id == ClipCandidate.id,
                )
                .outerjoin(
                    PublishedVideo,
                    PublishedVideo.clip_candidate_id == ClipCandidate.id,
                )
                .where(
                    SourceChannel.channel_id == channel_id,
                    SourceChannel.permission_status == "authorized",
                    RenderedClip.status == "rendered",
                    PublishedVideo.id.is_(None),
                )
            )
        )

    async def daily_published_count(self, channel_id: int) -> int:
        """Publications since local midnight (profile timezone)."""
        profile = await self.profile(channel_id)
        tz_name = profile.timezone or "UTC"
        try:
            from zoneinfo import ZoneInfo

            local_now = datetime.now(ZoneInfo(tz_name))
        except Exception:  # noqa: BLE001 - bilinmeyen saat dilimi: UTC
            local_now = datetime.now(UTC)
        midnight_utc = local_now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).astimezone(UTC)
        return (
            await self._count(
                sa.select(sa.func.count())
                .select_from(PublishedVideo)
                .where(
                    PublishedVideo.channel_id == channel_id,
                    PublishedVideo.status == "verified",
                    PublishedVideo.published_at >= midnight_utc,
                )
            )
        )

    async def publish_for_channel(self, channel_id: int) -> dict:
        """Target-, stock-, and pause-aware publish decision."""
        profile = await self.profile(channel_id)
        settings = profile.settings or {}
        if settings.get("paused"):
            return {
                "channel_id": channel_id,
                "published": 0,
                "reason": "kanal duraklatildi",
            }
        daily_target = max(0, profile.daily_clip_target)
        published_today = await self.daily_published_count(channel_id)
        if daily_target and published_today >= daily_target:
            return {
                "channel_id": channel_id,
                "published": 0,
                "reason": f"gunluk hedef dolu ({published_today}/{daily_target})",
            }
        stock = await self.stock_level(channel_id)
        candidate_id = await self._publishing.next_ready_candidate(channel_id)
        if candidate_id is None:
            # Stok yetersiz: guvensiz yayin YOK, kayit dusulur.
            await self._audit(
                channel_id,
                "publish.stock_low",
                {"stock": stock, "daily_target": daily_target},
            )
            return {
                "channel_id": channel_id,
                "published": 0,
                "reason": "yayina hazir klip yok (stok bos)",
                "stock": stock,
            }
        result = await self._publishing.publish_clip(candidate_id)
        return {"channel_id": channel_id, "published": 1, **result}

    async def operational_summary(self, channel_id: int) -> dict:
        """Stage counts + today's publishing state; audited."""
        profile = await self.profile(channel_id)
        summary = {
            "channel_id": channel_id,
            "discovered": await self._count(
                sa.select(sa.func.count())
                .select_from(SourceVideo)
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(SourceChannel.channel_id == channel_id)
            ),
            "planned": await self._count(
                sa.select(sa.func.count())
                .select_from(SourceVideo)
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(
                    SourceChannel.channel_id == channel_id,
                    SourceVideo.status == "planned",
                )
            ),
            "processed": await self._count(
                sa.select(sa.func.count())
                .select_from(SourceVideo)
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(
                    SourceChannel.channel_id == channel_id,
                    SourceVideo.status == "processed",
                )
            ),
            "candidates": await self._count(
                sa.select(sa.func.count())
                .select_from(ClipCandidate)
                .join(
                    SourceVideo,
                    ClipCandidate.source_video_id == SourceVideo.id,
                )
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(SourceChannel.channel_id == channel_id)
            ),
            "rendered": await self._count(
                sa.select(sa.func.count())
                .select_from(RenderedClip)
                .join(
                    ClipCandidate,
                    RenderedClip.clip_candidate_id == ClipCandidate.id,
                )
                .join(
                    SourceVideo,
                    ClipCandidate.source_video_id == SourceVideo.id,
                )
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(
                    SourceChannel.channel_id == channel_id,
                    RenderedClip.status == "rendered",
                )
            ),
            "published_total": await self._count(
                sa.select(sa.func.count())
                .select_from(PublishedVideo)
                .where(
                    PublishedVideo.channel_id == channel_id,
                    PublishedVideo.status == "verified",
                )
            ),
            "published_today": await self.daily_published_count(channel_id),
            "stock": await self.stock_level(channel_id),
            "daily_target": profile.daily_clip_target,
            "paused": bool((profile.settings or {}).get("paused")),
        }
        await self._audit(channel_id, "ops.summary", summary)
        return summary

    async def _audit(self, channel_id: int, event_type: str, detail: dict):
        async with self._sessionmaker() as session:
            record_event(session, channel_id, event_type, detail)
            await session.commit()

    async def _count(self, query) -> int:
        async with self._sessionmaker() as session:
            return int((await session.execute(query)).scalar() or 0)


async def auto_plan_channel(
    sessionmaker: async_sessionmaker[AsyncSession], channel_id: int
) -> dict:
    """Monitoring -> planning connection: plan a channel's discovered
    videos right after discovery (M11 task 1)."""
    from app.services.planning_service import PlanningService

    planning = PlanningService(sessionmaker)
    return await planning.plan_for_channel(channel_id)


def today_key(timezone_name: str | None = None) -> str:
    """Local date key for daily dedupe (ops summaries)."""
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(timezone_name or "UTC"))
    except Exception:  # noqa: BLE001
        now = datetime.now(UTC)
    return now.date().isoformat()
