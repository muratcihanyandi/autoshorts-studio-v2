"""Health endpoint tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_liveness(client_no_db: TestClient) -> None:
    response = client_no_db.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "autoshorts-backend"
    assert body["version"]


def test_readiness_without_database(client_no_db: TestClient) -> None:
    response = client_no_db.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "not_configured"


def test_readiness_with_sqlite(client_sqlite: TestClient) -> None:
    response = client_sqlite.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "reachable"


def test_readiness_reports_error_class_without_details() -> None:
    # Port 1 on loopback is closed; the connection is refused immediately.
    app = create_app(Settings(database_url="postgresql+asyncpg://u:p@127.0.0.1:1/none"))  # secret-scan-ok
    with TestClient(app) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["database"] == "unreachable"
    assert body.get("error")
    # No connection details (host, credentials) may leak into the response.
    assert "127.0.0.1" not in response.text
    assert "password" not in response.text.lower()
