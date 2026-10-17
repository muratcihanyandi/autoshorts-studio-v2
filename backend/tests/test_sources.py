"""Source channel registration + rights records tests (Milestone 4, slice 1)."""
from __future__ import annotations

import sqlalchemy as sa
from fastapi.testclient import TestClient


def _channel(client: TestClient, name: str = "Kanal") -> int:
    return client.post("/api/channels", json={"name": name}).json()["id"]


def _add_source(client: TestClient, channel_id: int, yt_id: str = "UCkaynak1"):
    return client.post(
        f"/api/channels/{channel_id}/sources",
        json={"youtube_channel_id": yt_id, "title": "Kaynak Kanal"},
    )


def _audit_types(client: TestClient) -> list[str]:
    engine = sa.create_engine(f"sqlite:///{client.app.state.test_db_path}")
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT event_type FROM audit_events ORDER BY id")
        ).fetchall()
    engine.dispose()
    return [r[0] for r in rows]


def test_sources_require_database(client_no_db: TestClient) -> None:
    response = client_no_db.get("/api/channels/1/sources")
    assert response.status_code == 503


def test_add_list_authorize_reject_delete(client_db: TestClient) -> None:
    channel_id = _channel(client_db)

    added = _add_source(client_db, channel_id)
    assert added.status_code == 201
    body = added.json()
    assert body["permission_status"] == "pending"
    assert body["authorized_at"] is None
    assert body["youtube_channel_id"] == "UCkaynak1"
    source_id = body["id"]

    listing = client_db.get(f"/api/channels/{channel_id}/sources").json()
    assert listing == {"sources": [body], "total": 1, "authorized": 0}

    authorized = client_db.patch(
        f"/api/sources/{source_id}",
        json={"permission_status": "authorized"},
    )
    assert authorized.status_code == 200
    auth_body = authorized.json()
    assert auth_body["permission_status"] == "authorized"
    assert auth_body["authorized_at"] is not None

    listing = client_db.get(f"/api/channels/{channel_id}/sources").json()
    assert listing["authorized"] == 1

    rejected = client_db.patch(
        f"/api/sources/{source_id}",
        json={"permission_status": "rejected"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["permission_status"] == "rejected"
    assert rejected.json()["authorized_at"] is None

    deleted = client_db.delete(f"/api/sources/{source_id}")
    assert deleted.status_code == 204
    assert client_db.patch(
        f"/api/sources/{source_id}", json={"permission_status": "authorized"}
    ).status_code == 404


def test_duplicate_source_rejected(client_db: TestClient) -> None:
    channel_id = _channel(client_db)
    assert _add_source(client_db, channel_id, "UCtek").status_code == 201
    duplicate = _add_source(client_db, channel_id, "UCtek")
    assert duplicate.status_code == 409

    # Aynı kaynak farklı stüdyo kanalına kayıt edilebilir.
    other_id = _channel(client_db, "İkinci")
    assert _add_source(client_db, other_id, "UCtek").status_code == 201


def test_invalid_permission_value_rejected(client_db: TestClient) -> None:
    channel_id = _channel(client_db)
    source_id = _add_source(client_db, channel_id).json()["id"]
    response = client_db.patch(
        f"/api/sources/{source_id}", json={"permission_status": "belki"}
    )
    assert response.status_code == 422


def test_missing_channel_returns_404(client_db: TestClient) -> None:
    assert _add_source(client_db, 999).status_code == 404
    assert client_db.get("/api/channels/999/sources").status_code == 404


def test_rights_records_audited_once(client_db: TestClient) -> None:
    channel_id = _channel(client_db)
    source_id = _add_source(client_db, channel_id).json()["id"]

    client_db.patch(
        f"/api/sources/{source_id}", json={"permission_status": "authorized"}
    )
    # Aynı duruma ikinci geçiş yeni hak kaydı yazmaz.
    client_db.patch(
        f"/api/sources/{source_id}", json={"permission_status": "authorized"}
    )
    client_db.patch(
        f"/api/sources/{source_id}", json={"permission_status": "rejected"}
    )
    client_db.delete(f"/api/sources/{source_id}")

    events = _audit_types(client_db)
    assert events.count("source.authorized") == 1
    assert events.count("source.rejected") == 1
    assert "source.added" in events
    assert "source.removed" in events


def test_title_update(client_db: TestClient) -> None:
    channel_id = _channel(client_db)
    source_id = _add_source(client_db, channel_id).json()["id"]
    response = client_db.patch(
        f"/api/sources/{source_id}", json={"title": "Yeni Başlık"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Yeni Başlık"
    assert response.json()["permission_status"] == "pending"
