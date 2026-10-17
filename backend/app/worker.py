"""Background job worker (Milestone 6).

Runs as an asyncio task inside the API process (enabled by
WORKER_ENABLED=true in deployment). Heavy work stays off the request
path: the API only reads/writes job rows; this worker claims and
executes them. Concurrency, stale threshold, and the source polling
interval come from effective settings, so site-managed values apply
without a restart.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services.job_service import JobService
from app.services.settings_service import SettingsService

Handler = Callable[[dict[str, Any]], Awaitable[Any]]
JobHandlers = dict[str, Handler]


def build_handlers(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> JobHandlers:
    """The job-type registry. M6 ships source discovery; M7 registers
    the media pipeline. One download lock is shared by every
    media_process job so downloads stay sequential."""

    download_lock = asyncio.Lock()

    async def source_discover(payload: dict[str, Any]) -> dict:
        from app.services.discovery_service import DiscoveryService

        channel_id = payload.get("channel_id")
        if not isinstance(channel_id, int):
            raise ValueError("payload.channel_id gerekli.")
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        discovery = DiscoveryService(sessionmaker, effective)
        return await discovery.discover_for_channel(channel_id)

    async def media_process(payload: dict[str, Any]) -> dict:
        from app.services.media_pipeline import MediaPipelineService

        source_video_id = payload.get("source_video_id")
        if not isinstance(source_video_id, int):
            raise ValueError("payload.source_video_id gerekli.")
        import_path = payload.get("import_path")
        if import_path is not None and not isinstance(import_path, str):
            raise ValueError("payload.import_path string olmali.")
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        pipeline = MediaPipelineService(
            sessionmaker, effective, download_lock=download_lock
        )
        return await pipeline.run(source_video_id, import_path=import_path)

    async def clip_render(payload: dict[str, Any]) -> dict:
        from app.services.vertical_pipeline import VerticalPipelineService

        clip_candidate_id = payload.get("clip_candidate_id")
        if not isinstance(clip_candidate_id, int):
            raise ValueError("payload.clip_candidate_id gerekli.")
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        pipeline = VerticalPipelineService(sessionmaker, effective)
        return await pipeline.run(clip_candidate_id)

    async def subtitle_correct(payload: dict[str, Any]) -> dict:
        from app.services.llm_service import LlmProviderService
        from app.services.subtitle_correction import SubtitleCorrectionService

        media_asset_id = payload.get("media_asset_id")
        if not isinstance(media_asset_id, int):
            raise ValueError("payload.media_asset_id gerekli.")
        llm = LlmProviderService(sessionmaker, settings)
        service = SubtitleCorrectionService(sessionmaker, llm)
        return await service.correct_transcript(media_asset_id)

    async def metadata_generate(payload: dict[str, Any]) -> dict:
        from app.services.llm_service import LlmProviderService
        from app.services.metadata_service import MetadataService

        clip_candidate_id = payload.get("clip_candidate_id")
        if not isinstance(clip_candidate_id, int):
            raise ValueError("payload.clip_candidate_id gerekli.")
        llm = LlmProviderService(sessionmaker, settings)
        service = MetadataService(sessionmaker, llm)
        return await service.generate(clip_candidate_id)

    async def publish_clip(payload: dict[str, Any]) -> dict:
        from app.services.publishing_service import PublishingService

        clip_candidate_id = payload.get("clip_candidate_id")
        if not isinstance(clip_candidate_id, int):
            raise ValueError("payload.clip_candidate_id gerekli.")
        service = PublishingService(sessionmaker, settings)
        return await service.publish_clip(clip_candidate_id)

    async def publish_due(payload: dict[str, Any]) -> dict:
        from app.services.publishing_service import PublishingService

        channel_id = payload.get("channel_id")
        if not isinstance(channel_id, int):
            raise ValueError("payload.channel_id gerekli.")
        service = PublishingService(sessionmaker, settings)
        candidate_id = await service.next_ready_candidate(channel_id)
        if candidate_id is None:
            return {"channel_id": channel_id, "published": 0}
        result = await service.publish_clip(candidate_id)
        return {"channel_id": channel_id, "published": 1, **result}

    return {
        "source_discover": source_discover,
        "media_process": media_process,
        "clip_render": clip_render,
        "subtitle_correct": subtitle_correct,
        "metadata_generate": metadata_generate,
        "publish_clip": publish_clip,
        "publish_due": publish_due,
    }


class JobWorker:
    """Claims queued jobs, executes handlers, heartbeats, settles results."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        handlers: JobHandlers | None = None,
        poll_seconds: float = 5.0,
        heartbeat_seconds: float = 30.0,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._jobs = JobService(sessionmaker, settings)
        self._handlers = handlers or build_handlers(sessionmaker, settings)
        self._poll_seconds = poll_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._running: dict[int, asyncio.Task] = {}
        self._worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self._last_poll_enqueue = 0.0
        self._last_planned_enqueue = 0.0
        self._last_render_enqueue = 0.0
        self._last_content_enqueue = 0.0
        self._last_publish_enqueue = 0.0
        self._last_tmp_cleanup = 0.0

    # --- testable pieces ---

    async def run_job(self, job_id: int) -> None:
        """Execute one claimed job with heartbeat + settle logic."""
        beat = asyncio.create_task(self._heartbeat_loop(job_id))
        try:
            job = await self._get(job_id)
            if job is None:
                return
            if job.status == "cancelling":
                await self._jobs.succeed(job_id)  # cancelling -> cancelled
                return
            handler = self._handlers.get(job.job_type)
            if handler is None:
                await self._jobs.fail(job_id, f"Bilinmeyen iş türü: {job.job_type}")
                return
            await handler(job.payload or {})
            await self._jobs.succeed(job_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - iş hatası kayda geçer
            await self._jobs.fail(job_id, f"{type(exc).__name__}: {exc}")
        finally:
            beat.cancel()

    async def _heartbeat_loop(self, job_id: int) -> None:
        try:
            while True:
                await self._jobs.heartbeat(job_id)
                await asyncio.sleep(self._heartbeat_seconds)
        except asyncio.CancelledError:
            pass

    async def claim_batch(self) -> int:
        """Claim jobs up to the concurrency limit; returns how many started."""
        started = 0
        while len(self._running) < self._settings.max_concurrent_jobs:
            job = await self._jobs.claim_next(self._worker_id)
            if job is None:
                break
            task = asyncio.create_task(self.run_job(job.id))
            self._running[job.id] = task
            task.add_done_callback(lambda t, jid=job.id: self._running.pop(jid, None))
            started += 1
        return started

    async def enqueue_poll_jobs(self) -> int:
        """Periodic source polling: one discover job per channel that has
        authorized sources. Dedupe keeps repeated ticks from piling up."""
        interval = self._settings.source_poll_interval_minutes * 60
        now = time.monotonic()
        if self._last_poll_enqueue and now - self._last_poll_enqueue < interval:
            return 0
        self._last_poll_enqueue = now
        added = 0
        async with self._sessionmaker() as session:
            channel_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT DISTINCT channel_id FROM source_channels "
                            "WHERE permission_status = 'authorized'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        for channel_id in channel_ids:
            job = await self._jobs.enqueue(
                "source_discover", {"channel_id": channel_id}, priority=9
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_planned_jobs(self) -> int:
        """Periodic planned-video enqueue: one media_process job per
        'planned' source video. Dedupe keeps repeated ticks from piling
        up, so the M7 pipeline stays fed without manual job creation."""
        interval = self._settings.planned_poll_interval_minutes * 60
        now = time.monotonic()
        if (
            self._last_planned_enqueue
            and now - self._last_planned_enqueue < interval
        ):
            return 0
        self._last_planned_enqueue = now
        added = 0
        async with self._sessionmaker() as session:
            video_ids = (
                (
                    await session.execute(
                        text("SELECT id FROM source_videos WHERE status = 'planned'")
                    )
                )
                .scalars()
                .all()
            )
        for video_id in video_ids:
            job = await self._jobs.enqueue(
                "media_process", {"source_video_id": video_id}, priority=8
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_render_jobs(self) -> int:
        """Periodic render feed: one clip_render job per candidate that
        is not rendered yet (rendered/review/failed rows are excluded
        by the NOT EXISTS subquery; dedupe guards repeated ticks)."""
        interval = self._settings.planned_poll_interval_minutes * 60
        now = time.monotonic()
        if (
            self._last_render_enqueue
            and now - self._last_render_enqueue < interval
        ):
            return 0
        self._last_render_enqueue = now
        added = 0
        async with self._sessionmaker() as session:
            candidate_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT cc.id FROM clip_candidates cc"
                            " WHERE cc.status = 'candidate'"
                            " AND NOT EXISTS ("
                            " SELECT 1 FROM rendered_clips rc"
                            " WHERE rc.clip_candidate_id = cc.id)"
                            " ORDER BY cc.source_video_id, cc.start_seconds"
                        )
                    )
                )
                .scalars()
                .all()
            )
        for candidate_id in candidate_ids:
            job = await self._jobs.enqueue(
                "clip_render", {"clip_candidate_id": candidate_id}, priority=8
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_content_jobs(self) -> int:
        """Feed the M9 content stages: subtitle correction for assets
        with an uncorrected transcript, metadata for rendered clips
        without metadata. Interval-gated like the other feeds; job
        dedupe guards repeated ticks."""
        interval = self._settings.planned_poll_interval_minutes * 60
        now = time.monotonic()
        if (
            self._last_content_enqueue
            and now - self._last_content_enqueue < interval
        ):
            return 0
        self._last_content_enqueue = now
        added = 0
        async with self._sessionmaker() as session:
            asset_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT t.media_asset_id FROM transcripts t"
                            " WHERE NOT EXISTS ("
                            " SELECT 1 FROM corrected_transcripts ct"
                            " WHERE ct.media_asset_id = t.media_asset_id)"
                        )
                    )
                )
                .scalars()
                .all()
            )
            candidate_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT rc.clip_candidate_id FROM rendered_clips rc"
                            " WHERE rc.status = 'rendered'"
                            " AND NOT EXISTS ("
                            " SELECT 1 FROM clip_metadata cm"
                            " WHERE cm.clip_candidate_id = rc.clip_candidate_id)"
                        )
                    )
                )
                .scalars()
                .all()
            )
        for asset_id in asset_ids:
            job = await self._jobs.enqueue(
                "subtitle_correct", {"media_asset_id": asset_id}, priority=7
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        for candidate_id in candidate_ids:
            job = await self._jobs.enqueue(
                "metadata_generate", {"clip_candidate_id": candidate_id}, priority=7
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_publish_jobs(self) -> int:
        """Schedule-aware publishing: one publish_due job per connected
        channel whose slot arrived. The job itself picks the best ready
        candidate; nothing publishes without the rights/approval
        guards."""
        interval = self._settings.publish_check_interval_minutes * 60
        now = time.monotonic()
        if (
            self._last_publish_enqueue
            and now - self._last_publish_enqueue < interval
        ):
            return 0
        self._last_publish_enqueue = now
        from app.services.publishing_service import PublishingService

        service = PublishingService(self._sessionmaker, self._settings)
        channel_ids = await service.due_channels()
        added = 0
        for channel_id in channel_ids:
            job = await self._jobs.enqueue(
                "publish_due", {"channel_id": channel_id}, priority=6
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def cleanup_tmp_once(self, max_age_hours: float = 24.0) -> list[str]:
        """Prune stale files from the media tmp folder (safe cleanup)."""
        if not self._settings.media_root:
            return []
        from app.services.media_storage import media_subdir
        from app.services.temp_cleanup import cleanup_temp_dir

        try:
            return cleanup_temp_dir(
                media_subdir(self._settings.media_root, "tmp"),
                max_age_hours=max_age_hours,
            )
        except Exception:  # noqa: BLE001 - temizlik best-effort
            return []

    async def _maybe_cleanup_tmp(self) -> None:
        """Run the tmp cleanup at most once per hour."""
        now = time.monotonic()
        if self._last_tmp_cleanup and now - self._last_tmp_cleanup < 3600:
            return
        self._last_tmp_cleanup = now
        await self.cleanup_tmp_once()

    async def _get(self, job_id: int):
        from app.models import Job

        async with self._sessionmaker() as session:
            return await session.get(Job, job_id)

    # --- main loop ---

    async def run_forever(self) -> None:
        # Yeniden başlatma kurtarması: sessiz kalmış running işleri geri al.
        await self._jobs.recover_stale()
        while True:
            try:
                await self.enqueue_poll_jobs()
                await self.enqueue_planned_jobs()
                await self.enqueue_render_jobs()
                await self.enqueue_content_jobs()
                await self.enqueue_publish_jobs()
                await self._maybe_cleanup_tmp()
                await self.claim_batch()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - döngü asla durmasın
                import logging

                logging.getLogger(__name__).exception("worker döngüsü adımı hata")
            await asyncio.sleep(self._poll_seconds)


def utc_now() -> datetime:
    return datetime.now(UTC)
