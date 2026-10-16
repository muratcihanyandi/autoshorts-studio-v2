"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import __version__
from app.api.routes.health import router as health_router
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
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(
        title="Autonomous Creator Studio API",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(health_router, prefix="/api")
    return app


app = create_app()
