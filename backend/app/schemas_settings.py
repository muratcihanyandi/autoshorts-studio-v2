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
