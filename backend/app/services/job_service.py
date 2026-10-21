"""Durable job queue on PostgreSQL (ADR-006).

Job rows live in the database, so they survive restarts. claim_next()
uses SELECT ... FOR UPDATE SKIP LOCKED so multiple workers never take
the same row (SQLite tests run the same statement without the lock
hint — the dialect ignores it — which is fine for single-worker
tests). A worker heartbeat plus attempts drive stale-job recovery:
running rows whose heartbeat is older than the configured threshold
are re-queued (or failed once attempts are exhausted).

Duplicate execution is prevented where possible: enqueue() refuses to
add a new row when an equivalent queued/running/cancelling job already
exists.
"""
from __future__ import annotations

import logging
import shutil
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Job

logger = logging.getLogger(__name__)

# Disk kapisi yalniz GB'larca medya yazan isleri bekletir (kullanici
# istegi 2026-10-21: dolu diskte sistem durmaz, BEKLEMEYE alinir).
# Yayinlama/kesif/temizlik akmaya devam eder: stok yayinlanip
# retention temizligiyle silindikce yer acilir ve isleme kendiliginden
# surer. Kucuk ciktili dikey klip render'i bilincli olarak serbest:
# eldeki indirilmis videolar stoga donusur, yer acilmasi hizlanir.
DISK_BLOCKED_JOB_TYPES = ("media_process", "clip_render_full_cut")

TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
ACTIVE_STATUSES = ("queued", "running", "cancelling")


class JobServiceError(Exception):
    """Queue operation failure with a user-facing Turkish message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class JobService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._last_disk_warning = 0.0

    # --- enqueue ---

    async def enqueue(
        self,
        job_type: str,
        payload: dict | None = None,
        *,
        priority: int = 5,
        max_attempts: int | None = None,
        dedupe: bool = True,
    ) -> Job:
        """Add a job; with dedupe, skip when an equivalent active job exists."""
        if max_attempts is None:
            max_attempts = self._settings.retry_max_attempts
        async with self._sessionmaker() as session:
            if dedupe:
                existing = (
                    await session.execute(
                        select(Job.id)
                        .where(Job.job_type == job_type)
                        .where(Job.status.in_(ACTIVE_STATUSES))
                        .where(Job.payload == (payload or {}))
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    row = await session.get(Job, existing)
                    return row  # type: ignore[return-value]
            job = Job(
                job_type=job_type,
                payload=payload or {},
                priority=priority,
                max_attempts=max_attempts,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    # --- claim / heartbeat / finish ---

    def disk_ok(self, path: str | None = None) -> bool:
        """Low disk space must prevent unsafe new jobs.

        Checks the media tree's disk when configured (that is where
        downloads land), the working directory otherwise.
        """
        target = path or self._settings.media_root or "."
        try:
            free = shutil.disk_usage(target).free
        except OSError:
            return False
        return free >= self._settings.min_free_disk_gb * 1024**3

    def _warn_disk_gate(self) -> None:
        now = time.monotonic()
        if now - self._last_disk_warning > 60:
            self._last_disk_warning = now
            logger.warning(
                "Disk esigin altinda (min %.1f GB bos alan); agir medya"
                " isleri beklemede, yayinlama ve temizlik suruyor",
                self._settings.min_free_disk_gb,
            )

    async def claim_next(
        self,
        worker_id: str,
        *,
        job_types: tuple[str, ...] | list[str] | None = None,
        exclude_types: tuple[str, ...] | list[str] | None = None,
    ) -> Job | None:
        """Atomically take the highest-priority queued job, if disk allows.

        job_types restricts the claim to the given types (the heavy-job
        limit needs this); run_at gates retry backoff — a job whose
        retry delay has not elapsed is not claimable yet. Dolu disk
        yalniz disk-yazan isleri bekletir; yayin isleri akar (pause,
        stop degil — 2026-10-21).
        """
        exclude = list(exclude_types) if exclude_types else []
        if not self.disk_ok():
            self._warn_disk_gate()
            exclude.extend(
                t for t in DISK_BLOCKED_JOB_TYPES if t not in exclude
            )
        now = _utcnow()
        async with self._sessionmaker() as session:
            # FOR UPDATE SKIP LOCKED: PostgreSQL'te eşzamanlı worker'lar
            # aynı satırı alamaz; sqlite kilit ipucunu yok sayar (tek
            # worker testleri için yeterli).
            query = (
                select(Job.id)
                .where(Job.status == "queued")
                .where(
                    (Job.run_at.is_(None)) | (Job.run_at <= now),
                )
            )
            if job_types is not None:
                query = query.where(Job.job_type.in_(job_types))
            if exclude:
                query = query.where(Job.job_type.not_in(exclude))
            row_id = (
                (
                    await session.execute(
                        query.order_by(Job.priority, Job.id)
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalar_one_or_none()
            )
            if row_id is None:
                return None
            await session.execute(
                update(Job)
                .where(Job.id == row_id)
                .values(
                    status="running",
                    worker_id=worker_id,
                    started_at=now,
                    heartbeat_at=now,
                    attempts=Job.attempts + 1,
                )
            )
            await session.commit()
            return await session.get(Job, row_id)

    async def heartbeat(self, job_id: int) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(heartbeat_at=_utcnow())
            )
            await session.commit()

    async def succeed(self, job_id: int) -> None:
        async with self._sessionmaker() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise JobServiceError("İş bulunamadı.", status_code=404)
            # İptal işaretlenmişse başarı bile olsa tutarlı son durum iptaldir.
            job.status = (
                "cancelled" if job.status == "cancelling" else "succeeded"
            )
            job.finished_at = _utcnow()
            await session.commit()

    async def fail(self, job_id: int, error: str) -> None:
        """Record a failure: retry while attempts remain, else fail for good."""
        async with self._sessionmaker() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise JobServiceError("İş bulunamadı.", status_code=404)
            if job.status == "cancelling":
                job.status = "cancelled"
                job.finished_at = _utcnow()
                await session.commit()
                return
            job.last_error = error[:2000]
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                job.finished_at = _utcnow()
            else:
                job.status = "queued"
                job.worker_id = None
                job.started_at = None
                job.heartbeat_at = None
                # Yeniden deneme bekleme araligi: run_at gelmeden alinmaz.
                backoff = max(0, self._settings.retry_backoff_seconds)
                if backoff:
                    job.run_at = _utcnow() + timedelta(seconds=backoff)
            await session.commit()

    async def cancel(self, job_id: int) -> Job:
        """Queued jobs cancel immediately; running jobs are marked and the
        worker settles them. Terminal jobs cannot be cancelled."""
        async with self._sessionmaker() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise JobServiceError("İş bulunamadı.", status_code=404)
            if job.status in TERMINAL_STATUSES:
                raise JobServiceError(
                    "Bu iş zaten sonuçlanmış; iptal edilemez.", status_code=409
                )
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = _utcnow()
            else:  # running / cancelling
                job.status = "cancelling"
            await session.commit()
            await session.refresh(job)
            return job

    # --- recovery ---

    async def recover_stale(self) -> int:
        """Requeue (or fail) running rows whose heartbeat went silent.

        Called at worker start and periodically: this is what makes jobs
        survive application crashes and restarts without double-running
        beyond the attempt budget.
        """
        threshold = _utcnow() - timedelta(
            seconds=self._settings.job_stale_after_seconds
        )
        recovered = 0
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(Job).where(
                            Job.status.in_(("running", "cancelling"))
                        )
                    )
                )
                .scalars()
                .all()
            )
            for job in rows:
                beat = _as_utc(job.heartbeat_at) or _as_utc(job.started_at)
                if beat is not None and beat >= threshold:
                    continue
                if job.status == "cancelling":
                    # Isaretlenmis ama sonucu yazacak islem cikmadi:
                    # iptal olarak netlestir (olu 'cancelling' kuyruk
                    # beslemesini 'running' kadar tikar).
                    job.status = "cancelled"
                    job.finished_at = _utcnow()
                elif job.attempts >= job.max_attempts:
                    job.status = "failed"
                    job.last_error = (
                        (job.last_error or "")
                        + " | worker sessiz kaldı (stale)"
                    ).strip(" |")
                    job.finished_at = _utcnow()
                else:
                    job.status = "queued"
                    job.worker_id = None
                    job.started_at = None
                    job.heartbeat_at = None
                recovered += 1
            if recovered:
                await session.commit()
        return recovered

    # --- listing ---

    async def list_jobs(
        self, status: str | None = None, limit: int = 50
    ) -> list[Job]:
        limit = max(1, min(limit, 200))
        query = select(Job).order_by(Job.id.desc()).limit(limit)
        if status:
            query = query.where(Job.status == status)
        async with self._sessionmaker() as session:
            return list((await session.execute(query)).scalars().all())

    async def counts(self) -> dict[str, int]:
        """Active/queued/running/failed tallies for the overview panel."""
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(select(Job.status, Job.id))
            ).all()
        counts = {"queued": 0, "running": 0, "failed": 0, "active": 0}
        for status, _ in rows:
            if status in counts:
                counts[status] += 1
            if status in ACTIVE_STATUSES:
                counts["active"] += 1
        return counts
