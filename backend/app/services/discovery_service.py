"""Source discovery: poll authorized sources, record new videos once.

Duplicate prevention is structural: source_videos carries a unique
(source_channel_id, youtube_video_id) constraint and discovery inserts
only ids it has not seen, so repeated polling never duplicates records
or downstream jobs.

Gorev 8 (2026-10-21): the SAME CONTENT re-uploaded by a different
mirrored source channel (different YouTube video id, slightly
different title format) is additionally caught by global title
dedupe (source_dedupe) — the new row lands as 'excluded' so it is
never downloaded or clipped twice.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import SourceChannel, SourceVideo
from app.services.channel_service import record_event
from app.services.source_dedupe import find_duplicate_title, normalize_title
from app.services.source_rules import evaluate_source_rules
from app.services.youtube_client import (
    QuotaTracker,
    YouTubeDataClient,
    YouTubeQuotaExceeded,
)

# Ayni kanalda iki kesif ayni anda yurumesin (API "Kesfet" cagrisi +
# worker saatligi yarisi): dedupe okumasi commit-oncesi yarista cift
# insert denemesi uretip butun turu UniqueViolation ile dusuruyordu
# (2026-10-20 canli gozlem). Surec ici kilit; tek uvicorn sureci var.
# Kilit event loop'a baglidir: testler her asyncio.run'da yeni loop
# actigindan loop degistiyse kilit tazelenir (uretimde tek loop, davranis
# ayni).
_DISCOVERY_LOCKS: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = {}


def _channel_lock(channel_id: int) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    entry = _DISCOVERY_LOCKS.get(channel_id)
    if entry is None or entry[0] is not loop:
        entry = (loop, asyncio.Lock())
        _DISCOVERY_LOCKS[channel_id] = entry
    return entry[1]


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # YouTube sends ISO-8601 with 'Z'.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class DiscoveryService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._client = YouTubeDataClient(
            settings, QuotaTracker(sessionmaker, settings.daily_quota_units)
        )

    async def _authorized_sources(
        self, session: AsyncSession, channel_id: int
    ) -> list[SourceChannel]:
        result = await session.execute(
            select(SourceChannel)
            .where(
                SourceChannel.channel_id == channel_id,
                SourceChannel.permission_status == "authorized",
            )
            .order_by(SourceChannel.id)
        )
        return list(result.scalars().all())

    async def discover_for_channel(self, channel_id: int) -> dict[str, Any]:
        """Kanal kilidiyle serialize edilmis kesif girisi (bkz.
        _DISCOVERY_LOCKS)."""
        async with _channel_lock(channel_id):
            return await self._discover_for_channel_locked(channel_id)

    async def _discover_for_channel_locked(
        self, channel_id: int
    ) -> dict[str, Any]:
        """Poll every authorized youtube source of the channel; non-youtube
        sources are skipped with a per-source platform note (their VODs
        are imported manually, M13)."""
        self._client.require_configured()
        new_videos = 0
        new_excluded = 0
        duplicate_excluded = 0
        sources_checked = 0
        quota_blocked = False
        skipped_platforms: list[str] = []

        async with self._sessionmaker() as session:
            sources = await self._authorized_sources(session, channel_id)

            # Gorev 8: ayni icerik farkli mirror kanaldan geldiginde
            # (farkli video kimligi, benzer baslik) tekrar islenmesin.
            # Karsilastirma tablosu: sistemin AKTIF (hariç olmayan)
            # videolarinin normalize edilmis basliklari; bu tur icinde
            # kesfedilen yeni aktif videolar da eklenir ki ayni turda
            # iki kaynaktan gelen cift yakalansin.
            active_title_rows = (
                await session.execute(
                    select(SourceVideo.id, SourceVideo.title).where(
                        SourceVideo.status != "excluded"
                    )
                )
            ).all()
            known_titles: list[tuple[str, int]] = [
                (normalize_title(title), video_id)
                for video_id, title in active_title_rows
            ]

            for source in sources:
                # YouTube keşfi yalnızca youtube kaynaklarını yoklar;
                # twitch/kick VOD'ları manuel içe aktarılır.
                if source.platform != "youtube":
                    skipped_platforms.append(source.platform)
                    continue
                try:
                    uploads_playlist = await self._client.get_uploads_playlist_id(
                        source.youtube_channel_id
                    )
                    if uploads_playlist is None:
                        continue
                    videos = await self._client.list_upload_videos(uploads_playlist)
                except YouTubeQuotaExceeded:
                    quota_blocked = True
                    break

                sources_checked += 1
                known_ids = set(
                    (
                        await session.execute(
                            select(SourceVideo.youtube_video_id).where(
                                SourceVideo.source_channel_id == source.id
                            )
                        )
                    ).scalars().all()
                )
                for video in videos:
                    if video["video_id"] in known_ids:
                        continue
                    published_at = _parse_published(video["published_at"])
                    exclusion = evaluate_source_rules(
                        source.filter_rules,
                        title=video["title"],
                        published_at=published_at,
                    )
                    duplicate_of = None
                    if not exclusion:
                        duplicate_of = find_duplicate_title(
                            normalize_title(video["title"]), known_titles
                        )
                    session.add(
                        SourceVideo(
                            source_channel_id=source.id,
                            youtube_video_id=video["video_id"],
                            title=video["title"],
                            published_at=published_at,
                            status=(
                                "excluded"
                                if exclusion or duplicate_of is not None
                                else "discovered"
                            ),
                        )
                    )
                    known_ids.add(video["video_id"])
                    if exclusion:
                        new_excluded += 1
                    elif duplicate_of is not None:
                        duplicate_excluded += 1
                    else:
                        new_videos += 1
                        # Yeni aktif video ayni turdaki sonraki
                        # kaynaklar icin karsilastirmaya girer; kimligi
                        # henüz belli olmadığından geçici işaretle
                        # (-1) tutulur — onemli olan eslesmenin kendisi.
                        known_titles.append(
                            (normalize_title(video["title"]), -1)
                        )

            record_event(
                session,
                channel_id,
                "discovery.run",
                {
                    "sources_checked": sources_checked,
                    "new_videos": new_videos,
                    "new_excluded": new_excluded,
                    "duplicate_excluded": duplicate_excluded,
                    "quota_blocked": quota_blocked,
                    "skipped_platforms": skipped_platforms,
                },
            )
            await session.commit()

        return {
            "sources_checked": sources_checked,
            "new_videos": new_videos,
            "new_excluded": new_excluded,
            "duplicate_excluded": duplicate_excluded,
            "quota_blocked": quota_blocked,
            "skipped_platforms": skipped_platforms,
        }

    async def list_videos(
        self, channel_id: int, status: str | None = None
    ) -> list[SourceVideo]:
        """Discovered videos across all sources of a studio channel."""
        async with self._sessionmaker() as session:
            query = (
                select(SourceVideo)
                .join(
                    SourceChannel,
                    SourceVideo.source_channel_id == SourceChannel.id,
                )
                .where(SourceChannel.channel_id == channel_id)
                .order_by(SourceVideo.discovered_at, SourceVideo.id)
            )
            if status is not None:
                query = query.where(SourceVideo.status == status)
            result = await session.execute(query)
            return list(result.scalars().all())
