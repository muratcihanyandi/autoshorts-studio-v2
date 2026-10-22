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
    BoolSettingOut,
    IntSettingOut,
    PlainSettingOut,
    SecretSettingOut,
    SettingSource,
    SettingsOut,
    SettingsUpdate,
)
from app.services.channel_service import record_event

RUNTIME_SETTINGS_KEY = "runtime_settings"

# Hint yalnızca yeterince uzun değerlerde verilir; kısa değerlerde son 4
# karakterin kendisi büyük kısmı olabilir.
HINT_MIN_LENGTH = 8

DAILY_QUOTA_MIN = 1
DAILY_QUOTA_MAX = 1_000_000

# Metaveri sistem promptu için makul üst sınır (M13).
METADATA_PROMPT_MAX_LENGTH = 8000

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
    "metadata_system_prompt",
    # Kaynak limitleri ve uretim ayarlari (Start/Stop donemi). Worker
    # her dongude efektif ayarlari yeniden okur: buradan degistirilen
    # degerler yeniden baslatma olmadan is akisina uygulanir.
    "cpu_target_percent",
    "ram_target_percent",
    "ffmpeg_threads",
    "max_heavy_jobs",
    "max_concurrent_jobs",
    "retry_max_attempts",
    "retry_backoff_seconds",
    "horizontal_stock_target_default",
    "shorts_per_video",
    "clip_min_seconds",
    "clip_max_seconds",
    "min_free_disk_gb",
    "download_rate_limit_kbps",
    "planned_poll_interval_minutes",
    # Yayinlanmis medyanin temizligi: -1 hicbir zaman, 0 yayin aninda,
    # N gun sonra (public_at tabanli).
    "media_retention_days",
    "transcription_method",
    "whisper_model",
    "whisper_language",
    # Dikey klip altyazi gomme (ASS stili; onizleme ayni degerleri
    # kullandigi icin render aninda etkili olur). Gorev 1+2: 5 stil
    # secenegi ve kadran uzerinde serbest konum kaydiricilari.
    "burn_subtitles",
    "subtitle_font_size",
    "subtitle_style_preset",
    "subtitle_pos_x_percent",
    "subtitle_pos_y_percent",
    # Dikey klip webcam/video bolum orani (yuzde; kalan videoya kalir).
    "shorts_webcam_percent",
)

URL_FIELDS = ("oauth_redirect_base", "frontend_base_url")

# Sayisal alanlar: (alt, ust) sinirlariyla. 0 genellikle "kapali".
INT_FIELDS: dict[str, tuple[int, int]] = {
    "daily_quota_units": (DAILY_QUOTA_MIN, DAILY_QUOTA_MAX),
    "cpu_target_percent": (0, 100),
    "ram_target_percent": (0, 100),
    "ffmpeg_threads": (0, 32),
    "max_heavy_jobs": (1, 8),
    "max_concurrent_jobs": (1, 8),
    "retry_max_attempts": (1, 10),
    "retry_backoff_seconds": (0, 3600),
    "horizontal_stock_target_default": (1, 50),
    "shorts_per_video": (1, 10),
    "clip_min_seconds": (5, 120),
    "clip_max_seconds": (20, 180),
    "download_rate_limit_kbps": (0, 10_000_000),
    "planned_poll_interval_minutes": (1, 1440),
    "media_retention_days": (-1, 3650),
    "subtitle_font_size": (24, 140),
    "subtitle_pos_x_percent": (0, 100),
    "subtitle_pos_y_percent": (0, 100),
    "shorts_webcam_percent": (20, 50),
}

FLOAT_FIELDS: dict[str, tuple[float, float]] = {
    "min_free_disk_gb": (0.0, 10000.0),
}

CHOICE_FIELDS: dict[str, tuple[str, ...]] = {
    "transcription_method": ("sidecar", "whisper"),
    "subtitle_style_preset": (
        "klasik",
        "shorts_sari",
        "anton",
        "kutu",
        "noto",
    ),
}

BOOL_FIELDS = ("burn_subtitles",)

# Sadece okunur goruntelenen ortam alanlari (degistirilmesi calisan
# dosya yollarini bozar); ayarlar ekraninda bilgi amaclidir.
READ_ONLY_FIELDS = ("media_root",)

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
    elif field in INT_FIELDS:
        low, high = INT_FIELDS[field]
        if not isinstance(value, int) or isinstance(value, bool) or not (
            low <= value <= high
        ):
            raise SettingsServiceError(
                f"{field} {low}..{high} aralığında bir tam sayı olmalı."
            )
    elif field in FLOAT_FIELDS:
        low, high = FLOAT_FIELDS[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (
            low <= float(value) <= high
        ):
            raise SettingsServiceError(
                f"{field} {low}..{high} aralığında bir sayı olmalı."
            )
    elif field in CHOICE_FIELDS:
        allowed = CHOICE_FIELDS[field]
        if str(value) not in allowed:
            raise SettingsServiceError(
                f"{field} şu değerlerden biri olmalı: {', '.join(allowed)}."
            )
    elif field == "metadata_system_prompt":
        if len(str(value)) > METADATA_PROMPT_MAX_LENGTH:
            raise SettingsServiceError(
                "metadata_system_prompt en fazla "
                f"{METADATA_PROMPT_MAX_LENGTH} karakter olabilir."
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

        def number(field: str) -> IntSettingOut:
            return IntSettingOut(
                value=int(getattr(effective, field) or 0),
                source=self._source_of(field, overrides),
            )

        return SettingsOut(
            google_client_id=plain("google_client_id"),
            google_client_secret=secret("google_client_secret"),
            token_encryption_key=secret("token_encryption_key"),
            oauth_redirect_base=plain("oauth_redirect_base"),
            frontend_base_url=plain("frontend_base_url"),
            youtube_api_key=secret("youtube_api_key"),
            daily_quota_units=number("daily_quota_units"),
            metadata_system_prompt=plain("metadata_system_prompt"),
            cpu_target_percent=number("cpu_target_percent"),
            ram_target_percent=number("ram_target_percent"),
            ffmpeg_threads=number("ffmpeg_threads"),
            max_heavy_jobs=number("max_heavy_jobs"),
            max_concurrent_jobs=number("max_concurrent_jobs"),
            retry_max_attempts=number("retry_max_attempts"),
            retry_backoff_seconds=number("retry_backoff_seconds"),
            horizontal_stock_target_default=number(
                "horizontal_stock_target_default"
            ),
            shorts_per_video=number("shorts_per_video"),
            clip_min_seconds=number("clip_min_seconds"),
            clip_max_seconds=number("clip_max_seconds"),
            min_free_disk_gb=plain("min_free_disk_gb"),
            download_rate_limit_kbps=number("download_rate_limit_kbps"),
            planned_poll_interval_minutes=number(
                "planned_poll_interval_minutes"
            ),
            media_retention_days=number("media_retention_days"),
            transcription_method=plain("transcription_method"),
            whisper_model=plain("whisper_model"),
            whisper_language=plain("whisper_language"),
            burn_subtitles=BoolSettingOut(
                value=bool(effective.burn_subtitles),
                source=self._source_of("burn_subtitles", overrides),
            ),
            subtitle_font_size=number("subtitle_font_size"),
            subtitle_style_preset=plain("subtitle_style_preset"),
            subtitle_pos_x_percent=number("subtitle_pos_x_percent"),
            subtitle_pos_y_percent=number("subtitle_pos_y_percent"),
            shorts_webcam_percent=number("shorts_webcam_percent"),
            media_root=PlainSettingOut(
                value=str(effective.media_root or ""),
                source=SettingSource.environment,
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
                if field in BOOL_FIELDS:
                    # bool, int'in alt sinifi oldugundan sayi dalindan
                    # once; kapali (False) gecerli bir depo degeridir.
                    if not isinstance(value, bool):
                        raise SettingsServiceError(
                            f"{field} true ya da false olmalı."
                        )
                    blob[field] = value
                    changed.append(field)
                    continue
                if field in INT_FIELDS or field in FLOAT_FIELDS:
                    _validate(field, value)
                    blob[field] = (
                        float(value) if field in FLOAT_FIELDS else int(value)
                    )
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
