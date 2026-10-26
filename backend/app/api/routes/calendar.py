"""Takvim API (Görev 1): planlanan ve gerçekleşen yayınlar."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.services.auth_service import gate_response, user_allows
from app.services.calendar_view import CalendarViewService
from app.services.publishing_service import (
    PublishingError,
    PublishingService,
)

router = APIRouter(tags=["calendar"])


def _service(request: Request) -> CalendarViewService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; takvim kapalı.",
        )
    return CalendarViewService(sessionmaker, request.app.state.settings)


def _publishing(request: Request) -> PublishingService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; yayınlama kapalı.",
        )
    return PublishingService(sessionmaker, request.app.state.settings)


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


class CalendarRescheduleIn(BaseModel):
    """Sürükle-bırak planlama: gizli yüklenmiş ya da stoktaki hazır
    videonun herkese açılma anını elle ata."""

    published_video_id: int | None = None
    clip_render_id: int | None = None
    # ISO zaman; verilmezse (null) elle planlama temizlenir.
    scheduled_at: datetime | None = None
    clear: bool = False


@router.post("/calendar/reschedule")
async def reschedule(request: Request, data: CalendarRescheduleIn) -> dict:
    """Takvimden sürüklenen videonun yayın saatini elle yerleştir.

    - Gizli yüklenmiş video (published_video_id): saat doğrudan satıra
      yazılır; saati gelince motor herkese açar.
    - Stoktaki hazır klip (clip_render_id): gizli yükleme işi hemen
      açılır, saat yükleme tamamlanınca otomatik uygulanır.
    - clear=true: elle planlamayı kaldır, video slot mantığına dönsün.
    """
    # Free plan kapısı (madde 6): manuel yayın planlama Pro ile açılır.
    if not user_allows(getattr(request.state, "auth_user", None), "manual_schedule"):
        return gate_response("manual_schedule")
    service = _publishing(request)
    if (data.published_video_id is None) == (data.clip_render_id is None):
        raise HTTPException(
            status_code=400,
            detail="Tam olarak biri gerekli: published_video_id ya da clip_render_id.",
        )
    if data.clear:
        scheduled_at = None
    else:
        if data.scheduled_at is None:
            raise HTTPException(
                status_code=400,
                detail="Yeni yayın saati (scheduled_at) gerekli.",
            )
        scheduled_at = data.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=UTC)
        if scheduled_at <= datetime.now(UTC).replace(microsecond=0):
            raise HTTPException(
                status_code=400,
                detail="Yayın saati gelecekte olmalı.",
            )
    try:
        if data.published_video_id is not None:
            row = await service.set_manual_schedule(
                data.published_video_id, scheduled_at
            )
            return {
                "published_video_id": row.id,
                "scheduled_at": (
                    row.scheduled_at.isoformat()
                    if row.scheduled_at
                    else None
                ),
            }
        result = await service.schedule_render(
            data.clip_render_id, scheduled_at
        )
        return result
    except PublishingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class CalendarRebuildIn(BaseModel):
    """Takvimi yeniden oluşturma girdisi (isteğe bağlı kanal kimliği)."""

    channel_id: int | None = None


@router.post("/calendar/rebuild")
async def rebuild_calendar(
    request: Request, data: CalendarRebuildIn | None = None
) -> dict:
    """Takvimi kanal ayarlarındaki güncel kotalar ve zirve saat analizine göre baştan kur."""
    service = _service(request)
    channel_id = data.channel_id if data else None
    return await service.rebuild_schedule(channel_id)
