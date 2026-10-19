"""Günlükler API: audit_events akışı, filtreli ve sayfalanabilir."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.services.audit_view import AuditViewService

router = APIRouter(tags=["logs"])


def _service(request: Request) -> AuditViewService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; günlükler kapalı.",
        )
    return AuditViewService(sessionmaker, request.app.state.settings)


@router.get("/logs")
async def logs(
    request: Request,
    limit: int = Query(80, ge=1, le=300),
    before_id: int | None = Query(None, ge=1),
    channel_id: int | None = Query(None, ge=1),
    category: str | None = Query(None, max_length=40),
) -> dict:
    """Kategori, event_type'in ilk noktaya kadar kısmıdır ('media' gibi);
    sayfalama en büyük id'den küçüğe before_id imleciyle yapılır."""
    return await _service(request).page(
        limit=limit,
        before_id=before_id,
        channel_id=channel_id,
        category=category,
    )
