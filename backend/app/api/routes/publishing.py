"""Publishing API (M10): manual publish trigger, metadata approval,
published list. Uploads themselves run through the worker queue; these
endpoints are the operator's control surface.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas_publishing import (
    ApproveResult,
    PublishResult,
    PublishedVideoOut,
    PublishedVideosOut,
)
from app.services.publishing_service import (
    PublishingError,
    PublishingService,
)

router = APIRouter(tags=["publishing"])


def _service(request: Request) -> PublishingService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; yayınlama kapalı.",
        )
    return PublishingService(sessionmaker, request.app.state.settings)


async def _enqueue_private_upload(
    request: Request, job_type: str, payload: dict
) -> None:
    """Onay = gizli yukleme tetikleyicisi: video YouTube'a private
    yüklenir; herkese açık yapılması plan saatine kalır (publish_due).
    Kuyruk yoksa (DB'siz kurulum) sessizce atlanır."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        return
    from app.services.job_service import JobService

    await JobService(
        sessionmaker, request.app.state.settings
    ).enqueue(job_type, payload)


@router.post(
    "/clips/{clip_candidate_id}/publish", response_model=PublishResult
)
async def publish_clip(request: Request, clip_candidate_id: int) -> PublishResult:
    """Publish one clip now (guards still apply: rights, render,
    approved metadata, not already published)."""
    service = _service(request)
    try:
        result = await service.publish_clip(clip_candidate_id)
    except PublishingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PublishResult(**result)


@router.post(
    "/clips/{clip_candidate_id}/approve", response_model=ApproveResult
)
async def approve_metadata(
    request: Request, clip_candidate_id: int
) -> ApproveResult:
    """Approve the latest metadata revision: approval is the trigger for
    the private upload (the scheduled slot later makes it public)."""
    service = _service(request)
    try:
        metadata = await service.approve_metadata(clip_candidate_id)
    except PublishingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _enqueue_private_upload(
        request, "publish_clip", {"clip_candidate_id": clip_candidate_id}
    )
    return ApproveResult(
        clip_candidate_id=clip_candidate_id, revision=metadata.revision
    )


@router.post(
    "/videos/{source_video_id}/approve", response_model=ApproveResult
)
async def approve_full_cut(
    request: Request, source_video_id: int
) -> ApproveResult:
    """Approve the horizontal full-cut metadata of a source video (M13);
    approval triggers the private upload of the full cut."""
    service = _service(request)
    try:
        metadata = await service.approve_full_cut(source_video_id)
    except PublishingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _enqueue_private_upload(
        request, "publish_full_cut", {"source_video_id": source_video_id}
    )
    return ApproveResult(
        source_video_id=source_video_id, revision=metadata.revision
    )


@router.post(
    "/videos/{source_video_id}/publish", response_model=PublishResult
)
async def publish_full_cut(
    request: Request, source_video_id: int
) -> PublishResult:
    """Publish the horizontal full cut of a reaction source video
    (guards still apply: rights, render, approved metadata, once per
    source video)."""
    service = _service(request)
    try:
        result = await service.publish_full_cut(source_video_id)
    except PublishingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PublishResult(**result)


@router.get(
    "/channels/{channel_id}/published", response_model=PublishedVideosOut
)
async def list_published(request: Request, channel_id: int) -> PublishedVideosOut:
    import sqlalchemy as sa

    from app.models import PublishedVideo

    service = _service(request)
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    sa.select(PublishedVideo)
                    .where(PublishedVideo.channel_id == channel_id)
                    .order_by(PublishedVideo.published_at.desc().nullslast())
                )
            )
            .scalars()
            .all()
        )
    return PublishedVideosOut(
        videos=[PublishedVideoOut.model_validate(row) for row in rows],
        total=len(rows),
    )
