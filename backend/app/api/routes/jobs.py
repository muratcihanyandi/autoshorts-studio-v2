"""Job queue API: list, enqueue, cancel, retry."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas_jobs import JobEnqueue, JobOut, JobsOut
from app.services.job_service import JobService, JobServiceError

router = APIRouter(tags=["jobs"])


def _service(request: Request) -> JobService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; iş kuyruğu kapalı.",
        )
    return JobService(sessionmaker, request.app.state.settings)


@router.get("/jobs", response_model=JobsOut)
async def list_jobs(
    request: Request, status: str | None = None, limit: int = 50
) -> JobsOut:
    service = _service(request)
    jobs = await service.list_jobs(status=status, limit=limit)
    return JobsOut(
        jobs=[JobOut.model_validate(job) for job in jobs], total=len(jobs)
    )


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def enqueue_job(request: Request, data: JobEnqueue) -> JobOut:
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
