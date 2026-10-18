"""Source channel registration + rights records tests (Milestone 4, slice 1).

M13 extensions: platform/character/reaction/trim fields, manual VOD
import (twitch/kick) and the discover skip note for non-youtube
platforms.
"""
from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from fastapi.testclient import TestClient

from tests.conftest import _make_app, mock_youtube  # noqa: F401 - fixture


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


def _job_payloads(client: TestClient) -> list[tuple[str, dict]]:
    engine = sa.create_engine(f"sqlite:///{client.app.state.test_db_path}")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("SELECT job_type, payload FROM jobs ORDER BY id")
            ).fetchall()
    finally:
        engine.dispose()
    return [(r[0], json.loads(r[1])) for r in rows]


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


# --- M13: platform / karakter / reaksiyon / budama ---


def test_source_defaults_platform_character_reaction_trim(
    client_db: TestClient,
) -> None:
    channel_id = _channel(client_db)
    body = _add_source(client_db, channel_id).json()
    assert body["platform"] == "youtube"
    assert body["character_id"] is None
    assert body["character_name"] is None
    assert body["reaction_source"] is False
    assert body["trim_start_seconds"] == 0.0
    assert body["trim_end_seconds"] == 0.0


def test_source_platform_character_reaction_trim_roundtrip(
    client_db: TestClient,
) -> None:
    channel_id = _channel(client_db)
    character_id = client_db.post(
        "/api/characters", json={"name": "Yayıncı Bir"}
    ).json()["id"]

    created = client_db.post(
        f"/api/channels/{channel_id}/sources",
        json={
            "youtube_channel_id": "https://www.twitch.tv/yayinci-bir",
            "title": "Twitch Kaynak",
            "platform": "twitch",
            "character_id": character_id,
            "reaction_source": True,
            "trim_start_seconds": 1.5,
            "trim_end_seconds": 2.5,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["platform"] == "twitch"
    assert body["character_id"] == character_id
    assert body["character_name"] == "Yayıncı Bir"
    assert body["reaction_source"] is True
    assert body["trim_start_seconds"] == 1.5
    assert body["trim_end_seconds"] == 2.5

    listing = client_db.get(f"/api/channels/{channel_id}/sources").json()
    assert listing["sources"] == [body]

    # PATCH: reaksiyon kapanir, budama degisir, karakter bagı çözülür.
    unbound = client_db.patch(
        f"/api/sources/{body['id']}",
        json={
            "reaction_source": False,
            "trim_end_seconds": 10.0,
            "character_id": None,
        },
    )
    assert unbound.status_code == 200
    unbound_body = unbound.json()
    assert unbound_body["reaction_source"] is False
    assert unbound_body["trim_end_seconds"] == 10.0
    assert unbound_body["trim_start_seconds"] == 1.5
    assert unbound_body["character_id"] is None
    assert unbound_body["character_name"] is None

    # PATCH ile baska karakter baglanabilir.
    other_id = client_db.post(
        "/api/characters", json={"name": "İkinci Kişi"}
    ).json()["id"]
    rebound = client_db.patch(
        f"/api/sources/{body['id']}", json={"character_id": other_id}
    )
    assert rebound.status_code == 200
    assert rebound.json()["character_id"] == other_id
    assert rebound.json()["character_name"] == "İkinci Kişi"

    # Platform da PATCH ile degisebilir.
    switched = client_db.patch(
        f"/api/sources/{body['id']}", json={"platform": "kick"}
    )
    assert switched.status_code == 200
    assert switched.json()["platform"] == "kick"


def test_source_unknown_character_404(client_db: TestClient) -> None:
    channel_id = _channel(client_db)
    created = client_db.post(
        f"/api/channels/{channel_id}/sources",
        json={
            "youtube_channel_id": "UCbilinmeyen",
            "title": "Kaynak",
            "character_id": 999,
        },
    )
    assert created.status_code == 404

    source_id = _add_source(client_db, channel_id).json()["id"]
    patched = client_db.patch(
        f"/api/sources/{source_id}", json={"character_id": 999}
    )
    assert patched.status_code == 404


def test_source_invalid_platform_and_negative_trim_rejected(
    client_db: TestClient,
) -> None:
    channel_id = _channel(client_db)
    assert (
        client_db.post(
            f"/api/channels/{channel_id}/sources",
            json={
                "youtube_channel_id": "UC1",
                "title": "Kaynak",
                "platform": "dailymotion",
            },
        ).status_code
        == 422
    )
    assert (
        client_db.post(
            f"/api/channels/{channel_id}/sources",
            json={
                "youtube_channel_id": "UC1",
                "title": "Kaynak",
                "trim_start_seconds": -1,
            },
        ).status_code
        == 422
    )
    source_id = _add_source(client_db, channel_id).json()["id"]
    assert (
        client_db.patch(
            f"/api/sources/{source_id}", json={"platform": "vimeo"}
        ).status_code
        == 422
    )
    assert (
        client_db.patch(
            f"/api/sources/{source_id}", json={"trim_end_seconds": -0.5}
        ).status_code
        == 422
    )


# --- M13: manuel VOD ice aktarimi (twitch/kick) ---


def test_manual_vod_creates_planned_video_and_media_process_job(
    client_db: TestClient,
) -> None:
    channel_id = _channel(client_db)
    source_id = _add_source(client_db, channel_id).json()["id"]
    url = "https://www.twitch.tv/videos/123456789"

    response = client_db.post(
        f"/api/sources/{source_id}/videos",
        json={"url": url, "title": "VOD Başlığı"},
    )
    assert response.status_code == 201, response.text
    video = response.json()
    assert video["source_channel_id"] == source_id
    assert video["youtube_video_id"] == "123456789"
    assert video["title"] == "VOD Başlığı"
    assert video["status"] == "planned"
    assert video["published_at"] is None

    payloads = _job_payloads(client_db)
    assert ("media_process", {"source_video_id": video["id"], "import_path": url}) in (
        payloads
    )

    # Aynı URL ikinci kez 409 verir; yeni iş de kuyruklanmaz.
    duplicate = client_db.post(
        f"/api/sources/{source_id}/videos",
        json={"url": url, "title": "VOD Başlığı"},
    )
    assert duplicate.status_code == 409
    assert len(_job_payloads(client_db)) == 1

    # Farklı URL aynı kaynağa eklenebilir.
    other = client_db.post(
        f"/api/sources/{source_id}/videos",
        json={"url": "https://www.twitch.tv/videos/987654321", "title": "İkinci"},
    )
    assert other.status_code == 201


def test_manual_vod_url_without_segment_uses_sha_key(
    client_db: TestClient,
) -> None:
    channel_id = _channel(client_db)
    source_id = _add_source(client_db, channel_id).json()["id"]
    url = "https://ornek-site.test/"
    expected = hashlib.sha256(url.encode()).hexdigest()[:16]

    response = client_db.post(
        f"/api/sources/{source_id}/videos", json={"url": url, "title": "Başlıksız"}
    )
    assert response.status_code == 201
    assert response.json()["youtube_video_id"] == expected


def test_manual_vod_missing_source_404(client_db: TestClient) -> None:
    response = client_db.post(
        "/api/sources/999/videos",
        json={"url": "https://www.twitch.tv/videos/1", "title": "Başlık"},
    )
    assert response.status_code == 404


# --- M13: kesif yalnizca youtube kaynaklarini yoklar ---


def test_discover_skips_non_youtube_sources(tmp_path, mock_youtube) -> None:
    app = _make_app(tmp_path, youtube_api_key="test-yt-key")
    with TestClient(app) as client:
        channel_id = _channel(client, "Keşif Kanalı")
        youtube_id = client.post(
            f"/api/channels/{channel_id}/sources",
            json={"youtube_channel_id": "UCkaynak1", "title": "YT Kaynak"},
        ).json()["id"]
        twitch_id = client.post(
            f"/api/channels/{channel_id}/sources",
            json={
                "youtube_channel_id": "https://www.twitch.tv/yayinci",
                "title": "Twitch Kaynak",
                "platform": "twitch",
            },
        ).json()["id"]
        for source_id in (youtube_id, twitch_id):
            client.patch(
                f"/api/sources/{source_id}",
                json={"permission_status": "authorized"},
            )

        response = client.post(f"/api/channels/{channel_id}/discover")
        assert response.status_code == 200
        body = response.json()
        assert body["sources_checked"] == 1
        assert body["skipped_platforms"] == ["twitch"]
        assert body["new_videos"] == 2
