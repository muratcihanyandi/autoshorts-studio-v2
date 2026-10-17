"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import __version__
from app.api.routes.channels import router as channels_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.llm import router as llm_router
from app.api.routes.overview import router as overview_router
from app.api.routes.settings import router as settings_router
from app.api.routes.sources import router as sources_router
from app.api.routes.system import router as system_router
from app.config import Settings, get_settings
from app.db import create_engine_and_sessionmaker
from app.logging_config import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine: AsyncEngine | None = None
        sessionmaker: async_sessionmaker | None = None
        if settings.database_url:
            engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.settings = settings
        app.state.started_at = time.time()
        # Medya klasör ağacı: volume bağlıysa etiketli klasörleri kur.
        if settings.media_root:
            from app.services.media_storage import ensure_media_tree

            app.state.media_tree = ensure_media_tree(settings.media_root)
        # Seed the psutil CPU baseline so the first /api/system poll is real.
        try:
            import psutil

            psutil.cpu_percent(interval=None)
        except Exception:  # noqa: BLE001 - measurement only
            pass
        # Milestone 6: background job worker (off in tests; deployment
        # sets WORKER_ENABLED=true). Heavy work stays off the request path.
        worker_task = None
        if settings.worker_enabled and sessionmaker is not None:
            from app.worker import JobWorker

            worker = JobWorker(sessionmaker, settings)
            worker_task = asyncio.create_task(worker.run_forever())
        app.state.worker_task = worker_task
        yield
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if engine is not None:
            await engine.dispose()

    app = FastAPI(
        title="AutoShorts Studio API",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(overview_router, prefix="/api")
    app.include_router(system_router, prefix="/api")
    app.include_router(channels_router, prefix="/api")
    app.include_router(sources_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(llm_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")
    return app


app = create_app()
