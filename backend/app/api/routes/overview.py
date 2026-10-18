"""Overview endpoint: the studio's real, current state.

Channel counts come from the channels table (Milestone 3). `phase` drives
the frontend marquee stamp: setup -> awaiting_channels -> running.

Start/Stop era: stock and today-published are real numbers (never
hardcoded zeros), every channel gets a status row (automation state,
engine activity, stock/queue/shorts counts, last error/success), and
the worker's health is read from its app_meta heartbeat — an idle API
is not a running worker, and the UI must be able to prove the
difference.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import text

from app import __version__
from app.services.channel_service import ChannelService

router = APIRouter(tags=["overview"])

# Worker canli sayilirken kullanilan esik: poll + 2 x heartbeat + pay.
WORKER_LIVENESS_GRACE_SECONDS = 60.0


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


async def _real_totals(request: Request) -> tuple[int, int, list[dict]]:
    """(ready clip stock, published today, channel rows) — computed
    from the database; a schema behind its migration degrades to
    zeros/empty instead of failing the endpoint."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        return 0, 0, []
    try:
        from app.services.automation_service import AutomationService
        from app.services.channel_service import ChannelService
        from app.services.status_service import StatusService

        settings = request.app.state.settings
        automation = AutomationService(sessionmaker, settings)
        status = StatusService(sessionmaker, settings)
        channels = await ChannelService(sessionmaker).list_channels()
        stock_total = 0
        published_today = 0
        rows: list[dict] = []
        for channel in channels:
            stock_total += await automation.stock_level(channel.id)
            published_today += await automation.daily_published_count(channel.id)
            rows.append(await status.channel_status_row(channel))
        return stock_total, published_today, rows
    except Exception:  # noqa: BLE001 - migration'dan geride şema
        return 0, 0, []


async def _worker_health(request: Request) -> dict:
    """Worker liveness from the app_meta heartbeat written by the
    worker loop (enabled + running + last tick)."""
    settings = request.app.state.settings
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    state: dict = {}
    if sessionmaker is not None:
        try:
            from app.models import AppMeta

            async with sessionmaker() as session:
                row = await session.get(AppMeta, "worker_state")
            if row is not None and isinstance(row.value, dict):
                state = row.value
        except Exception:  # noqa: BLE001 - migration'dan geride şema
            state = {}
    running = False
    last_tick = state.get("last_tick_at")
    if last_tick:
        try:
            tick = datetime.fromisoformat(str(last_tick))
            if tick.tzinfo is None:
                tick = tick.replace(tzinfo=UTC)
            running = (datetime.now(UTC) - tick).total_seconds() <= (
                WORKER_LIVENESS_GRACE_SECONDS
                + float(state.get("heartbeat_seconds") or 30.0)
            )
        except ValueError:
            running = False
    return {
        "enabled": bool(settings.worker_enabled),
        "running": bool(settings.worker_enabled and running),
        "worker_id": state.get("worker_id"),
        "started_at": state.get("started_at"),
        "last_tick_at": last_tick,
        "jobs_processed": int(state.get("jobs_processed") or 0),
    }


@router.get("/overview")
async def overview(request: Request) -> dict:
    database = await _database_state(request)
    started_at = getattr(request.app.state, "started_at", None)
    uptime_seconds = round(time.time() - started_at) if started_at else None

    channels_total, channels_connected = await _channels_connected(request, database)
    llm_providers_configured = await _llm_providers_configured(request, database)
    job_counts = await _job_counts(request, database)
    sources_monitored = await _sources_monitored(request, database)
    stock_clips, today_published, channel_rows = await _real_totals(request)
    worker = await _worker_health(request)

    jobs_active = job_counts["active"]
    jobs_queued = job_counts["queued"]

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
        "channel_rows": channel_rows,
        "worker": worker,
    }
