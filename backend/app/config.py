"""Application settings loaded from environment variables (and optional .env).

Secrets must only ever arrive through the environment; they are never
written to code or committed files.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "info"
    database_url: str = ""

    # Google/YouTube OAuth (all optional: the flow reports "not configured"
    # until the user supplies their own client credentials).
    google_client_id: str = ""
    google_client_secret: str = ""
    # Externally reachable bases; the Pi's LAN address in deployment.
    oauth_redirect_base: str = ""
    frontend_base_url: str = ""
    # Fernet key (urlsafe base64, 32 bytes) encrypting OAuth tokens at rest.
    token_encryption_key: str = ""
    # YouTube Data API v3 key for source monitoring (public data).
    youtube_api_key: str = ""
    # Source polling tuning.
    source_cache_ttl_seconds: int = 300
    daily_quota_units: int = 10000

    @property
    def oauth_configured(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.token_encryption_key
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
