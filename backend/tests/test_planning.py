"""Planning + source rule tests (Milestone 4, slice 3)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.services.source_rules import evaluate_source_rules


def _setup_authorized_source(client: TestClient, rules: dict | None = None) -> int:
    channel_id = client.post("/api/channels", json={"name": "Kanal"}).json()["id"]
    source_id = client.post(
        f"/api/channels/{channel_id}/sources",
        json={
            "youtube_channel_id": "UCkaynak1",
            "title": "Kaynak",
            "filter_rules": rules,
        },
    ).json()["id"]
    response = client.patch(
        f"/api/sources/{source_id}", json={"permission_status": "authorized"}
    )
    assert response.status_code == 200
    return channel_id


def _sync_count(client: TestClient, sql: str) -> int:
    engine = sa.create_engine(f"sqlite:///{client.app.state.test_db_path}")
    with engine.connect() as conn:
        value = conn.execute(sa.text(sql)).scalar_one()
    engine.dispose()
    return value


# --- kural değerlendirici (birim) ---


def test_rule_evaluator_passes_clean_video() -> None:
    assert (
        evaluate_source_rules(
            {"exclude_title_patterns": ["reklam"]},
            title="Normal Video",
            published_at=datetime.now(UTC),
        )
        is None
    )
    assert evaluate_source_rules(None, title="Herhangi", published_at=None) is None


def test_rule_evaluator_title_pattern() -> None:
    reason = evaluate_source_rules(
        {"exclude_title_patterns": ["SHORTS"]},
        title="Kanal Shorts #12",
        published_at=datetime.now(UTC),
    )
    assert reason is not None
    assert "başlık kuralı" in reason


def test_rule_evaluator_max_age() -> None:
    old = datetime.now(UTC) - timedelta(days=3)
    reason = evaluate_source_rules(
        {"max_age_days": 2}, title="Eski Video", published_at=old
    )
    assert reason is not None
    assert "yaş kuralı" in reason
    fresh = datetime.now(UTC) - timedelta(hours=1)
    assert (
        evaluate_source_rules(
            {"max_age_days": 2}, title="Yeni Video", published_at=fresh
        )
        is None
    )


# --- API üzerinden kurallar ---


def test_invalid_rule_keys_rejected(client_db: TestClient) -> None:
    channel_id = client_db.post("/api/channels", json={"name": "K"}).json()["id"]
    response = client_db.post(
        f"/api/channels/{channel_id}/sources",
        json={
            "youtube_channel_id": "UCkaynak1",
            "title": "Kaynak",
            "filter_rules": {"bilinmeyen_kural": 1},
        },
    )
    assert response.status_code == 422


def test_discovery_applies_title_rule(
    client_youtube: TestClient, mock_youtube: None
) -> None:
    channel_id = _setup_authorized_source(
        client_youtube, {"exclude_title_patterns": ["Video 1"]}
    )

    result = client_youtube.post(f"/api/channels/{channel_id}/discover").json()
    assert result["new_videos"] == 1
    assert result["new_excluded"] == 1

    excluded = client_youtube.get(
        f"/api/channels/{channel_id}/videos", params={"status": "excluded"}
    ).json()
    assert excluded["total"] == 1
    assert excluded["videos"][0]["title"] == "Kaynak Video 1"

    discovered = client_youtube.get(
        f"/api/channels/{channel_id}/videos", params={"status": "discovered"}
    ).json()
    assert discovered["total"] == 1


# --- planlama ---


def test_plan_is_idempotent_and_audited(
    client_youtube: TestClient, mock_youtube: None
) -> None:
    channel_id = _setup_authorized_source(client_youtube)
    client_youtube.post(f"/api/channels/{channel_id}/discover")

    first = client_youtube.post(f"/api/channels/{channel_id}/plan")
    assert first.status_code == 200
    assert first.json() == {"planned": 2, "skipped": 0}

    planned = client_youtube.get(
        f"/api/channels/{channel_id}/videos", params={"status": "planned"}
    ).json()
    assert planned["total"] == 2

    # Tekrar planlama: kararlar tekilleştirilmiş, yeni karar yazılmaz.
    second = client_youtube.post(f"/api/channels/{channel_id}/plan")
    assert second.json() == {"planned": 0, "skipped": 0}

    decisions = _sync_count(
        client_youtube, "SELECT COUNT(*) FROM planning_decisions"
    )
    assert decisions == 2

    runs = _sync_count(
        client_youtube,
        "SELECT COUNT(*) FROM audit_events WHERE event_type = 'planning.run'",
    )
    assert runs == 2


def test_plan_skips_excluded_videos(
    client_youtube: TestClient, mock_youtube: None
) -> None:
    channel_id = _setup_authorized_source(
        client_youtube, {"exclude_title_patterns": ["Video 1"]}
    )
    client_youtube.post(f"/api/channels/{channel_id}/discover")

    result = client_youtube.post(f"/api/channels/{channel_id}/plan").json()
    assert result == {"planned": 1, "skipped": 0}

    # Hariç tutulan video için karar satırı yazılmaz.
    decisions = _sync_count(
        client_youtube, "SELECT COUNT(*) FROM planning_decisions"
    )
    assert decisions == 1
    excluded = client_youtube.get(
        f"/api/channels/{channel_id}/videos", params={"status": "excluded"}
    ).json()
    assert excluded["total"] == 1
