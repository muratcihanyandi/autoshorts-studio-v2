"""Publishing service (M10): guards, upload, verification, schedule.

A clip can publish only when EVERY guard passes: the source channel is
authorized (rights record — enforced in code, independent of LLM
output), the render exists and succeeded, approved metadata exists
(unless the channel profile opts into auto-approval), and the clip was
never published (unique row + pre-check = duplicate prevention).

Uploads are private-first and verified through videos.list; the
resumable session URI is persisted so an interrupted upload can be
reconciled. Failures mark the row 'failed' with a Turkish reason and
the job can retry.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx
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
from app.services.channel_service import record_event
from app.services.oauth_service import OAuthService
from app.services.publishing_schedule import (
    ScheduleError,
    is_due,
    next_due_time,
)
from app.services.youtube_upload import (
    UploadError,
    YouTubeUploadClient,
)


class PublishingError(Exception):
    """Publishing failure with a user-facing Turkish message."""


class PublishingService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._oauth = OAuthService(sessionmaker, settings)

    async def publish_clip(
        self, clip_candidate_id: int, *, http: httpx.AsyncClient | None = None
    ) -> dict:
        async with self._sessionmaker() as session:
            context = await self._load_context(session, clip_candidate_id)
        if context is None:
            raise PublishingError("Klip adayi bulunamadi.")

        # --- guvenlik guvenleri ---
        if not context["source_authorized"]:
            raise PublishingError(
                "Kaynak kanalin hak kaydi yetkili degil; yayin reddedildi."
            )
        if context["already_published"]:
            # Kabul kriteri: yinelenen yukleme engellenir (idempotent).
            return {
                "clip_candidate_id": clip_candidate_id,
                "skipped": True,
                "youtube_video_id": context["published_row"].youtube_video_id,
            }
        if context["render"] is None or context["render"].status != "rendered":
            raise PublishingError(
                "Klip henuz render edilmedi; once dikey video uretilmeli."
            )
        metadata = context["metadata"]
        if metadata is None:
            raise PublishingError("Onaylanmis metaveri yok; once M9 adimi.")
        if metadata.status != "approved" and not context["auto_approve"]:
            raise PublishingError(
                "Metaveri onay bekliyor; once onaylayin veya kanalda "
                "otomatik onayi acin."
            )

        row = await self._ensure_row(context)
        owned = http is None
        client = http if http is not None else _default_client()
        try:
            token = await self._oauth.access_token(
                context["channel_id"], http=client
            )
            uploader = YouTubeUploadClient(token)
            session_uri = row.upload_session_uri or await uploader.start_session(
                client,
                title=metadata.title,
                description=metadata.description,
                tags=list(metadata.tags),
            )
            await self._save_session_uri(row.id, session_uri)
            video_id = await uploader.upload_file(
                client, session_uri, context["render"].file_path
            )
            await self._mark(row.id, "uploaded", youtube_video_id=video_id)
            status = await uploader.fetch_status(client, video_id)
            if status.privacy_status != "private":
                raise UploadError(
                    f"Gorunurluk dogrulanamadi: {status.privacy_status!r}"
                )
            await self._mark(
                row.id,
                "verified",
                youtube_video_id=video_id,
                published=True,
            )
        except Exception as exc:  # noqa: BLE001 - hata kayda gecer
            message = f"{type(exc).__name__}: {exc}"
            await self._fail(row.id, message)
            raise PublishingError(message) from exc
        finally:
            if owned:
                await client.aclose()

        await self._audit(
            context["channel_id"],
            "publish.done",
            {
                "clip_candidate_id": clip_candidate_id,
                "youtube_video_id": video_id,
                "visibility": "private",
            },
        )
        return {
            "clip_candidate_id": clip_candidate_id,
            "youtube_video_id": video_id,
            "visibility": "private",
        }

    async def approve_metadata(self, clip_candidate_id: int) -> ClipMetadata:
        """Approval control: mark the latest metadata revision approved."""
        async with self._sessionmaker() as session:
            latest = (
                (
                    await session.execute(
                        sa.select(ClipMetadata)
                        .where(ClipMetadata.clip_candidate_id == clip_candidate_id)
                        .order_by(ClipMetadata.revision.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .one_or_none()
            )
            if latest is None:
                raise PublishingError("Metaveri revizyonu bulunamadi.")
            latest.status = "approved"
            await session.commit()
            await session.refresh(latest)
            return latest

    async def due_channels(self) -> list[int]:
        """Connected channels whose schedule slot has arrived."""
        now = datetime.now(UTC)
        channel_ids: list[int] = []
        async with self._sessionmaker() as session:
            profiles = (
                (
                    await session.execute(
                        sa.select(PublishingProfile).join(
                            Channel, PublishingProfile.channel_id == Channel.id
                        ).where(Channel.status == "connected")
                    )
                )
                .scalars()
                .all()
            )
        for profile in profiles:
            async with self._sessionmaker() as session:
                last = (
                    await session.execute(
                        sa.select(PublishedVideo.published_at)
                        .where(PublishedVideo.channel_id == profile.channel_id)
                        .order_by(PublishedVideo.published_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            try:
                if is_due(
                    now_utc=now,
                    timezone_name=profile.timezone,
                    publish_times=profile.settings.get("publish_times"),
                    last_published_at=last,
                ):
                    channel_ids.append(profile.channel_id)
            except ScheduleError:
                continue  # bozuk saat yapilandirmasi: kanali atla
        return channel_ids

    async def next_ready_candidate(self, channel_id: int) -> int | None:
        """Best unpublished candidate for a channel (render ok)."""
        async with self._sessionmaker() as session:
            row = (
                (
                    await session.execute(
                        sa.select(ClipCandidate.id)
                        .join(
                            SourceVideo,
                            ClipCandidate.source_video_id == SourceVideo.id,
                        )
                        .join(
                            SourceChannel,
                            SourceVideo.source_channel_id == SourceChannel.id,
                        )
                        .join(
                            RenderedClip,
                            RenderedClip.clip_candidate_id == ClipCandidate.id,
                        )
                        .outerjoin(PublishedVideo, PublishedVideo.clip_candidate_id == ClipCandidate.id)
                        .where(
                            SourceChannel.channel_id == channel_id,
                            SourceChannel.permission_status == "authorized",
                            RenderedClip.status == "rendered",
                            PublishedVideo.id.is_(None),
                        )
                        .order_by(ClipCandidate.score.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .one_or_none()
            )
        return row

    # --- yardimcilar ---

    async def _load_context(
        self, session: AsyncSession, clip_candidate_id: int
    ) -> dict | None:
        candidate = await session.get(ClipCandidate, clip_candidate_id)
        if candidate is None:
            return None
        video = await session.get(SourceVideo, candidate.source_video_id)
        source = await session.get(SourceChannel, video.source_channel_id)
        render = (
            (
                await session.execute(
                    sa.select(RenderedClip).where(
                        RenderedClip.clip_candidate_id == clip_candidate_id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        metadata = (
            (
                await session.execute(
                    sa.select(ClipMetadata)
                    .where(ClipMetadata.clip_candidate_id == clip_candidate_id)
                    .order_by(ClipMetadata.revision.desc())
                    .limit(1)
                )
            )
            .scalars()
            .one_or_none()
        )
        published_row = (
            (
                await session.execute(
                    sa.select(PublishedVideo).where(
                        PublishedVideo.clip_candidate_id == clip_candidate_id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        profile = (
            (
                await session.execute(
                    sa.select(PublishingProfile).where(
                        PublishingProfile.channel_id == source.channel_id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        return {
            "candidate": candidate,
            "channel_id": source.channel_id,
            "source_authorized": source.permission_status == "authorized",
            "render": render,
            "metadata": metadata,
            "published_row": published_row,
            "already_published": published_row is not None
            and published_row.status in ("uploaded", "verified"),
            "auto_approve": bool(
                profile and profile.settings.get("auto_approve_metadata")
            ),
        }

    async def _ensure_row(self, context: dict) -> PublishedVideo:
        row = context["published_row"]
        if row is None:
            async with self._sessionmaker() as session:
                row = PublishedVideo(
                    clip_candidate_id=context["candidate"].id,
                    channel_id=context["channel_id"],
                    title=context["metadata"].title,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
        return row

    async def _save_session_uri(self, row_id: int, session_uri: str) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(PublishedVideo, row_id)
            row.upload_session_uri = session_uri
            await session.commit()

    async def _mark(
        self,
        row_id: int,
        status: str,
        *,
        youtube_video_id: str | None = None,
        published: bool = False,
    ) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(PublishedVideo, row_id)
            row.status = status
            if youtube_video_id:
                row.youtube_video_id = youtube_video_id
            if published:
                row.published_at = datetime.now(UTC)
            await session.commit()

    async def _fail(self, row_id: int, message: str) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(PublishedVideo, row_id)
            if row is None:
                return
            row.status = "failed"
            row.last_error = message[:2000]
            await session.commit()

    async def _audit(
        self, channel_id: int, event_type: str, detail: dict
    ) -> None:
        async with self._sessionmaker() as session:
            record_event(session, channel_id, event_type, detail)
            await session.commit()


DEFAULT_HTTP_TIMEOUT = 900.0


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT)
