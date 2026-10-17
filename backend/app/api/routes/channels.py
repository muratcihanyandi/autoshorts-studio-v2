"""Channel management API.

Responses carry channel facts only; OAuth tokens never leave the service
layer (see docs/SECURITY.md: secrets stay out of API responses).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.api.routes.settings import effective_settings
from app.schemas import ChannelCreate, ChannelOut, ChannelUpdate, ChannelsOut
from app.services.channel_service import ChannelService
from app.services.oauth_service import OAuthError, OAuthService

router = APIRouter(tags=["channels"])


def _service(request: Request) -> ChannelService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; kanal yönetimi kapalı.",
        )
    return ChannelService(sessionmaker)


async def _oauth_service(request: Request) -> OAuthService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; kanal yönetimi kapalı.",
        )
    return OAuthService(sessionmaker, await effective_settings(request))


def _out_or_404(channel) -> ChannelOut:
    if channel is None:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    return ChannelOut.model_validate(channel)


@router.get("/channels", response_model=ChannelsOut)
async def list_channels(request: Request) -> ChannelsOut:
    service = _service(request)
    channels = await service.list_channels()
    connected = sum(1 for c in channels if c.status.value == "connected")
    return ChannelsOut(
        channels=[ChannelOut.model_validate(c) for c in channels],
        total=len(channels),
        connected=connected,
    )


@router.post(
    "/channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED
)
async def create_channel(request: Request, data: ChannelCreate) -> ChannelOut:
    service = _service(request)
    channel = await service.create_channel(data)
    return ChannelOut.model_validate(channel)


@router.get("/channels/{channel_id}", response_model=ChannelOut)
async def get_channel(request: Request, channel_id: int) -> ChannelOut:
    service = _service(request)
    return _out_or_404(await service.get_channel(channel_id))


@router.patch("/channels/{channel_id}", response_model=ChannelOut)
async def update_channel(
    request: Request, channel_id: int, data: ChannelUpdate
) -> ChannelOut:
    service = _service(request)
    return _out_or_404(await service.update_channel(channel_id, data))


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(request: Request, channel_id: int) -> None:
    service = _service(request)
    if not await service.delete_channel(channel_id):
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")


@router.post("/channels/{channel_id}/disconnect", response_model=ChannelOut)
async def disconnect_channel(request: Request, channel_id: int) -> ChannelOut:
    service = _service(request)
    return _out_or_404(await service.disconnect_channel(channel_id))


@router.post("/channels/{channel_id}/oauth/start")
async def oauth_start(request: Request, channel_id: int) -> dict:
    oauth = await _oauth_service(request)
    try:
        return await oauth.start(channel_id)
    except OAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/channels/{channel_id}/oauth/callback")
async def oauth_callback(
    request: Request,
    channel_id: int,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Google lands the browser here after consent.

    Success/failure redirect to the frontend channels screen when its base
    URL is configured; otherwise the result is plain JSON (API clients).
    """
    frontend = (await effective_settings(request)).frontend_base_url.rstrip("/")
    oauth = await _oauth_service(request)
    try:
        channel = await oauth.callback(channel_id, code, state, error)
    except OAuthError as exc:
        if frontend:
            return RedirectResponse(
                f"{frontend}/kanallar?oauth=hata", status_code=307
            )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if frontend:
        return RedirectResponse(f"{frontend}/kanallar?oauth=basarili", status_code=307)
    return ChannelOut.model_validate(channel)


@router.post("/channels/{channel_id}/oauth/refresh")
async def oauth_refresh(request: Request, channel_id: int) -> dict:
    oauth = await _oauth_service(request)
    try:
        refreshed = await oauth.refresh_if_needed(channel_id)
    except OAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"channel_id": channel_id, "refreshed": refreshed}
