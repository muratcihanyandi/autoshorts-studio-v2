"""LLM provider management API.

Provider API keys are write-only: they arrive once (create/PATCH),
are encrypted before storage, and responses carry only a masked hint.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.routes.settings import effective_settings
from app.schemas_llm import (
    LlmProviderCreate,
    LlmProviderOut,
    LlmProviderUpdate,
    LlmProvidersOut,
    LlmRequestLogOut,
    LlmRequestLogsOut,
    LlmTestResult,
)
from app.services.llm_service import LlmProviderService, LlmServiceError

router = APIRouter(tags=["llm"])


async def _service(request: Request) -> LlmProviderService:
    """Service bound to effective settings (site-managed cipher key)."""
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; LLM yönetimi kapalı.",
        )
    return LlmProviderService(sessionmaker, await effective_settings(request))


@router.get("/llm/providers", response_model=LlmProvidersOut)
async def list_providers(request: Request) -> LlmProvidersOut:
    service = await _service(request)
    providers = await service.list_providers()
    return LlmProvidersOut(
        providers=providers,
        total=len(providers),
        enabled=sum(1 for p in providers if p.enabled),
    )


@router.post(
    "/llm/providers",
    response_model=LlmProviderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    request: Request, data: LlmProviderCreate
) -> LlmProviderOut:
    service = await _service(request)
    try:
        return await service.create_provider(data)
    except LlmServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.patch("/llm/providers/{provider_id}", response_model=LlmProviderOut)
async def update_provider(
    request: Request, provider_id: int, data: LlmProviderUpdate
) -> LlmProviderOut:
    service = await _service(request)
    try:
        return await service.update_provider(provider_id, data)
    except LlmServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete(
    "/llm/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_provider(request: Request, provider_id: int) -> None:
    service = await _service(request)
    try:
        await service.delete_provider(provider_id)
    except LlmServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/llm/providers/{provider_id}/test", response_model=LlmTestResult)
async def test_provider(request: Request, provider_id: int) -> LlmTestResult:
    service = await _service(request)
    try:
        result = await service.test_provider(provider_id)
    except LlmServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return LlmTestResult(**result)


@router.get("/llm/logs", response_model=LlmRequestLogsOut)
async def list_llm_logs(request: Request, limit: int = 50) -> LlmRequestLogsOut:
    service = await _service(request)
    logs = await service.recent_logs(limit=limit)
    return LlmRequestLogsOut(
        logs=[LlmRequestLogOut.model_validate(log) for log in logs],
        total=len(logs),
    )
