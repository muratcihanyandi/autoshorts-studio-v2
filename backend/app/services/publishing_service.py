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

M13: publishing is per orientation — vertical candidates publish via
publish_clip, the horizontal full cut of a reaction source via
publish_full_cut (once per source video, code-guarded). Approving
metadata (either orientation) also composes the 1280x720 thumbnail
and stores its path on the rendered row.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
from app.services.thumbnail import ThumbnailError, compose
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
        return await self._publish(
            context, clip_candidate_id=clip_candidate_id, http=http
        )

    async def publish_full_cut(
        self, source_video_id: int, *, http: httpx.AsyncClient | None = None
    ) -> dict:
        """Publish the horizontal full cut of a reaction source video.

        Yatay yayin yalnizca reaksiyon kaynaklarina aciktir; kaynak
        basina tek PublishedVideo satiri kod guvenligiyle sinirlidir.
        """
        async with self._sessionmaker() as session:
            context = await self._load_full_cut_context(
                session, source_video_id
            )
        if context is None:
            raise PublishingError("Kaynak video bulunamadi.")
        return await self._publish(
            context, source_video_id=source_video_id, http=http
        )

    async def _publish(
        self,
        context: dict,
        *,
        clip_candidate_id: int | None = None,
        source_video_id: int | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> dict:
        # --- guvenlik guvenleri ---
        if not context["source_authorized"]:
            raise PublishingError(
                "Kaynak kanalin hak kaydi yetkili degil; yayin reddedildi."
            )
        if context["is_horizontal"] and not context["reaction_source"]:
            raise PublishingError(
                "Yatay tam kesit yayini yalnizca reaksiyon kaynaklarinda "
                "aciktir."
            )
        if context["already_published"]:
            # Kabul kriteri: yinelenen yukleme engellenir (idempotent).
            skipped = {"skipped": True, "youtube_video_id": context[
                "published_row"
            ].youtube_video_id, "visibility": "private"}
            if clip_candidate_id is not None:
                skipped["clip_candidate_id"] = clip_candidate_id
            else:
                skipped["source_video_id"] = source_video_id
            return skipped
        if context["render"] is None or context["render"].status != "rendered":
            raise PublishingError(
                "Klip henuz render edilmedi; once video uretilmeli."
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

        detail = {
            "youtube_video_id": video_id,
            "visibility": "private",
            "orientation": context["orientation"],
        }
        if clip_candidate_id is not None:
            detail["clip_candidate_id"] = clip_candidate_id
        else:
            detail["source_video_id"] = source_video_id
        await self._audit(context["channel_id"], "publish.done", detail)
        result = {
            "youtube_video_id": video_id,
            "visibility": "private",
        }
        if clip_candidate_id is not None:
            result["clip_candidate_id"] = clip_candidate_id
        else:
            result["source_video_id"] = source_video_id
        return result

    async def approve_metadata(self, clip_candidate_id: int) -> ClipMetadata:
        """Approval control: mark the latest metadata revision approved.

        M13: onay, dikey render satirina thumbnail da yazar.
        """
        return await self._approve(clip_candidate_id=clip_candidate_id)

    async def approve_full_cut(self, source_video_id: int) -> ClipMetadata:
        """Approval control for the horizontal full cut of a video."""
        return await self._approve(source_video_id=source_video_id)

    async def _approve(
        self,
        *,
        clip_candidate_id: int | None = None,
        source_video_id: int | None = None,
    ) -> ClipMetadata:
        async with self._sessionmaker() as session:
            if clip_candidate_id is not None:
                revision_filter = (
                    ClipMetadata.clip_candidate_id == clip_candidate_id
                )
            else:
                revision_filter = (
                    (ClipMetadata.source_video_id == source_video_id)
                    & ClipMetadata.clip_candidate_id.is_(None)
                )
            latest = (
                (
                    await session.execute(
                        sa.select(ClipMetadata)
                        .where(revision_filter)
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
            if clip_candidate_id is not None:
                render_filter = (
                    RenderedClip.clip_candidate_id == clip_candidate_id
                ) & (RenderedClip.orientation == "vertical")
            else:
                render_filter = (
                    (RenderedClip.source_video_id == source_video_id)
                    & (RenderedClip.orientation == "horizontal")
                    & RenderedClip.clip_candidate_id.is_(None)
                )
            render = (
                (
                    await session.execute(
                        sa.select(RenderedClip).where(render_filter)
                    )
                )
                .scalars()
                .one_or_none()
            )
            await session.commit()
            await session.refresh(latest)

        await self._compose_thumbnail(render, latest)
        return latest

    async def _compose_thumbnail(
        self, render: RenderedClip | None, metadata: ClipMetadata
    ) -> None:
        """Onaylanan metaveriyle thumbnail uret; yolu render satirina
        yaz. Render/henüz dosya yoksa sessizce atlanir (onay asil is)."""
        if render is None or render.status != "rendered":
            return
        if not render.file_path or not Path(render.file_path).is_file():
            return
        if not self._settings.media_root:
            return
        text = (metadata.thumbnail_text or "").strip() or (
            metadata.title or ""
        ).strip()
        rel_path = f"thumbnails/thumb_{render.id}.jpg"
        out_path = Path(self._settings.media_root) / rel_path
        try:
            await compose(
                self._settings.ffmpeg_bin,
                render.file_path,
                text,
                out_path,
            )
        except ThumbnailError as exc:
            raise PublishingError(f"Thumbnail olusturulamadi: {exc}") from exc
        async with self._sessionmaker() as session:
            row = await session.get(RenderedClip, render.id)
            if row is None:
                return
            row.thumbnail_path = rel_path
            await session.commit()

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
            # Start/Stop donemi: yayinlama yalnizca 'running' kanallarda
            # beslenir (paused/stopped/error kanallar due sayilmaz).
            if profile.automation_state != "running":
                continue
            if (profile.settings or {}).get("paused"):
                continue  # M11: duraklatilmis kanal due sayilmaz
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
                        RenderedClip.clip_candidate_id == clip_candidate_id,
                        RenderedClip.orientation == "vertical",
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
                        PublishedVideo.clip_candidate_id == clip_candidate_id,
                        PublishedVideo.orientation == "vertical",
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
            "is_horizontal": False,
            "reaction_source": bool(source.reaction_source),
            "orientation": "vertical",
        }

    async def _load_full_cut_context(
        self, session: AsyncSession, source_video_id: int
    ) -> dict | None:
        """Yatay tam kesit baglami: video -> kaynak -> render/metadata."""
        video = await session.get(SourceVideo, source_video_id)
        if video is None:
            return None
        source = await session.get(SourceChannel, video.source_channel_id)
        if source is None:
            return None
        render = (
            (
                await session.execute(
                    sa.select(RenderedClip).where(
                        RenderedClip.source_video_id == source_video_id,
                        RenderedClip.orientation == "horizontal",
                        RenderedClip.clip_candidate_id.is_(None),
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
                    .where(
                        ClipMetadata.source_video_id == source_video_id,
                        ClipMetadata.clip_candidate_id.is_(None),
                    )
                    .order_by(ClipMetadata.revision.desc())
                    .limit(1)
                )
            )
            .scalars()
            .one_or_none()
        )
        # TODO(integration): PublishedVideo'da source_video_id FK'si yok
        # (Task 0'da sema donduruldu); tam kesit yinelenen yayini su an
        # baslik eslesmesiyle onleniyor (metaveri zinciri kaynak basina
        # tektir). Kalici cozum sema degisikligi ister.
        published_row = None
        if metadata is not None:
            revision_titles = (
                (
                    await session.execute(
                        sa.select(ClipMetadata.title).where(
                            ClipMetadata.source_video_id == source_video_id,
                            ClipMetadata.clip_candidate_id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if revision_titles:
                published_row = (
                    (
                        await session.execute(
                            sa.select(PublishedVideo).where(
                                PublishedVideo.channel_id
                                == source.channel_id,
                                PublishedVideo.orientation == "horizontal",
                                PublishedVideo.clip_candidate_id.is_(None),
                                PublishedVideo.title.in_(revision_titles),
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
            "candidate": None,
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
            "is_horizontal": True,
            "reaction_source": bool(source.reaction_source),
            "orientation": "horizontal",
        }

    async def _ensure_row(self, context: dict) -> PublishedVideo:
        row = context["published_row"]
        if row is None:
            async with self._sessionmaker() as session:
                row = PublishedVideo(
                    clip_candidate_id=(
                        context["candidate"].id
                        if context["candidate"] is not None
                        else None
                    ),
                    orientation=context["orientation"],
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
