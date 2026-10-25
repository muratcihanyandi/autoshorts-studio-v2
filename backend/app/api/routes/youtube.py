"""YouTube kanal yonetimi API (kullanici istegi 2026-10-25): site
uzerinden kanalin videolarini listeleme, analiz etme ve silme.

Liste ve analiz yuzeyleri kanalin OAuth baglantisi uzerinden calisir;
siteden silinmis ama YouTube'da kalan (orphan) videolar gorunur ve
silinebilir. Hata sozlesmesi: kanal yok -> 404, OAuth bagli degil ->
409, gunluk kota tukendi -> 429; mesajlar Turkce ve kullanici dostu.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.routes.settings import effective_settings
from app.services.auth_service import (
    ensure_channel_access,
    gate_response,
    user_allows,
)
from app.services.youtube_client import YouTubeQuotaExceeded
from app.services.youtube_manage import YouTubeManageError, YouTubeManageService

router = APIRouter(tags=["youtube-manage"])


async def _service(request: Request) -> YouTubeManageService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; YouTube yönetimi kapalı.",
        )
    # Efektif ayarlar: TOKEN_ENCRYPTION_KEY Ayarlar ekranindan
    # girildiyse DB'de durur; OAuth ve kota bu degerlerle calisir.
    settings = await effective_settings(request)
    return YouTubeManageService(sessionmaker, settings)


@router.get("/youtube/channels/{channel_id}/videos")
async def list_channel_videos(request: Request, channel_id: int) -> dict:
    """Kanalin YouTube videolari: managed/orphan isaretli, kota bilgisiyle."""
    await ensure_channel_access(request, channel_id)
    service = await _service(request)
    try:
        return await service.list_channel_videos(channel_id)
    except YouTubeManageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except YouTubeQuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc


@router.get("/youtube/channels/{channel_id}/analytics")
async def channel_analytics(request: Request, channel_id: int) -> dict:
    """Kanal istatistikleri + yonetilen videolarin toplamlari + en cok
    izlenen 5 video (listeyle ayni TTL onbellek)."""
    # Free plan kapisi (madde 6): YouTube analitigi Pro ile acilir.
    if not user_allows(getattr(request.state, "auth_user", None), "youtube_analytics"):
        return gate_response("youtube_analytics")
    await ensure_channel_access(request, channel_id)
    service = await _service(request)
    try:
        return await service.channel_analytics(channel_id)
    except YouTubeManageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except YouTubeQuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc


@router.delete("/youtube/channels/{channel_id}/videos/{youtube_video_id}")
async def delete_channel_video(
    request: Request, channel_id: int, youtube_video_id: str
) -> dict:
    """YouTube videosunu sil: managed ise klip kaldirma yolu (yerel dosya
    + kayitlar dahil), orphan ise dogrudan videos.delete."""
    await ensure_channel_access(request, channel_id)
    service = await _service(request)
    try:
        return await service.delete_channel_video(channel_id, youtube_video_id)
    except YouTubeManageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except YouTubeQuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
