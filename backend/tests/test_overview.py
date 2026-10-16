"""Overview endpoint tests."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_overview_without_database(client_no_db: TestClient) -> None:
    response = client_no_db.get("/api/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "setup"
    assert body["database"] == "not_configured"
    assert body["channels"]["connected"] == 0
    assert body["today_published"] == 0
    assert body["version"]
    assert body["uptime_seconds"] is not None


def test_overview_with_database_reports_reachable_and_phase(
    client_sqlite: TestClient,
) -> None:
    response = client_sqlite.get("/api/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "reachable"
    # No channels exist yet (Milestone 3), so the studio awaits channels.
    assert body["phase"] == "awaiting_channels"
    assert body["jobs"] == {"active": 0, "queued": 0}
    assert body["stock"] == {"clips": 0}
