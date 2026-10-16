"""Health endpoints.

`/api/health` answers liveness without touching external systems.
`/api/health/ready` answers readiness including a database round-trip.
Error details are reduced to exception class names so connection strings
or hostnames never leak into responses or logs.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "autoshorts-backend", "version": __version__}


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "not_configured"},
        )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - report class name only
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable", "error": type(exc).__name__},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "database": "reachable"},
    )
