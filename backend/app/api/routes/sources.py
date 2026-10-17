"""Source channel registration, rights records, and discovery API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.routes.settings import effective_settings
from app.schemas_sources import (
    DiscoverResult,
    PlanningResult,
    SourceCreate,
    SourceOut,
    SourceUpdate,
    SourceVideoOut,
    SourceVideosOut,
    SourcesOut,
    WebcamCalibrationIn,
    WebcamCalibrationOut,
)
from app.services.channel_service import ChannelService
from app.services.discovery_service import DiscoveryService
from app.services.planning_service import PlanningService
from app.services.source_service import SourceService, SourceServiceError
from app.services.webcam_calibration import (
    CalibrationError,
    WebcamCalibrationService,
)
from app.services.youtube_client import YouTubeNotConfigured

router = APIRouter(tags=["sources"])


def _services(request: Request) -> tuple[SourceService, ChannelService]:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; kaynak yönetimi kapalı.",
        )
    return SourceService(sessionmaker), ChannelService(sessionmaker)


def _out_or_404(source) -> SourceOut:
    if source is None:
        raise HTTPException(status_code=404, detail="Kaynak kanal bulunamadı.")
    return SourceOut.model_validate(source)


@router.get("/channels/{channel_id}/sources", response_model=SourcesOut)
async def list_sources(request: Request, channel_id: int) -> SourcesOut:
    sources_service, channels_service = _services(request)
    if await channels_service.get_channel(channel_id) is None:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    sources = await sources_service.list_sources(channel_id)
    authorized = sum(
        1 for s in sources if s.permission_status == "authorized"
    )
    return SourcesOut(
        sources=[SourceOut.model_validate(s) for s in sources],
        total=len(sources),
        authorized=authorized,
    )


@router.post(
    "/channels/{channel_id}/sources",
    response_model=SourceOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_source(
    request: Request, channel_id: int, data: SourceCreate
) -> SourceOut:
    sources_service, channels_service = _services(request)
    if await channels_service.get_channel(channel_id) is None:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    try:
        source = await sources_service.add_source(channel_id, data)
    except SourceServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc)
        ) from exc
    return SourceOut.model_validate(source)


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def update_source(
    request: Request, source_id: int, data: SourceUpdate
) -> SourceOut:
    sources_service, _ = _services(request)
    return _out_or_404(await sources_service.update_source(source_id, data))


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(request: Request, source_id: int) -> None:
    sources_service, _ = _services(request)
    if not await sources_service.delete_source(source_id):
        raise HTTPException(status_code=404, detail="Kaynak kanal bulunamadı.")


@router.post("/channels/{channel_id}/discover", response_model=DiscoverResult)
async def discover_channel(request: Request, channel_id: int) -> DiscoverResult:
    _, channels_service = _services(request)
    if await channels_service.get_channel(channel_id) is None:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    discovery = DiscoveryService(
        request.app.state.sessionmaker, await effective_settings(request)
    )
    try:
        result = await discovery.discover_for_channel(channel_id)
    except YouTubeNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DiscoverResult(**result)


@router.get("/channels/{channel_id}/videos", response_model=SourceVideosOut)
async def list_channel_videos(
    request: Request, channel_id: int, status: str | None = None
) -> SourceVideosOut:
    _, channels_service = _services(request)
    if await channels_service.get_channel(channel_id) is None:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    discovery = DiscoveryService(
        request.app.state.sessionmaker, await effective_settings(request)
    )
    videos = await discovery.list_videos(channel_id, status=status)
    return SourceVideosOut(
        videos=[SourceVideoOut.model_validate(v) for v in videos],
        total=len(videos),
    )


@router.post("/channels/{channel_id}/plan", response_model=PlanningResult)
async def plan_channel(request: Request, channel_id: int) -> PlanningResult:
    _, channels_service = _services(request)
    if await channels_service.get_channel(channel_id) is None:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    planning = PlanningService(request.app.state.sessionmaker)
    result = await planning.plan_for_channel(channel_id)
    return PlanningResult(**result)


@router.get(
    "/sources/{source_id}/webcam-calibration",
    response_model=WebcamCalibrationOut,
)
async def get_webcam_calibration(request: Request, source_id: int):
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=503,
            detail="Veritabanı yapılandırılmadı; kalibrasyon kapalı.",
        )
    sources_service, _ = _services(request)
    if await sources_service.get_source(source_id) is None:
        raise HTTPException(status_code=404, detail="Kaynak kanal bulunamadı.")
    calibration = await WebcamCalibrationService(sessionmaker).get(source_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Kalibrasyon kaydı yok.")
    return WebcamCalibrationOut.model_validate(calibration)


@router.put(
    "/sources/{source_id}/webcam-calibration",
    response_model=WebcamCalibrationOut,
)
async def set_webcam_calibration(
    request: Request, source_id: int, data: WebcamCalibrationIn
):
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=503,
            detail="Veritabanı yapılandırılmadı; kalibrasyon kapalı.",
        )
    sources_service, _ = _services(request)
    if await sources_service.get_source(source_id) is None:
        raise HTTPException(status_code=404, detail="Kaynak kanal bulunamadı.")
    service = WebcamCalibrationService(sessionmaker)
    try:
        calibration = await service.set_calibration(
            source_id,
            (data.region.x, data.region.y, data.region.w, data.region.h),
            manual=data.manual,
            min_confidence=data.min_confidence,
        )
    except CalibrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return WebcamCalibrationOut.model_validate(calibration)


@router.delete(
    "/sources/{source_id}/webcam-calibration",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_webcam_calibration(request: Request, source_id: int) -> None:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=503,
            detail="Veritabanı yapılandırılmadı; kalibrasyon kapalı.",
        )
    sources_service, _ = _services(request)
    if await sources_service.get_source(source_id) is None:
        raise HTTPException(status_code=404, detail="Kaynak kanal bulunamadı.")
    await WebcamCalibrationService(sessionmaker).delete(source_id)
