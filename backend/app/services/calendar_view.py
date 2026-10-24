"""Takvim görünümü (Görev 1): planlanan ve gerçekleşen yayınlar.

Her çalışan kanalın yayın dilimleri (yön bazlı prime time saatleri +
saat dilimi) ay bazında listelenir. Gelecek dilimler mevcut stokla
simüle edilir:

- ``scheduled`` — gizli yüklenmiş (verified) video, saat bekliyor. Bu
  dilimlere kesin olarak bu video düşer. Elle planlananlar
  (``scheduled_at``) kendi saatlerinde, ``manual`` işaretli durur.
- ``planned``   — stoktaki hazır klip (render edilmiş, henüz yüklenmemiş).
  Onay/yükleme sonrası bu dilime düşmesi beklenir.
- ``empty``     — dilim boş: hazır video yok ya da günlük limit doldu.
- ``published`` — gerçekleşen yayın (public_at ay içinde).

Her kayıt tıklanabilir detay taşır: klip render kimliği (detay penceresi
için), başlık, kapak, YouTube bağlantısı ve metaveri özeti. Dikey ve
yatay videolar KENDİ slot setlerinde simüle edilir (shorts prime time).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    Channel,
    ClipCandidate,
    ClipMetadata,
    PublishedVideo,
    PublishingProfile,
    RenderedClip,
    SourceChannel,
    SourceVideo,
)
from app.services.library_view import LibraryViewService
from app.services.publishing_schedule import (
    DEFAULT_PUBLISH_TIMES,
    DEFAULT_TIMEZONE,
    DEFAULT_VERTICAL_PUBLISH_TIMES,
    parse_publish_times,
    slots_for_orientation,
)

MONTH_NAMES = (
    "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class CalendarViewService:
    """Takvim ekranının tüm verisi (salt okunur)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def calendar(self, year: int, month: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        async with self._sessionmaker() as session:
            profiles = (
                (
                    await session.execute(
                        sa.select(PublishingProfile, Channel)
                        .join(Channel, PublishingProfile.channel_id == Channel.id)
                        .where(
                            Channel.status == "connected",
                            PublishingProfile.automation_state == "running",
                        )
                        .order_by(PublishingProfile.channel_id)
                    )
                )
                .all()
            )
            # Yatay uretim yetenegi: kanalda en az bir yetkili kaynak yatay
            # tam kesit uretiyor mu (output_orientation='horizontal' ya da
            # 'auto' + reaction_source). Yeteneksiz kanalda yatay dilim
            # simule EDILMEZ: yoksa takvim ayda onlarca hic dolmayacak
            # turuncu dilimle dolar (2026-10-24 canli bildirimi).
            horizontal_capable: set[int] = set(
                (
                    await session.execute(
                        sa.select(SourceChannel.channel_id)
                        .where(
                            SourceChannel.permission_status == "authorized",
                            sa.or_(
                                SourceChannel.output_orientation == "horizontal",
                                sa.and_(
                                    SourceChannel.output_orientation == "auto",
                                    SourceChannel.reaction_source.is_(True),
                                ),
                            ),
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            channels_meta = []
            slot_map: dict[int, dict[str, list]] = {}
            queues: dict[int, dict[str, list[dict]]] = {}
            for profile, channel in profiles:
                # Bozuk saat yapilandirmasi takvimi patratmam: varsayilana
                # dus ve kanali listele.
                try:
                    v_slots = list(
                        slots_for_orientation(profile.settings, "vertical")
                    )
                    h_slots = list(
                        slots_for_orientation(profile.settings, "horizontal")
                    )
                except Exception:  # noqa: BLE001 - ScheduleError varsayilan
                    v_slots = list(
                        parse_publish_times(
                            list(DEFAULT_VERTICAL_PUBLISH_TIMES)
                        )
                    )
                    h_slots = list(parse_publish_times(list(DEFAULT_PUBLISH_TIMES)))
                channels_meta.append(
                    {
                        "id": channel.id,
                        "name": channel.name,
                        "ribbon_color": channel.ribbon_color,
                        "timezone": profile.timezone or DEFAULT_TIMEZONE,
                        "publish_times": [
                            s.strftime("%H:%M") for s in h_slots
                        ],
                        "publish_times_vertical": [
                            s.strftime("%H:%M") for s in v_slots
                        ],
                        "automation_state": profile.automation_state,
                        "daily_vertical_limit": profile.daily_clip_target,
                        "daily_horizontal_limit": profile.daily_horizontal_limit,
                    }
                )
                slot_map[channel.id] = {
                    "vertical": v_slots,
                    "horizontal": h_slots,
                }
                queues[channel.id] = {
                    "vertical": await self._ready_queue(
                        session, channel.id, "vertical"
                    ),
                    "horizontal": await self._ready_queue(
                        session, channel.id, "horizontal"
                    ),
                }
                # Stokta/sirada yatay video varsa kaynak ayari degisse bile
                # yatay dilimler gosterilir (mevcut yatay stok yayinlanabilir).
                active = ["vertical"]
                if (
                    channel.id in horizontal_capable
                    or queues[channel.id]["horizontal"]
                ):
                    active.append("horizontal")
                channels_meta[-1]["orientations"] = active

            published = await self._published_entries(session, year, month)

        month_start = datetime(year, month, 1).date()
        month_end = datetime(year, month, monthrange(year, month)[1]).date()
        entries: list[dict[str, Any]] = list(published)

        entry_id = 1000
        for profile_row in channels_meta:
            channel_id = profile_row["id"]
            queue = queues[channel_id]
            slots = slot_map[channel_id]
            tz = ZoneInfo(profile_row["timezone"])
            today_local = now.astimezone(tz).date()

            # Elle planlanmis videolar slot simulasyonundan ayri: kendi
            # saatlerinde, kendi günlerinde dururlar.
            active_orientations = profile_row["orientations"]
            for orientation in active_orientations:
                unscheduled = []
                for item in queue[orientation]:
                    raw = item.get("scheduled_at")
                    if raw is None:
                        unscheduled.append(item)
                        continue
                    try:
                        moment = _as_utc(datetime.fromisoformat(raw))
                    except (TypeError, ValueError):
                        moment = None
                    if moment is None:
                        unscheduled.append(item)
                        continue
                    if moment <= now:
                        continue  # saati gecmis: kisa surede yayina cikar
                    local_day = moment.astimezone(tz).date()
                    if not (month_start <= local_day <= month_end):
                        continue
                    entry_id += 1
                    entries.append(
                        {
                            "id": entry_id,
                            "channel_id": channel_id,
                            "channel_name": profile_row["name"],
                            "ribbon_color": profile_row["ribbon_color"],
                            "orientation": orientation,
                            "status": item["status"],
                            "scheduled_at": moment.isoformat(),
                            "local_date": local_day.isoformat(),
                            "title": item["title"],
                            "clip_render_id": item["clip_render_id"],
                            "published_video_id": item.get(
                                "published_video_id"
                            ),
                            "thumbnail_url": item["thumbnail_url"],
                            "youtube_video_id": item.get("youtube_video_id"),
                            "youtube_url": item.get("youtube_url"),
                            "metadata": item["metadata"],
                            "note": "Elle planlandı; bu saatte herkese açılacak.",
                            "manual": True,
                        }
                    )
                queue[orientation] = unscheduled

            day = max(month_start, today_local)
            while day <= month_end:
                counts = self._todays_counts(
                    entries, channel_id, day, tz
                )
                for orientation in active_orientations:
                    for slot in slots[orientation]:
                        slot_utc = (
                            datetime.combine(day, slot, tzinfo=tz)
                            .astimezone(UTC)
                        )
                        if slot_utc <= now:
                            continue
                        entry_id += 1
                        entry = self._slot_entry(
                            entry_id,
                            profile_row,
                            orientation,
                            slot_utc,
                            day,
                            counts,
                            queue,
                        )
                        if entry is not None:
                            entries.append(entry)
                day += timedelta(days=1)

        entries.sort(key=lambda e: (e["scheduled_at"], e["channel_id"]))
        return {
            "year": year,
            "month": month,
            "month_label": f"{MONTH_NAMES[month]} {year}",
            "entries": entries,
            "channels": channels_meta,
            "generated_at": now.isoformat(),
        }

    # --- yardimcilar ---

    @staticmethod
    def _todays_counts(
        entries: list[dict], channel_id: int, day, tz: ZoneInfo
    ) -> dict[str, int]:
        """Kanal-yerel bugune dusen yayinlar (gerceklesen + simulasyon).
        Elle planlananlar gunluk limit sayimina girmez: motor da onlari
        limit disinda yayina acar."""
        counts = {"vertical": 0, "horizontal": 0}
        for entry in entries:
            if entry["channel_id"] != channel_id:
                continue
            if entry.get("status") == "empty" or entry.get("manual"):
                continue
            try:
                moment = datetime.fromisoformat(entry["scheduled_at"])
            except (TypeError, ValueError):
                continue
            if moment.astimezone(tz).date() != day:
                continue
            orientation = entry.get("orientation")
            if orientation in counts:
                counts[orientation] += 1
        return counts

    def _slot_entry(
        self,
        entry_id: int,
        channel: dict,
        orientation: str,
        slot_utc: datetime,
        day,
        counts: dict[str, int],
        queue: dict[str, list[dict]],
    ) -> dict[str, Any] | None:
        """Bir yonun dilimini kendi kuyrugundan doldurur; limit doluysa
        ya da stok yoksa dilim bos kalir."""
        base = {
            "id": entry_id,
            "channel_id": channel["id"],
            "channel_name": channel["name"],
            "ribbon_color": channel["ribbon_color"],
            "scheduled_at": slot_utc.isoformat(),
            "local_date": day.isoformat(),
        }
        limit = (
            channel["daily_vertical_limit"]
            if orientation == "vertical"
            else channel["daily_horizontal_limit"]
        )
        items = queue.get(orientation) or []
        if limit and counts[orientation] >= limit:
            return {
                **base,
                "orientation": orientation,
                "status": "empty",
                "title": None,
                "clip_render_id": None,
                "published_video_id": None,
                "thumbnail_url": None,
                "youtube_video_id": None,
                "youtube_url": None,
                "metadata": None,
                "manual": False,
                "note": "Günlük limit doldu",
            }
        if not items:
            return {
                **base,
                "orientation": orientation,
                "status": "empty",
                "title": None,
                "clip_render_id": None,
                "published_video_id": None,
                "thumbnail_url": None,
                "youtube_video_id": None,
                "youtube_url": None,
                "metadata": None,
                "manual": False,
                "note": "Bu dilim için hazır video yok",
            }
        item = items.pop(0)
        counts[orientation] += 1
        return {
            **base,
            "orientation": orientation,
            "status": item["status"],
            "title": item["title"],
            "clip_render_id": item["clip_render_id"],
            "published_video_id": item.get("published_video_id"),
            "thumbnail_url": item["thumbnail_url"],
            "youtube_video_id": item.get("youtube_video_id"),
            "youtube_url": item.get("youtube_url"),
            "metadata": item["metadata"],
            "manual": False,
            "note": item["note"],
        }

    async def _ready_queue(
        self, session: AsyncSession, channel_id: int, orientation: str
    ) -> list[dict[str, Any]]:
        """Bir kanal+yön için yükleme sırası: önce gizli yüklenmiş
        (scheduled), sonra stoktaki hazır klip (planned)."""
        scheduled = await self._published_queue(
            session, channel_id, orientation
        )
        planned = await self._stock_queue(session, channel_id, orientation)
        return scheduled + planned

    async def _published_queue(
        self, session: AsyncSession, channel_id: int, orientation: str
    ) -> list[dict[str, Any]]:
        statement = (
            sa.select(PublishedVideo, ClipCandidate.score)
            .outerjoin(
                ClipCandidate,
                PublishedVideo.clip_candidate_id == ClipCandidate.id,
            )
            .where(
                PublishedVideo.channel_id == channel_id,
                PublishedVideo.orientation == orientation,
                PublishedVideo.status == "verified",
                PublishedVideo.visibility == "private",
            )
        )
        if orientation == "vertical":
            statement = statement.order_by(
                sa.desc(sa.func.coalesce(ClipCandidate.score, 0))
            )
        else:
            statement = statement.order_by(PublishedVideo.id)
        rows = (await session.execute(statement)).all()
        items = []
        for row, _score in rows:
            render = await self._render_for_published(session, row)
            metadata = await self._metadata_for(
                session, row.clip_candidate_id, row.source_video_id
            )
            items.append(
                {
                    "status": "scheduled",
                    "title": metadata["title"]
                    if metadata
                    else (row.title or "Hazır video"),
                    "clip_render_id": render.id if render is not None else None,
                    "published_video_id": row.id,
                    "scheduled_at": (
                        row.scheduled_at.isoformat()
                        if row.scheduled_at
                        else None
                    ),
                    "thumbnail_url": (
                        LibraryViewService._thumbnail_url(
                            render,
                            await self._video_of(session, row),
                            await self._source_of(session, row),
                        )
                        if render is not None
                        else None
                    ),
                    "youtube_video_id": row.youtube_video_id or None,
                    "youtube_url": (
                        f"https://www.youtube.com/watch?v={row.youtube_video_id}"
                        if row.youtube_video_id
                        else None
                    ),
                    "metadata": metadata,
                    "note": "Gizli yüklendi; plan saatinde herkese açılacak.",
                }
            )
        return items

    async def _stock_queue(
        self, session: AsyncSession, channel_id: int, orientation: str
    ) -> list[dict[str, Any]]:
        """Stoktaki hazır klipler: render edilmiş, henüz yüklenmemiş."""
        statement = (
            sa.select(RenderedClip, ClipCandidate)
            .outerjoin(
                ClipCandidate, RenderedClip.clip_candidate_id == ClipCandidate.id
            )
            .join(
                SourceVideo,
                sa.or_(
                    ClipCandidate.source_video_id == SourceVideo.id,
                    RenderedClip.source_video_id == SourceVideo.id,
                ),
            )
            .join(
                SourceChannel,
                SourceVideo.source_channel_id == SourceChannel.id,
            )
            .outerjoin(
                PublishedVideo,
                sa.or_(
                    sa.and_(
                        PublishedVideo.clip_candidate_id
                        == RenderedClip.clip_candidate_id,
                        PublishedVideo.orientation == orientation,
                    ),
                    sa.and_(
                        PublishedVideo.source_video_id == SourceVideo.id,
                        PublishedVideo.clip_candidate_id.is_(None),
                        PublishedVideo.orientation == orientation,
                    ),
                ),
            )
            .where(
                SourceChannel.channel_id == channel_id,
                SourceChannel.permission_status == "authorized",
                RenderedClip.status == "rendered",
                RenderedClip.orientation == orientation,
                PublishedVideo.id.is_(None),
                (
                    ClipCandidate.id.is_not(None)
                    if orientation == "vertical"
                    else ClipCandidate.id.is_(None)
                ),
            )
        )
        if orientation == "vertical":
            statement = statement.order_by(
                sa.desc(sa.func.coalesce(ClipCandidate.score, 0))
            )
        else:
            statement = statement.order_by(RenderedClip.id)
        rows = (await session.execute(statement)).all()
        items = []
        for render, candidate in rows:
            video_id = (
                candidate.source_video_id
                if candidate is not None
                else render.source_video_id
            )
            video = await session.get(SourceVideo, video_id)
            source = (
                await session.get(SourceChannel, video.source_channel_id)
                if video is not None
                else None
            )
            metadata = await self._metadata_for(
                session,
                candidate.id if candidate is not None else None,
                video_id if candidate is None else None,
            )
            items.append(
                {
                    "status": "planned",
                    "title": metadata["title"]
                    if metadata
                    else (video.title if video is not None else "Hazır klip"),
                    "clip_render_id": render.id,
                    "published_video_id": None,
                    "scheduled_at": None,
                    "thumbnail_url": LibraryViewService._thumbnail_url(
                        render, video, source
                    ),
                    "youtube_video_id": None,
                    "youtube_url": None,
                    "metadata": metadata,
                    "note": "Stokta hazır; onay/yükleme sonrası bu dilime düşer.",
                }
            )
        return items

    async def _published_entries(
        self, session: AsyncSession, year: int, month: int
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    sa.select(PublishedVideo, Channel)
                    .join(Channel, PublishedVideo.channel_id == Channel.id)
                    .where(PublishedVideo.visibility == "public")
                    .order_by(PublishedVideo.public_at.asc())
                )
            )
            .all()
        )
        entries = []
        for row, channel in rows:
            public_at = _as_utc(row.public_at)
            if public_at is None:
                continue
            if public_at.year != year or public_at.month != month:
                continue
            render = await self._render_for_published(session, row)
            metadata = await self._metadata_for(
                session, row.clip_candidate_id, row.source_video_id
            )
            entries.append(
                {
                    "id": 100000 + row.id,
                    "channel_id": channel.id,
                    "channel_name": channel.name,
                    "ribbon_color": channel.ribbon_color,
                    "orientation": row.orientation,
                    "status": "published",
                    "scheduled_at": public_at.isoformat(),
                    "local_date": public_at.date().isoformat(),
                    "title": metadata["title"]
                    if metadata
                    else (row.title or "Yayınlanan video"),
                    "clip_render_id": render.id if render is not None else None,
                    "published_video_id": row.id,
                    "thumbnail_url": (
                        LibraryViewService._thumbnail_url(
                            render,
                            await self._video_of(session, row),
                            await self._source_of(session, row),
                        )
                        if render is not None
                        else None
                    ),
                    "youtube_video_id": row.youtube_video_id or None,
                    "youtube_url": (
                        f"https://www.youtube.com/watch?v={row.youtube_video_id}"
                        if row.youtube_video_id
                        else None
                    ),
                    "metadata": metadata,
                    "manual": False,
                    "note": "Yayına verildi.",
                }
            )
        return entries

    @staticmethod
    async def _render_for_published(
        session: AsyncSession, row: PublishedVideo
    ) -> RenderedClip | None:
        if row.clip_candidate_id is not None:
            statement = sa.select(RenderedClip).where(
                RenderedClip.clip_candidate_id == row.clip_candidate_id,
                RenderedClip.orientation == row.orientation,
            )
        else:
            statement = sa.select(RenderedClip).where(
                RenderedClip.source_video_id == row.source_video_id,
                RenderedClip.clip_candidate_id.is_(None),
                RenderedClip.orientation == row.orientation,
            )
        return (
            (await session.execute(statement)).scalars().one_or_none()
        )

    @staticmethod
    async def _video_of(
        session: AsyncSession, row: PublishedVideo
    ) -> SourceVideo | None:
        video_id = row.source_video_id
        if video_id is None and row.clip_candidate_id is not None:
            candidate = await session.get(
                ClipCandidate, row.clip_candidate_id
            )
            video_id = candidate.source_video_id if candidate else None
        return (
            await session.get(SourceVideo, video_id)
            if video_id is not None
            else None
        )

    @staticmethod
    async def _source_of(
        session: AsyncSession, row: PublishedVideo
    ) -> SourceChannel | None:
        video = await CalendarViewService._video_of(session, row)
        if video is None:
            return None
        return await session.get(SourceChannel, video.source_channel_id)

    @staticmethod
    async def _metadata_for(
        session: AsyncSession,
        clip_candidate_id: int | None,
        source_video_id: int | None,
    ) -> dict[str, Any] | None:
        if clip_candidate_id is not None:
            statement = (
                sa.select(ClipMetadata)
                .where(ClipMetadata.clip_candidate_id == clip_candidate_id)
                .order_by(ClipMetadata.revision.desc())
                .limit(1)
            )
        elif source_video_id is not None:
            statement = (
                sa.select(ClipMetadata)
                .where(
                    ClipMetadata.source_video_id == source_video_id,
                    ClipMetadata.clip_candidate_id.is_(None),
                )
                .order_by(ClipMetadata.revision.desc())
                .limit(1)
            )
        else:
            return None
        row = (
            (await session.execute(statement)).scalars().one_or_none()
        )
        if row is None:
            return None
        return {
            "title": row.title,
            "description": row.description,
            "tags": list(row.tags or []),
            "hook": row.hook,
            "thumbnail_text": row.thumbnail_text,
            "status": row.status,
            "content_warning": row.content_warning,
            "ai_disclosure": row.ai_disclosure,
        }
