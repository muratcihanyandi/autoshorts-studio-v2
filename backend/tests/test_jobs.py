"""Durable job queue: claim, retry, cancel, stale recovery, worker.

Queue semantics run against schema-backed SQLite (the SKIP LOCKED hint
is PostgreSQL-only and silently dropped by the sqlite dialect — fine
for single-worker tests). Worker execution uses injected handlers so
job lifecycle transitions are verified without real side effects; the
source-discover handler is exercised with the YouTube mock.
"""
from __future__ import annotations

import asyncio

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import Base
from app.services.job_service import JobService
from app.worker import JobWorker
from tests.conftest import _make_app, mock_youtube  # noqa: F401 - fixture


def _sync_one(tmp_path, table: str, row_id: int, column: str):
    db_path = tmp_path / "jobs.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text(f"SELECT {column} FROM {table} WHERE id = {row_id}")
            ).scalar()
    finally:
        engine.dispose()


def _queue_env(tmp_path, **overrides):
    """Kendi motoruyla çalışan kuyruk ortamı: (sessionmaker, settings, db_path)."""
    db_path = tmp_path / "jobs.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", **overrides
    )
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine, str(db_path)


class TestJobService:
    def test_enqueue_and_dedupe(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(tmp_path)
            try:
                service = JobService(sessionmaker, settings)
                first = await service.enqueue(
                    "source_discover", {"channel_id": 1}
                )
                second = await service.enqueue(
                    "source_discover", {"channel_id": 1}
                )
                third = await service.enqueue(
                    "source_discover", {"channel_id": 2}
                )
                return first.id, second.id, third.id
            finally:
                await engine.dispose()

        first, second, third = asyncio.run(scenario())
        assert first == second  # yinelenen enqueue aynı işi döndürür
        assert third != first

    def test_claim_marks_running_and_counts_attempts(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(tmp_path)
            try:
                service = JobService(sessionmaker, settings)
                job = await service.enqueue("job_a", {"x": 1})
                claimed = await service.claim_next("worker-1")
                return job.id, claimed
            finally:
                await engine.dispose()

        job_id, claimed = asyncio.run(scenario())
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.status == "running"
        assert claimed.attempts == 1
        assert claimed.worker_id == "worker-1"

    def test_claim_respects_priority_order(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(tmp_path)
            try:
                service = JobService(sessionmaker, settings)
                low = await service.enqueue("low", priority=9)
                high = await service.enqueue("high", priority=1)
                first = await service.claim_next("w")
                second = await service.claim_next("w")
                return low.id, high.id, first.id, second.id
            finally:
                await engine.dispose()

        low_id, high_id, first_id, second_id = asyncio.run(scenario())
        assert first_id == high_id
        assert second_id == low_id

    def test_low_disk_blocks_claim(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(
                tmp_path, min_free_disk_gb=99999
            )
            try:
                service = JobService(sessionmaker, settings)
                await service.enqueue("job_a")
                claimed = await service.claim_next("w")
                # Disk engellendiğinde iş kuyrukta kalır, kaybolmaz.
                counts = await service.counts()
                return claimed, counts
            finally:
                await engine.dispose()

        claimed, counts = asyncio.run(scenario())
        assert claimed is None
        assert counts["queued"] == 1

    def test_fail_retries_then_fails_for_good(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(tmp_path)
            try:
                service = JobService(sessionmaker, settings)
                job = await service.enqueue("flaky", max_attempts=2)
                for _ in range(2):
                    claimed = await service.claim_next("w")
                    await service.fail(claimed.id, "deneme hatasi")
                return job.id
            finally:
                await engine.dispose()

        job_id = asyncio.run(scenario())
        # attempts=2 = max_attempts -> failed, kuyruğa dönmez
        status = _sync_one(tmp_path, "jobs", job_id, "status")
        attempts = _sync_one(tmp_path, "jobs", job_id, "attempts")
        assert status == "failed"
        assert attempts == 2

    def test_fail_within_budget_requeues(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(tmp_path)
            try:
                service = JobService(sessionmaker, settings)
                job = await service.enqueue("flaky", max_attempts=3)
                claimed = await service.claim_next("w")
                await service.fail(claimed.id, "gecici hata")
                return job.id
            finally:
                await engine.dispose()

        job_id = asyncio.run(scenario())
        assert _sync_one(tmp_path, "jobs", job_id, "status") == "queued"
        assert _sync_one(tmp_path, "jobs", job_id, "attempts") == 1

    def test_cancel_semantics(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(tmp_path)
            try:
                service = JobService(sessionmaker, settings)
                queued = await service.enqueue("q")
                cancelled_queued = await service.cancel(queued.id)

                running = await service.enqueue("r")
                await service.claim_next("w")
                cancelling = await service.cancel(running.id)
                # running iş bitince settled: cancelling -> cancelled
                await service.succeed(running.id)

                done = await service.enqueue("d")
                await service.claim_next("w")
                await service.succeed(done.id)
                try:
                    await service.cancel(done.id)
                    terminal_error = None
                except Exception as exc:  # noqa: BLE001
                    terminal_error = str(exc)
                return (
                    cancelled_queued.status,
                    cancelling.status,
                    _sync_one(tmp_path, "jobs", running.id, "status"),
                    terminal_error,
                )
            finally:
                await engine.dispose()

        (
            queued_status,
            cancelling_status,
            settled_status,
            terminal_error,
        ) = asyncio.run(scenario())
        assert queued_status == "cancelled"
        assert cancelling_status == "cancelling"
        assert settled_status == "cancelled"  # iptal tutarlı son durum
        assert terminal_error is not None  # sonuçlanmış iş iptal edilemez

    def test_recover_stale_requeues_and_fails_exhausted(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(
                tmp_path, job_stale_after_seconds=0, worker_enabled=False
            )
            try:
                service = JobService(sessionmaker, settings)
                fresh = await service.enqueue("fresh", max_attempts=3)
                await service.claim_next("w")
                await service.heartbeat(fresh.id)

                exhausted = await service.enqueue("exhausted", max_attempts=1)
                await service.claim_next("w")

                import asyncio as aio

                await aio.sleep(0.05)  # heartbeat eşik değerinin (0sn) dışına
                recovered = await service.recover_stale()
                return fresh.id, exhausted.id, recovered
            finally:
                await engine.dispose()

        fresh_id, exhausted_id, recovered = asyncio.run(scenario())
        # stale_after=0: her iki running iş de ele alınır; fresh'in heartbeat'i
        # yeni olduğundan tekrar kuyruğa, exhausted attempts bittiğinden failed.
        fresh_status = _sync_one(tmp_path, "jobs", fresh_id, "status")
        exhausted_status = _sync_one(tmp_path, "jobs", exhausted_id, "status")
        assert recovered == 2
        assert fresh_status in ("queued", "running")
        assert exhausted_status == "failed"


class TestJobWorker:
    def test_run_job_success_and_failure_paths(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(tmp_path)
            try:
                calls = []

                async def ok_handler(payload):
                    calls.append(("ok", payload))
                    return {"done": True}

                async def boom_handler(payload):
                    calls.append(("boom", payload))
                    raise RuntimeError("patladi")

                handlers = {
                    "ok_job": ok_handler,
                    "boom_job": boom_handler,
                }
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                service = worker._jobs

                ok = await service.enqueue("ok_job", {"n": 1})
                await service.claim_next(worker._worker_id)
                await worker.run_job(ok.id)

                boom = await service.enqueue("boom_job", max_attempts=1)
                await service.claim_next(worker._worker_id)
                await worker.run_job(boom.id)

                unknown = await service.enqueue(
                    "nope_job", {"u": 1}, max_attempts=1
                )
                await service.claim_next(worker._worker_id)
                await worker.run_job(unknown.id)

                return ok.id, boom.id, unknown.id, calls
            finally:
                await engine.dispose()

        ok_id, boom_id, unknown_id, calls = asyncio.run(scenario())
        assert ("ok", {"n": 1}) in calls
        assert _sync_one(tmp_path, "jobs", ok_id, "status") == "succeeded"
        # Hata: attempts=1 = max -> failed, mesaj kayıtlı.
        assert _sync_one(tmp_path, "jobs", boom_id, "status") == "failed"
        assert "patladi" in _sync_one(tmp_path, "jobs", boom_id, "last_error")
        assert _sync_one(tmp_path, "jobs", unknown_id, "status") == "failed"

    def test_claim_batch_respects_concurrency(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(
                tmp_path, max_concurrent_jobs=2
            )
            try:
                started = asyncio.Event()
                release = asyncio.Event()

                async def slow_handler(payload):
                    started.set()
                    await release.wait()

                worker = JobWorker(
                    sessionmaker, settings, handlers={"slow": slow_handler}
                )
                service = worker._jobs
                # Ayri payload'lar: dedupe ayni tip+payload'i tek satirda tutar.
                for i in range(4):
                    await service.enqueue("slow", {"n": i})

                first = await worker.claim_batch()
                second = await worker.claim_batch()  # dolu slotlar
                release.set()
                await asyncio.gather(*worker._running.values())
                return first, second
            finally:
                await engine.dispose()

        first, second = asyncio.run(scenario())
        assert first == 2  # eşzamanlılık sınırı kadar iş başlar
        assert second == 0  # slotlar doluyken yeni iş alınmaz

    def test_enqueue_poll_jobs_per_authorized_channel(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(tmp_path)
            try:
                # Bir kanal + iki kaynak (biri authorized, biri pending).
                from sqlalchemy.ext.asyncio import AsyncSession

                from app.models import Channel, SourceChannel

                async with sessionmaker() as session:  # type: AsyncSession
                    session.add(Channel(id=1, name="Kanal 1"))
                    session.add(Channel(id=2, name="Kanal 2"))
                    session.add(
                        SourceChannel(
                            channel_id=1,
                            youtube_channel_id="UCauth",
                            title="Yetkili",
                            permission_status="authorized",
                        )
                    )
                    session.add(
                        SourceChannel(
                            channel_id=2,
                            youtube_channel_id="UCpend",
                            title="Bekleyen",
                            permission_status="pending",
                        )
                    )
                    await session.commit()

                worker = JobWorker(sessionmaker, settings)
                added = await worker.enqueue_poll_jobs()
                # Tekrar: dedupe ile yığın büyümez.
                added_again = await worker.enqueue_poll_jobs()
                service = worker._jobs
                jobs = await service.list_jobs()
                return added, added_again, [(j.job_type, j.payload) for j in jobs]
            finally:
                await engine.dispose()

        added, added_again, jobs = asyncio.run(scenario())
        assert added == 1
        assert added_again == 0
        assert jobs == [("source_discover", {"channel_id": 1})]

    def test_source_discover_handler_runs_discovery(
        self, tmp_path, mock_youtube  # noqa: F811 - fixture
    ):
        async def scenario():
            sessionmaker, settings, engine, db = _queue_env(
                tmp_path, youtube_api_key="test-yt-key"
            )
            try:
                from app.models import Channel, SourceChannel

                async with sessionmaker() as session:
                    session.add(Channel(id=1, name="Kanal"))
                    session.add(
                        SourceChannel(
                            channel_id=1,
                            youtube_channel_id="UCkaynak1",
                            title="Kaynak",
                            permission_status="authorized",
                        )
                    )
                    await session.commit()

                handlers = {}  # build_handlers ile gerçek kayıt
                from app.worker import build_handlers

                handlers = build_handlers(sessionmaker, settings)
                worker = JobWorker(sessionmaker, settings, handlers=handlers)
                service = worker._jobs
                job = await service.enqueue(
                    "source_discover", {"channel_id": 1}
                )
                await service.claim_next(worker._worker_id)
                await worker.run_job(job.id)
                return job.id
            finally:
                await engine.dispose()

        job_id = asyncio.run(scenario())
        assert _sync_one(tmp_path, "jobs", job_id, "status") == "succeeded"
        # Keşif gerçekten koştu: video satırları oluştu.
        engine = sa.create_engine(f"sqlite:///{tmp_path}/jobs.db")
        with engine.connect() as conn:
            videos = conn.execute(
                sa.text("SELECT COUNT(*) FROM source_videos")
            ).scalar()
        engine.dispose()
        assert videos == 2


class TestJobsApi:
    def test_list_cancel_retry_roundtrip(self, tmp_path):
        app = _make_app(tmp_path, worker_enabled=False)
        with TestClient(app) as client:
            created = client.post(
                "/api/jobs",
                json={"job_type": "manual_job", "payload": {"k": 1}},
            )
            assert created.status_code == 201, created.text
            job_id = created.json()["id"]

            listed = client.get("/api/jobs").json()
            assert listed["total"] >= 1

            cancelled = client.post(f"/api/jobs/{job_id}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"

            retried = client.post(f"/api/jobs/{job_id}/retry")
            assert retried.status_code == 200
            assert retried.json()["status"] == "queued"
            assert retried.json()["attempts"] == 0

    def test_worker_disabled_by_default(self, tmp_path):
        with TestClient(_make_app(tmp_path)) as client:
            assert client.app.state.worker_task is None

    def test_worker_enabled_starts_task(self, tmp_path):
        app = _make_app(tmp_path, worker_enabled=True)
        with TestClient(app) as client:
            assert client.app.state.worker_task is not None
            assert not client.app.state.worker_task.done()

    def test_overview_reports_real_job_counts(self, tmp_path):
        app = _make_app(tmp_path, worker_enabled=False)
        with TestClient(app) as client:
            client.post(
                "/api/jobs", json={"job_type": "overview_job", "payload": {}}
            )
            body = client.get("/api/overview").json()
            assert body["jobs"]["queued"] >= 1
            assert body["jobs"]["active"] >= 1
