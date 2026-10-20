"""Medya kütüphanesi API: kaynak videolar, klipler, oynatma ve detay."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from app.config import Settings
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


def _safe_media_path(settings: Settings, stored_path: str | None) -> Path | None:
    """MEDIA_ROOT dışına çıkan yolları reddet (path traversal guard)."""
    if not stored_path or not settings.media_root:
        return None
    root = Path(settings.media_root).resolve()
    path = Path(stored_path)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


@router.get("/media")
async def media_library(
    request: Request,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_excluded: bool = Query(False),
    active_only: bool = Query(True),
    engine_selected_only: bool = Query(False),
    ready_only: bool = Query(False),
) -> dict:
    return await _service(request).media_library(
        limit=limit,
        offset=offset,
        include_excluded=include_excluded,
        active_only=active_only,
        engine_selected_only=engine_selected_only,
        ready_only=ready_only,
    )


@router.delete("/media/videos/{source_video_id}")
async def remove_source_video(
    request: Request, source_video_id: int
) -> dict:
    """Kaynak videoyu sistemden kaldır: dosyalar, satırlar ve bekleyen
    işler temizlenir; video hariç olarak kaybolur (kullanıcı isteği)."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı.",
        )
    from app.services.video_removal import (
        VideoRemovalError,
        remove_source_video,
    )

    try:
        return await remove_source_video(
            sessionmaker, request.app.state.settings, source_video_id
        )
    except VideoRemovalError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc


@router.get("/media/clips/{render_id}")
async def clip_detail(request: Request, render_id: int) -> dict:
    detail = await _service(request).clip_detail(render_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Klip bulunamadı.",
        )
    return detail


@router.get("/media/clips/{render_id}/stream")
async def clip_stream(request: Request, render_id: int) -> FileResponse:
    """Üretilmiş videoyu tarayıcıda oynat (Range destekli)."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı.",
        )
    from app.models import RenderedClip

    async with sessionmaker() as session:
        render = await session.get(RenderedClip, render_id)
    if render is None or render.status != "rendered":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hazır klip bulunamadı.",
        )
    path = _safe_media_path(request.app.state.settings, render.file_path)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Klip dosyası bulunamadı.",
        )
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.get("/media/clips/{render_id}/thumbnail")
async def clip_thumbnail(request: Request, render_id: int) -> FileResponse:
    """Onay/preview sırasında üretilen kapak görseli."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı.",
        )
    from app.models import RenderedClip

    async with sessionmaker() as session:
        render = await session.get(RenderedClip, render_id)
    if render is None or not render.thumbnail_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kapak görseli bulunamadı.",
        )
    path = _safe_media_path(
        request.app.state.settings, render.thumbnail_path
    )
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kapak dosyası bulunamadı.",
        )
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=300"},
    )
