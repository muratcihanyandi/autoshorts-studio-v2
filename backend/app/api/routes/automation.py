"""Publishing profile API (M11): pause/resume, daily target, publish
times, auto-approval — the operator's automation controls.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas_publishing import (
    PublishingProfileIn,
    PublishingProfileOut,
)
from app.services.automation_service import AutomationService
from app.services.publishing_schedule import ScheduleError

router = APIRouter(tags=["publishing"])


def _service(request: Request) -> AutomationService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; otomasyon kapalı.",
        )
    return AutomationService(sessionmaker, request.app.state.settings)


def _out(profile) -> PublishingProfileOut:
    settings = profile.settings or {}
    return PublishingProfileOut(
        channel_id=profile.channel_id,
        daily_clip_target=profile.daily_clip_target,
        timezone=profile.timezone,
        publish_times=settings.get("publish_times"),
        auto_approve_metadata=bool(settings.get("auto_approve_metadata")),
        paused=bool(settings.get("paused")),
    )


@router.get(
    "/channels/{channel_id}/publishing", response_model=PublishingProfileOut
)
async def get_publishing_profile(
    request: Request, channel_id: int
) -> PublishingProfileOut:
    service = _service(request)
    profile = await service.profile(channel_id)
    return _out(profile)


@router.put(
    "/channels/{channel_id}/publishing", response_model=PublishingProfileOut
)
async def update_publishing_profile(
    request: Request, channel_id: int, data: PublishingProfileIn
) -> PublishingProfileOut:
    service = _service(request)
    profile = await service.profile(channel_id)
    if data.publish_times is not None:
        try:
            from app.services.publishing_schedule import parse_publish_times

            parse_publish_times(data.publish_times)
        except ScheduleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if data.daily_clip_target is not None and data.daily_clip_target < 0:
        raise HTTPException(status_code=400, detail="Hedef negatif olamaz.")

    import sqlalchemy as sa

    from app.models import PublishingProfile

    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        row = await session.get(PublishingProfile, profile.id)
        if data.daily_clip_target is not None:
            row.daily_clip_target = data.daily_clip_target
        if data.timezone:
            row.timezone = data.timezone
        settings = dict(row.settings or {})
        if data.publish_times is not None:
            settings["publish_times"] = data.publish_times
        if data.auto_approve_metadata is not None:
            settings["auto_approve_metadata"] = data.auto_approve_metadata
        if data.paused is not None:
            settings["paused"] = data.paused
        row.settings = settings
        await session.commit()
        await session.refresh(row)
        return _out(row)


@router.get("/channels/{channel_id}/summary")
async def channel_summary(request: Request, channel_id: int) -> dict:
    """Operational summary (also recorded as an audit event)."""
    service = _service(request)
    return await service.operational_summary(channel_id)
