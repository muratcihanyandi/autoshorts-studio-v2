"""Settings loading tests."""
from __future__ import annotations

from app.config import Settings


def test_settings_defaults(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    settings = Settings()
    assert settings.app_env == "development"
    assert settings.log_level == "info"
    assert settings.database_url == ""
    assert not settings.is_production


def test_settings_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("APP_ENV", "production")
    settings = Settings()
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"
    assert settings.is_production
