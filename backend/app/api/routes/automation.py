"""Automation API: Start/Stop controls, channel settings, engine state.

Publishing profile basics (daily target, publish times, pause) live in
the M11 endpoints below; the Start/Stop era adds the per-channel
automation state machine, the channel settings modal payloads, followed
characters, and the per-channel horizontal/shorts listings with the
central status tags.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas_automation import (
    AutomationActionOut,
    ChannelSettingsIn,
    ChannelSettingsOut,
    ChannelShortOut,
    ChannelShortsOut,
    ChannelVideoOut,
    ChannelVideosOut,
    EngineStateOut,
    FollowedCharacterOut,
)
from app.schemas_publishing import (
    PublishingProfileIn,
    PublishingProfileOut,
)
from app.services.automation_service import (
    AutomationError,
    AutomationService,
)
from app.services.publishing_schedule import ScheduleError

router = APIRouter(tags=["automation"])


def _service(request: Request) -> AutomationService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; otomasyon kapalı.",
        )
    return AutomationService(sessionmaker, request.app.state.settings)


async def _channel_or_404(request: Request, channel_id: int):
    import sqlalchemy as sa

    from app.models import Channel

    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        channel = await session.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    return channel


# --- Start/Stop durum makinesi ---


@router.post(
    "/channels/{channel_id}/automation/start",
    response_model=AutomationActionOut,
)
async def start_automation(
    request: Request, channel_id: int
) -> AutomationActionOut:
    """Baslat: otomasyon 'running' olur ve stok kontrolu hemen yapilir."""
    await _channel_or_404(request, channel_id)
    service = _service(request)
    try:
        result = await service.start(channel_id)
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AutomationActionOut(**result)


@router.post(
    "/channels/{channel_id}/automation/stop",
    response_model=AutomationActionOut,
)
async def stop_automation(
    request: Request, channel_id: int
) -> AutomationActionOut:
    """Durdur: yeni isler baslamaz; siradaki isler iptal edilir,
    suruyen isler guvenlice tamamlanir."""
    await _channel_or_404(request, channel_id)
    service = _service(request)
    try:
        result = await service.stop(channel_id)
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AutomationActionOut(**result)


@router.post(
    "/channels/{channel_id}/automation/pause",
    response_model=AutomationActionOut,
)
async def pause_automation(
    request: Request, channel_id: int
) -> AutomationActionOut:
    """Duraklat: yayinlama bekler, uretim surer."""
    await _channel_or_404(request, channel_id)
    service = _service(request)
    try:
        result = await service.pause(channel_id)
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AutomationActionOut(**result)


# --- kanal ayarlari (modal) ---


@router.get(
    "/channels/{channel_id}/automation", response_model=ChannelSettingsOut
)
async def get_channel_settings(
    request: Request, channel_id: int
) -> ChannelSettingsOut:
    await _channel_or_404(request, channel_id)
    service = _service(request)
    profile = await service.profile(channel_id)
    characters = await service.followed_characters(channel_id)
    return ChannelSettingsOut(
        channel_id=channel_id,
        automation_state=profile.automation_state,
        horizontal_stock_target=profile.horizontal_stock_target,
        daily_vertical_limit=profile.daily_clip_target,
        daily_horizontal_limit=profile.daily_horizontal_limit,
        title_mode=profile.title_mode,
        description_mode=profile.description_mode,
        tags_mode=profile.tags_mode,
        content_warning_mode=profile.content_warning_mode,
        ai_disclosure_mode=profile.ai_disclosure_mode,
        channel_system_prompt=profile.channel_system_prompt,
        characters=[
            FollowedCharacterOut(**character) for character in characters
        ],
    )


@router.put(
    "/channels/{channel_id}/automation", response_model=ChannelSettingsOut
)
async def update_channel_settings(
    request: Request, channel_id: int, data: ChannelSettingsIn
) -> ChannelSettingsOut:
    """Ayarları kaydet: stok hedefi, icerik modlari, sistem promptu ve
    takip edilen karakterler. Kaydedilen degerler sonraki acilista ayni
    doner; bir kanalin ayarlari digerlerini etkilemez."""
    await _channel_or_404(request, channel_id)
    service = _service(request)
    try:
        if data.character_ids is not None:
            await service.set_followed_characters(channel_id, data.character_ids)
        await service.update_channel_settings(
            channel_id,
            horizontal_stock_target=data.horizontal_stock_target,
            daily_vertical_limit=data.daily_vertical_limit,
            daily_horizontal_limit=data.daily_horizontal_limit,
            title_mode=data.title_mode,
            description_mode=data.description_mode,
            tags_mode=data.tags_mode,
            content_warning_mode=data.content_warning_mode,
            ai_disclosure_mode=data.ai_disclosure_mode,
            channel_system_prompt=data.channel_system_prompt,
        )
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await get_channel_settings(request, channel_id)


# --- kanal listeleri (durum etiketleriyle) ---


@router.get(
    "/channels/{channel_id}/horizontal", response_model=ChannelVideosOut
)
async def list_channel_videos(
    request: Request, channel_id: int
) -> ChannelVideosOut:
    """Kanalin yatay videolari: merkez durum etiketi, sure, dosya ve
    hata bilgisiyle (Genel Bakis ayrinti listesi)."""
    import sqlalchemy as sa

    from app.models import MediaAsset, MediaInspection, SourceChannel, SourceVideo
    from app.services.status_service import StatusService

    await _channel_or_404(request, channel_id)
    sessionmaker = request.app.state.sessionmaker
    status_service = StatusService(sessionmaker, request.app.state.settings)
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    sa.select(SourceVideo, SourceChannel, MediaAsset)
                    .join(
                        SourceChannel,
                        SourceVideo.source_channel_id == SourceChannel.id,
                    )
                    .outerjoin(
                        MediaAsset, MediaAsset.source_video_id == SourceVideo.id
                    )
                    .where(SourceChannel.channel_id == channel_id)
                    .order_by(SourceVideo.id.desc())
                    .limit(200)
                )
            )
            .all()
        )
        videos: list[ChannelVideoOut] = []
        for video, source, asset in rows:
            duration = None
            file_bytes = None
            file_path = None
            error = None
            if asset is not None:
                file_bytes = asset.file_bytes
                file_path = asset.file_path or None
                error = asset.last_error
                inspection = (
                    (
                        await session.execute(
                            sa.select(MediaInspection).where(
                                MediaInspection.media_asset_id == asset.id
                            )
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
                if inspection is not None:
                    duration = inspection.duration_seconds
            tag = await status_service.source_tag(video.id)
            if tag is None:
                continue
            videos.append(
                ChannelVideoOut(
                    source_video_id=video.id,
                    title=video.title,
                    tag=tag,
                    status=video.status,
                    platform=source.platform,
                    duration_seconds=duration,
                    file_bytes=file_bytes,
                    file_path=file_path,
                    error=error,
                )
            )
    return ChannelVideosOut(videos=videos, total=len(videos))


@router.get(
    "/channels/{channel_id}/shorts", response_model=ChannelShortsOut
)
async def list_channel_shorts(
    request: Request, channel_id: int
) -> ChannelShortsOut:
    """Kanalin urettigi dikey shorts ve yatay tam kesitler (#shorts)."""
    import sqlalchemy as sa

    from app.models import (
        ClipCandidate,
        RenderedClip,
        SourceChannel,
        SourceVideo,
    )
    from app.services.status_service import StatusService

    await _channel_or_404(request, channel_id)
    sessionmaker = request.app.state.sessionmaker
    status_service = StatusService(sessionmaker, request.app.state.settings)
    async with sessionmaker() as session:
        vertical_rows = (
            (
                await session.execute(
                    sa.select(RenderedClip, ClipCandidate)
                    .join(
                        ClipCandidate,
                        RenderedClip.clip_candidate_id == ClipCandidate.id,
                    )
                    .join(
                        SourceVideo,
                        ClipCandidate.source_video_id == SourceVideo.id,
                    )
                    .join(
                        SourceChannel,
                        SourceVideo.source_channel_id == SourceChannel.id,
                    )
                    .where(SourceChannel.channel_id == channel_id)
                    .order_by(RenderedClip.id.desc())
                    .limit(200)
                )
            )
            .all()
        )
        horizontal_rows = (
            (
                await session.execute(
                    sa.select(RenderedClip)
                    .join(
                        SourceVideo,
                        RenderedClip.source_video_id == SourceVideo.id,
                    )
                    .join(
                        SourceChannel,
                        SourceVideo.source_channel_id == SourceChannel.id,
                    )
                    .where(
                        SourceChannel.channel_id == channel_id,
                        RenderedClip.clip_candidate_id.is_(None),
                        RenderedClip.orientation == "horizontal",
                    )
                    .order_by(RenderedClip.id.desc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
    shorts: list[ChannelShortOut] = []
    for render, candidate in vertical_rows:
        shorts.append(
            ChannelShortOut(
                rendered_clip_id=render.id,
                tag=status_service.clip_tag(render),
                status=render.status,
                orientation=render.orientation,
                clip_candidate_id=candidate.id,
                source_video_id=candidate.source_video_id,
                duration_seconds=render.duration_seconds,
                file_bytes=render.file_bytes,
                width=render.width,
                height=render.height,
                error=render.last_error,
            )
        )
    for render in horizontal_rows:
        shorts.append(
            ChannelShortOut(
                rendered_clip_id=render.id,
                tag=status_service.clip_tag(render),
                status=render.status,
                orientation=render.orientation,
                clip_candidate_id=None,
                source_video_id=render.source_video_id,
                duration_seconds=render.duration_seconds,
                file_bytes=render.file_bytes,
                width=render.width,
                height=render.height,
                error=render.last_error,
            )
        )
    return ChannelShortsOut(shorts=shorts, total=len(shorts))


# --- M11 yayin profili (mevcut davranis korunur) ---


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
