"""Source discovery tests (Milestone 4, slice 2).

YouTube Data API is mocked via httpx.MockTransport on the client's
_default_http_client indirection (shared fixture in conftest); the mock
counts calls so caching and quota behavior are observable.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from fastapi.testclient import TestClient

from tests.conftest import YOUTUBE_MOCK_CALLS


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
        "new_excluded": 0,
        "duplicate_excluded": 0,
        "quota_blocked": False,
        "skipped_platforms": [],
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
    assert YOUTUBE_MOCK_CALLS["channels"] == 1
    assert YOUTUBE_MOCK_CALLS["playlist_items"] == 1

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
        "new_excluded": 0,
        "duplicate_excluded": 0,
        "quota_blocked": False,
        "skipped_platforms": [],
    }
    assert YOUTUBE_MOCK_CALLS["channels"] == 0


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


def test_discovery_excludes_duplicate_content_across_mirrors(
    client_youtube: TestClient, mock_youtube: None
) -> None:
    """Görev 8 (canlı bulgu 2026-10-21): izlenen iki kaynak kanal aynı
    içeriği yükler (mirror) — farklı YouTube video kimliği, biraz farklı
    başlık biçimi. Aynı içerik ikinci kez işlenmez: satır 'excluded'
    olarak kayıt olur, gerçekten farklı video normal keşfedilir."""

    from app.services.source_dedupe import (
        normalize_title,
        titles_match,
    )

    # Birim sözleşme: canlıda görülen başlık çiftleri eşleşmeli.
    assert titles_match(
        normalize_title(
            "RRaenee | DÜNYANIN EN BÜYÜK ELMAS SOYGUNU | Tepki | @bentropi ​"
        ),
        normalize_title(
            "RRaenee | Dünyanın En Büyük Elmas Soygunu Tepki! @bentropi"
        ),
    )
    assert titles_match(
        normalize_title(
            "RRaenee | 33 Kişi Yola Çıktı, Sadece 11'i Döndü"
            " (Birbirlerini Avladılar) | Tepki | Mehmet Ali Güldal"
        ),
        normalize_title(
            "RRaenee | 33 Kişi Yola Çıktı, Sadece 11'i Döndü Tepki!"
            " @mehmetaliguldal"
        ),
    )
    # Serinin farklı bölümleri farklı içeriktir (sayı koruması).
    assert not titles_match(
        normalize_title("Motosiklet Kazalarına Tepki! #12 @ZaferAKCAY"),
        normalize_title(
            "Motosiklet Kazalarına Tepki! #13 (Mimari Yapı Tartışması!)"
            " @ZaferAKCAY"
        ),
    )

    # Keşif: iki yetkili kaynak (UCkaynak1 + mirror UUkaynak2).
    channel_id = _setup_authorized_source(client_youtube)
    second_source = client_youtube.post(
        f"/api/channels/{channel_id}/sources",
        json={"youtube_channel_id": "UCkaynak2", "title": "Mirror Kaynak"},
    ).json()["id"]
    client_youtube.patch(
        f"/api/sources/{second_source}", json={"permission_status": "authorized"}
    )

    response = client_youtube.post(f"/api/channels/{channel_id}/discover")
    assert response.status_code == 200
    body = response.json()
    assert body["sources_checked"] == 2
    assert body["new_videos"] == 3  # kaynak 1'in ikisi + mirror'un farklı videosu
    assert body["duplicate_excluded"] == 1  # mirror'daki aynı içerik

    videos = client_youtube.get(f"/api/channels/{channel_id}/videos").json()
    by_id = {v["youtube_video_id"]: v["status"] for v in videos["videos"]}
    assert by_id["vid-kaynak-1"] == "discovered"
    assert by_id["vid-kaynak-2"] == "discovered"
    assert by_id["vid-mirror-1"] == "excluded"  # aynı içerik, Hariç
    assert by_id["vid-mirror-2"] == "discovered"  # gerçekten yeni video


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


def test_concurrent_discovery_serialized_per_channel(tmp_path) -> None:
    """Aynı kanalda iki eşzamanlı keşif birbirini bekler (2026-10-20 canlı
    olay: API "Keşfet" + worker saatliği yarışı çift insert deneyip turu
    UniqueViolation ile düşürüyordu)."""
    import asyncio

    from app.config import Settings
    from app.db import create_engine_and_sessionmaker
    from app.models import Base
    from app.services.discovery_service import DiscoveryService

    db_path = tmp_path / "disc.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO channels (name, status, ribbon_color)"
                " VALUES ('K', 'connected', '#111111')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO source_channels"
                " (channel_id, platform, youtube_channel_id, title,"
                " permission_status, reaction_source, trim_start_seconds,"
                " trim_end_seconds, filter_rules) VALUES"
                " (1, 'youtube', 'UCx', 'Kaynak', 'authorized', 0, 0.0,"
                " 0.0, '{}')"
            )
        )
    sync_engine.dispose()

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}", youtube_api_key="k"
    )

    class FakeClient:
        """Yavaş keşif istemcisi: eşzamanlılığı ölçer."""

        def __init__(self) -> None:
            self.concurrent = 0
            self.max_concurrent = 0

        def require_configured(self) -> None:
            return None

        async def get_uploads_playlist_id(self, channel_id: str):
            return "UUx"

        async def list_upload_videos(self, playlist_id: str):
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
            await asyncio.sleep(0.05)
            self.concurrent -= 1
            return [
                {
                    "video_id": "vid-race",
                    "title": "Yarış videosu",
                    "published_at": "2026-10-20T10:00:00Z",
                }
            ]

    async def scenario():
        engine, sessionmaker = create_engine_and_sessionmaker(
            settings.database_url
        )
        try:
            service = DiscoveryService(sessionmaker, settings)
            fake = FakeClient()
            service._client = fake
            results = await asyncio.gather(
                service.discover_for_channel(1),
                service.discover_for_channel(1),
            )
            return results, fake.max_concurrent
        finally:
            await engine.dispose()

    results, max_concurrent = asyncio.run(scenario())
    assert max_concurrent == 1  # keşifler sıraya girer, iç içe girmez
    new_counts = sorted(r["new_videos"] for r in results)
    assert new_counts == [0, 1]  # ikinci tur aynı videoyu tekrar eklemez
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        total = conn.execute(
            sa.text(
                "SELECT count(*) FROM source_videos"
                " WHERE youtube_video_id = 'vid-race'"
            )
        ).scalar()
    engine.dispose()
    assert total == 1
