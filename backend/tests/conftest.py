"""Shared test fixtures.

Unit tests never touch a real PostgreSQL: readiness is exercised against
SQLite in-memory, and failure paths against a closed local port.
"""
from __future__ import annotations

import pytest
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
