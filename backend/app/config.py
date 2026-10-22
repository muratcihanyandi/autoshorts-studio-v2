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
    # Medya diski (flash bellek) guvenlik payi: bu kadar bos alan kalinca
    # yeni agir medya isleri beklemeye alinir (yayinlama surer; stok
    # yayinlanip silindikce yer acilir ve isleme surer). Kullanici
    # istegi 2026-10-21: dolu disk sistemi durdurmaz, bekletir.
    min_free_disk_gb: float = 3.0
    download_rate_limit_kbps: int = 0
    # Labelled media tree root INSIDE the container (deployment mounts
    # /mnt/usb/Autoshorts_Studio here). Empty keeps the feature off.
    media_root: str = ""

    # Milestone 7 media pipeline. External tools run as subprocesses
    # and are probed on PATH; binaries live in the container image.
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    # Klip sure araligi (Gorev 3): alt sinir korunur, ust sinir Shorts'un
    # 3 dakika limitine cekildi — hype ani 20 sn'e sigmiyorsa 1-2 dk da
    # secilebilir. Ayarlar ekranindan degistirilebilir.
    clip_min_seconds: int = 20
    clip_max_seconds: int = 180
    silence_noise_db: float = -35.0
    silence_min_seconds: float = 1.5
    scene_threshold: float = 0.4
    planned_poll_interval_minutes: int = 5
    publish_check_interval_minutes: int = 10
    # Yayinlanmis (herkese acik) medyanin temizligi: 0 = herkese acik
    # yapildiktan hemen sonra sil, N = N gun sonra sil, -1 = hicbir zaman.
    media_retention_days: int = 0

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
    # Dikey (Reels) kliplerine gomulecek altyazi. Stil ASS
    # 1080x1920 piksel uzayindadir (subtitle_style); konum Gorev 2
    # ile serbestlesti — altyazi cimbasi (alt kenar ortasi) yuzde
    # kaydiricilariyla kadranin herhangi bir noktasina tasinabilir.
    # Varsayilan Shorts standarti: alt-orta, ~%78 yukseklik. Ayarlar
    # ekranindaki onizleme ayni degerlerle cizilir. Eski
    # subtitle_position (top/middle/bottom) alani artik kullanilmaz;
    # DB'de eski override kalsa da etkisizdir.
    burn_subtitles: bool = True
    subtitle_font_size: int = 64
    subtitle_style_preset: str = "klasik"
    subtitle_pos_x_percent: int = 50
    subtitle_pos_y_percent: int = 78
    # Dikey (Reels) kliplerinde webcam bolumunun kadran yuksekliginden
    # alacagi pay (yuzde). Kullanici istegi 2026-10-22: oran ayarlanabilir
    # (%30/%70, %35/%65 gibi); webcam ustte, video altta. Dikdortgen
    # zoomlanmaz — bolume contain ile oturur (kirpma yok).
    shorts_webcam_percent: int = 35
    # Bir yatay videodan cikarilacak en fazla Shorts sayisi.
    shorts_per_video: int = 3

    # Studio girişi: ilk ziyaret parolayı app_meta'da oluşturur; sonraki
    # ziyaretler imzalı HttpOnly çerezle açılır. HTTPS arkasında
    # AUTH_COOKIE_SECURE=true yapılmalı (LAN HTTP'de çerez gitmez).
    auth_session_ttl_seconds: int = 7 * 24 * 3600
    auth_cookie_secure: bool = False

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
