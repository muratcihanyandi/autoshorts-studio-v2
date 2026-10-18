"""Source channel service: registration + rights records + audit trail.

A source channel is only eligible for monitoring while its permission
status is 'authorized'; authorization is an explicit user act recorded
with a timestamp (rights record). M13: sources carry a platform, an
optional bound character, reaction-source and trim settings; twitch/
kick sources import their VODs manually (add_manual_video enqueues the
same media_process job the pipeline consumes).
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Character, SourceChannel, SourceVideo
from app.repositories.sources import SourceRepository
from app.schemas_sources import ManualVideoCreate, SourceCreate, SourceUpdate
from app.services.channel_service import record_event
from app.services.job_service import JobService


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _video_key(url: str) -> str:
    """VOD anahtarı: URL'nin son yol parçası; net parça yoksa URL'nin
    sha özeti (ilk 16 karakter) kullanılır."""
    path = urlsplit(url).path
    segment = path.rstrip("/").rsplit("/", 1)[-1] if path else ""
    if segment:
        return segment
    return hashlib.sha256(url.encode()).hexdigest()[:16]


class SourceServiceError(Exception):
    """Business rule failure with a user-facing Turkish message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class SourceService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_sources(self, channel_id: int) -> list[SourceChannel]:
        async with self._sessionmaker() as session:
            return await SourceRepository(session).list_for_channel(channel_id)

    async def get_source(self, source_id: int) -> SourceChannel | None:
        async with self._sessionmaker() as session:
            return await SourceRepository(session).get(source_id)

    async def character_names(self, character_ids) -> dict[int, str]:
        """Karakter id -> ad eşlemesi (kaynak çıktıları için tek sorgu)."""
        ids = {cid for cid in character_ids if cid is not None}
        if not ids:
            return {}
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(Character.id, Character.name).where(
                    Character.id.in_(ids)
                )
            )
            return {row[0]: row[1] for row in rows.all()}

    async def _require_character(
        self, session: AsyncSession, character_id: int
    ) -> None:
        if await session.get(Character, character_id) is None:
            raise SourceServiceError(
                "Karakter bulunamadı.", status_code=404
            )

    async def add_source(
        self, channel_id: int, data: SourceCreate
    ) -> SourceChannel:
        async with self._sessionmaker() as session:
            repo = SourceRepository(session)
            existing = await repo.get_for_channel(
                channel_id, data.youtube_channel_id
            )
            if existing is not None:
                raise SourceServiceError(
                    "Bu kaynak kanal bu stüdyo kanalına zaten kayıtlı.",
                    status_code=409,
                )
            if data.character_id is not None:
                await self._require_character(session, data.character_id)
            source = await repo.create(channel_id, data)
            record_event(
                session,
                channel_id,
                "source.added",
                {"youtube_channel_id": data.youtube_channel_id},
            )
            await session.commit()
            await session.refresh(source)
            return source

    async def update_source(
        self, source_id: int, data: SourceUpdate
    ) -> SourceChannel | None:
        async with self._sessionmaker() as session:
            repo = SourceRepository(session)
            source = await repo.get(source_id)
            if source is None:
                return None

            changes = data.model_dump(exclude_unset=True)
            if "title" in changes:
                source.title = changes["title"]
            if "filter_rules" in changes:
                source.filter_rules = changes["filter_rules"] or {}
            if "platform" in changes:
                source.platform = changes["platform"]
            if "character_id" in changes:
                new_character = changes["character_id"]
                if new_character is not None:
                    await self._require_character(session, new_character)
                source.character_id = new_character
            if "reaction_source" in changes:
                source.reaction_source = changes["reaction_source"]
            if "trim_start_seconds" in changes:
                source.trim_start_seconds = changes["trim_start_seconds"]
            if "trim_end_seconds" in changes:
                source.trim_end_seconds = changes["trim_end_seconds"]

            new_permission = changes.get("permission_status")
            permission_changed = (
                new_permission is not None
                and source.permission_status != new_permission
            )
            if permission_changed:
                source.permission_status = new_permission
                source.authorized_at = (
                    _utcnow() if new_permission == "authorized" else None
                )
                record_event(
                    session,
                    source.channel_id,
                    f"source.{new_permission}",
                    {
                        "source_id": source_id,
                        "youtube_channel_id": source.youtube_channel_id,
                    },
                )

            if not changes and not permission_changed:
                # Aynı duruma geçiş hak kaydı yazmaz (idempotent).
                return source

            await session.commit()
            await session.refresh(source)
            return source

    async def delete_source(self, source_id: int) -> bool:
        async with self._sessionmaker() as session:
            repo = SourceRepository(session)
            source = await repo.get(source_id)
            if source is None:
                return False
            channel_id = source.channel_id
            youtube_id = source.youtube_channel_id
            await repo.delete(source)
            record_event(
                session,
                channel_id,
                "source.removed",
                {"source_id": source_id, "youtube_channel_id": youtube_id},
            )
            await session.commit()
            return True

    async def count_authorized(self, channel_id: int | None = None) -> int:
        async with self._sessionmaker() as session:
            return await SourceRepository(session).count_authorized(channel_id)

    async def add_manual_video(
        self, source_id: int, data: ManualVideoCreate, jobs: JobService
    ) -> SourceVideo:
        """Manuel VOD içe aktarımı (twitch/kick): kayıt 'planned' olarak
        doğar ve boru hattını besleyen media_process işini kuyruklar."""
        video_key = _video_key(data.url)
        async with self._sessionmaker() as session:
            repo = SourceRepository(session)
            source = await repo.get(source_id)
            if source is None:
                raise SourceServiceError(
                    "Kaynak kanal bulunamadı.", status_code=404
                )
            existing = await repo.get_video(source_id, video_key)
            if existing is not None:
                raise SourceServiceError(
                    "Bu video bu kaynak kanala zaten kayıtlı.",
                    status_code=409,
                )
            video = await repo.create_video(source_id, video_key, data.title)
            record_event(
                session,
                source.channel_id,
                "source.video_added",
                {"source_id": source_id, "video_key": video_key},
            )
            await session.commit()
            await session.refresh(video)
            video_id = video.id
        await jobs.enqueue(
            "media_process",
            {"source_video_id": video_id, "import_path": data.url},
        )
        return video
