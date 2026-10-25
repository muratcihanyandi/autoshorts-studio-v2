"""Medya kütüphanesi API: kaynak videolar, klipler, oynatma ve detay."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import Settings
from app.services.auth_service import gate_response, user_allows
from app.services.library_view import LibraryViewService

router = APIRouter(tags=["media-library"])


class BulkClipActionIn(BaseModel):
    """Toplu klip eylemi gövdesi (Görev 4)."""

    action: Literal["delete", "public", "private"]
    render_ids: list[int] = Field(min_length=1, max_length=50)


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
    excluded_only: bool = Query(False),
) -> dict:
    return await _service(request).media_library(
        limit=limit,
        offset=offset,
        include_excluded=include_excluded,
        active_only=active_only,
        engine_selected_only=engine_selected_only,
        ready_only=ready_only,
        excluded_only=excluded_only,
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


@router.post("/media/videos/{source_video_id}/resume")
async def resume_source_video(
    request: Request, source_video_id: int
) -> dict:
    """Hata veren videoyu KALDIĞI AŞAMADAN sürdür (2026-10-23 kullanıcı
    isteği): varlık 'failed' işaretini temizler, media_process işi elle
    (manuel) kuyruğa alınır — boru hattı indirmeden, kaldığı aşamadan
    devam eder. Video zaten tamamlanmışsa veya işlem sürüyorsa reddedilir."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı.",
        )
    import sqlalchemy as sa

    from app.models import Job, MediaAsset, SourceVideo
    from app.services.job_service import JobService

    async with sessionmaker() as session:
        video = await session.get(SourceVideo, source_video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="Video bulunamadı.")
        if video.status == "excluded":
            raise HTTPException(
                status_code=409,
                detail="Video hariç tutulmuş; önce işleme geri alınmalı.",
            )
        if video.status == "processed":
            raise HTTPException(
                status_code=409,
                detail="Video zaten tamamlandı; sürdürülecek iş yok.",
            )
        asset = (
            (
                await session.execute(
                    sa.select(MediaAsset).where(
                        MediaAsset.source_video_id == source_video_id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if asset is None:
            raise HTTPException(
                status_code=409,
                detail="Video henüz işlem görmedi (indirme başlamamış).",
            )
        # Aktif media_process isleri azdir; payload JSON'u SQL yerine
        # Python tarafinda eslestir (SQLite/PostgreSQL tasinabilirligi).
        active_rows = (
            (
                await session.execute(
                    sa.select(Job.id, Job.payload).where(
                        Job.job_type == "media_process",
                        Job.status.in_(("queued", "running", "cancelling")),
                    )
                )
            )
            .all()
        )
        running = any(
            (payload or {}).get("source_video_id") == source_video_id
            for _jid, payload in active_rows
        )
        if running:
            raise HTTPException(
                status_code=409,
                detail="Bu videonun işi zaten kuyrukta/sürüyor.",
            )
        if asset.status == "failed":
            # 'failed' işaretini kaldır: aşamanın çalışma durumu geri gelir,
            # stok beslemesi ve kütüphane etiketi tekrar aker.
            stage_status = {
                "download": "downloading",
                "inspect": "downloaded",
                "transcript": "inspected",
                "analysis": "transcribed",
                "candidates": "analyzed",
            }
            asset.status = stage_status.get(asset.stage, "downloading")
            await session.commit()

    jobs = JobService(sessionmaker, request.app.state.settings)
    job = await jobs.enqueue(
        "media_process",
        {"source_video_id": source_video_id, "manual": True},
        priority=6,
    )
    return {
        "source_video_id": source_video_id,
        "job_id": job.id,
        "stage": asset.stage,
        "resumed": True,
    }


@router.delete("/media/clips/{render_id}")
async def remove_clip(request: Request, render_id: int) -> dict:
    """Hazır klibi kaldır (kullanıcı isteği 2026-10-21): gizli yüklenmişse
    video önce YouTube'dan silinir, sonra yerel dosya ve kayıtlar;
    YouTube silinemediyse yerel klip korunur."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı.",
        )
    from app.services.video_removal import (
        VideoRemovalError,
        remove_rendered_clip,
    )

    try:
        return await remove_rendered_clip(
            sessionmaker, request.app.state.settings, render_id
        )
    except VideoRemovalError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc


@router.post("/media/clips/bulk")
async def bulk_clips(request: Request, payload: BulkClipActionIn) -> dict:
    """Toplu klip eylemi (Görev 4, kullanıcı isteği 2026-10-21):
    seçilen klipleri toplu kaldir / herkese aç / gizliye al.
    İndirme tarayıcı tarafında stream uçları üzerinden yapılır."""
    # Free plan kapısı (madde 6): toplu işlemler Pro ile açılır.
    if not user_allows(getattr(request.state, "auth_user", None), "bulk_actions"):
        return gate_response("bulk_actions")
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı.",
        )
    from app.services.clip_actions import (
        ClipActionError,
        bulk_clip_action,
    )
    from app.services.settings_service import SettingsService

    effective = await SettingsService(
        sessionmaker, request.app.state.settings
    ).effective_settings()
    try:
        return await bulk_clip_action(
            sessionmaker,
            effective,
            payload.render_ids,
            payload.action,
        )
    except ClipActionError as exc:
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
async def clip_stream(
    request: Request,
    render_id: int,
    download: bool = Query(False),
) -> FileResponse:
    """Üretilmiş videoyu tarayıcıda oynat (Range destekli).
    ?download=true dosyayı kaydetmek üzere ek olarak gönderir
    (toplu indirme, Görev 4)."""
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
        content_disposition_type="attachment" if download else "inline",
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
