"""Product media view: engine-selected videos, detail and playback.

Only source videos the engine has actually selected (or is processing
right now) reach the product surface; processed-but-unselected videos
stay out. Ready clips expose a playable stream, a cover and the full
YouTube publishing plan.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
import sqlalchemy as sa

from tests.conftest import _make_app
from tests.test_pipeline_view import _seed, _seed_jobs


def _seed_product(db_path: str, media_root):
    """Seeded pipeline + one selected candidate, render, metadata, upload."""
    _seed(db_path)
    _seed_jobs(db_path)
    media_root.mkdir(parents=True, exist_ok=True)
    edited = media_root / "edited"
    edited.mkdir(parents=True, exist_ok=True)
    clip_file = edited / "1.mp4"
    clip_file.write_bytes(b"0123456789" * 200)
    thumbs = media_root / "thumbnails"
    thumbs.mkdir(parents=True, exist_ok=True)
    (thumbs / "preview_1.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            # Video 3: pipeline tamam ama motor hiçbir an seçmedi -> gizli.
            conn.execute(
                sa.text(
                    "UPDATE source_videos SET status='processed' WHERE id=3"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO media_assets "
                    "(source_video_id, origin, status, stage, file_path, "
                    " file_bytes) VALUES "
                    "(3, 'youtube', 'processed', 'candidates', '/x/3.mp4', 5000)"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO clip_candidates "
                    "(source_video_id, start_seconds, end_seconds, "
                    " duration_seconds, score, reason, status, detail) VALUES "
                    "(1, 12.0, 48.0, 36.0, 0.91, 'yuksek enerji', "
                    " 'selected', :detail)"
                ),
                {"detail": '{"hype": {"confidence": 0.87, "refined": true}}'},
            )
            candidate_id = conn.execute(
                sa.text("SELECT id FROM clip_candidates")
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO rendered_clips "
                    "(clip_candidate_id, source_video_id, orientation, status, "
                    " file_path, file_bytes, thumbnail_path, width, height, "
                    " duration_seconds, webcam_confidence, validation) VALUES "
                    "(:candidate, 1, 'vertical', 'rendered', :path, :size, "
                    " 'thumbnails/preview_1.jpg', 1080, 1920, 36.0, 0.9, :validation)"
                ),
                {
                    "candidate": candidate_id,
                    "path": str(clip_file),
                    "size": clip_file.stat().st_size,
                    "validation": '{"ok": true, "av_sync_delta": 0.01}',
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO clip_metadata "
                    "(clip_candidate_id, source_video_id, revision, title, "
                    " description, tags, hook, thumbnail_text, content_warning, "
                    " ai_disclosure, status, provider_name) VALUES "
                    "(:candidate, 1, 1, :title, :description, :tags, :hook, "
                    " :thumb_text, 0, 0, 'approved', 'test-provider')"
                ),
                {
                    "candidate": candidate_id,
                    "title": "Motorun seçtiği an",
                    "description": "Bu klip motorun seçtiği en yüksek enerjili andan üretildi.",
                    "tags": '["shorts", "reaksiyon"]',
                    "hook": "İlk üç saniyede ne oldu?",
                    "thumb_text": "İZLE",
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO published_videos "
                    "(clip_candidate_id, source_video_id, orientation, channel_id, "
                    " youtube_video_id, visibility, status, title) VALUES "
                    "(:candidate, 1, 'vertical', 1, 'yt-pub-1', 'private', "
                    " 'verified', 'Motorun seçtiği an')"
                ),
                {"candidate": candidate_id},
            )
    finally:
        engine.dispose()


def test_engine_selected_only_hides_unselected_and_shows_stages(tmp_path):
    media_root = tmp_path / "media"
    app = _make_app(tmp_path, media_root=str(media_root))
    _seed_product(app.state.test_db_path, media_root)

    with TestClient(app) as client:
        payload = client.get(
            "/api/media",
            params={
                "engine_selected_only": True,
                "ready_only": True,
                "active_only": False,
            },
        ).json()

    source_ids = {source["id"] for source in payload["sources"]}
    assert source_ids == {1, 2}
    assert payload["current_source_id"] == 2

    selected = next(source for source in payload["sources"] if source["id"] == 1)
    assert selected["source_channel_title"] == "Kaynak Kanal"
    assert selected["youtube_url"] == "https://www.youtube.com/watch?v=yt-1"
    assert selected["selected_count"] == 1
    assert selected["selected_candidates"][0]["render_status"] == "rendered"
    assert selected["selected_candidates"][0]["hype_confidence"] == 0.87
    assert [step["key"] for step in selected["stages"]] == [
        "download",
        "inspect",
        "transcript",
        "analysis",
        "candidates",
        "selection",
    ]
    assert all(step["state"] == "done" for step in selected["stages"])

    active = next(source for source in payload["sources"] if source["id"] == 2)
    assert active["is_current"] is True

    # Yalnızca hazır klip listelenir; detay URL'leri hazır.
    assert len(payload["clips"]) == 1
    clip = payload["clips"][0]
    assert clip["status"] == "rendered"
    assert clip["thumbnail_url"] == "/api/media/clips/1/thumbnail"
    assert clip["stream_url"] == "/api/media/clips/1/stream"
    assert clip["published_status"] == "verified"
    assert clip["visibility"] == "private"
    assert clip["youtube_url"] == "https://www.youtube.com/watch?v=yt-pub-1"


def test_clip_detail_carries_youtube_plan_metadata_and_filters(tmp_path):
    media_root = tmp_path / "media"
    app = _make_app(tmp_path, media_root=str(media_root))
    _seed_product(app.state.test_db_path, media_root)

    with TestClient(app) as client:
        detail = client.get("/api/media/clips/1").json()

    assert detail["render"]["stream_url"] == "/api/media/clips/1/stream"
    assert detail["render"]["thumbnail_url"] == "/api/media/clips/1/thumbnail"
    assert detail["source"]["channel_title"] == "Kaynak Kanal"
    assert detail["source"]["youtube_url"] == "https://www.youtube.com/watch?v=yt-1"
    assert detail["metadata"]["title"] == "Motorun seçtiği an"
    assert detail["metadata"]["tags"] == ["shorts", "reaksiyon"]
    assert detail["metadata"]["status"] == "approved"
    assert detail["publishing"]["upload_status"] == "verified"
    assert detail["publishing"]["visibility"] == "private"
    assert detail["publishing"]["youtube_url"] == (
        "https://www.youtube.com/watch?v=yt-pub-1"
    )
    assert detail["publishing"]["next_slot"] is not None
    assert detail["publishing"]["metadata_approved"] is True
    assert detail["filters"]["reaction_source"] is False
    assert detail["candidate"]["hype_confidence"] == 0.87
    assert "Gizli yüklendi" in detail["note"]


def test_clip_stream_supports_range_and_thumbnail_serves_image(tmp_path):
    media_root = tmp_path / "media"
    app = _make_app(tmp_path, media_root=str(media_root))
    _seed_product(app.state.test_db_path, media_root)

    with TestClient(app) as client:
        stream = client.get(
            "/api/media/clips/1/stream", headers={"Range": "bytes=0-3"}
        )
        assert stream.status_code == 206
        assert stream.content == b"0123"

        thumbnail = client.get("/api/media/clips/1/thumbnail")
        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"] == "image/jpeg"


def test_stream_is_closed_after_login_is_configured(tmp_path):
    media_root = tmp_path / "media"
    app = _make_app(tmp_path, media_root=str(media_root))
    _seed_product(app.state.test_db_path, media_root)

    with TestClient(app) as client:
        setup = client.post(
            "/api/auth/setup",
            json={"username": "operator", "password": "guclu-sifre"},  # secret-scan-ok
        )
        assert setup.status_code == 201
        client.post("/api/auth/logout")
        assert client.get("/api/media/clips/1/stream").status_code == 401


def test_remove_source_video_clears_files_rows_and_jobs(tmp_path):
    """Arayüzden video kaldırma (kullanıcı isteği 2026-10-20): dosyalar,
    aday/render/metaveri satırları ve bekleyen işler temizlenir; video
    'excluded' olarak varsayılan görünümden kaybolur, tekrar keşfedilmez."""
    media_root = tmp_path / "media"
    app = _make_app(tmp_path, media_root=str(media_root))
    _seed_product(app.state.test_db_path, media_root)

    engine = sa.create_engine(f"sqlite:///{app.state.test_db_path}")
    try:
        with engine.begin() as conn:
            candidate_id = conn.execute(
                sa.text("SELECT id FROM clip_candidates")
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO jobs (job_type, payload, status, priority,"
                    " attempts, max_attempts) VALUES"
                    " ('clip_render', :p, 'queued', 5, 0, 3)"
                ),
                {"p": f'{{"clip_candidate_id": {candidate_id}}}'},
            )
    finally:
        engine.dispose()

    with TestClient(app) as client:
        missing = client.delete("/api/media/videos/999")
        assert missing.status_code == 404

        removed = client.delete("/api/media/videos/1")
        assert removed.status_code == 200, removed.text
        body = removed.json()
        assert body["status"] == "excluded"
        assert body["files_removed"] >= 2  # render ciktisi + kapak
        assert body["jobs_cancelled"] == 1  # adaya bagli kuyruk isi

        after = client.get(
            "/api/media", params={"active_only": False}
        ).json()
        assert all(source["id"] != 1 for source in after["sources"])
        assert all(clip["id"] != 1 for clip in after["clips"])

    engine = sa.create_engine(f"sqlite:///{app.state.test_db_path}")
    try:
        with engine.connect() as conn:
            status = conn.execute(
                sa.text("SELECT status FROM source_videos WHERE id = 1")
            ).scalar()
            counts = conn.execute(
                sa.text(
                    "SELECT (SELECT count(*) FROM media_assets"
                    " WHERE source_video_id = 1)"
                    " + (SELECT count(*) FROM clip_candidates"
                    " WHERE source_video_id = 1)"
                    " + (SELECT count(*) FROM rendered_clips"
                    " WHERE source_video_id = 1)"
                    " + (SELECT count(*) FROM clip_metadata"
                    " WHERE source_video_id = 1)"
                )
            ).scalar()
    finally:
        engine.dispose()
    assert status == "excluded"
    assert counts == 0
    assert not (media_root / "edited" / "1.mp4").exists()
    assert not (media_root / "thumbnails" / "preview_1.jpg").exists()


def test_download_stage_carries_percent_detail(tmp_path):
    """İndirme sırasında download adımı canlı yüzde detayı taşır
    (app_meta.download_progress -> '%63')."""
    import json

    media_root = tmp_path / "media"
    app = _make_app(tmp_path, media_root=str(media_root))
    _seed(app.state.test_db_path)

    engine = sa.create_engine(f"sqlite:///{app.state.test_db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE media_assets SET status='downloading',"
                    " stage='download', file_path='' WHERE source_video_id = 2"
                )
            )
            asset_id = conn.execute(
                sa.text(
                    "SELECT id FROM media_assets WHERE source_video_id = 2"
                )
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO app_meta (key, value)"
                    " VALUES ('download_progress', :value)"
                ),
                {
                    "value": json.dumps(
                        {"media_asset_id": asset_id, "percent": 63.4}
                    )
                },
            )
    finally:
        engine.dispose()

    with TestClient(app) as client:
        payload = client.get("/api/media").json()

    current = next(s for s in payload["sources"] if s["id"] == 2)
    download_step = next(
        step for step in current["stages"] if step["key"] == "download"
    )
    assert download_step["state"] == "active"
    assert download_step["detail"] == "%63"
