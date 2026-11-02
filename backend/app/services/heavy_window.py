"""Ağır iş penceresi (2026-11-02, Murat isteği).

Sorun: Pi 5 üzerinde indirme + ffmpeg analiz + transkript + render
işleri gün içinde sürekli koştuğunda CPU/RAM doyuyor; OpenClaw, Immich,
n8n ve freqtrade gibi diğer hizmetler aç kalıyor (backend 137/OOM).

Çözüm: ağır işler (HEAVY_PROCESSING_JOB_TYPES) yalnızca yerel saatle
tanımlı bir gece penceresinde çalışır. Pencere dışında worker hafif
işleri (yayınlama, keşif) yürütmeye devam eder — sistem tamamen durmaz,
sadece Pi'yi yoran kısım ertelenir.

Pencere başlangıcı bitişten büyükse gece yarısını aşan aralık kabul
edilir (23:00 -> 06:00). Saf fonksiyonlar: test edilebilir, I/O yok.
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Europe/Istanbul"


def parse_clock(value: str | None, fallback: str) -> time:
    """'HH:MM' -> time; bozuk/boş değer varsayılana düşer."""
    try:
        hours, minutes = str(value or "").strip().split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError):
        hours, minutes = fallback.split(":")
        return time(int(hours), int(minutes))


def in_window(
    now: datetime,
    start: time,
    end: time,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> bool:
    """Şu an pencere içinde mi?

    start == end  -> pencere kapalı sayılır (boş aralık).
    start <  end  -> aynı gün içinde aralık.
    start >  end  -> gece yarısını aşan aralık.
    """
    if start == end:
        return False
    try:
        local = now.astimezone(ZoneInfo(timezone_name or DEFAULT_TIMEZONE))
    except Exception:  # noqa: BLE001 - bozuk saat dilimi: UTC'ye düş
        local = now
    current = local.time()
    if start < end:
        return start <= current < end
    return current >= start or current < end


def window_open(
    *,
    enabled: bool,
    start: str | None,
    end: str | None,
    timezone_name: str = DEFAULT_TIMEZONE,
    now: datetime | None = None,
) -> bool:
    """Efektif ayarlardan pencere durumu. Kapalıysa her zaman True
    (kısıt yok) döner ki varsayılan davranış değişmesin."""
    if not enabled:
        return True
    moment = now or datetime.now(ZoneInfo(timezone_name or DEFAULT_TIMEZONE))
    return in_window(
        moment,
        parse_clock(start, "01:00"),
        parse_clock(end, "07:00"),
        timezone_name,
    )


def describe_window(start: str | None, end: str | None) -> str:
    return f"{start or '01:00'}-{end or '07:00'}"
