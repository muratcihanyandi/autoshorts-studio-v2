"""Settings API schemas.

Secret fields are write-only from the client's perspective: responses
carry only `configured` + `source` + a masked hint (last 4 characters of
values long enough to be safe to hint), never the value itself.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class SettingSource(str, Enum):
    database = "database"
    environment = "environment"
    unset = "unset"


class PlainSettingOut(BaseModel):
    """Non-secret field: full value + where it comes from."""

    value: str
    source: SettingSource


class IntSettingOut(BaseModel):
    value: int
    source: SettingSource


class BoolSettingOut(BaseModel):
    value: bool
    source: SettingSource


class SecretSettingOut(BaseModel):
    """Secret field: never carries the value."""

    configured: bool
    source: SettingSource
    hint: str


class SettingsOut(BaseModel):
    google_client_id: PlainSettingOut
    google_client_secret: SecretSettingOut
    token_encryption_key: SecretSettingOut
    oauth_redirect_base: PlainSettingOut
    frontend_base_url: PlainSettingOut
    youtube_api_key: SecretSettingOut
    daily_quota_units: IntSettingOut
    metadata_system_prompt: PlainSettingOut
    # Kaynak limitleri ve uretim ayarlari (Start/Stop donemi).
    cpu_target_percent: IntSettingOut
    ram_target_percent: IntSettingOut
    ffmpeg_threads: IntSettingOut
    max_heavy_jobs: IntSettingOut
    max_concurrent_jobs: IntSettingOut
    retry_max_attempts: IntSettingOut
    retry_backoff_seconds: IntSettingOut
    horizontal_stock_target_default: IntSettingOut
    shorts_per_video: IntSettingOut
    clip_min_seconds: IntSettingOut
    clip_max_seconds: IntSettingOut
    min_free_disk_gb: PlainSettingOut
    download_rate_limit_kbps: IntSettingOut
    planned_poll_interval_minutes: IntSettingOut
    media_retention_days: IntSettingOut
    transcription_method: PlainSettingOut
    whisper_model: PlainSettingOut
    whisper_language: PlainSettingOut
    burn_subtitles: BoolSettingOut
    subtitle_font_size: IntSettingOut
    subtitle_position: PlainSettingOut
    media_root: PlainSettingOut


class SettingsUpdate(BaseModel):
    """Patch semantics per field: None = leave untouched, "" = clear the
    database override (fall back to environment), any other value = save
    as the database override (after validation)."""

    google_client_id: str | None = None
    google_client_secret: str | None = None
    token_encryption_key: str | None = None
    oauth_redirect_base: str | None = None
    frontend_base_url: str | None = None
    youtube_api_key: str | None = None
    daily_quota_units: int | None = None
    metadata_system_prompt: str | None = None
    cpu_target_percent: int | None = None
    ram_target_percent: int | None = None
    ffmpeg_threads: int | None = None
    max_heavy_jobs: int | None = None
    max_concurrent_jobs: int | None = None
    retry_max_attempts: int | None = None
    retry_backoff_seconds: int | None = None
    horizontal_stock_target_default: int | None = None
    shorts_per_video: int | None = None
    clip_min_seconds: int | None = None
    clip_max_seconds: int | None = None
    min_free_disk_gb: float | None = None
    download_rate_limit_kbps: int | None = None
    planned_poll_interval_minutes: int | None = None
    media_retention_days: int | None = None
    transcription_method: str | None = None
    whisper_model: str | None = None
    whisper_language: str | None = None
    burn_subtitles: bool | None = None
    subtitle_font_size: int | None = None
    subtitle_position: str | None = None
