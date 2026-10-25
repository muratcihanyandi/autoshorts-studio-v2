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
publish_clip, the horizontal full cut via publish_full_cut (once per
source video, code-guarded). Every source that is not explicitly
vertical-only produces both orientations. Approving metadata (either
orientation) also composes the 1280x720 thumbnail and stores its path
on the rendered row.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import (
    AppMeta,
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
from app.services.source_orientation import produces_full_cut
from app.services.publishing_schedule import (
    ScheduleError,
    is_due,
    next_due_time,
    slots_for_orientation,
)
from app.services.thumbnail import ThumbnailError, compose
from app.services.youtube_upload import (
    UploadError,
    YouTubeUploadClient,
)


class PublishingError(Exception):
    """Publishing failure with a user-facing Turkish message."""


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite naif datetime'leri UTC kabul et; tz farki due hesabini
    kaydirmasin (2026-10-23 canli olayin testleri de bunu dogruluyor)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


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

    async def make_public(
        self, row_id: int, *, http: httpx.AsyncClient | None = None
    ) -> dict:
        """Zamanli yayin adimi: dogrulanmis gizli videoyu herkese acik
        yap. published_at/public_at bu anda set edilir — gunluk limit
        sayimlari ve medya temizligi bu ana baglidir."""
        async with self._sessionmaker() as session:
            row = await session.get(PublishedVideo, row_id)
        if row is None:
            raise PublishingError("Yayin kaydi bulunamadi.")
        if row.visibility == "public":
            return {
                "youtube_video_id": row.youtube_video_id,
                "visibility": "public",
                "skipped": True,
            }
        if row.status != "verified":
            raise PublishingError(
                "Video henuz dogrulanmadi; once gizli yukleme yapilmali."
            )
        if not row.youtube_video_id:
            raise PublishingError("YouTube video kimligi yok.")
        owned = http is None
        client = http if http is not None else _default_client()
        try:
            token = await self._oauth.access_token(row.channel_id, http=client)
            uploader = YouTubeUploadClient(token)
            await uploader.set_privacy_public(client, row.youtube_video_id)
            status = await uploader.fetch_status(client, row.youtube_video_id)
            if status.privacy_status != "public":
                raise UploadError(
                    f"Gorunurluk dogrulanamadi: {status.privacy_status!r}"
                )
        except Exception as exc:  # noqa: BLE001 - hata kayda gecer
            # Satir 'verified' kalir: video yuklenmis ve dogrulanmis bir
            # durumdadir; acilisin basarisiz olmasi (kapsam/kota/gecici
            # API hatasi) klibi mahsur birakmamali — sonraki slot
            # denemesinde yeniden secilir. Isin kendisi hata verir.
            message = f"{type(exc).__name__}: {exc}"
            raise PublishingError(message) from exc
        finally:
            if owned:
                await client.aclose()
        now = datetime.now(UTC)
        async with self._sessionmaker() as session:
            fresh = await session.get(PublishedVideo, row.id)
            fresh.visibility = "public"
            fresh.public_at = now
            fresh.published_at = now
            await session.commit()
        await self._audit(
            row.channel_id,
            "publish.public",
            {
                "youtube_video_id": row.youtube_video_id,
                "orientation": row.orientation,
            },
        )
        return {
            "youtube_video_id": row.youtube_video_id,
            "visibility": "public",
            "orientation": row.orientation,
        }

    async def next_ready_public(
        self, channel_id: int, orientation: str
    ) -> int | None:
        """Kanalin yayina hazir kaydi: dogrulanmis ama hala gizli.
        Dikeyde en yuksek skorlu aday, yatayda en eski tam kesit.

        Gelecege elle planlanmis satirlar HARIC tutulur: kullanici bir
        videoyu takvimden 27 Ekim'e tasidiysa, motor onu 25 Ekim'in
        normal slotunda yayina acmamalidir (2026-10-25 canli hatasi:
        planlama yaziliyor ama video yine eski slotta public oluyordu —
        kullaniciya "tarih degismiyor" gorunuyordu). Saati gelmis
        planlamalar ``next_manual_due`` uzerinden oncelikli akar.
        """
        now = datetime.now(UTC)
        async with self._sessionmaker() as session:
            statement = (
                sa.select(PublishedVideo.id, PublishedVideo.scheduled_at)
                .where(
                    PublishedVideo.channel_id == channel_id,
                    PublishedVideo.orientation == orientation,
                    PublishedVideo.status == "verified",
                    PublishedVideo.visibility == "private",
                )
            )
            if orientation == "vertical":
                statement = statement.join(
                    ClipCandidate,
                    PublishedVideo.clip_candidate_id == ClipCandidate.id,
                ).order_by(ClipCandidate.score.desc())
            else:
                statement = statement.order_by(PublishedVideo.id)
            rows = (await session.execute(statement)).all()
        for row_id, scheduled_at in rows:
            moment = _as_utc(scheduled_at)
            if moment is not None and moment > now:
                # Gelecek icin elle planlanmis: kendi saatini bekler.
                continue
            return row_id
        return None

    async def today_published_counts(self, channel_id: int) -> dict:
        """Bugun herkese acik yapilan videolarin yon bazli sayilari.
        published_at yalniz public aninda yazilir, sayim ona baglidir."""
        start_of_day = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        sa.select(PublishedVideo.orientation).where(
                            PublishedVideo.channel_id == channel_id,
                            PublishedVideo.published_at >= start_of_day,
                        )
                    )
                )
                .scalars()
                .all()
            )
        return {
            "vertical": sum(1 for r in rows if r == "vertical"),
            "horizontal": sum(1 for r in rows if r == "horizontal"),
        }

    async def publish_full_cut(
        self, source_video_id: int, *, http: httpx.AsyncClient | None = None
    ) -> dict:
        """Publish the horizontal full cut of a source video.

        Yatay yayin dikey yonlu OLMAYAN kaynaklara aciktir (auto ve
        horizontal); kaynak basina tek PublishedVideo satiri kod
        guvenligiyle sinirlidir.
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
        if context["is_horizontal"] and not context["full_cut_source"]:
            raise PublishingError(
                "Yatay tam kesit yayını dikey yönlü kaynaklarda açık "
                "değildir."
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
            raise PublishingError(
                "Klip metaverisi henuz uretilmedi; motor bir sonraki "
                "uretim dongusunde hazirlar, klip birakinca kendisi "
                "yuklenir."
            )
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
            # Gizli yukleme tamam: yayin ani (published_at) degil, public
            # yapma ani (make_public) doldurur — zamanli yayin akisi.
            await self._mark(row.id, "verified", youtube_video_id=video_id)
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

    async def due_channels(self) -> list[tuple[int, str]]:
        """(channel_id, orientation) pairs whose slot has arrived.

        Yön bazlı çalışır: shorts kendi prime time dilimlerinde, yatay
        videolar kendi dilimlerinde due olur. Elle planlanmış ve saati
        gelmiş bir yayın kanalı her yönde due sayar. published_at NULL
        satırlar (gizli yüklenmiş, henüz açılmamış) yok sayılır — yoksa
        "hiç yayınlanmamış" sanılır ve motor her turda üst üste yayın
        açardı (2026-10-23 canlı olay: üç shorts gece 03:02-03:22
        arka arkaya yayına çıktı).
        """
        now = datetime.now(UTC)
        dues: list[tuple[int, str]] = []
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
            for orientation in ("vertical", "horizontal"):
                if await self._manual_due(profile.channel_id, orientation):
                    dues.append((profile.channel_id, orientation))
                    continue
                async with self._sessionmaker() as session:
                    last = _as_utc(
                        (
                            await session.execute(
                                sa.select(PublishedVideo.published_at)
                                .where(
                                    PublishedVideo.channel_id
                                    == profile.channel_id,
                                    PublishedVideo.orientation == orientation,
                                    PublishedVideo.published_at.is_not(None),
                                )
                                .order_by(PublishedVideo.published_at.desc())
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                    )
                try:
                    slots = slots_for_orientation(profile.settings, orientation)
                    if is_due(
                        now_utc=now,
                        timezone_name=profile.timezone,
                        publish_times=slots,
                        last_published_at=last,
                    ):
                        dues.append((profile.channel_id, orientation))
                except ScheduleError:
                    continue  # bozuk saat yapilandirmasi: yonu atla
        return dues

    async def _manual_due(
        self, channel_id: int, orientation: str
    ) -> bool:
        """Elle planlanmış ve saati gelmiş gizli yayın var mı?"""
        return (
            await self.next_manual_due(channel_id, orientation) is not None
        )

    async def next_manual_due(
        self, channel_id: int, orientation: str
    ) -> int | None:
        """Elle planlanmış, saati gelmiş (scheduled_at <= now) kayıt.
        SQLite naif datetime'leri Python tarafında UTC'ye normalize
        edilir; SQL karşılaştırması ortamlar arasında taşınamaz."""
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        sa.select(
                            PublishedVideo.id, PublishedVideo.scheduled_at
                        )
                        .where(
                            PublishedVideo.channel_id == channel_id,
                            PublishedVideo.orientation == orientation,
                            PublishedVideo.status == "verified",
                            PublishedVideo.visibility == "private",
                            PublishedVideo.scheduled_at.is_not(None),
                        )
                        .order_by(PublishedVideo.scheduled_at.asc())
                        .limit(5)
                    )
                )
                .all()
            )
        now = datetime.now(UTC)
        for row_id, scheduled in rows:
            moment = _as_utc(scheduled)
            if moment is not None and moment <= now:
                return row_id
        return None

    async def set_manual_schedule(
        self, row_id: int, scheduled_at: datetime | None
    ) -> PublishedVideo:
        """Bir gizli yüklenmiş videonun herkese açılma anını elle ata.
        None temizler: video tekrar slot mantığına döner."""
        async with self._sessionmaker() as session:
            row = await session.get(PublishedVideo, row_id)
            if row is None:
                raise PublishingError("Yayın kaydı bulunamadı.")
            if row.visibility == "public":
                raise PublishingError(
                    "Video zaten yayında; geçmiş yayın saati değiştirilemez."
                )
            if row.status != "verified":
                raise PublishingError(
                    "Video henüz doğrulanmadı; önce gizli yükleme tamamlanmalı."
                )
            row.scheduled_at = scheduled_at
            await session.commit()
            await session.refresh(row)
        await self._audit(
            row.channel_id,
            "publish.rescheduled",
            {
                "published_video_id": row.id,
                "scheduled_at": (
                    scheduled_at.isoformat() if scheduled_at else None
                ),
            },
        )
        return row

    # --- stok klibi planlama: yükleme niyeti ---

    SCHEDULE_INTENTS_KEY = "schedule_intents"

    @staticmethod
    def _intent_key(orientation: str, candidate_id: int | None, video_id: int | None) -> str:
        """_ensure_row ile aynı anahtar üretir: yönlendirilmiş planlama
        niyeti yükleme satırı oluşunca otomatik uygulanır."""
        if candidate_id is not None:
            return f"{orientation}:c{candidate_id}"
        return f"{orientation}:v{video_id}"

    async def _store_intent(
        self, key: str, scheduled_at: datetime | None
    ) -> None:
        """app_meta.schedule_intents sözlüğüne niyet yaz/sil."""
        async with self._sessionmaker() as session:
            row = await session.get(AppMeta, self.SCHEDULE_INTENTS_KEY)
            intents = dict(row.value) if row is not None else {}
            if scheduled_at is None:
                intents.pop(key, None)
            else:
                intents[key] = scheduled_at.isoformat()
            if row is None:
                session.add(
                    AppMeta(key=self.SCHEDULE_INTENTS_KEY, value=intents)
                )
            else:
                row.value = intents
            await session.commit()

    async def _pop_intent(
        self,
        orientation: str,
        candidate_id: int | None,
        video_id: int | None,
    ) -> datetime | None:
        """Niyeti oku ve temizle; yoksa None."""
        key = self._intent_key(orientation, candidate_id, video_id)
        async with self._sessionmaker() as session:
            row = await session.get(AppMeta, self.SCHEDULE_INTENTS_KEY)
            intents = dict(row.value) if row is not None else {}
            raw = intents.pop(key, None)
            if raw is None:
                return None
            if row is None:
                session.add(
                    AppMeta(key=self.SCHEDULE_INTENTS_KEY, value=intents)
                )
            else:
                row.value = intents
            await session.commit()
        try:
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None

    async def schedule_render(
        self, render_id: int, scheduled_at: datetime | None
    ) -> dict:
        """Stoktaki hazır klibi planla: gizli yükleme işini hemen açar
        (manuel işaretli), saati de yükleme satırına niyet olarak yazar.
        Yükleme tamamlanınca scheduled_at otomatik uygulanır."""
        from app.services.job_service import JobService

        async with self._sessionmaker() as session:
            render = await session.get(RenderedClip, render_id)
            if render is None:
                raise PublishingError("Klip bulunamadı.")
            if render.status != "rendered":
                raise PublishingError(
                    "Klip henüz hazır değil; render tamamlandığında "
                    "planlanabilir."
                )
            candidate = (
                await session.get(ClipCandidate, render.clip_candidate_id)
                if render.clip_candidate_id is not None
                else None
            )
            if render.clip_candidate_id is not None and candidate is None:
                raise PublishingError("Klip adayı bulunamadı.")
            source = (
                await session.get(
                    SourceVideo,
                    candidate.source_video_id
                    if candidate is not None
                    else render.source_video_id,
                )
            )
            source_channel = (
                await session.get(
                    SourceChannel, source.source_channel_id
                )
                if source is not None
                else None
            )
        if source_channel is None:
            raise PublishingError("Kaynak kanal bulunamadı.")
        channel_id = source_channel.channel_id
        orientation = render.orientation
        candidate_id = render.clip_candidate_id
        video_id = (
            candidate.source_video_id
            if candidate is not None
            else render.source_video_id
        )
        # Video zaten gizli yuklenmisse saati dogrudan satira yaz; yeni
        # yukleme islemi acmaya gerek yok (niyet uygulanmazdi).
        async with self._sessionmaker() as session:
            if candidate_id is not None:
                existing = await session.execute(
                    sa.select(PublishedVideo).where(
                        PublishedVideo.clip_candidate_id == candidate_id,
                        PublishedVideo.orientation == orientation,
                    )
                )
            else:
                existing = await session.execute(
                    sa.select(PublishedVideo).where(
                        PublishedVideo.source_video_id == video_id,
                        PublishedVideo.orientation == orientation,
                        PublishedVideo.clip_candidate_id.is_(None),
                    )
                )
            existing_row = existing.scalars().one_or_none()
        if existing_row is not None:
            # Satir dogrulanmadiysa set_manual_schedule anlasilir hata
            # verir; sessizce kaybolan planlama olmasin.
            await self.set_manual_schedule(existing_row.id, scheduled_at)
            return {
                "clip_render_id": render_id,
                "published_video_id": existing_row.id,
                "scheduled_at": (
                    scheduled_at.isoformat() if scheduled_at else None
                ),
            }
        await self._store_intent(
            self._intent_key(orientation, candidate_id, video_id),
            scheduled_at,
        )
        # Gizli yükleme işini hemen kuyruğa al (motor sırasını beklemeden).
        jobs = JobService(self._sessionmaker, self._settings)
        if candidate_id is not None:
            job_type, payload = "publish_clip", {"clip_candidate_id": candidate_id}
        else:
            job_type, payload = "publish_full_cut", {"source_video_id": video_id}
        payload = {**payload, "manual": True}
        job = await jobs.enqueue(job_type, payload, priority=6)
        await self._audit(
            channel_id,
            "publish.rescheduled",
            {
                "clip_render_id": render_id,
                "scheduled_at": (
                    scheduled_at.isoformat() if scheduled_at else None
                ),
                "upload_job_id": job.id,
            },
        )
        return {
            "clip_render_id": render_id,
            "scheduled_at": (
                scheduled_at.isoformat() if scheduled_at else None
            ),
            "upload_job_id": job.id,
        }

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
            "source_video_id": candidate.source_video_id,
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
            "full_cut_source": produces_full_cut(source),
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
            "source_video_id": source_video_id,
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
            "full_cut_source": produces_full_cut(source),
            "orientation": "horizontal",
        }

    async def _ensure_row(self, context: dict) -> PublishedVideo:
        row = context["published_row"]
        if row is None:
            async with self._sessionmaker() as session:
                candidate = context["candidate"]
                candidate_id = (
                    candidate.id if candidate is not None else None
                )
                video_id = (
                    candidate.source_video_id
                    if candidate is not None
                    else context.get("source_video_id")
                )
                row = PublishedVideo(
                    clip_candidate_id=candidate_id,
                    source_video_id=video_id,
                    orientation=context["orientation"],
                    channel_id=context["channel_id"],
                    title=context["metadata"].title,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
            # Stok klibi takvimden planlandıysa saati satıra uygula.
            scheduled_at = await self._pop_intent(
                context["orientation"], candidate_id, video_id
            )
            if scheduled_at is not None:
                async with self._sessionmaker() as session:
                    fresh = await session.get(PublishedVideo, row.id)
                    fresh.scheduled_at = scheduled_at
                    await session.commit()
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
