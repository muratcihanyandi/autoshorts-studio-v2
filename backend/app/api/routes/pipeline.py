"""Canlı boru hattı API: Genel Bakış'ın iş kartlarını besler."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.services.pipeline_view import PipelineViewService

router = APIRouter(tags=["pipeline"])


def _service(request: Request) -> PipelineViewService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; boru hattı görünümü kapalı.",
        )
    return PipelineViewService(sessionmaker, request.app.state.settings)


@router.get("/pipeline")
async def pipeline_overview(request: Request) -> dict:
    return await _service(request).overview()
