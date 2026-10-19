"""System endpoint tests."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_system_returns_real_measurements(client_no_db: TestClient) -> None:
    response = client_no_db.get("/api/system")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "cpu_percent",
        "memory_percent",
        "memory_total_mb",
        "disk_percent",
        "disk_total_gb",
        "temperature_c",
    }
    assert 0.0 <= body["cpu_percent"] <= 100.0
    assert 0.0 <= body["memory_percent"] <= 100.0
    assert body["memory_total_mb"] > 0
    assert body["disk_total_gb"] > 0
    # Temperature is None on hosts without sensors (dev machine).
    assert body["temperature_c"] is None or body["temperature_c"] > 0
