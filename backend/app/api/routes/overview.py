"""Overview endpoint: the studio's real, current state.

Channel counts come from the channels table (Milestone 3). `phase` drives
the frontend marquee stamp: setup -> awaiting_channels -> running.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request
from sqlalchemy import text

from app import __version__
from app.services.channel_service import ChannelService

router = APIRouter(tags=["overview"])


async def _database_state(request: Request) -> str:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        return "not_configured"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - status word only
        return "unreachable"
    return "reachable"


async def _channels_connected(request: Request, database: str) -> tuple[int, int]:
    """(total, connected); a schema behind its migration reads as zero."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if database != "reachable" or sessionmaker is None:
        return 0, 0
    try:
        service = ChannelService(sessionmaker)
        channels = await service.list_channels()
    except Exception:  # noqa: BLE001 - migration'dan geride şema
        return 0, 0
    connected = sum(1 for c in channels if c.status.value == "connected")
    return len(channels), connected


async def _llm_providers_configured(request: Request, database: str) -> int:
    """Enabled LLM providers; a schema behind its migration reads as zero."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if database != "reachable" or sessionmaker is None:
        return 0
    try:
        from sqlalchemy import select

        from app.models import LlmProvider

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(LlmProvider.id).where(LlmProvider.enabled.is_(True))
                    )
                )
                .scalars()
                .all()
            )
        return len(rows)
    except Exception:  # noqa: BLE001 - migration'dan geride şema
        return 0


async def _job_counts(request: Request, database: str) -> dict[str, int]:
    """Job tallies; a schema behind its migration reads as zero."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if database != "reachable" or sessionmaker is None:
        return {"active": 0, "queued": 0}
    try:
        from app.services.job_service import JobService

        counts = await JobService(
            sessionmaker, request.app.state.settings
        ).counts()
        return {"active": counts["active"], "queued": counts["queued"]}
    except Exception:  # noqa: BLE001 - migration'dan geride şema
        return {"active": 0, "queued": 0}


async def _sources_monitored(request: Request, database: str) -> int:
    """Authorized source channels; a schema behind its migration reads as zero."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if database != "reachable" or sessionmaker is None:
        return 0
    try:
        from sqlalchemy import text

        async with sessionmaker() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM source_channels "
                        "WHERE permission_status = 'authorized'"
                    )
                )
            ).scalar()
        return int(count or 0)
    except Exception:  # noqa: BLE001 - migration'dan geride şema
        return 0


@router.get("/overview")
async def overview(request: Request) -> dict:
    database = await _database_state(request)
    started_at = getattr(request.app.state, "started_at", None)
    uptime_seconds = round(time.time() - started_at) if started_at else None

    channels_total, channels_connected = await _channels_connected(request, database)
    llm_providers_configured = await _llm_providers_configured(request, database)
    job_counts = await _job_counts(request, database)
    sources_monitored = await _sources_monitored(request, database)

    jobs_active = job_counts["active"]
    jobs_queued = job_counts["queued"]
    stock_clips = 0
    today_published = 0

    if database != "reachable":
        phase = "setup"
    elif channels_connected == 0:
        phase = "awaiting_channels"
    else:
        phase = "running"

    return {
        "version": __version__,
        "app_env": request.app.state.settings.app_env,
        "uptime_seconds": uptime_seconds,
        "phase": phase,
        "database": database,
        "channels": {"connected": channels_connected, "total": channels_total},
        "sources": {"monitored": sources_monitored},
        "llm_providers": {"configured": llm_providers_configured},
        "jobs": {"active": jobs_active, "queued": jobs_queued},
        "stock": {"clips": stock_clips},
        "today_published": today_published,
    }
