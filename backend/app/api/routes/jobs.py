"""Job queue API: list, enqueue, cancel, retry."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas_jobs import JobEnqueue, JobOut, JobsOut
from app.services.auth_service import require_admin
from app.services.job_service import JobService, JobServiceError
from app.services.pipeline_view import PipelineViewService

router = APIRouter(tags=["jobs"])


def _service(request: Request) -> JobService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; iş kuyruğu kapalı.",
        )
    return JobService(sessionmaker, request.app.state.settings)


async def _enrich(
    request: Request,
    jobs: list,
    allowed_channel_ids: set[int] | None = None,
) -> list[JobOut]:
    """Her işe video başlığı/kanal/aşama bağlamı ekler; veritabanı yoksa
    veya eşleşme bulunamazsa alanlar null kalır.

    allowed_channel_ids verilirse yalnız o kanalların işleri döner;
    operatör hesabı başka kullanıcının işlerini göremez."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        return [JobOut.model_validate(job) for job in jobs]
    context = await PipelineViewService(
        sessionmaker, request.app.state.settings
    ).job_context(jobs)
    out: list[JobOut] = []
    for job in jobs:
        ctx = context.get(job.id, {})
        if (
            allowed_channel_ids is not None
            and ctx.get("channel_id") not in allowed_channel_ids
        ):
            continue
        item = JobOut.model_validate(job)
        item.title = ctx.get("title")
        item.youtube_video_id = ctx.get("youtube_video_id")
        item.channel_name = ctx.get("channel_name")
        item.ribbon_color = ctx.get("ribbon_color")
        if job.job_type == "media_process":
            item.stage = ctx.get("asset_stage")
        out.append(item)
    return out


@router.get("/jobs", response_model=JobsOut)
async def list_jobs(
    request: Request, status: str | None = None, limit: int = 50
) -> JobsOut:
    from app.services.auth_service import owned_channel_ids

    service = _service(request)
    jobs = await service.list_jobs(status=status, limit=limit)
    enriched = await _enrich(
        request, jobs, await owned_channel_ids(request)
    )
    return JobsOut(jobs=enriched, total=len(enriched))


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def enqueue_job(request: Request, data: JobEnqueue) -> JobOut:
    # Rastgele iş türü kuyruğa yazmak motorun güvenlik kapılarını
    # atlatmanın yoluydu (2026-11-03 denetimi): yönetici yetkisi ister.
    require_admin(request)
    service = _service(request)
    try:
        job = await service.enqueue(
            data.job_type,
            data.payload,
            priority=data.priority,
            max_attempts=data.max_attempts,
        )
    except JobServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(request: Request, job_id: int) -> JobOut:
    service = _service(request)
    try:
        job = await service.cancel(job_id)
    except JobServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(request: Request, job_id: int) -> JobOut:
    """Re-queue a failed/cancelled job with a fresh attempt budget."""
    from app.models import Job

    service = _service(request)
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="İş bulunamadı.")
        if job.status not in ("failed", "cancelled"):
            raise HTTPException(
                status_code=409,
                detail="Yalnızca sonuçlanmış işler yeniden kuyruğa alınabilir.",
            )
        job.status = "queued"
        job.attempts = 0
        job.worker_id = None
        job.started_at = None
        job.finished_at = None
        job.heartbeat_at = None
        await session.commit()
        await session.refresh(job)
    return JobOut.model_validate(job)
