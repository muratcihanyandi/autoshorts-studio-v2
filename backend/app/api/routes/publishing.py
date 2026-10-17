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
    """Approve the latest metadata revision for publication."""
    service = _service(request)
    try:
        metadata = await service.approve_metadata(clip_candidate_id)
    except PublishingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApproveResult(
        clip_candidate_id=clip_candidate_id, revision=metadata.revision
    )


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
