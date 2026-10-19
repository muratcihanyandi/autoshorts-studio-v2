"""Channel management API tests (Milestone 3, slice 1)."""
from __future__ import annotations

from fastapi.testclient import TestClient

SECRET_FIELDS = (
    "access_token",
    "refresh_token",
    "access_token_enc",
    "refresh_token_enc",
    "token",
    "secret",
    "password",
)


def test_channels_requires_database(client_no_db: TestClient) -> None:
    response = client_no_db.get("/api/channels")
    assert response.status_code == 503


def test_channel_response_carries_no_secret_fields(client_db: TestClient) -> None:
    created = client_db.post("/api/channels", json={"name": "Gizli Kanal"})
    assert created.status_code == 201
    for field in SECRET_FIELDS:
        assert field not in created.json()

    listing = client_db.get("/api/channels")
    for channel in listing.json()["channels"]:
        for field in SECRET_FIELDS:
            assert field not in channel

    detail = client_db.get(f"/api/channels/{created.json()['id']}")
    for field in SECRET_FIELDS:
        assert field not in detail.json()


def test_create_list_get_update_delete_channel(client_db: TestClient) -> None:
    created = client_db.post(
        "/api/channels",
        json={"name": "Ana Kanal", "ribbon_color": "#C93A2E", "handle": "@ana"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Ana Kanal"
    assert body["status"] == "pending"
    assert body["ribbon_color"] == "#c93a2e"
    assert body["youtube_channel_id"] is None
    channel_id = body["id"]

    listing = client_db.get("/api/channels").json()
    assert listing["total"] == 1
    assert listing["connected"] == 0
    assert listing["channels"][0]["id"] == channel_id

    detail = client_db.get(f"/api/channels/{channel_id}")
    assert detail.status_code == 200
    assert detail.json()["handle"] == "@ana"

    patched = client_db.patch(
        f"/api/channels/{channel_id}", json={"name": "Yeni Ad", "handle": None}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Yeni Ad"

    deleted = client_db.delete(f"/api/channels/{channel_id}")
    assert deleted.status_code == 204
    assert client_db.get(f"/api/channels/{channel_id}").status_code == 404


def test_invalid_ribbon_color_rejected(client_db: TestClient) -> None:
    response = client_db.post(
        "/api/channels", json={"name": "Kötü Renk", "ribbon_color": "kirmizi"}
    )
    assert response.status_code == 422


def test_empty_name_rejected(client_db: TestClient) -> None:
    response = client_db.post("/api/channels", json={"name": ""})
    assert response.status_code == 422


def test_multiple_channels_are_independent(client_db: TestClient) -> None:
    ids = []
    for i in range(3):
        response = client_db.post("/api/channels", json={"name": f"Kanal {i}"})
        assert response.status_code == 201
        ids.append(response.json()["id"])

    # Bir kanalı silmek diğerlerini etkilemez.
    assert client_db.delete(f"/api/channels/{ids[0]}").status_code == 204
    assert client_db.get(f"/api/channels/{ids[1]}").status_code == 200
    assert client_db.get(f"/api/channels/{ids[2]}").status_code == 200
    listing = client_db.get("/api/channels").json()
    assert listing["total"] == 2


def test_disconnect_channel(client_db: TestClient) -> None:
    created = client_db.post("/api/channels", json={"name": "Koparılacak"})
    channel_id = created.json()["id"]

    response = client_db.post(f"/api/channels/{channel_id}/disconnect")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "disconnected"
    assert body["last_disconnected_at"] is not None


def test_missing_channel_returns_404(client_db: TestClient) -> None:
    assert client_db.get("/api/channels/999").status_code == 404
    assert client_db.patch("/api/channels/999", json={"name": "x"}).status_code == 404
    assert client_db.delete("/api/channels/999").status_code == 404
    assert client_db.post("/api/channels/999/disconnect").status_code == 404


def test_overview_counts_channels(client_db: TestClient) -> None:
    client_db.post("/api/channels", json={"name": "Kanal A"})
    client_db.post("/api/channels", json={"name": "Kanal B"})

    body = client_db.get("/api/overview").json()
    assert body["database"] == "reachable"
    # Bağlı (connected) kanal yok; ikisi de beklemede.
    assert body["channels"] == {"connected": 0, "total": 2}
    assert body["phase"] == "awaiting_channels"
