"""Async SQLAlchemy engine and session factory.

The engine is created once per application process from the configured
DATABASE_URL. With no DATABASE_URL configured the application still starts
(health reports "not_configured") so local development works without a
database. SQLite connections (tests) get foreign key enforcement so they
fail like PostgreSQL does, not silently.
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_and_sessionmaker(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _enforce_foreign_keys(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, sessionmaker
