"""Site-managed settings: masked GET, patch PUT, effective resolution.

Secrets must never appear in any API response (checked against the raw
response text), the audit trail records field names only, and services
(OAuth, discovery) must honour database-configured credentials without a
restart.
"""
from __future__ import annotations

import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from tests.conftest import _make_app, mock_youtube  # noqa: F401 - fixture


def _make_settings_app(tmp_path, **overrides) -> TestClient:
    app = _make_app(tmp_path, **overrides)
    client = TestClient(app)
    client.__enter__()
    return client


def test_get_masks_secrets_from_environment(tmp_path):
    secret_key = "env-yt-api-key-1234"
    client = _make_settings_app(tmp_path, youtube_api_key=secret_key)
    try:
        response = client.get("/api/settings")
        assert response.status_code == 200
        body = response.json()
        # Gizli değer ham haliyle asla dönmemeli.
        assert secret_key not in response.text
        yt = body["youtube_api_key"]
        assert yt["configured"] is True
        assert yt["source"] == "environment"
        assert yt["hint"] == "1234"
        # Düz alanlar tam değerle döner.
        assert body["daily_quota_units"] == {"value": 10000, "source": "environment"}
        assert body["google_client_id"] == {"value": "", "source": "unset"}
    finally:
        client.__exit__(None, None, None)


def test_put_stores_override_and_get_reports_database_source(tmp_path):
    client = _make_settings_app(tmp_path)
    try:
        response = client.put(
            "/api/settings",
            json={"youtube_api_key": "db-yt-api-key-abcd", "daily_quota_units": 5000},
        )
        assert response.status_code == 200
        assert "db-yt-api-key-abcd" not in response.text

        body = client.get("/api/settings").json()
        assert body["youtube_api_key"] == {
            "configured": True,
            "source": "database",
            "hint": "abcd",
        }
        assert body["daily_quota_units"] == {"value": 5000, "source": "database"}
    finally:
        client.__exit__(None, None, None)


def test_put_empty_string_clears_override_back_to_environment(tmp_path):
    client = _make_settings_app(tmp_path, frontend_base_url="http://env-ui:1478")
    try:
        client.put("/api/settings", json={"frontend_base_url": "http://db-ui:1478"})
        assert (
            client.get("/api/settings").json()["frontend_base_url"]["source"]
            == "database"
        )

        client.put("/api/settings", json={"frontend_base_url": ""})
        body = client.get("/api/settings").json()
        assert body["frontend_base_url"] == {
            "value": "http://env-ui:1478",
            "source": "environment",
        }
    finally:
        client.__exit__(None, None, None)


def test_put_validates_urls_fernet_and_quota(tmp_path):
    client = _make_settings_app(tmp_path)
    try:
        assert (
            client.put(
                "/api/settings", json={"oauth_redirect_base": "not-a-url"}
            ).status_code
            == 400
        )
        assert (
            client.put(
                "/api/settings", json={"token_encryption_key": "bozuk-anahtar"}
            ).status_code
            == 400
        )
        assert (
            client.put(
                "/api/settings", json={"daily_quota_units": 0}
            ).status_code
            == 400
        )
        # Başarısız PUT'lar hiçbir şey yazmamalı.
        assert client.get("/api/settings").json()["oauth_redirect_base"]["source"] == "unset"
    finally:
        client.__exit__(None, None, None)


def test_put_valid_fernet_key_is_accepted(tmp_path):
    client = _make_settings_app(tmp_path)
    try:
        key = Fernet.generate_key().decode()
        response = client.put("/api/settings", json={"token_encryption_key": key})
        assert response.status_code == 200
        assert key not in response.text
        body = client.get("/api/settings").json()
        assert body["token_encryption_key"]["configured"] is True
        assert body["token_encryption_key"]["source"] == "database"
    finally:
        client.__exit__(None, None, None)


def test_empty_patch_changes_nothing(tmp_path):
    client = _make_settings_app(tmp_path)
    try:
        response = client.put("/api/settings", json={})
        assert response.status_code == 200
        assert client.get("/api/settings").json()["youtube_api_key"]["source"] == "unset"
    finally:
        client.__exit__(None, None, None)


def test_settings_without_database_returns_503(client_no_db):
    assert client_no_db.get("/api/settings").status_code == 503


def test_audit_records_field_names_but_not_values(tmp_path):
    client = _make_settings_app(tmp_path)
    try:
        client.put(
            "/api/settings",
            json={"youtube_api_key": "gizli-anahtar-degeri-9876"},
        )
        engine = sa.create_engine(f"sqlite:///{client.app.state.test_db_path}")
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT detail FROM audit_events "
                    "WHERE event_type = 'settings.update'"
                )
            ).one_or_none()
        engine.dispose()
        assert row is not None
        import json

        detail = json.loads(row[0])
        assert detail["fields"] == ["youtube_api_key"]
        assert "gizli-anahtar-degeri-9876" not in row[0]
    finally:
        client.__exit__(None, None, None)


def test_oauth_start_uses_database_configured_client(tmp_path):
    # Ortamda OAuth yok; kimlik bilgileri yalnızca siteden girildi.
    client = _make_settings_app(tmp_path)
    try:
        key = Fernet.generate_key().decode()
        client.put(
            "/api/settings",
            json={
                "google_client_id": "db-client-id",
                "google_client_secret": "db-client-secret",
                "token_encryption_key": key,
                "oauth_redirect_base": "http://db-lan:8000",
            },
        )
        channel_id = client.post(
            "/api/channels", json={"name": "DB Ayarlı Kanal"}
        ).json()["id"]

        response = client.post(f"/api/channels/{channel_id}/oauth/start")
        assert response.status_code == 200
        url = response.json()["authorization_url"]
        assert "db-client-id" in url
        assert "http%3A%2F%2Fdb-lan%3A8000" in url
    finally:
        client.__exit__(None, None, None)


def test_discovery_uses_database_configured_api_key(
    tmp_path, mock_youtube  # noqa: F811 - fixture
):
    # Ortamda YOUTUBE_API_KEY yok; keşif yalnızca DB ayarıyla çalışmalı.
    client = _make_settings_app(tmp_path)
    try:
        channel_id = client.post(
            "/api/channels", json={"name": "Keşif Kanalı"}
        ).json()["id"]
        source_id = client.post(
            f"/api/channels/{channel_id}/sources",
            json={"youtube_channel_id": "UCkaynak1", "title": "Kaynak Kanal"},
        ).json()["id"]
        client.patch(
            f"/api/sources/{source_id}", json={"permission_status": "authorized"}
        )

        # Ayar yokken keşif 503.
        assert client.post(f"/api/channels/{channel_id}/discover").status_code == 503

        client.put("/api/settings", json={"youtube_api_key": "db-yt-key-1234"})
        response = client.post(f"/api/channels/{channel_id}/discover")
        assert response.status_code == 200
        assert response.json()["new_videos"] > 0
    finally:
        client.__exit__(None, None, None)
