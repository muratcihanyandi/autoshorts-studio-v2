"""Medya kütüphanesi API: kaynak videolar, klipler, stok özeti."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.services.library_view import LibraryViewService

router = APIRouter(tags=["media-library"])


def _service(request: Request) -> LibraryViewService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; kütüphane kapalı.",
        )
    return LibraryViewService(sessionmaker, request.app.state.settings)


@router.get("/media")
async def media_library(
    request: Request,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_excluded: bool = Query(False),
    active_only: bool = Query(False),
) -> dict:
    return await _service(request).media_library(
        limit=limit,
        offset=offset,
        include_excluded=include_excluded,
        active_only=active_only,
    )
