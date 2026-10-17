"""Shared test fixtures.

Unit tests never touch a real PostgreSQL: readiness is exercised against
SQLite in-memory, and failure paths against a closed local port. Channel
API tests run on a file-backed SQLite whose schema is created from the
models with a synchronous engine before the async app opens it.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client_no_db() -> TestClient:
    app = create_app(Settings(database_url=""))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_sqlite() -> TestClient:
    app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_db(tmp_path) -> TestClient:
    from app.models import Base

    db_file = tmp_path / "test.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    app = create_app(Settings(database_url=f"sqlite+aiosqlite:///{db_file}"))
    with TestClient(app) as client:
        yield client
