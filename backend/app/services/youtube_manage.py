"""YouTube kanal yonetimi (kullanici istegi 2026-10-25): site uzerinden
kanalin videolarini listeleme, analiz etme ve silme — stüdyo kaydinda
olmayan (siteden silinmis ya da elle yuklenmis) "orphan" videolar dahil.

Akis (tumu kanalin OAuth token'i ile, API key'siz):
1. channels.list?mine=true -> kanal basligi, istatistikler, uploads listesi.
2. playlistItems.list (sayfali, en fazla 3 sayfa = 150 video) -> video id'leri.
3. videos.list (50'lik gruplar) -> baslik, tarih, gizlilik, sayilar, kapak.
4. DB birlestirme: published_videos satirlariyla eslesenler 'managed',
   kalanlar 'orphan' (stüdyo kaydi yok).

Kota: channels.list=1, playlistItems.list=1, videos.list=1, videos.delete=50
birim — mevcut QuotaTracker uzerinden harcanir; liste sonuclari 60 saniyelik
surec-genel TTL onbellekte tutulur ki polling kotayi yakmasin.

Silme: managed video mevcut klip kaldirma yolunu yeniden kullanir
(remove_rendered_clip: YouTube'dan sil + yerel dosya + kayitlar);
orphan video dogrudan videos.delete ile silinir. Her iki durumda da
audit event yazilir.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Channel, ChannelStatus, PublishedVideo, RenderedClip
from app.services.channel_service import record_event
from app.services.oauth_service import OAuthError, OAuthService
from app.services.settings_service import SettingsService
from app.services.youtube_client import (
    COST_CHANNELS_LIST,
    COST_PLAYLIST_ITEMS,
    QuotaTracker,
)
from app.services.youtube_upload import UploadError, YouTubeUploadClient

YOUTUBE_DATA_BASE = "https://www.googleapis.com/youtube/v3"
# QuotaTracker maliyet tablosunun yonetim ucantlari icin genislemesi:
# videos.list okuma, videos.delete ise agir (Google'un yayimlanmis
# maliyetleri) — silme bütçeyi hizla tüketir, bu yüzden ayrı sabit.
COST_VIDEOS_LIST = 1
COST_VIDEOS_DELETE = 50

# playlistItems sayfalama siniri: 3 sayfa x 50 = en fazla 150 video.
MAX_PLAYLIST_PAGES = 3
PLAYLIST_PAGE_SIZE = 50
VIDEOS_CHUNK_SIZE = 50

# Liste/analiz anlik goruntusunun TTL'i (saniye) — polling kotayi yakmasin.
CACHE_TTL_SECONDS = 60.0

# Surec-genel TTL onbellek (youtube_client'teki _CACHE deseninin aynisi;
# yonetim verisi ayri tutulur cunku TTL ve amac farklidir).
_MANAGE_CACHE: dict[str, tuple[float, Any]] = {}


def clear_cache() -> None:
    """Test kancasi: yonetim onbellegini bosaltir."""
    _MANAGE_CACHE.clear()


def _default_http_client() -> httpx.AsyncClient:
    """Indirection point so tests can inject a mock transport."""
    return httpx.AsyncClient(timeout=30)


def _to_int(value: Any) -> int:
    """YouTube istatistik degerleri string doner; guvenli int'e cevir."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _iso(value: Any) -> str | None:
    """DB datetime -> isoformat; None ve tuhaf degerler None kalir."""
    return value.isoformat() if value is not None else None


class YouTubeManageError(Exception):
    """Kullaniciya Turkce mesajla tasinan yonetim hatasi."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class YouTubeManageService:
    """Kanalin YouTube varligini listeleme / analiz / silme servisi."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    # --- ortak parcalar -------------------------------------------------

    def _quota(self) -> QuotaTracker:
        return QuotaTracker(self._sessionmaker, self._settings.daily_quota_units)

    async def quota_view(self) -> dict[str, int]:
        tracker = self._quota()
        return {
            "used_today": await tracker.used_today(),
            "daily_limit": int(self._settings.daily_quota_units),
        }

    def _cache_get(self, key: str) -> Any | None:
        entry = _MANAGE_CACHE.get(key)
        if entry is None:
            return None
        expires, value = entry
        if time.monotonic() >= expires:
            return None
        return value

    def _cache_store(self, key: str, value: Any) -> None:
        _MANAGE_CACHE[key] = (time.monotonic() + CACHE_TTL_SECONDS, value)

    @staticmethod
    def _cache_pop(key: str) -> None:
        _MANAGE_CACHE.pop(key, None)

    def _snapshot_key(self, channel_id: int) -> str:
        return f"youtube_manage:snapshot:{channel_id}"

    async def _channel_view(
        self, session: AsyncSession, channel_id: int
    ) -> Channel:
        channel = await session.get(Channel, channel_id)
        if channel is None:
            raise YouTubeManageError("Kanal bulunamadı.", 404)
        return channel

    @staticmethod
    def _channel_payload(channel: Channel) -> dict[str, Any]:
        return {
            "id": channel.id,
            "name": channel.name,
            "ribbon_color": channel.ribbon_color,
            "connected": channel.status == ChannelStatus.connected,
        }

    async def _oauth(
        self, channel_id: int, http: httpx.AsyncClient
    ) -> OAuthService:
        """Efektif ayarlarla OAuth servisi (anahtar DB'de olabilir)."""
        effective = await SettingsService(
            self._sessionmaker, self._settings
        ).effective_settings()
        return OAuthService(self._sessionmaker, effective)

    @staticmethod
    async def _token(
        oauth: OAuthService, channel_id: int, http: httpx.AsyncClient
    ) -> str:
        """Kanalin guncel access token'i; bagli degilse 409 ile reddet."""
        try:
            return await oauth.access_token(channel_id, http=http)
        except OAuthError as exc:
            if exc.status_code == 409:
                raise YouTubeManageError(
                    "Bu kanalın YouTube bağlantısı yok.", 409
                ) from exc
            raise YouTubeManageError(str(exc), exc.status_code) from exc

    # --- YouTube HTTP zinciri -------------------------------------------

    async def _fetch_channel(
        self, http: httpx.AsyncClient, token: str
    ) -> dict[str, Any]:
        await self._quota().try_spend(COST_CHANNELS_LIST)
        response = await http.get(
            f"{YOUTUBE_DATA_BASE}/channels",
            params={
                "part": "snippet,statistics,contentDetails",
                "mine": "true",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            raise YouTubeManageError(
                f"YouTube kanal bilgisi alınamadı (HTTP {response.status_code}).",
                502,
            )
        items = response.json().get("items") or []
        if not items:
            raise YouTubeManageError(
                "Bu Google hesabına bağlı bir YouTube kanalı yok.", 409
            )
        item = items[0]
        statistics = item.get("statistics", {}) or {}
        return {
            "youtube_channel_id": item.get("id"),
            "channel_title": (item.get("snippet", {}) or {}).get("title", ""),
            "subscriber_count": _to_int(statistics.get("subscriberCount")),
            "view_count": _to_int(statistics.get("viewCount")),
            "video_count": _to_int(statistics.get("videoCount")),
            "uploads_playlist_id": (
                (item.get("contentDetails", {}) or {})
                .get("relatedPlaylists", {})
                .get("uploads")
            ),
        }

    async def _fetch_upload_ids(
        self, http: httpx.AsyncClient, token: str, uploads_playlist_id: str | None
    ) -> list[str]:
        if not uploads_playlist_id:
            return []
        ids: list[str] = []
        page_token: str | None = None
        for _ in range(MAX_PLAYLIST_PAGES):
            await self._quota().try_spend(COST_PLAYLIST_ITEMS)
            params = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": str(PLAYLIST_PAGE_SIZE),
            }
            if page_token:
                params["pageToken"] = page_token
            response = await http.get(
                f"{YOUTUBE_DATA_BASE}/playlistItems",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 200:
                raise YouTubeManageError(
                    "Kanal video listesi alınamadı "
                    f"(HTTP {response.status_code}).",
                    502,
                )
            data = response.json()
            for item in data.get("items") or []:
                video_id = (item.get("contentDetails", {}) or {}).get("videoId")
                if video_id:
                    ids.append(str(video_id))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return ids

    async def _fetch_video_details(
        self, http: httpx.AsyncClient, token: str, video_ids: list[str]
    ) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for start in range(0, len(video_ids), VIDEOS_CHUNK_SIZE):
            chunk = video_ids[start : start + VIDEOS_CHUNK_SIZE]
            await self._quota().try_spend(COST_VIDEOS_LIST)
            response = await http.get(
                f"{YOUTUBE_DATA_BASE}/videos",
                params={
                    "part": "snippet,status,statistics",
                    "id": ",".join(chunk),
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 200:
                raise YouTubeManageError(
                    f"Video bilgileri alınamadı (HTTP {response.status_code}).",
                    502,
                )
            for item in response.json().get("items") or []:
                snippet = item.get("snippet", {}) or {}
                statistics = item.get("statistics", {}) or {}
                video_id = str(item.get("id", ""))
                thumbnails = snippet.get("thumbnails", {}) or {}
                thumbnail_url = (
                    (thumbnails.get("medium", {}) or {}).get("url")
                    or (
                        f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
                        if video_id
                        else None
                    )
                )
                details.append(
                    {
                        "youtube_video_id": video_id,
                        "title": snippet.get("title", ""),
                        "published_at": snippet.get("publishedAt"),
                        "privacy_status": (
                            item.get("status", {}) or {}
                        ).get("privacyStatus", ""),
                        "view_count": _to_int(statistics.get("viewCount")),
                        "like_count": _to_int(statistics.get("likeCount")),
                        "comment_count": _to_int(statistics.get("commentCount")),
                        "thumbnail_url": thumbnail_url,
                    }
                )
        return details

    async def _snapshot(
        self, channel_id: int, http: httpx.AsyncClient
    ) -> dict[str, Any]:
        """Kanal istatistikleri + video listesi (TTL onbellekli).

        Onbellek tutarsa HTTP hic yapilmaz; OAuth da gerekmez (veri zaten
        eldedir, polling kotayi yakmasin)."""
        key = self._snapshot_key(channel_id)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        oauth = await self._oauth(channel_id, http)
        token = await self._token(oauth, channel_id, http)
        channel_data = await self._fetch_channel(http, token)
        upload_ids = await self._fetch_upload_ids(
            http, token, channel_data.get("uploads_playlist_id")
        )
        videos = await self._fetch_video_details(http, token, upload_ids)
        snapshot = {
            "youtube": {
                "channel_title": channel_data["channel_title"],
                "subscriber_count": channel_data["subscriber_count"],
                "view_count": channel_data["view_count"],
                "video_count": channel_data["video_count"],
            },
            "videos": videos,
        }
        self._cache_store(key, snapshot)
        return snapshot

    # --- DB birlestirme ---------------------------------------------------

    async def _managed_map(self, channel_id: int) -> dict[str, dict[str, Any]]:
        """youtube_video_id -> yonetim bilgisi (render, yon, damgalar).

        published_videos satiri olan videolar 'managed' sayilir; render
        eslemesi PublishedVideo <-> RenderedClip cifti uzerinden
        (candidate+yon ya da kaynak video+yon) kurulur."""
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        sa.select(PublishedVideo).where(
                            PublishedVideo.channel_id == channel_id,
                            PublishedVideo.youtube_video_id != "",
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return {}
            render_conditions = []
            for row in rows:
                if row.clip_candidate_id is not None:
                    render_conditions.append(
                        sa.and_(
                            RenderedClip.clip_candidate_id == row.clip_candidate_id,
                            RenderedClip.orientation == row.orientation,
                        )
                    )
                elif row.source_video_id is not None:
                    render_conditions.append(
                        sa.and_(
                            RenderedClip.source_video_id == row.source_video_id,
                            RenderedClip.clip_candidate_id.is_(None),
                            RenderedClip.orientation == row.orientation,
                        )
                    )
            renders: list[RenderedClip] = []
            if render_conditions:
                renders = list(
                    (
                        await session.execute(
                            sa.select(RenderedClip).where(
                                sa.or_(*render_conditions)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            by_candidate = {
                (r.clip_candidate_id, r.orientation): r
                for r in renders
                if r.clip_candidate_id is not None
            }
            by_source = {
                (r.source_video_id, r.orientation): r
                for r in renders
                if r.clip_candidate_id is None and r.source_video_id is not None
            }
            mapping: dict[str, dict[str, Any]] = {}
            for row in rows:
                if row.clip_candidate_id is not None:
                    render = by_candidate.get(
                        (row.clip_candidate_id, row.orientation)
                    )
                else:
                    render = by_source.get((row.source_video_id, row.orientation))
                mapping[row.youtube_video_id] = {
                    "render_id": render.id if render is not None else None,
                    "orientation": row.orientation,
                    "public_at": _iso(row.public_at),
                    "scheduled_at": _iso(row.scheduled_at),
                }
            return mapping

    def _merge_videos(
        self,
        snapshot: dict[str, Any],
        managed_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """YouTube listesini yonetim bilgisiyle birlestir."""
        merged: list[dict[str, Any]] = []
        for video in snapshot["videos"]:
            managed = managed_map.get(video["youtube_video_id"])
            merged.append(
                {
                    **video,
                    "managed": managed is not None,
                    "render_id": managed["render_id"] if managed else None,
                    "orientation": managed["orientation"] if managed else None,
                    "public_at": managed["public_at"] if managed else None,
                    "scheduled_at": managed["scheduled_at"] if managed else None,
                }
            )
        return merged

    # --- genel API --------------------------------------------------------

    async def list_channel_videos(
        self,
        channel_id: int,
        http: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            channel = await self._channel_view(session, channel_id)
            channel_payload = self._channel_payload(channel)
        owned = http is None
        client = http if http is not None else _default_http_client()
        try:
            snapshot = await self._snapshot(channel_id, client)
        finally:
            if owned:
                await client.aclose()
        managed_map = await self._managed_map(channel_id)
        return {
            "channel": channel_payload,
            "youtube": snapshot["youtube"],
            "videos": self._merge_videos(snapshot, managed_map),
            "quota": await self.quota_view(),
        }

    async def channel_analytics(
        self,
        channel_id: int,
        http: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            channel = await self._channel_view(session, channel_id)
            channel_payload = self._channel_payload(channel)
        owned = http is None
        client = http if http is not None else _default_http_client()
        try:
            snapshot = await self._snapshot(channel_id, client)
        finally:
            if owned:
                await client.aclose()
        managed_map = await self._managed_map(channel_id)
        merged = self._merge_videos(snapshot, managed_map)
        managed_videos = [video for video in merged if video["managed"]]
        top_videos = sorted(
            merged, key=lambda video: video["view_count"], reverse=True
        )[:5]
        return {
            "channel": channel_payload,
            "youtube": snapshot["youtube"],
            "managed_totals": {
                "video_count": len(managed_videos),
                "total_view_count": sum(v["view_count"] for v in managed_videos),
                "total_like_count": sum(v["like_count"] for v in managed_videos),
                "total_comment_count": sum(
                    v["comment_count"] for v in managed_videos
                ),
            },
            "top_videos": top_videos,
            "quota": await self.quota_view(),
        }

    async def delete_channel_video(
        self,
        channel_id: int,
        youtube_video_id: str,
        http: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """YouTube videosunu sil.

        Managed (published_videos satiri var): mevcut klip kaldirma yolu
        (remove_rendered_clip) render_id uzerinden yeniden kullanilir —
        YouTube'dan sil + yerel dosya + kayitlar. Orphan: dogrudan
        videos.delete. Kota: videos.delete = 50 birim (islemden once)."""
        from app.services.video_removal import (
            VideoRemovalError,
            remove_rendered_clip,
        )

        async with self._sessionmaker() as session:
            await self._channel_view(session, channel_id)
            pub = (
                (
                    await session.execute(
                        sa.select(PublishedVideo).where(
                            PublishedVideo.channel_id == channel_id,
                            PublishedVideo.youtube_video_id == youtube_video_id,
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            render_id: int | None = None
            if pub is not None:
                if pub.clip_candidate_id is not None:
                    render = (
                        await session.execute(
                            sa.select(RenderedClip.id).where(
                                RenderedClip.clip_candidate_id
                                == pub.clip_candidate_id,
                                RenderedClip.orientation == pub.orientation,
                            )
                        )
                    ).scalar_one_or_none()
                else:
                    render = (
                        await session.execute(
                            sa.select(RenderedClip.id).where(
                                RenderedClip.source_video_id
                                == pub.source_video_id,
                                RenderedClip.clip_candidate_id.is_(None),
                                RenderedClip.orientation == pub.orientation,
                            )
                        )
                    ).scalar_one_or_none()
                render_id = render

        owned = http is None
        client = http if http is not None else _default_http_client()
        try:
            oauth = await self._oauth(channel_id, client)
            token = await self._token(oauth, channel_id, client)
            uploader = YouTubeUploadClient(token)

            # Silme agir bir kota islemi: once ayir, asarsa 429.
            await self._quota().try_spend(COST_VIDEOS_DELETE)

            files_removed = 0
            managed = pub is not None
            removed_via_render = False
            if managed and render_id is not None:
                try:
                    outcome = await remove_rendered_clip(
                        self._sessionmaker,
                        self._settings,
                        render_id,
                        http=client,
                    )
                except VideoRemovalError as exc:
                    raise YouTubeManageError(
                        str(exc), exc.status_code
                    ) from exc
                if not outcome.get("skipped"):
                    removed_via_render = True
                    files_removed = int(outcome.get("files_removed") or 0)
                    async with self._sessionmaker() as session:
                        record_event(
                            session,
                            channel_id,
                            "youtube.video_deleted",
                            {
                                "youtube_video_id": youtube_video_id,
                                "render_id": render_id,
                                "files_removed": files_removed,
                            },
                        )
                        await session.commit()
            if managed and not removed_via_render:
                # Kayit var ama render yok (ya da render zaten kaldirilmis):
                # dogrudan sil + yerel yayin satirini dusur.
                try:
                    await uploader.delete_video(client, youtube_video_id)
                except UploadError as exc:
                    raise YouTubeManageError(str(exc), 502) from exc
                async with self._sessionmaker() as session:
                    await session.execute(
                        sa.delete(PublishedVideo).where(
                            PublishedVideo.channel_id == channel_id,
                            PublishedVideo.youtube_video_id == youtube_video_id,
                        )
                    )
                    record_event(
                        session,
                        channel_id,
                        "youtube.video_deleted",
                        {"youtube_video_id": youtube_video_id},
                    )
                    await session.commit()
                files_removed = 0
            if not managed:
                # Orphan: stüdyo kaydi yok (siteden silinmis ya da elle
                # yuklenmis) — dogrudan videos.delete yeter.
                try:
                    await uploader.delete_video(client, youtube_video_id)
                except UploadError as exc:
                    raise YouTubeManageError(str(exc), 502) from exc
                async with self._sessionmaker() as session:
                    record_event(
                        session,
                        channel_id,
                        "youtube.orphan_deleted",
                        {"youtube_video_id": youtube_video_id},
                    )
                    await session.commit()
        finally:
            if owned:
                await client.aclose()

        # Silinen video onbellekteki listede kalmasin.
        self._cache_pop(self._snapshot_key(channel_id))
        return {
            "youtube_video_id": youtube_video_id,
            "deleted": True,
            "managed": managed,
            "files_removed": files_removed,
        }
