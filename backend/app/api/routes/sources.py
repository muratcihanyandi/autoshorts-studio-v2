"""Source channel registration and rights records API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas_sources import SourceCreate, SourceOut, SourceUpdate, SourcesOut
from app.services.channel_service import ChannelService
from app.services.source_service import SourceService, SourceServiceError

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
