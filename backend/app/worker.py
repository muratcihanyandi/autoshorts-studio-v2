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
    """The job-type registry. M6 ships source discovery; later milestones
    register processing jobs here."""

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

    return {"source_discover": source_discover}


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
                await self.claim_batch()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - döngü asla durmasın
                import logging

                logging.getLogger(__name__).exception("worker döngüsü adımı hata")
            await asyncio.sleep(self._poll_seconds)


def utc_now() -> datetime:
    return datetime.now(UTC)
