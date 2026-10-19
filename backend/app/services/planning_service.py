"""Durable planning: discovered videos become planned, exactly once.

The planning_decisions ledger is the audit trail; the unique
source_video_id constraint plus the status vocabulary make repeated
runs idempotent (a decided video is never re-decided, a planned video
is never re-planned).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import PlanningDecision, SourceChannel, SourceVideo
from app.services.channel_service import record_event


class PlanningService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    def _decide(self, video: SourceVideo) -> tuple[str, str | None]:
        """Planning criteria hook. Jobs (Milestone 6) consume 'planned'."""
        return "planned", None

    async def plan_for_channel(self, channel_id: int) -> dict[str, Any]:
        planned = 0
        skipped = 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(SourceVideo)
                .join(SourceChannel, SourceVideo.source_channel_id == SourceChannel.id)
                .where(
                    SourceChannel.channel_id == channel_id,
                    SourceVideo.status == "discovered",
                )
                .order_by(SourceVideo.id)
            )
            for video in result.scalars().all():
                decision, reason = self._decide(video)
                session.add(
                    PlanningDecision(
                        source_video_id=video.id,
                        decision=decision,
                        reason=reason,
                    )
                )
                video.status = decision
                if decision == "planned":
                    planned += 1
                else:
                    skipped += 1

            record_event(
                session,
                channel_id,
                "planning.run",
                {"planned": planned, "skipped": skipped},
            )
            await session.commit()

        return {"planned": planned, "skipped": skipped}
