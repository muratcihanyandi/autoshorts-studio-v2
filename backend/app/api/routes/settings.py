"""Settings API: site-managed runtime configuration.

GET returns masked views (secrets never leave the service layer); PUT
applies patch semantics (None = untouched, "" = fall back to the
environment, value = database override after validation).

Only administrators may read or change site settings: the screen holds
OAuth credentials, the token encryption key and engine-wide limits, so
an operator account must not see or edit them (2026-11-03 audit).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.config import Settings
from app.schemas_settings import SettingsOut, SettingsUpdate
from app.services.auth_service import require_admin
from app.services.settings_service import SettingsService, SettingsServiceError

router = APIRouter(tags=["settings"])


def _service(request: Request) -> SettingsService:
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; ayar yönetimi kapalı.",
        )
    return SettingsService(sessionmaker, request.app.state.settings)


async def effective_settings(request: Request) -> Settings:
    """Environment settings overlaid with site-managed overrides.

    Shared by routes whose services consume credentials (OAuth, YouTube
    discovery) so database-configured values take effect without a
    restart. Without a database the environment settings pass through.
    """
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        return request.app.state.settings
    service = SettingsService(sessionmaker, request.app.state.settings)
    return await service.effective_settings()


@router.get("/settings", response_model=SettingsOut)
async def get_settings(request: Request) -> SettingsOut:
    require_admin(request)
    return await _service(request).view()


@router.put("/settings", response_model=SettingsOut)
async def update_settings(
    request: Request, patch: SettingsUpdate
) -> SettingsOut:
    require_admin(request)
    service = _service(request)
    try:
        return await service.update(patch)
    except SettingsServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
