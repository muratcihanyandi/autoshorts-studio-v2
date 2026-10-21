"""Whisper runtime installation API (UI "Indir ve Kur" button).

GET reports whether Whisper is resolvable right now plus the last
install attempt's state; POST starts a platform-aware background pip
install (see whisper_install). Guards: already installed (400),
install already running (409), insufficient disk (503).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, status

from app.services.whisper_install import (
    WhisperInstallError,
    disk_ok_for_install,
    install_whisper,
    platform_info,
    plan_install,
    reconcile_stale_state,
    whisper_available,
)

router = APIRouter(tags=["whisper"])


def _sessionmaker(request: Request):
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    if sessionmaker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı yapılandırılmadı; kurulum durumu izlenemez.",
        )
    return sessionmaker


@router.get("/whisper")
async def whisper_status(request: Request) -> dict:
    settings = request.app.state.settings
    sessionmaker = getattr(request.app.state, "sessionmaker", None)
    status_row = await reconcile_stale_state(sessionmaker)
    return {
        "installed": whisper_available(settings),
        **platform_info(),
        "status": status_row,
    }


@router.post("/whisper/install", status_code=status.HTTP_202_ACCEPTED)
async def start_whisper_install(request: Request) -> dict:
    """Whisper'i indir ve kur (arka planda; durum /api/whisper'dan
    izlenir). Platforma göre venv'e ya da kalıcı medya dizinine
    kurulur."""
    sessionmaker = _sessionmaker(request)
    settings = request.app.state.settings

    if whisper_available(settings):
        raise HTTPException(
            status_code=400,
            detail="Whisper zaten kurulu.",
        )
    if getattr(request.app.state, "whisper_install_running", False):
        raise HTTPException(
            status_code=409,
            detail="Whisper kurulumu zaten sürüyor.",
        )
    # Once olu kilidi kaldir: kalp atisi susmus bir 'running' durumu
    # (yeniden baslatma golpeyi oldurdu) 'failed'a cevrilir ki 409
    # yalnizca gercekten kosan kurulumu korusun.
    state_row = await reconcile_stale_state(sessionmaker)
    if state_row is not None and state_row.get("state") == "running":
        raise HTTPException(
            status_code=409,
            detail="Whisper kurulumu zaten sürüyor.",
        )
    if not disk_ok_for_install(settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Kurulum için yeterli boş disk yok (en az 2 GB gerekli; "
                "torch tekerlekleri büyüktür)."
            ),
        )
    try:
        plan = plan_install(settings)
    except WhisperInstallError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request.app.state.whisper_install_running = True

    async def _task() -> None:
        try:
            await install_whisper(sessionmaker, settings)
        finally:
            request.app.state.whisper_install_running = False

    request.app.state.whisper_install_task = asyncio.create_task(_task())
    return {
        "state": "running",
        "mode": plan["mode"],
        **platform_info(),
    }
