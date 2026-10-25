"""Pulse API: panelin olay akışı (iş sonuçları + yayın/otomasyon olayları)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.services.pulse_service import EVENT_LIMIT, PulseService

router = APIRouter(tags=["pulse"])


@router.get("/pulse")
async def pulse(
    request: Request,
    since: str | None = Query(
        default=None,
        description="ISO zaman damgası: bu andan sonraki olaylar döner.",
    ),
    limit: int = Query(default=30, ge=1, le=EVENT_LIMIT),
) -> dict[str, Any]:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; olay akışı kapalı.",
        )
    service = PulseService(sessionmaker, request.app.state.settings)
    return await service.recent(since=since, limit=limit)
