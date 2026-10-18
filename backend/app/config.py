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
    # Global LLM system prompt for AI metadata (title/hook/description/
    # tags/thumbnail text). Empty = built-in default; a character's own
    # system_prompt (M13) overrides it for that character's clips.
    metadata_system_prompt: str = ""
    # Source polling tuning.
    source_cache_ttl_seconds: int = 300
    daily_quota_units: int = 10000

    # Job queue and worker (Milestone 6). The worker is off by default so
    # tests and plain API runs stay deterministic; deployment sets
    # WORKER_ENABLED=true.
    worker_enabled: bool = False
    max_concurrent_jobs: int = 2
    job_stale_after_seconds: int = 600
    source_poll_interval_minutes: int = 60
    min_free_disk_gb: float = 2.0
    download_rate_limit_kbps: int = 0
    # Labelled media tree root INSIDE the container (deployment mounts
    # /mnt/usb/Autoshorts_Studio here). Empty keeps the feature off.
    media_root: str = ""

    # Milestone 7 media pipeline. External tools run as subprocesses
    # and are probed on PATH; binaries live in the container image.
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    clip_min_seconds: int = 20
    clip_max_seconds: int = 90
    silence_noise_db: float = -35.0
    silence_min_seconds: float = 1.5
    scene_threshold: float = 0.4
    planned_poll_interval_minutes: int = 5
    publish_check_interval_minutes: int = 10

    # Start/Stop otomasyon donemi: kaynak limitleri ve uretim ayarlari.
    # 0 = sinir kapali; doldugunda worker yeni is almaya bekler.
    cpu_target_percent: int = 0
    ram_target_percent: int = 0
    # ffmpeg -threads N (0 = otomatik); agir isler ayni anda bu kadar
    # kolatek ile kosar (indirme + render tek kilit uzerinden siralanir).
    ffmpeg_threads: int = 0
    max_heavy_jobs: int = 1
    # Is yeniden deneme politikasi.
    retry_max_attempts: int = 3
    retry_backoff_seconds: int = 60
    # Yatay stok hedefi varsayilani (kanal profili olusurken kullanilir).
    horizontal_stock_target_default: int = 3
    # Transkripsiyon: 'sidecar' (yalnizca mevcut altyazi) veya
    # 'whisper' (altyazi yoksa yerel Whisper CLI fallback).
    transcription_method: str = "sidecar"
    whisper_model: str = "tiny"
    whisper_language: str = "tr"
    # Bir yatay videodan cikarilacak en fazla Shorts sayisi.
    shorts_per_video: int = 3

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
