"""Takvim API (Görev 1): planlanan ve gerçekleşen yayınlar."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.services.calendar_view import CalendarViewService

router = APIRouter(tags=["calendar"])


def _service(request: Request) -> CalendarViewService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; takvim kapalı.",
        )
    return CalendarViewService(sessionmaker, request.app.state.settings)


@router.get("/calendar")
async def calendar(
    request: Request,
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
) -> dict:
    """İstenen ayın takvimi; yıl/ay verilmezse içinde bulunulan ay."""
    now = datetime.now(UTC)
    resolved_year = year or now.year
    resolved_month = month or now.month
    return await _service(request).calendar(resolved_year, resolved_month)
