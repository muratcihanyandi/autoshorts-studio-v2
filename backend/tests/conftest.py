"""Shared test fixtures.

Unit tests never touch a real PostgreSQL: readiness is exercised against
SQLite in-memory, and failure paths against a closed local port. Channel
API tests run on a file-backed SQLite whose schema is created from the
models with a synchronous engine before the async app opens it.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
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


@pytest.fixture
def client_db(tmp_path) -> TestClient:
    from app.models import Base

    db_file = tmp_path / "test.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    app = create_app(Settings(database_url=f"sqlite+aiosqlite:///{db_file}"))
    app.state.test_db_path = str(db_file)
    with TestClient(app) as client:
        yield client


def _make_app(tmp_path, **settings_overrides):
    """Schema'lı sqlite uygulaması; ayarlar test türüne göre verilir.

    app.state üzerindeki test_token_key ve test_db_path, testlerin
    şifreli token'ları ve denetim olaylarını senkron motordan
    doğrulaması içindir.
    """
    from cryptography.fernet import Fernet

    from app.models import Base

    db_file = tmp_path / "test.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file}",
        **settings_overrides,
    )
    app = create_app(settings)
    app.state.test_token_key = settings.token_encryption_key or ""
    app.state.test_db_path = str(db_file)
    return app


@pytest.fixture
def client_oauth(tmp_path) -> TestClient:
    app = _make_app(
        tmp_path,
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        oauth_redirect_base="http://lan-test:8000",
        token_encryption_key=Fernet.generate_key().decode(),
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_oauth_redirect(tmp_path) -> TestClient:
    app = _make_app(
        tmp_path,
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        oauth_redirect_base="http://lan-test:8000",
        token_encryption_key=Fernet.generate_key().decode(),
        frontend_base_url="http://ui-test:1478",
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_youtube(tmp_path) -> TestClient:
    app = _make_app(tmp_path, youtube_api_key="test-yt-key")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_youtube_tight_quota(tmp_path) -> TestClient:
    """İki isteklik günlük kota: sınır davranışını test etmek için."""
    app = _make_app(
        tmp_path, youtube_api_key="test-yt-key", daily_quota_units=2
    )
    with TestClient(app) as client:
        yield client


# --- YouTube Data API mock'u (keşif/planlama testleri paylaşırlar) ---

YOUTUBE_MOCK_CALLS = {"channels": 0, "playlist_items": 0}


def youtube_mock_handler(request) -> "httpx.Response":
    import httpx

    url = str(request.url)
    if "/channels" in url:
        YOUTUBE_MOCK_CALLS["channels"] += 1
        # Kanal kimligini istekten coz: her kaynak kendi uploads
        # listesini alir (mirror kaynak testleri icin).
        channel_id = "UCkaynak1"
        if "id=UCkaynak2" in url:
            channel_id = "UCkaynak2"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": channel_id,
                        "contentDetails": {
                            "relatedPlaylists": {
                                "uploads": "UU" + channel_id[2:]
                            }
                        },
                    }
                ]
            },
        )
    if "/playlistItems" in url:
        YOUTUBE_MOCK_CALLS["playlist_items"] += 1
        # UUkaynak2: ayni icerigin mirror kanali — birinci video ayni
        # icerik farkli baslik bicimiyle (Gorev 8 dedupe senaryosu),
        # ikincisi gercekten farkli bir video.
        if "playlistId=UUkaynak2" in url:
            items = [
                {
                    "snippet": {
                        "title": "Kaynak Video 1 Tepki! @kaynakkanal",
                        "publishedAt": "2026-10-15T12:00:00Z",
                        "resourceId": {"videoId": "vid-mirror-1"},
                    }
                },
                {
                    "snippet": {
                        "title": "Bambaşka Ayrı Bir Video",
                        "publishedAt": "2026-10-17T09:00:00Z",
                        "resourceId": {"videoId": "vid-mirror-2"},
                    }
                },
            ]
        else:
            items = [
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
        return httpx.Response(200, json={"items": items})
    return httpx.Response(404, json={"error": "beklenmeyen adres"})


@pytest.fixture
def mock_youtube(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.services import youtube_client

    YOUTUBE_MOCK_CALLS["channels"] = 0
    YOUTUBE_MOCK_CALLS["playlist_items"] = 0
    youtube_client.clear_cache()
    monkeypatch.setattr(
        "app.services.youtube_client._default_http_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(youtube_mock_handler)
        ),
    )
