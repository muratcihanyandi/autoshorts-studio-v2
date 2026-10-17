"""Source discovery tests (Milestone 4, slice 2).

YouTube Data API is mocked via httpx.MockTransport on the client's
_default_http_client indirection; the mock counts calls so caching and
quota behavior are observable.
"""
from __future__ import annotations

import json

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

CALLS = {"channels": 0, "playlist_items": 0}


def youtube_mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/channels" in url:
        CALLS["channels"] += 1
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UCkaynak1",
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": "UUkaynak1"}
                        },
                    }
                ]
            },
        )
    if "/playlistItems" in url:
        CALLS["playlist_items"] += 1
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "snippet": {
                            "title": "Kaynak Video 1",
                            "publishedAt": "2026-10-15T10:00:00Z",
                            "resourceId": {"videoId": "vid-kaynak-1"},
                        }
                    },
                    {
                        "snippet": {
                            "title": "Kaynak Video 2",
                            "publishedAt": "2026-10-16T11:30:00Z",
                            "resourceId": {"videoId": "vid-kaynak-2"},
                        }
                    },
                ]
            },
        )
    return httpx.Response(404, json={"error": "beklenmeyen adres"})


@pytest.fixture
def mock_youtube(monkeypatch: pytest.MonkeyPatch) -> None:
    CALLS["channels"] = 0
    CALLS["playlist_items"] = 0
    from app.services import youtube_client

    youtube_client.clear_cache()
    monkeypatch.setattr(
        "app.services.youtube_client._default_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(youtube_mock_handler)),
    )


def _setup_authorized_source(client: TestClient) -> int:
    channel_id = client.post("/api/channels", json={"name": "Kanal"}).json()["id"]
    source_id = client.post(
        f"/api/channels/{channel_id}/sources",
        json={"youtube_channel_id": "UCkaynak1", "title": "Kaynak"},
    ).json()["id"]
    response = client.patch(
        f"/api/sources/{source_id}", json={"permission_status": "authorized"}
    )
    assert response.status_code == 200
    return channel_id


def test_discover_requires_api_key(client_db: TestClient) -> None:
    channel_id = client_db.post("/api/channels", json={"name": "K"}).json()["id"]
    response = client_db.post(f"/api/channels/{channel_id}/discover")
    assert response.status_code == 503
    assert "YOUTUBE_API_KEY" in response.json()["detail"]


def test_discover_records_new_videos_once(
    client_youtube: TestClient, mock_youtube: None
) -> None:
    channel_id = _setup_authorized_source(client_youtube)

    first = client_youtube.post(f"/api/channels/{channel_id}/discover")
    assert first.status_code == 200
    assert first.json() == {
        "sources_checked": 1,
        "new_videos": 2,
        "quota_blocked": False,
    }

    videos = client_youtube.get(f"/api/channels/{channel_id}/videos").json()
    assert videos["total"] == 2
    assert {v["youtube_video_id"] for v in videos["videos"]} == {
        "vid-kaynak-1",
        "vid-kaynak-2",
    }
    assert videos["videos"][0]["status"] == "discovered"
    assert videos["videos"][0]["published_at"] is not None

    # İkinci keşif: aynı videolar tekrar kayıt olmaz ve TTL önbelleği
    # sayesinde YouTube'a yeni istek gitmez.
    second = client_youtube.post(f"/api/channels/{channel_id}/discover")
    assert second.status_code == 200
    assert second.json()["new_videos"] == 0
    assert CALLS["channels"] == 1
    assert CALLS["playlist_items"] == 1

    videos = client_youtube.get(f"/api/channels/{channel_id}/videos").json()
    assert videos["total"] == 2


def test_unauthorized_source_not_polled(
    client_youtube: TestClient, mock_youtube: None
) -> None:
    channel_id = client_youtube.post("/api/channels", json={"name": "K"}).json()["id"]
    client_youtube.post(
        f"/api/channels/{channel_id}/sources",
        json={"youtube_channel_id": "UCkaynak1", "title": "Kaynak"},
    )

    response = client_youtube.post(f"/api/channels/{channel_id}/discover")
    assert response.status_code == 200
    assert response.json() == {
        "sources_checked": 0,
        "new_videos": 0,
        "quota_blocked": False,
    }
    assert CALLS["channels"] == 0


def test_quota_limit_respected(
    client_youtube_tight_quota: TestClient, mock_youtube: None
) -> None:
    # İki yetkili kaynak, günlük kota 2 birim: ilk kaynak 1+1 harcar,
    # ikinci kaynağın channels çağrısı reddedilir.
    channel_id = _setup_authorized_source(client_youtube_tight_quota)
    second_source = client_youtube_tight_quota.post(
        f"/api/channels/{channel_id}/sources",
        json={"youtube_channel_id": "UCkaynak2", "title": "İkinci Kaynak"},
    ).json()["id"]
    client_youtube_tight_quota.patch(
        f"/api/sources/{second_source}", json={"permission_status": "authorized"}
    )

    response = client_youtube_tight_quota.post(
        f"/api/channels/{channel_id}/discover"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sources_checked"] == 1
    assert body["new_videos"] == 2
    assert body["quota_blocked"] is True

    # Kota defteri gerçekten yazılmış olmalı.
    engine = sa.create_engine(
        f"sqlite:///{client_youtube_tight_quota.app.state.test_db_path}"
    )
    with engine.connect() as conn:
        units = conn.execute(
            sa.text("SELECT units_used FROM quota_usage")
        ).scalar_one()
        events = [
            r[0]
            for r in conn.execute(
                sa.text("SELECT event_type FROM audit_events ORDER BY id")
            ).fetchall()
        ]
    engine.dispose()
    assert units == 2
    assert "discovery.run" in events


def test_discovery_run_audited(client_youtube: TestClient, mock_youtube: None) -> None:
    channel_id = _setup_authorized_source(client_youtube)
    client_youtube.post(f"/api/channels/{channel_id}/discover")

    engine = sa.create_engine(f"sqlite:///{client_youtube.app.state.test_db_path}")
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT detail FROM audit_events WHERE event_type = 'discovery.run'"
            )
        ).fetchone()
    engine.dispose()
    assert row is not None
    detail = json.loads(row[0])
    assert detail["new_videos"] == 2
