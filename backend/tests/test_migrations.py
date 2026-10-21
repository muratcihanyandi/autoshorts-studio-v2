"""Alembic migration tests.

Migrations target PostgreSQL (ADR-008); without live PostgreSQL credentials
on the dev machine, correctness is verified through offline SQL generation:
the full upgrade path must compile to valid SQL without a database.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_offline_upgrade_sql_generates() -> None:
    env = dict(os.environ)
    # Synthetic URL for SQL generation only; offline mode never connects.
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://offlinegen:offlinegen@localhost:5432/autoshorts_studio"  # secret-scan-ok
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE app_meta" in result.stdout, result.stdout
    assert "CREATE INDEX ix_app_meta_updated_at" in result.stdout


def test_offline_downgrade_sql_generates() -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://offlinegen:offlinegen@localhost:5432/autoshorts_studio"  # secret-scan-ok
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "head:base", "--sql"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "DROP TABLE app_meta" in result.stdout


def test_offline_sql_contains_0012_channel_automation() -> None:
    """0012: otomasyon durumu, stok hedefi, modlar, channel_characters,
    'confirmed' durumu, whisper kaynagi, bildirim bayraklari, run_at."""
    env = dict(os.environ)
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://offlinegen:offlinegen@localhost:5432/autoshorts_studio"  # secret-scan-ok
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    sql = result.stdout
    assert "automation_state" in sql
    assert "horizontal_stock_target" in sql
    assert "content_warning_mode" in sql
    assert "ai_disclosure_mode" in sql
    assert "channel_system_prompt" in sql
    assert "CREATE TABLE channel_characters" in sql
    # 'confirmed' terminal durumu ve whisper transkript kaynagi.
    assert "'confirmed'" in sql
    assert "'whisper'" in sql
    # Bildirim bayraklari ve is bekleme kolonu.
    assert "content_warning" in sql
    assert "ai_disclosure" in sql
    assert "run_at" in sql


def test_offline_sql_contains_0015_removed_status() -> None:
    """0015: rendered_clips 'removed' mezartas durumu (klip kaldirma)."""
    env = dict(os.environ)
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://offlinegen:offlinegen@localhost:5432/autoshorts_studio"  # secret-scan-ok
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    sql = result.stdout
    assert "'removed'" in sql
    assert "ck_rendered_clips_status" in sql
