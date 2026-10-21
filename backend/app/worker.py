"""Background job worker (Milestone 6, Start/Stop era).

Runs as an asyncio task inside the API process (enabled by
WORKER_ENABLED=true in deployment). Heavy work stays off the request
path: the API only reads/writes job rows; this worker claims and
executes them.

Start/Stop era contract:

- Feeds are channel-aware: only channels whose persistent automation
  state is 'running' (or 'paused' for production work) get new jobs.
- Horizontal stock refill: when a channel's ready stock (#done, not
  #confirmed) drops below its target (default 3), exactly ONE new
  media_process job is enqueued — globally at most one horizontal
  source is in the pipeline at any time (heavy lock + feed cap).
- Heavy jobs (media pipeline, renders) serialize on one shared lock
  and are additionally capped by max_heavy_jobs; the claim respects
  CPU/RAM targets and pauses new work under overload instead of
  crashing.
- The worker heartbeats to app_meta ('worker_state') so the UI can
  prove the engine is actually alive — an idle API is not a running
  worker.
- Handlers refuse to run for stopped channels (manual jobs flagged
  'manual' bypass the gate); a terminally failed media job excludes
  its video and moves the channel to 'error' for operator review.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services.job_service import JobService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[Any]]
JobHandlers = dict[str, Handler]

# Agir isler: tek paylasilan kilit uzerinden siralanir ve ayrica
# max_heavy_jobs ile sinirlanir (iki agir FFmpeg render ayni anda baslamaz).
HEAVY_JOB_TYPES = ("media_process", "clip_render", "clip_render_full_cut")

# Bir videonun hazirlanma zinciri (kullanici istegi 2026-10-19): ayni
# anda yalniz bir video islenir. Yayin/sistem isleri (publish_due,
# ops_summary, source_discover, publish_full_cut) bu kisittan muaf
# kalir ki planlanan yayın saatleri uzun bir isleme tarafindan
# bloklanmasin.
PROCESSING_JOB_TYPES = (
    "media_process",
    "hype_evaluate",
    "clip_render",
    "clip_render_full_cut",
    "metadata_generate",
)

WORKER_STATE_KEY = "worker_state"


async def resolve_job_channel(
    sessionmaker: async_sessionmaker[AsyncSession],
    job_type: str,
    payload: dict[str, Any],
) -> int | None:
    """Which publishing channel does a job belong to? Payload keys map
    to source videos / candidates / assets; None when unknown."""
    from app.models import ClipCandidate, MediaAsset, SourceChannel, SourceVideo

    if job_type in ("source_discover", "publish_due", "ops_summary"):
        cid = payload.get("channel_id")
        return cid if isinstance(cid, int) else None
    source_video_id = None
    if job_type in (
        "media_process",
        "hype_evaluate",
        "clip_render_full_cut",
        "publish_full_cut",
    ):
        vid = payload.get("source_video_id")
        source_video_id = vid if isinstance(vid, int) else None
    elif job_type == "clip_render":
        cand = payload.get("clip_candidate_id")
        if isinstance(cand, int):
            async with sessionmaker() as session:
                row = await session.get(ClipCandidate, cand)
                source_video_id = row.source_video_id if row else None
    elif job_type == "subtitle_correct":
        aid = payload.get("media_asset_id")
        if isinstance(aid, int):
            async with sessionmaker() as session:
                row = await session.get(MediaAsset, aid)
                source_video_id = row.source_video_id if row else None
    elif job_type == "metadata_generate":
        vid = payload.get("source_video_id")
        if isinstance(vid, int):
            source_video_id = vid
        else:
            cand = payload.get("clip_candidate_id")
            if isinstance(cand, int):
                async with sessionmaker() as session:
                    row = await session.get(ClipCandidate, cand)
                    source_video_id = row.source_video_id if row else None
    if source_video_id is None:
        return None
    async with sessionmaker() as session:
        video = await session.get(SourceVideo, source_video_id)
        if video is None:
            return None
        source = await session.get(SourceChannel, video.source_channel_id)
        return source.channel_id if source else None


async def channel_allows_work(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    channel_id: int | None,
) -> bool:
    """Stopped channels execute nothing. 'error' channels still run
    already-queued/controlled retries (the feeds add no new work there);
    'paused' keeps producing but publishing is gated elsewhere."""
    if channel_id is None:
        return True  # baglam cozulemedi: is yurusun, guvenlik baska yerde
    from app.services.automation_service import AutomationService

    profile = await AutomationService(sessionmaker, settings).profile(channel_id)
    return profile.automation_state != "stopped"


def build_handlers(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> JobHandlers:
    """The job-type registry. M6 ships source discovery; M7 registers
    the media pipeline. One heavy lock is shared by every media/render
    job so the whole horizontal pipeline (download -> analysis) and the
    renders serialize — a second heavy job never starts before the
    first one finishes."""

    heavy_lock = asyncio.Lock()

    async def _guard(payload: dict[str, Any], job_type: str) -> bool:
        # Manuel isler (operator istegiyle kuyruga alinan) otomasyon
        # durumundan bagimsiz yurur.
        if payload.get("manual"):
            return True
        channel_id = await resolve_job_channel(sessionmaker, job_type, payload)
        return await channel_allows_work(sessionmaker, settings, channel_id)

    async def source_discover(payload: dict[str, Any]) -> dict:
        from app.services.discovery_service import DiscoveryService

        channel_id = payload.get("channel_id")
        if not isinstance(channel_id, int):
            raise ValueError("payload.channel_id gerekli.")
        if not await _guard(payload, "source_discover"):
            return {"channel_id": channel_id, "skipped": "channel_stopped"}
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        discovery = DiscoveryService(sessionmaker, effective)
        result = await discovery.discover_for_channel(channel_id)
        # M11: izleme -> planlama baglantisi (kesiften hemen sonra).
        from app.services.automation_service import auto_plan_channel

        planned = await auto_plan_channel(sessionmaker, channel_id)
        result["planned"] = planned.get("planned", 0)
        return result

    async def media_process(payload: dict[str, Any]) -> dict:
        from app.services.media_pipeline import MediaPipelineService

        source_video_id = payload.get("source_video_id")
        if not isinstance(source_video_id, int):
            raise ValueError("payload.source_video_id gerekli.")
        import_path = payload.get("import_path")
        if import_path is not None and not isinstance(import_path, str):
            raise ValueError("payload.import_path string olmali.")
        if not await _guard(payload, "media_process"):
            return {"source_video_id": source_video_id, "skipped": "channel_stopped"}
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        pipeline = MediaPipelineService(
            sessionmaker, effective, download_lock=None
        )
        # Agir is kilidi tum hatti kapsar: indirme, transkript, analiz
        # ve render asamalarinda ikinci bir yatay kaynak baslamaz.
        async with heavy_lock:
            return await pipeline.run(source_video_id, import_path=import_path)

    async def hype_evaluate(payload: dict[str, Any]) -> dict:
        from app.services.hype_service import HypeService
        from app.services.llm_service import LlmProviderService

        source_video_id = payload.get("source_video_id")
        if not isinstance(source_video_id, int):
            raise ValueError("payload.source_video_id gerekli.")
        if not await _guard(payload, "hype_evaluate"):
            return {"source_video_id": source_video_id, "skipped": "channel_stopped"}
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        # Anahtar DB'de saklanmissa (Ayarlar ekranindan girildiyse) cipher
        # efektif ayarlardan cozulmelidir; ham env ayarinda bos kalir.
        llm = LlmProviderService(sessionmaker, effective)
        service = HypeService(sessionmaker, llm, effective)
        return await service.evaluate_source(source_video_id)

    async def clip_render(payload: dict[str, Any]) -> dict:
        from app.services.vertical_pipeline import VerticalPipelineService

        clip_candidate_id = payload.get("clip_candidate_id")
        if not isinstance(clip_candidate_id, int):
            raise ValueError("payload.clip_candidate_id gerekli.")
        if not await _guard(payload, "clip_render"):
            return {"clip_candidate_id": clip_candidate_id, "skipped": "channel_stopped"}
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        pipeline = VerticalPipelineService(sessionmaker, effective)
        async with heavy_lock:
            result = await pipeline.run(clip_candidate_id)
        await _maybe_confirm(payload, "clip_render")
        return result

    async def clip_render_full_cut(payload: dict[str, Any]) -> dict:
        # M13: reaksiyon kaynagi videonun yatay tam kesidi.
        from app.services.vertical_pipeline import VerticalPipelineService

        source_video_id = payload.get("source_video_id")
        if not isinstance(source_video_id, int):
            raise ValueError("payload.source_video_id gerekli.")
        if not await _guard(payload, "clip_render_full_cut"):
            return {"source_video_id": source_video_id, "skipped": "channel_stopped"}
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        pipeline = VerticalPipelineService(sessionmaker, effective)
        async with heavy_lock:
            result = await pipeline.run_full_cut(source_video_id)
        await _maybe_confirm(payload, "clip_render_full_cut")
        return result

    async def _maybe_confirm(payload: dict[str, Any], job_type: str) -> None:
        # Render tamamlandi: kaynagin Shorts uretimi bittiyse #confirmed.
        from app.services.status_service import StatusService

        source_video_id = payload.get("source_video_id")
        if not isinstance(source_video_id, int) and job_type == "clip_render":
            from app.models import ClipCandidate

            cand = payload.get("clip_candidate_id")
            if isinstance(cand, int):
                async with sessionmaker() as session:
                    row = await session.get(ClipCandidate, cand)
                    source_video_id = row.source_video_id if row else None
        if isinstance(source_video_id, int):
            await StatusService(sessionmaker, settings).maybe_confirm_source(
                source_video_id
            )

    async def subtitle_correct(payload: dict[str, Any]) -> dict:
        from app.services.llm_service import LlmProviderService
        from app.services.subtitle_correction import SubtitleCorrectionService

        media_asset_id = payload.get("media_asset_id")
        if not isinstance(media_asset_id, int):
            raise ValueError("payload.media_asset_id gerekli.")
        if not await _guard(payload, "subtitle_correct"):
            return {"media_asset_id": media_asset_id, "skipped": "channel_stopped"}
        # Efektif ayar: TOKEN_ENCRYPTION_KEY Ayarlar ekranindan girildiyse
        # DB'de durur; cipher ham env ayariyla bos kalir.
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        llm = LlmProviderService(sessionmaker, effective)
        service = SubtitleCorrectionService(sessionmaker, llm)
        return await service.correct_transcript(media_asset_id)

    async def metadata_generate(payload: dict[str, Any]) -> dict:
        from app.services.llm_service import LlmProviderService
        from app.services.metadata_service import MetadataService

        clip_candidate_id = payload.get("clip_candidate_id")
        source_video_id = payload.get("source_video_id")
        if not isinstance(clip_candidate_id, int) and not isinstance(
            source_video_id, int
        ):
            raise ValueError(
                "payload.clip_candidate_id veya payload.source_video_id "
                "gerekli."
            )
        if not await _guard(payload, "metadata_generate"):
            return {"skipped": "channel_stopped"}
        # Efektif ayarlar: DB'de saklanan genel metaveri promptu da
        # cozumlenir (M13 prompt zinciri).
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        llm = LlmProviderService(sessionmaker, effective)
        service = MetadataService(sessionmaker, llm, settings=effective)
        if isinstance(clip_candidate_id, int):
            return await service.generate(clip_candidate_id)
        return await service.generate_full_cut(source_video_id)

    async def publish_clip(payload: dict[str, Any]) -> dict:
        from app.services.publishing_service import PublishingService

        clip_candidate_id = payload.get("clip_candidate_id")
        if not isinstance(clip_candidate_id, int):
            raise ValueError("payload.clip_candidate_id gerekli.")
        # Efektif ayarlar: TOKEN_ENCRYPTION_KEY Ayarlar ekranindan DB'de
        # durur; ham env ayariyla OAuth anahtari cozulemez (2026-10-21
        # canli olay — ayni ders hype/metaveri isleyicilerinde alinmisti).
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        service = PublishingService(sessionmaker, effective)
        return await service.publish_clip(clip_candidate_id)

    async def publish_full_cut(payload: dict[str, Any]) -> dict:
        """Yatay tam kesitin gizli yuklemesi (onay tetikleyicili)."""
        from app.services.publishing_service import PublishingService

        source_video_id = payload.get("source_video_id")
        if not isinstance(source_video_id, int):
            raise ValueError("payload.source_video_id gerekli.")
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        service = PublishingService(sessionmaker, effective)
        return await service.publish_full_cut(source_video_id)

    async def publish_due(payload: dict[str, Any]) -> dict:
        from app.services.automation_service import AutomationService

        channel_id = payload.get("channel_id")
        if not isinstance(channel_id, int):
            raise ValueError("payload.channel_id gerekli.")
        # make_public yolu da OAuth anahtarina uzanir: efektif ayarlar.
        effective = await SettingsService(
            sessionmaker, settings
        ).effective_settings()
        service = AutomationService(sessionmaker, effective)
        return await service.publish_for_channel(channel_id)

    async def ops_summary(payload: dict[str, Any]) -> dict:
        from app.services.automation_service import AutomationService

        channel_id = payload.get("channel_id")
        if not isinstance(channel_id, int):
            raise ValueError("payload.channel_id gerekli.")
        service = AutomationService(sessionmaker, settings)
        return await service.operational_summary(channel_id)

    return {
        "source_discover": source_discover,
        "media_process": media_process,
        "hype_evaluate": hype_evaluate,
        "clip_render": clip_render,
        "clip_render_full_cut": clip_render_full_cut,
        "subtitle_correct": subtitle_correct,
        "metadata_generate": metadata_generate,
        "publish_clip": publish_clip,
        "publish_full_cut": publish_full_cut,
        "publish_due": publish_due,
        "ops_summary": ops_summary,
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
        self._running_types: dict[int, str] = {}
        self._worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self._last_poll_enqueue = 0.0
        self._last_planned_enqueue = 0.0
        self._last_render_enqueue = 0.0
        self._last_content_enqueue = 0.0
        self._last_upload_enqueue = 0.0
        self._last_hype_enqueue = 0.0
        self._last_publish_enqueue = 0.0
        self._last_media_cleanup = 0.0
        self._last_stale_recover = 0.0
        self._last_heartbeat_warning = 0.0
        self._last_summary_day = ""
        self._last_tmp_cleanup = 0.0
        self._last_state_write = 0.0
        self._jobs_processed = 0
        self._last_resource_warning = 0.0
        self._started_at: str | None = None
        # Efektif ayarlar her dongude tazelenebilir (site ayarlari
        # yeniden baslatma olmadan gecerli olur).
        self._effective = settings

    # --- testable pieces ---

    async def run_job(self, job_id: int) -> None:
        """Execute one claimed job with heartbeat + settle logic."""
        beat = asyncio.create_task(self._heartbeat_loop(job_id))
        job = None
        try:
            job = await self._get(job_id)
            if job is None:
                return
            if job.status in ("succeeded", "failed", "cancelled"):
                return  # sonuc lanmis is yeniden yurutulmez
            if job.status == "cancelling":
                await self._jobs.succeed(job_id)  # cancelling -> cancelled
                return
            handler = self._handlers.get(job.job_type)
            if handler is None:
                await self._jobs.fail(job_id, f"Bilinmeyen iş türü: {job.job_type}")
                return
            await handler(job.payload or {})
            await self._jobs.succeed(job_id)
            self._jobs_processed += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - iş hatası kayda geçer
            terminal = (
                job is not None and job.attempts >= job.max_attempts
            )
            await self._jobs.fail(job_id, f"{type(exc).__name__}: {exc}")
            if terminal and job is not None:
                # Kullanici istegi (2026-10-19): kalici is hatasi kanali
                # 'error'a dusurup tum uretimi durdurmaz. Basarisiz
                # videonun varligi 'failed' kalir; stok beslemesi bu
                # videolari atlar ve siradaki videoyla devam eder.
                logger.error(
                    "is kalici olarak basarisiz (kanal durmadi, video "
                    "kuyruk disi birakildi): %s #%s: %s",
                    job.job_type,
                    job.id,
                    exc,
                )
        finally:
            beat.cancel()

    async def _heartbeat_loop(self, job_id: int) -> None:
        try:
            while True:
                try:
                    await self._jobs.heartbeat(job_id)
                except Exception:  # noqa: BLE001 - gecici DB hatasi kalp atisini oldurmesin
                    now = time.monotonic()
                    if now - self._last_heartbeat_warning > 60:
                        self._last_heartbeat_warning = now
                        logger.warning(
                            "is #%s kalp atisi yazilamadi, tekrar denenecek",
                            job_id,
                        )
                await asyncio.sleep(self._heartbeat_seconds)
        except asyncio.CancelledError:
            pass

    async def refresh_effective_settings(self) -> Settings:
        """Site ayarlarindaki gecersiz kilmalari oku; hata olursa
        son gecerli ayarlarla devam et."""
        try:
            self._effective = await SettingsService(
                self._sessionmaker, self._settings
            ).effective_settings()
            # Kuyruk servisi de efektif ayarlari gorsun: disk esigi site
            # ayarindan degistiginde restart gerektirmesin.
            self._jobs.update_settings(self._effective)
        except Exception:  # noqa: BLE001 - ayar okunamazsa onceki deger
            pass
        return self._effective

    def _resource_ok(self) -> bool:
        """CPU/RAM hedefleri asildiysa yeni is almaya bekle (is kilidi
        yok; asiri yuk gectiginde kendiliginden toparlanir)."""
        cpu_target = self._effective.cpu_target_percent
        ram_target = self._effective.ram_target_percent
        if cpu_target <= 0 and ram_target <= 0:
            return True
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
        except Exception:  # noqa: BLE001 - olcum yoksa kisit uygulanmaz
            return True
        if cpu > cpu_target > 0 or ram > ram_target > 0:
            now = time.monotonic()
            if now - self._last_resource_warning > 60:
                self._last_resource_warning = now
                logger.warning(
                    "kaynak limiti asildi (CPU %s%%/%s, RAM %s%%/%s); "
                    "yeni isler bekliyor",
                    round(cpu, 1),
                    cpu_target,
                    round(ram, 1),
                    ram_target,
                )
            return False
        return True

    async def claim_batch(self) -> int:
        """Claim jobs up to the concurrency limit; heavy jobs are
        additionally capped by max_heavy_jobs and at most ONE video
        processing job runs at a time (the rest waits its turn; publish
        and system jobs may use the remaining slot). Returns how many
        started."""
        started = 0
        while len(self._running) < self._effective.max_concurrent_jobs:
            running_heavy = sum(
                1
                for job_type in self._running_types.values()
                if job_type in HEAVY_JOB_TYPES
            )
            exclude: set[str] = set()
            if running_heavy >= self._effective.max_heavy_jobs:
                exclude |= set(HEAVY_JOB_TYPES)
            if any(
                job_type in PROCESSING_JOB_TYPES
                for job_type in self._running_types.values()
            ):
                exclude |= set(PROCESSING_JOB_TYPES)
            job = await self._jobs.claim_next(
                self._worker_id,
                exclude_types=sorted(exclude) if exclude else None,
            )
            if job is None:
                break
            task = asyncio.create_task(self.run_job(job.id))
            self._running[job.id] = task
            self._running_types[job.id] = job.job_type
            task.add_done_callback(
                lambda t, jid=job.id: (
                    self._running.pop(jid, None),
                    self._running_types.pop(jid, None),
                )
            )
            started += 1
        return started

    async def _work_channel_ids(self) -> list[int]:
        """Yeni is almaya uygun kanallar ('running'/'paused')."""
        async with self._sessionmaker() as session:
            return list(
                (
                    await session.execute(
                        text(
                            "SELECT pp.channel_id FROM publishing_profiles pp "
                            "JOIN channels c ON c.id = pp.channel_id "
                            "WHERE pp.automation_state IN ('running','paused')"
                        )
                    )
                )
                .scalars()
                .all()
            )

    async def enqueue_poll_jobs(self) -> int:
        """Periodic source polling: one discover job per working channel
        that has authorized sources. Dedupe keeps repeated ticks from
        piling up."""
        interval = self._effective.source_poll_interval_minutes * 60
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
        working = set(await self._work_channel_ids())
        for channel_id in channel_ids:
            if channel_id not in working:
                continue
            job = await self._jobs.enqueue(
                "source_discover", {"channel_id": channel_id}, priority=9
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_planned_jobs(self) -> int:
        """Stock-target-aware horizontal refill (Start/Stop era).

        For every working channel whose ready stock is below its
        target, enqueue ONE media_process job — the global single-source
        rule keeps a second download from starting while one runs.
        Stopped/error channels produce nothing."""
        from app.services.automation_service import refill_channel_stock

        interval = self._effective.planned_poll_interval_minutes * 60
        now = time.monotonic()
        if (
            self._last_planned_enqueue
            and now - self._last_planned_enqueue < interval
        ):
            return 0
        self._last_planned_enqueue = now
        async with self._sessionmaker() as session:
            channel_ids = list(
                (
                    await session.execute(
                        text(
                            "SELECT channel_id FROM publishing_profiles "
                            "WHERE automation_state IN ('running','paused')"
                        )
                    )
                )
                .scalars()
                .all()
            )
        added = 0
        for channel_id in channel_ids:
            result = await refill_channel_stock(
                self._sessionmaker, self._effective, channel_id
            )
            if result.get("enqueued"):
                added += 1
        return added

    async def enqueue_hype_jobs(self) -> int:
        """Hype feed: processed videos with pending candidates and no
        selection yet get one hype_evaluate job (dedupe guards repeats;
        selection marks the video as evaluated)."""
        interval = self._effective.planned_poll_interval_minutes * 60
        now = time.monotonic()
        if self._last_hype_enqueue and now - self._last_hype_enqueue < interval:
            return 0
        self._last_hype_enqueue = now
        async with self._sessionmaker() as session:
            video_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT sv.id FROM source_videos sv"
                            " JOIN media_assets ma ON ma.source_video_id = sv.id"
                            " JOIN source_channels sc"
                            " ON sv.source_channel_id = sc.id"
                            " JOIN publishing_profiles pp"
                            " ON pp.channel_id = sc.channel_id"
                            " WHERE sv.status = 'processed'"
                            " AND ma.status = 'processed'"
                            " AND pp.automation_state IN ('running','paused')"
                            " AND EXISTS ("
                            "  SELECT 1 FROM clip_candidates cc"
                            "  WHERE cc.source_video_id = sv.id"
                            "  AND cc.status = 'candidate')"
                            " AND NOT EXISTS ("
                            "  SELECT 1 FROM clip_candidates cc2"
                            "  WHERE cc2.source_video_id = sv.id"
                            "  AND cc2.status = 'selected')"
                            " ORDER BY sv.id"
                        )
                    )
                )
                .scalars()
                .all()
            )
        added = 0
        for video_id in video_ids:
            job = await self._jobs.enqueue(
                "hype_evaluate", {"source_video_id": video_id}, priority=8
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_render_jobs(self) -> int:
        """Periodic render feed: one clip_render job per SELECTED
        candidate (hype evaluation picks them) that is not rendered
        yet; reaction sources additionally feed one horizontal full-cut
        render job per source video without such a row."""
        interval = self._effective.planned_poll_interval_minutes * 60
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
                            " JOIN source_videos sv ON sv.id = cc.source_video_id"
                            " JOIN source_channels sc"
                            " ON sv.source_channel_id = sc.id"
                            " JOIN publishing_profiles pp"
                            " ON pp.channel_id = sc.channel_id"
                            " WHERE cc.status = 'selected'"
                            " AND pp.automation_state IN ('running','paused')"
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
            fullcut_video_ids = (
                (
                    await session.execute(
                        sa.text(
                            "SELECT sv.id FROM source_videos sv"
                            " JOIN source_channels sc"
                            " ON sv.source_channel_id = sc.id"
                            " JOIN publishing_profiles pp"
                            " ON pp.channel_id = sc.channel_id"
                            " WHERE (sc.output_orientation = 'horizontal'"
                            "  OR (sc.output_orientation = 'auto'"
                            "      AND sc.reaction_source = TRUE))"
                            " AND pp.automation_state IN ('running','paused')"
                            " AND NOT EXISTS ("
                            " SELECT 1 FROM rendered_clips rc"
                            " WHERE rc.source_video_id = sv.id"
                            " AND rc.orientation = 'horizontal')"
                            " ORDER BY sv.id"
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
        for video_id in fullcut_video_ids:
            job = await self._jobs.enqueue(
                "clip_render_full_cut",
                {"source_video_id": video_id},
                priority=8,
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_content_jobs(self) -> int:
        """Feed the content stages: metadata for rendered clips without
        metadata — only for working channels. M13: horizontal full cuts
        (candidate NULL, source_video set) get their metadata job keyed
        by source_video_id. LLM subtitle correction was removed from the
        engine (user request 2026-10-19): the provider kept failing real
        requests, hype/metadata already fall back to the raw transcript,
        and rendering never burned corrected subtitles."""
        interval = self._effective.planned_poll_interval_minutes * 60
        now = time.monotonic()
        if (
            self._last_content_enqueue
            and now - self._last_content_enqueue < interval
        ):
            return 0
        self._last_content_enqueue = now
        added = 0
        async with self._sessionmaker() as session:
            candidate_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT rc.clip_candidate_id FROM rendered_clips rc"
                            " JOIN clip_candidates cc ON cc.id = rc.clip_candidate_id"
                            " JOIN source_videos sv ON sv.id = cc.source_video_id"
                            " JOIN source_channels sc"
                            " ON sv.source_channel_id = sc.id"
                            " JOIN publishing_profiles pp"
                            " ON pp.channel_id = sc.channel_id"
                            " WHERE rc.status = 'rendered'"
                            " AND rc.clip_candidate_id IS NOT NULL"
                            " AND pp.automation_state IN ('running','paused')"
                            " AND NOT EXISTS ("
                            " SELECT 1 FROM clip_metadata cm"
                            " WHERE cm.clip_candidate_id = rc.clip_candidate_id)"
                        )
                    )
                )
                .scalars()
                .all()
            )
            fullcut_video_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT rc.source_video_id FROM rendered_clips rc"
                            " JOIN source_videos sv ON sv.id = rc.source_video_id"
                            " JOIN source_channels sc"
                            " ON sv.source_channel_id = sc.id"
                            " JOIN publishing_profiles pp"
                            " ON pp.channel_id = sc.channel_id"
                            " WHERE rc.status = 'rendered'"
                            " AND rc.clip_candidate_id IS NULL"
                            " AND rc.orientation = 'horizontal'"
                            " AND pp.automation_state IN ('running','paused')"
                            " AND NOT EXISTS ("
                            " SELECT 1 FROM clip_metadata cm"
                            " WHERE cm.source_video_id = rc.source_video_id"
                            " AND cm.clip_candidate_id IS NULL)"
                        )
                    )
                )
                .scalars()
                .all()
            )
        for candidate_id in candidate_ids:
            job = await self._jobs.enqueue(
                "metadata_generate", {"clip_candidate_id": candidate_id}, priority=7
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        for video_id in fullcut_video_ids:
            job = await self._jobs.enqueue(
                "metadata_generate", {"source_video_id": video_id}, priority=7
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_upload_jobs(self) -> int:
        """Tamamlandiktan sonra otomatik GIZLI yukleme (kullanici istegi
        2026-10-21): render'i hazir ve metaverisi onayli (ya da kanalda
        otomatik onay acik) ama henuz YouTube'a yuklenmemis klipler icin
        publish_clip / publish_full_cut isleri acar. Yukleme GIZLIDIR;
        herkese acilma yine planlanan saatte publish_due ile yapilir.
        Manuel onay akisi bozulmaz: otomatik onayi kapali kanalda yalniz
        onaylanmis metaveri yuklenir."""
        interval = self._effective.planned_poll_interval_minutes * 60
        now = time.monotonic()
        if (
            self._last_upload_enqueue
            and now - self._last_upload_enqueue < interval
        ):
            return 0
        self._last_upload_enqueue = now
        added = 0
        async with self._sessionmaker() as session:
            candidate_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT rc.clip_candidate_id FROM rendered_clips rc"
                            " JOIN clip_candidates cc"
                            " ON cc.id = rc.clip_candidate_id"
                            " JOIN source_videos sv"
                            " ON sv.id = cc.source_video_id"
                            " JOIN source_channels sc"
                            " ON sv.source_channel_id = sc.id"
                            " JOIN publishing_profiles pp"
                            " ON pp.channel_id = sc.channel_id"
                            " WHERE rc.status = 'rendered'"
                            " AND rc.clip_candidate_id IS NOT NULL"
                            " AND rc.orientation = 'vertical'"
                            " AND pp.automation_state IN ('running','paused')"
                            " AND ("
                            " pp.settings->>'auto_approve_metadata' = 'true'"
                            " OR EXISTS ("
                            " SELECT 1 FROM clip_metadata cm"
                            " WHERE cm.clip_candidate_id"
                            " = rc.clip_candidate_id"
                            " AND cm.status = 'approved')"
                            " )"
                            " AND NOT EXISTS ("
                            " SELECT 1 FROM published_videos pv"
                            " WHERE pv.clip_candidate_id = rc.clip_candidate_id)"
                        )
                    )
                )
                .scalars()
                .all()
            )
            fullcut_video_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT rc.source_video_id FROM rendered_clips rc"
                            " JOIN source_videos sv"
                            " ON sv.id = rc.source_video_id"
                            " JOIN source_channels sc"
                            " ON sv.source_channel_id = sc.id"
                            " JOIN publishing_profiles pp"
                            " ON pp.channel_id = sc.channel_id"
                            " WHERE rc.status = 'rendered'"
                            " AND rc.clip_candidate_id IS NULL"
                            " AND rc.orientation = 'horizontal'"
                            " AND pp.automation_state IN ('running','paused')"
                            " AND ("
                            " pp.settings->>'auto_approve_metadata' = 'true'"
                            " OR EXISTS ("
                            " SELECT 1 FROM clip_metadata cm"
                            " WHERE cm.source_video_id = rc.source_video_id"
                            " AND cm.clip_candidate_id IS NULL"
                            " AND cm.status = 'approved')"
                            " )"
                            " AND NOT EXISTS ("
                            " SELECT 1 FROM published_videos pv"
                            " WHERE pv.source_video_id = rc.source_video_id"
                            " AND pv.clip_candidate_id IS NULL)"
                        )
                    )
                )
                .scalars()
                .all()
            )
        for candidate_id in candidate_ids:
            job = await self._jobs.enqueue(
                "publish_clip", {"clip_candidate_id": candidate_id}, priority=6
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        for video_id in fullcut_video_ids:
            job = await self._jobs.enqueue(
                "publish_full_cut", {"source_video_id": video_id}, priority=6
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_publish_jobs(self) -> int:
        """Schedule-aware publishing: one publish_due job per connected,
        running channel whose slot arrived. The job itself picks the
        best ready candidate; nothing publishes without the
        rights/approval guards."""
        interval = self._effective.publish_check_interval_minutes * 60
        now = time.monotonic()
        if (
            self._last_publish_enqueue
            and now - self._last_publish_enqueue < interval
        ):
            return 0
        self._last_publish_enqueue = now
        from app.services.publishing_service import PublishingService

        service = PublishingService(self._sessionmaker, self._effective)
        channel_ids = await service.due_channels()
        added = 0
        for channel_id in channel_ids:
            job = await self._jobs.enqueue(
                "publish_due", {"channel_id": channel_id}, priority=6
            )
            if job.status == "queued" and job.attempts == 0:
                added += 1
        return added

    async def enqueue_summary_jobs(self) -> int:
        """Daily operational summary per working channel: one
        ops_summary job per local day (payload dedupes repeats)."""
        from app.services.automation_service import today_key

        day = today_key()
        if self._last_summary_day == day:
            return 0
        self._last_summary_day = day
        added = 0
        for channel_id in await self._work_channel_ids():
            job = await self._jobs.enqueue(
                "ops_summary",
                {"channel_id": channel_id, "day": day},
                priority=9,
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

    async def cleanup_media_once(self) -> dict:
        """Retention dolumu gelen yayın dosyalarını ve dikey yönlü
        kaynakların kalan yatay dosyalarını temizle."""
        from app.services.media_cleanup import (
            cleanup_published_media,
            cleanup_vertical_source_files,
        )

        try:
            result = await cleanup_published_media(
                self._sessionmaker, self._effective
            )
        except Exception:  # noqa: BLE001 - temizlik best-effort
            result = {"cleaned": 0}
        try:
            vertical = await cleanup_vertical_source_files(
                self._sessionmaker, self._effective
            )
        except Exception:  # noqa: BLE001 - temizlik best-effort
            vertical = {"cleaned": 0}
        result["vertical_cleaned"] = vertical.get("cleaned", 0)
        return result

    async def _maybe_cleanup_media(self) -> None:
        """Run the retention cleanup at most once per hour."""
        now = time.monotonic()
        if self._last_media_cleanup and now - self._last_media_cleanup < 3600:
            return
        self._last_media_cleanup = now
        await self.cleanup_media_once()

    async def _maybe_recover_stale(self) -> None:
        """Sessiz kalan 'running' isleri dongu icinde de toparla.

        Startup'taki tek seferlik toparlama, uzun omurlu worker'da
        olum/iptal aralarinda 'running' kalan hayalet isleri goremuyor;
        hayalet is kuyruk beslemesini saatlerce tikayabiliyor (2026-10-21
        canli olay), bu yuzden dakikada bir tekrarlanir."""
        now = time.monotonic()
        if now - self._last_stale_recover < 60:
            return 0
        self._last_stale_recover = now
        recovered = await self._jobs.recover_stale()
        if recovered:
            logger.warning(
                "%s sessiz 'running' is geri kuyruga alindi (hayalet temizligi)",
                recovered,
            )
        return recovered

    # --- worker saglik durumu (UI kaniti) ---

    async def write_worker_state(self) -> None:
        """Heartbeat the worker into app_meta so the UI can prove the
        engine runs (an idle API is not a running worker). Throttled to
        the heartbeat interval."""
        now = time.monotonic()
        if now - self._last_state_write < self._heartbeat_seconds:
            return
        self._last_state_write = now
        from app.models import AppMeta

        try:
            async with self._sessionmaker() as session:
                row = await session.get(AppMeta, WORKER_STATE_KEY)
                value = {
                    "worker_id": self._worker_id,
                    "started_at": self._started_at or "",
                    "last_tick_at": datetime.now(UTC).isoformat(),
                    "jobs_processed": self._jobs_processed,
                    "poll_seconds": self._poll_seconds,
                    "heartbeat_seconds": self._heartbeat_seconds,
                }
                if row is None:
                    session.add(AppMeta(key=WORKER_STATE_KEY, value=value))
                else:
                    row.value = value
                await session.commit()
        except Exception:  # noqa: BLE001 - saglik yazimi best-effort
            pass

    async def _get(self, job_id: int):
        from app.models import Job

        async with self._sessionmaker() as session:
            return await session.get(Job, job_id)

    # --- main loop ---

    async def run_forever(self) -> None:
        logger.info(
            "worker basladi (id=%s, poll=%.1fs)", self._worker_id, self._poll_seconds
        )
        self._started_at = datetime.now(UTC).isoformat()
        try:
            # Yeniden başlatma kurtarması: sessiz kalmış running işleri geri al.
            await self._jobs.recover_stale()
            while True:
                try:
                    await self.refresh_effective_settings()
                    await self.enqueue_poll_jobs()
                    await self.enqueue_planned_jobs()
                    await self.enqueue_hype_jobs()
                    await self.enqueue_render_jobs()
                    await self.enqueue_content_jobs()
                    await self.enqueue_upload_jobs()
                    await self.enqueue_publish_jobs()
                    await self.enqueue_summary_jobs()
                    await self._maybe_cleanup_tmp()
                    await self._maybe_cleanup_media()
                    await self._maybe_recover_stale()
                    await self.write_worker_state()
                    if self._resource_ok():
                        await self.claim_batch()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - döngü asla durmasın
                    logger.exception("worker döngüsü adımı hata")
                await asyncio.sleep(self._poll_seconds)
        except asyncio.CancelledError:
            logger.info("worker durduruldu (id=%s)", self._worker_id)
            raise


def utc_now() -> datetime:
    return datetime.now(UTC)
