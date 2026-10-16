"""Overview endpoint: the studio's real, current state.

Counts are honest: domain features arrive with their milestones, so the
numbers start at zero. `phase` drives the frontend marquee stamp:
setup -> awaiting_channels -> running.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request
from sqlalchemy import text

from app import __version__

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


@router.get("/overview")
async def overview(request: Request) -> dict:
    database = await _database_state(request)
    started_at = getattr(request.app.state, "started_at", None)
    uptime_seconds = round(time.time() - started_at) if started_at else None

    channels_connected = 0
    sources_monitored = 0
    llm_providers_configured = 0
    jobs_active = 0
    jobs_queued = 0
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
        "channels": {"connected": channels_connected},
        "sources": {"monitored": sources_monitored},
        "llm_providers": {"configured": llm_providers_configured},
        "jobs": {"active": jobs_active, "queued": jobs_queued},
        "stock": {"clips": stock_clips},
        "today_published": today_published,
    }
