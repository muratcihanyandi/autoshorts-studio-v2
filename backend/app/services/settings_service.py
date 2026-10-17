"""Site-managed runtime settings.

Overrides live in the app_meta table under the 'runtime_settings' key
(one JSON blob, field -> value). Resolution order: a non-empty database
override wins over the process environment; clearing a field ("" in the
PUT payload) removes the override and falls back to the environment.

Secret fields (API keys, client secret, encryption key) are stored in the
database but never leave through API responses: the view layer exposes
only configured/source plus a last-4-characters hint, and the audit
trail records field NAMES, never values.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import AppMeta
from app.schemas_settings import (
    IntSettingOut,
    PlainSettingOut,
    SecretSettingOut,
    SettingSource,
    SettingsOut,
    SettingsUpdate,
)
from app.services.channel_service import record_event

RUNTIME_SETTINGS_KEY = "runtime_settings"

SECRET_FIELDS = (
    "youtube_api_key",
    "google_client_secret",
    "token_encryption_key",
)

EDITABLE_FIELDS = (
    "google_client_id",
    "google_client_secret",
    "token_encryption_key",
    "oauth_redirect_base",
    "frontend_base_url",
    "youtube_api_key",
    "daily_quota_units",
)

URL_FIELDS = ("oauth_redirect_base", "frontend_base_url")

# Hint yalnızca yeterince uzun değerlerde verilir; kısa değerlerde son 4
# karakterin kendisi büyük kısmı olabilir.
HINT_MIN_LENGTH = 8

DAILY_QUOTA_MIN = 1
DAILY_QUOTA_MAX = 1_000_000


class SettingsServiceError(Exception):
    """Validation failure with a user-facing Turkish message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _validate(field: str, value: object) -> None:
    if field in URL_FIELDS:
        parts = urlsplit(str(value))
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise SettingsServiceError(
                f"{field} geçerli bir http(s) adresi olmalı."
            )
    elif field == "token_encryption_key":
        try:
            Fernet(str(value).encode())
        except Exception as exc:  # noqa: BLE001 - biçim hatası demesi yeterli
            raise SettingsServiceError(
                "token_encryption_key geçerli bir Fernet anahtarı değil "
                "(32 bayt urlsafe base64 bekleniyor)."
            ) from exc
    elif field == "daily_quota_units":
        if not isinstance(value, int) or not (
            DAILY_QUOTA_MIN <= value <= DAILY_QUOTA_MAX
        ):
            raise SettingsServiceError(
                f"daily_quota_units {DAILY_QUOTA_MIN}..{DAILY_QUOTA_MAX} "
                "aralığında olmalı."
            )


def _hint(effective_value: str) -> str:
    return effective_value[-4:] if len(effective_value) >= HINT_MIN_LENGTH else ""


class SettingsService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    async def _load_overrides(self) -> dict:
        """Read the override blob; any storage error degrades to 'no
        overrides' so the app keeps running on environment settings."""
        try:
            async with self._sessionmaker() as session:
                row = await session.get(AppMeta, RUNTIME_SETTINGS_KEY)
        except Exception:  # noqa: BLE001 - read-only degrade
            return {}
        if row is None or not isinstance(row.value, dict):
            return {}
        return {
            k: v
            for k, v in row.value.items()
            if k in EDITABLE_FIELDS and v not in (None, "")
        }

    async def effective_settings(self) -> Settings:
        """Environment settings overlaid by non-empty database overrides."""
        overrides = await self._load_overrides()
        if not overrides:
            return self._settings
        return self._settings.model_copy(update=overrides)

    def _source_of(self, field: str, overrides: dict) -> SettingSource:
        if field in overrides:
            return SettingSource.database
        if getattr(self._settings, field):
            return SettingSource.environment
        return SettingSource.unset

    def _view(self, effective: Settings, overrides: dict) -> SettingsOut:
        def plain(field: str) -> PlainSettingOut:
            return PlainSettingOut(
                value=str(getattr(effective, field) or ""),
                source=self._source_of(field, overrides),
            )

        def secret(field: str) -> SecretSettingOut:
            value = str(getattr(effective, field) or "")
            return SecretSettingOut(
                configured=bool(value),
                source=self._source_of(field, overrides),
                hint=_hint(value),
            )

        return SettingsOut(
            google_client_id=plain("google_client_id"),
            google_client_secret=secret("google_client_secret"),
            token_encryption_key=secret("token_encryption_key"),
            oauth_redirect_base=plain("oauth_redirect_base"),
            frontend_base_url=plain("frontend_base_url"),
            youtube_api_key=secret("youtube_api_key"),
            daily_quota_units=IntSettingOut(
                value=effective.daily_quota_units,
                source=self._source_of("daily_quota_units", overrides),
            ),
        )

    async def view(self) -> SettingsOut:
        return self._view(await self.effective_settings(), await self._load_overrides())

    async def update(self, patch: SettingsUpdate) -> SettingsOut:
        """Apply the patch, audit field names, and return the fresh view."""
        incoming = patch.model_dump(exclude_unset=True)
        changed: list[str] = []
        cleared: list[str] = []

        async with self._sessionmaker() as session:
            row = await session.get(AppMeta, RUNTIME_SETTINGS_KEY)
            blob: dict = dict(row.value) if row is not None and isinstance(row.value, dict) else {}

            for field, value in incoming.items():
                if field not in EDITABLE_FIELDS:
                    continue
                if value is None:
                    continue
                if value == "":
                    if field in blob:
                        del blob[field]
                        cleared.append(field)
                    continue
                if field == "daily_quota_units":
                    _validate(field, value)
                    blob[field] = value
                    changed.append(field)
                    continue
                value = str(value).strip()
                if not value:
                    # Yalnızca boşluklardan oluşan girdi temizleme sayılır.
                    if field in blob:
                        del blob[field]
                        cleared.append(field)
                    continue
                _validate(field, value)
                blob[field] = value
                changed.append(field)

            if not (changed or cleared):
                await session.rollback()
                return await self.view()

            if row is None:
                row = AppMeta(key=RUNTIME_SETTINGS_KEY, value=blob)
                session.add(row)
            else:
                row.value = blob

            # Denetim izi yalnızca alan ADLARINI taşır; değerler asla.
            record_event(
                session,
                None,
                "settings.update",
                {"fields": sorted(changed), "cleared": sorted(cleared)},
            )
            await session.commit()

        return await self.view()
