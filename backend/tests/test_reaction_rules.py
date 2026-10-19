"""Tepki/reaksiyon içerik kuralı: pozitif başlık eşleşmesi, kural
değişince geri uygulama (backfill), manuel durum düzeltmesi ve pipeline
guard'ı.

Katı kuralın özü: kaynak kanalda require_reaction_content açıkken
başlığında tepki göstergesi OLMAYAN video işlenmez; göstergesi olan
video izlediği içerik ne olursa olsun (ör. funny moments) serbesttir.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_sessionmaker
from app.models import Base
from app.schemas_sources import SourceUpdate
from app.services.media_pipeline import MediaPipelineService
from app.services.source_rules import (
    age_exclusion,
    evaluate_source_rules,
    is_reaction_title,
)
from app.services.source_service import SourceService


def _rules_env(tmp_path):
    db_path = tmp_path / "rules.db"
    sync_engine = sa.create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{db_path}")
    engine, sessionmaker = create_engine_and_sessionmaker(settings.database_url)
    return sessionmaker, settings, engine, str(db_path)


def _seed(db_path):
    """Kanal + yetkili kaynak + üç video (tepki, montaj, işlenmiş)."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO channels (name, status, ribbon_color) "
                    "VALUES ('Kanal', 'connected', '#111111')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO source_channels "
                    "(channel_id, platform, youtube_channel_id, title, "
                    " permission_status, reaction_source, trim_start_seconds, "
                    " trim_end_seconds, filter_rules) "
                    "VALUES (1, 'youtube', 'UCsrc', 'RRaenee', "
                    "'authorized', 1, 0.0, 0.0, '{}')"
                )
            )
            # 1: tepki videosu, 2: montaj (funny moments), 3: islenmis.
            conn.execute(
                sa.text(
                    "INSERT INTO source_videos "
                    "(id, source_channel_id, youtube_video_id, title, status) "
                    "VALUES "
                    "(1, 1, 'r1', 'Reacting to funny moments', 'planned'), "
                    "(2, 1, 'r2', 'RRaenee funniest moments compilation', "
                    "'planned'), "
                    "(3, 1, 'r3', 'RRaenee best of stream', 'processed')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO media_assets "
                    "(source_video_id, origin, status, stage, file_path, "
                    " file_bytes) VALUES "
                    "(3, 'youtube', 'processed', 'candidates', '/x/3.mp4', 100)"
                )
            )
    finally:
        engine.dispose()


class TestReactionTitleRule:
    def test_positive_match_keeps_funny_moments_reaction(self):
        # Tepki göstergesi var: izlenen içerik ne olursa olsun serbest.
        assert is_reaction_title("Reacting to funny moments")
        assert is_reaction_title("RRaenee watching funny moments")
        assert is_reaction_title("Twitch izliyorum — en iyi anlar")
        reason = evaluate_source_rules(
            {"require_reaction_content": True},
            title="Reacting to the funniest moments ever",
            published_at=None,
        )
        assert reason is None

    def test_publisher_edit_without_reaction_cue_is_excluded(self):
        reason = evaluate_source_rules(
            {"require_reaction_content": True},
            title="RRaenee funniest moments compilation",
            published_at=None,
        )
        assert reason is not None
        assert reason.startswith("tepkime kuralı")

    def test_rule_off_changes_nothing(self):
        reason = evaluate_source_rules(
            {}, title="RRaenee funniest moments compilation", published_at=None
        )
        assert reason is None

    def test_age_exclusion_helper(self):
        old = datetime.now(UTC) - timedelta(days=10)
        reason = age_exclusion({"max_age_days": 7}, published_at=old)
        assert reason is not None and reason.startswith("yaş kuralı")
        assert age_exclusion({"max_age_days": 15}, published_at=old) is None
        # Tarih bilinmiyorsa yargi verilmez.
        assert age_exclusion({"max_age_days": 7}, published_at=None) is None
        assert age_exclusion({}, published_at=old) is None


class TestReapplyOnRuleChange:
    def test_enabling_rule_excludes_unprocessed_and_keeps_processed(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _rules_env(tmp_path)
            try:
                _seed(db)
                service = SourceService(sessionmaker)
                source = await service.update_source(
                    1, SourceUpdate(filter_rules={"require_reaction_content": True})
                )
                return source
            finally:
                await engine.dispose()

        asyncio.run(scenario())
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'rules.db'}")
        try:
            with engine.connect() as conn:
                statuses = dict(
                    conn.execute(
                        sa.text(
                            "SELECT id, status FROM source_videos ORDER BY id"
                        )
                    ).all()
                )
        finally:
            engine.dispose()
        assert statuses[1] == "planned"  # tepki: kalir
        assert statuses[2] == "excluded"  # montaj: haric
        assert statuses[3] == "processed"  # islenmis: dokunulmaz

    def test_disabling_rule_restores_only_rule_exclusions(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _rules_env(tmp_path)
            try:
                _seed(db)
                service = SourceService(sessionmaker)
                # Kural ac: 2 numarali montaj haric duser.
                await service.update_source(
                    1, SourceUpdate(filter_rules={"require_reaction_content": True})
                )
                # Manuel haric: 1 numarali tepki videosunu elle cikar.
                await service.set_video_status(1, "excluded")
                # Kural kapat: yalniz kural kaynakli haric geri gelmeli.
                await service.update_source(
                    1, SourceUpdate(filter_rules={})
                )
                rows = {}
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.connect() as conn:
                    for vid, status in conn.execute(
                        sa.text("SELECT id, status FROM source_videos")
                    ):
                        rows[vid] = status
                eng.dispose()
                return rows
            finally:
                await engine.dispose()

        rows = asyncio.run(scenario())
        assert rows[1] == "excluded"  # manuel haric: korunur
        assert rows[2] == "planned"  # kural harici: geri gelir
        assert rows[3] == "processed"  # islenmis: dokunulmaz

    def test_age_window_widening_restores_age_exclusions(self, tmp_path):
        """Güncellik penceresi genişletilince yalnız yaş kuralının
        hariç tuttuğu videolar geri değerlendirilir."""

        async def scenario():
            sessionmaker, settings, engine, db = _rules_env(tmp_path)
            try:
                _seed(db)
                old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
                fresh = (datetime.now(UTC) - timedelta(days=1)).isoformat()
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.begin() as conn:
                    conn.execute(
                        sa.text(
                            "UPDATE source_videos SET published_at=:d "
                            "WHERE id=1"
                        ),
                        {"d": old},
                    )
                    conn.execute(
                        sa.text(
                            "UPDATE source_videos SET published_at=:d "
                            "WHERE id=2"
                        ),
                        {"d": fresh},
                    )
                eng.dispose()
                service = SourceService(sessionmaker)
                await service.update_source(
                    1, SourceUpdate(filter_rules={"max_age_days": 7})
                )
                narrow = _statuses(db)
                await service.update_source(
                    1, SourceUpdate(filter_rules={"max_age_days": 15})
                )
                return narrow, _statuses(db)
            finally:
                await engine.dispose()

        narrow, wide = asyncio.run(scenario())
        assert narrow[1] == "excluded"  # 10 gunluk video 7 gunluk pencerede disarida
        assert narrow[2] == "planned"
        assert wide[1] == "planned"  # pencere 15 gene: geri gelir
        assert wide[2] == "planned"


def _statuses(db_path):
    eng = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with eng.connect() as conn:
            return dict(
                conn.execute(
                    sa.text("SELECT id, status FROM source_videos")
                ).all()
            )
    finally:
        eng.dispose()


class TestRefillAgeGuard:
    def test_refill_skips_aged_planned_videos(self, tmp_path):
        """Kuyrukta beklerken eskiyen planned videolar indirilmez;
        sıradaki uygun (güncel) video seçilir."""

        async def scenario():
            sessionmaker, settings, engine, db = _rules_env(tmp_path)
            try:
                _seed(db)
                old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
                fresh = (datetime.now(UTC) - timedelta(days=1)).isoformat()
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.begin() as conn:
                    conn.execute(
                        sa.text(
                            "INSERT INTO publishing_profiles "
                            "(channel_id, daily_clip_target, "
                            " daily_horizontal_limit, timezone, "
                            " automation_state, horizontal_stock_target, "
                            " title_mode, description_mode, tags_mode, "
                            " content_warning_mode, ai_disclosure_mode, "
                            " settings) "
                            "VALUES (1, 3, 3, 'Europe/Istanbul', "
                            "'running', 3, 'auto', 'auto', 'auto', "
                            "'auto', 'auto', '{}')"
                        )
                    )
                    conn.execute(
                        sa.text(
                            "UPDATE source_videos SET published_at=:d "
                            "WHERE id=1"
                        ),
                        {"d": old},
                    )
                    conn.execute(
                        sa.text(
                            "UPDATE source_videos SET published_at=:d "
                            "WHERE id=2"
                        ),
                        {"d": fresh},
                    )
                    conn.execute(
                        sa.text(
                            "UPDATE source_channels SET filter_rules=:r"
                        ),
                        {"r": json.dumps({"max_age_days": 7})},
                    )
                eng.dispose()
                from app.services.automation_service import (
                    refill_channel_stock,
                )

                result = await refill_channel_stock(
                    sessionmaker, settings, 1
                )
                return result, _statuses(db)
            finally:
                await engine.dispose()

        result, statuses = asyncio.run(scenario())
        assert result["enqueued"] is True
        # Kucuk id'li video 10 gunluk: atlanir, 1 gunluk video secilir.
        assert result["source_video_id"] == 2
        # Yasli video HARIC yazilmaz: pencere genislerse geri gelir.
        assert statuses[1] == "planned"


class TestVideoStatusApi:
    def test_roundtrip_and_processed_guard(self, tmp_path):
        from tests.conftest import _make_app

        app = _make_app(tmp_path)
        _seed(app.state.test_db_path)
        with TestClient(app) as client:
            # Montaj videosunu elle geri getir.
            body = {"status": "planned"}
            restored = client.post("/api/sources/videos/2/status", json=body)
            assert restored.status_code == 200
            assert restored.json()["status"] == "planned"
            # Tekrar haric tut.
            excluded = client.post(
                "/api/sources/videos/2/status", json={"status": "excluded"}
            )
            assert excluded.status_code == 200
            assert excluded.json()["status"] == "excluded"
            # Islenmis video degistirilemez.
            guarded = client.post(
                "/api/sources/videos/3/status", json=body
            )
            assert guarded.status_code == 422
            # Bilinmeyen video.
            missing = client.post(
                "/api/sources/videos/999/status", json=body
            )
            assert missing.status_code == 404


class TestPipelineExcludedGuard:
    def test_excluded_video_skips_pipeline_without_asset(self, tmp_path):
        async def scenario():
            sessionmaker, settings, engine, db = _rules_env(tmp_path)
            try:
                _seed(db)
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.begin() as conn:
                    conn.execute(
                        sa.text(
                            "UPDATE source_videos SET status='excluded' "
                            "WHERE id=2"
                        )
                    )
                eng.dispose()
                pipeline = MediaPipelineService(sessionmaker, settings)
                result = await pipeline.run(2)
                eng = sa.create_engine(f"sqlite:///{db}")
                with eng.connect() as conn:
                    assets = conn.execute(
                        sa.text(
                            "SELECT COUNT(*) FROM media_assets "
                            "WHERE source_video_id=2"
                        )
                    ).scalar()
                eng.dispose()
                return result, assets
            finally:
                await engine.dispose()

        result, assets = asyncio.run(scenario())
        assert result == {"source_video_id": 2, "skipped": True}
        assert assets == 0  # hic varlik/indirme olusmaz
