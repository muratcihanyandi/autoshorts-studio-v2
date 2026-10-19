"""YouTube Data API v3 client with daily quota tracking and a TTL cache.

Quota costs follow Google's published numbers for the endpoints used
(channels.list = 1, playlistItems.list = 1 unit). Requests are refused
with YouTubeQuotaExceeded once the configured daily budget is spent, so
polling can never silently burn past the limit. Responses are cached
process-locally for the configured TTL to keep repeated polls cheap.
"""
from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import QuotaUsage

YOUTUBE_DATA_BASE = "https://www.googleapis.com/youtube/v3"
COST_CHANNELS_LIST = 1
COST_PLAYLIST_ITEMS = 1


class YouTubeQuotaExceeded(Exception):
    """The daily quota budget is spent; the request was not made."""


class YouTubeNotConfigured(Exception):
    """No API key configured."""


def _default_http_client() -> httpx.AsyncClient:
    """Indirection point so tests can inject a mock transport."""
    return httpx.AsyncClient(timeout=15)


def _today() -> date:
    return datetime.now(UTC).date()


# Süreç-genel TTL önbelleği: istekler arası da yaşar (polling ucuz kalır).
_CACHE: dict[str, tuple[float, Any]] = {}


def clear_cache() -> None:
    """Test kancası: önbelleği boşaltır."""
    _CACHE.clear()


class QuotaTracker:
    """Daily quota ledger backed by the quota_usage table."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        daily_limit: int,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._daily_limit = daily_limit

    async def used_today(self) -> int:
        async with self._sessionmaker() as session:
            row = await session.get(QuotaUsage, _today())
            return row.units_used if row is not None else 0

    async def try_spend(self, units: int) -> None:
        """Reserve units or raise; the row is created on first use."""
        async with self._sessionmaker() as session:
            day = _today()
            row = await session.get(QuotaUsage, day)
            if row is None:
                row = QuotaUsage(day=day, units_used=0)
                session.add(row)
            if row.units_used + units > self._daily_limit:
                raise YouTubeQuotaExceeded(
                    "Günlük YouTube kota bütçesi tükendi; yoklama yarın devam eder."
                )
            row.units_used += units
            await session.commit()


class YouTubeDataClient:
    """Thin, quota-gated, cached reader for the endpoints monitoring needs."""

    def __init__(self, settings: Settings, quota: QuotaTracker | None = None) -> None:
        self._settings = settings
        self._quota = quota

    def require_configured(self) -> None:
        self._check_configured()

    def _check_configured(self) -> None:
        if not self._settings.youtube_api_key:
            raise YouTubeNotConfigured(
                "YOUTUBE_API_KEY yapılandırılmamış; kaynak izleme kapalı."
            )

    def _cached(self, key: str) -> Any | None:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        expires, value = entry
        if time.monotonic() >= expires:
            return None
        return value

    def _store(self, key: str, value: Any) -> None:
        ttl = self._settings.source_cache_ttl_seconds
        _CACHE[key] = (time.monotonic() + ttl, value)

    async def _get_json(self, path: str, params: dict[str, str]) -> Any:
        key = f"{path}?{sorted(params.items())}"
        cached = self._cached(key)
        if cached is not None:
            return cached
        async with _default_http_client() as http:
            response = await http.get(
                YOUTUBE_DATA_BASE + path,
                params={**params, "key": self._settings.youtube_api_key},
            )
        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"YouTube API hatası: HTTP {response.status_code}",
                request=response.request,
                response=response,
            )
        data = response.json()
        self._store(key, data)
        return data

    async def get_uploads_playlist_id(self, youtube_channel_id: str) -> str | None:
        self._check_configured()
        if self._quota is not None:
            await self._quota.try_spend(COST_CHANNELS_LIST)
        data = await self._get_json(
            "/channels",
            {"part": "contentDetails", "id": youtube_channel_id},
        )
        items = data.get("items") or []
        if not items:
            return None
        return items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get(
            "uploads"
        )

    async def list_upload_videos(
        self, uploads_playlist_id: str, max_results: int = 50
    ) -> list[dict[str, Any]]:
        """Latest uploads as [{video_id, title, published_at}]."""
        self._check_configured()
        if self._quota is not None:
            await self._quota.try_spend(COST_PLAYLIST_ITEMS)
        data = await self._get_json(
            "/playlistItems",
            {
                "part": "snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": str(max_results),
            },
        )
        videos: list[dict[str, Any]] = []
        for item in data.get("items") or []:
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue
            videos.append(
                {
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt"),
                }
            )
        return videos
