"""OAuth handshake tests (Milestone 3, slice 2).

Google's endpoints are mocked with httpx.MockTransport via the service's
_default_http_client indirection; the app under test runs on file-backed
SQLite so token storage and audit events can be verified through a
synchronous engine after the async app commits.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.security import TokenCipher


def mock_google_handler(request: httpx.Request) -> httpx.Response:
    body = request.read().decode()
    url = str(request.url)

    if url.startswith("https://oauth2.googleapis.com"):
        if "grant_type=refresh_token" in body:
            return httpx.Response(
                200,
                json={
                    "access_token": "ya29.refreshed",  # secret-scan-ok (sentetik)
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        if "code=mock-code-b" in body:
            access_token = "ya29.token-b"  # secret-scan-ok (sentetik)
        else:
            access_token = "ya29.token-a"  # secret-scan-ok (sentetik)
        return httpx.Response(
            200,
            json={
                "access_token": access_token,  # secret-scan-ok (sentetik test fikstürü)
                "refresh_token": "1//mock-refresh",  # secret-scan-ok (sentetik test fikstürü)
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/youtube.upload",
                "token_type": "Bearer",
            },
        )

    if "youtube/v3/channels" in url:
        auth = request.headers.get("Authorization", "")
        if auth.endswith("ya29.token-b"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UCmock456",
                            "snippet": {"title": "İkinci Kanal", "customUrl": "@ikinci"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UCmock123",
                        "snippet": {"title": "Birinci Kanal", "customUrl": "@birinci"},
                    }
                ]
            },
        )

    return httpx.Response(404, json={"error": "beklenmeyen adres"})


@pytest.fixture
def mock_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.oauth_service._default_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(mock_google_handler)),
    )


def _sync_engine(client: TestClient) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{client.app.state.test_db_path}")


def _start_and_extract_state(client: TestClient, channel_id: int) -> str:
    response = client.post(f"/api/channels/{channel_id}/oauth/start")
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    return parse_qs(urlparse(url).query)["state"][0]


def _connect(client: TestClient, channel_id: int, code: str = "mock-code") -> dict:
    state = _start_and_extract_state(client, channel_id)
    response = client.get(
        f"/api/channels/{channel_id}/oauth/callback",
        params={"code": code, "state": state},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_start_requires_configuration(client_db: TestClient) -> None:
    created = client_db.post("/api/channels", json={"name": "Kanal"})
    response = client_db.post(f"/api/channels/{created.json()['id']}/oauth/start")
    assert response.status_code == 503


def test_start_returns_authorization_url(client_oauth: TestClient) -> None:
    channel_id = client_oauth.post("/api/channels", json={"name": "Kanal A"}).json()["id"]
    response = client_oauth.post(f"/api/channels/{channel_id}/oauth/start")
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert query["client_id"] == ["test-client-id"]
    assert query["response_type"] == ["code"]
    assert query["access_type"] == ["offline"]
    assert query["redirect_uri"] == [
        f"http://lan-test:8000/api/channels/{channel_id}/oauth/callback"
    ]
    assert "youtube.upload" in query["scope"][0]
    assert len(query["state"][0]) >= 32


def test_start_on_missing_channel(client_oauth: TestClient) -> None:
    assert client_oauth.post("/api/channels/999/oauth/start").status_code == 404


def test_callback_connects_channel_and_stores_encrypted_tokens(
    client_oauth: TestClient, mock_google: None
) -> None:
    channel_id = client_oauth.post(
        "/api/channels", json={"name": "Benim Kanalım"}
    ).json()["id"]

    body = _connect(client_oauth, channel_id)
    assert body["status"] == "connected"
    assert body["youtube_channel_id"] == "UCmock123"
    # Kullanıcının verdiği isim korunur; handle YouTube'dan dolmaz.
    assert body["name"] == "Benim Kanalım"
    assert body["handle"] == "@birinci"
    assert body["last_connected_at"] is not None

    # Token düz metin olarak saklanmamalı; şifreli halden çözüle bilmeli.
    engine = _sync_engine(client_oauth)
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT access_token_enc, refresh_token_enc FROM oauth_credentials"
                " WHERE channel_id = :c"
            ),
            {"c": channel_id},
        ).fetchone()
        events = [
            r[0]
            for r in conn.execute(
                sa.text(
                    "SELECT event_type FROM audit_events ORDER BY id"
                )
            ).fetchall()
        ]
    engine.dispose()

    cipher = TokenCipher(client_oauth.app.state.test_token_key)
    assert "ya29.token-a" not in row[0]
    assert cipher.decrypt(row[0]) == "ya29.token-a"
    assert cipher.decrypt(row[1]) == "1//mock-refresh"
    assert "channel.created" in events
    assert "oauth.started" in events
    assert "oauth.connected" in events


def test_callback_rejects_wrong_state(client_oauth: TestClient, mock_google: None) -> None:
    channel_id = client_oauth.post("/api/channels", json={"name": "K"}).json()["id"]
    client_oauth.post(f"/api/channels/{channel_id}/oauth/start")

    response = client_oauth.get(
        f"/api/channels/{channel_id}/oauth/callback",
        params={"code": "mock-code", "state": "sahte-state"},
    )
    assert response.status_code == 400
    assert "Geçersiz" in response.json()["detail"]


def test_callback_state_is_single_use(client_oauth: TestClient, mock_google: None) -> None:
    channel_id = client_oauth.post("/api/channels", json={"name": "K"}).json()["id"]
    state = _start_and_extract_state(client_oauth, channel_id)

    first = client_oauth.get(
        f"/api/channels/{channel_id}/oauth/callback",
        params={"code": "mock-code", "state": state},
    )
    assert first.status_code == 200

    replay = client_oauth.get(
        f"/api/channels/{channel_id}/oauth/callback",
        params={"code": "mock-code", "state": state},
    )
    assert replay.status_code == 400
    assert "kullanılmış" in replay.json()["detail"]


def test_callback_rejects_expired_state(client_oauth: TestClient) -> None:
    channel_id = client_oauth.post("/api/channels", json={"name": "K"}).json()["id"]
    engine = _sync_engine(client_oauth)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO oauth_states (state, channel_id, created_at, expires_at)"
                " VALUES ('eski-state', :c, :created, :expires)"
            ),
            {
                "c": channel_id,
                "created": datetime.now(UTC) - timedelta(minutes=11),
                "expires": datetime.now(UTC) - timedelta(minutes=1),
            },
        )
    engine.dispose()

    response = client_oauth.get(
        f"/api/channels/{channel_id}/oauth/callback",
        params={"code": "mock-code", "state": "eski-state"},
    )
    assert response.status_code == 400
    assert "süresi dolmuş" in response.json()["detail"]


def test_callback_state_bound_to_channel(client_oauth: TestClient, mock_google: None) -> None:
    channel_a = client_oauth.post("/api/channels", json={"name": "A"}).json()["id"]
    channel_b = client_oauth.post("/api/channels", json={"name": "B"}).json()["id"]
    state = _start_and_extract_state(client_oauth, channel_a)

    response = client_oauth.get(
        f"/api/channels/{channel_b}/oauth/callback",
        params={"code": "mock-code", "state": state},
    )
    assert response.status_code == 400


def test_callback_reports_google_denial(client_oauth: TestClient) -> None:
    channel_id = client_oauth.post("/api/channels", json={"name": "K"}).json()["id"]
    _start_and_extract_state(client_oauth, channel_id)

    response = client_oauth.get(
        f"/api/channels/{channel_id}/oauth/callback",
        params={"error": "access_denied"},
    )
    assert response.status_code == 400
    assert "reddedildi" in response.json()["detail"]

    engine = _sync_engine(client_oauth)
    with engine.connect() as conn:
        events = [
            r[0]
            for r in conn.execute(
                sa.text("SELECT event_type FROM audit_events ORDER BY id")
            ).fetchall()
        ]
    engine.dispose()
    assert "oauth.failed" in events


def test_duplicate_youtube_channel_rejected(
    client_oauth: TestClient, mock_google: None
) -> None:
    channel_a = client_oauth.post("/api/channels", json={"name": "A"}).json()["id"]
    channel_b = client_oauth.post("/api/channels", json={"name": "B"}).json()["id"]
    _connect(client_oauth, channel_a, code="mock-code")

    state = _start_and_extract_state(client_oauth, channel_b)
    response = client_oauth.get(
        f"/api/channels/{channel_b}/oauth/callback",
        params={"code": "mock-code", "state": state},
    )
    assert response.status_code == 400
    assert "başka bir stüdyo kanalına bağlı" in response.json()["detail"]


def test_disconnected_channel_does_not_disable_others(
    client_oauth: TestClient, mock_google: None
) -> None:
    channel_a = client_oauth.post("/api/channels", json={"name": "A"}).json()["id"]
    channel_b = client_oauth.post("/api/channels", json={"name": "B"}).json()["id"]
    _connect(client_oauth, channel_a, code="mock-code")
    _connect(client_oauth, channel_b, code="mock-code-b")

    overview = client_oauth.get("/api/overview").json()
    assert overview["channels"] == {"connected": 2, "total": 2}
    assert overview["phase"] == "running"

    disconnect = client_oauth.post(f"/api/channels/{channel_a}/disconnect")
    assert disconnect.status_code == 200

    overview = client_oauth.get("/api/overview").json()
    assert overview["channels"] == {"connected": 1, "total": 2}
    assert overview["phase"] == "running"
    assert client_oauth.get(f"/api/channels/{channel_b}").json()["status"] == "connected"

    # Koparılan kanalın token'ı silinmiş olmalı.
    engine = _sync_engine(client_oauth)
    with engine.connect() as conn:
        count = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM oauth_credentials WHERE channel_id = :c"
            ),
            {"c": channel_a},
        ).scalar_one()
    engine.dispose()
    assert count == 0


def test_refresh_skipped_when_token_fresh(
    client_oauth: TestClient, mock_google: None
) -> None:
    channel_id = client_oauth.post("/api/channels", json={"name": "K"}).json()["id"]
    _connect(client_oauth, channel_id, code="mock-code")

    response = client_oauth.post(f"/api/channels/{channel_id}/oauth/refresh")
    assert response.status_code == 200
    assert response.json() == {"channel_id": channel_id, "refreshed": False}


def test_refresh_rotates_expired_token(client_oauth: TestClient, mock_google: None) -> None:
    channel_id = client_oauth.post("/api/channels", json={"name": "K"}).json()["id"]
    _connect(client_oauth, channel_id, code="mock-code")

    engine = _sync_engine(client_oauth)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE oauth_credentials SET token_expires_at = :p"
                " WHERE channel_id = :c"
            ),
            {"p": datetime.now(UTC) - timedelta(minutes=5), "c": channel_id},
        )
    engine.dispose()

    response = client_oauth.post(f"/api/channels/{channel_id}/oauth/refresh")
    assert response.status_code == 200
    assert response.json() == {"channel_id": channel_id, "refreshed": True}

    engine = _sync_engine(client_oauth)
    with engine.connect() as conn:
        encrypted = conn.execute(
            sa.text(
                "SELECT access_token_enc FROM oauth_credentials WHERE channel_id = :c"
            ),
            {"c": channel_id},
        ).scalar_one()
        events = [
            r[0]
            for r in conn.execute(
                sa.text("SELECT event_type FROM audit_events ORDER BY id")
            ).fetchall()
        ]
    engine.dispose()

    cipher = TokenCipher(client_oauth.app.state.test_token_key)
    assert cipher.decrypt(encrypted) == "ya29.refreshed"
    assert "oauth.token_refreshed" in events


def test_callback_redirects_to_frontend(client_oauth_redirect: TestClient, mock_google: None) -> None:
    channel_id = client_oauth_redirect.post(
        "/api/channels", json={"name": "K"}
    ).json()["id"]
    state = _start_and_extract_state(client_oauth_redirect, channel_id)

    success = client_oauth_redirect.get(
        f"/api/channels/{channel_id}/oauth/callback",
        params={"code": "mock-code", "state": state},
        follow_redirects=False,
    )
    assert success.status_code == 307
    assert success.headers["location"] == "http://ui-test:1478/kanallar?oauth=basarili"

    failure = client_oauth_redirect.get(
        f"/api/channels/{channel_id}/oauth/callback",
        params={"code": "mock-code", "state": "sahte"},
        follow_redirects=False,
    )
    assert failure.status_code == 307
    assert failure.headers["location"] == "http://ui-test:1478/kanallar?oauth=hata"
