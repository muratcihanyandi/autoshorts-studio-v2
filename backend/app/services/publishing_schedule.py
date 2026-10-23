"""Timezone-aware publishing schedule planning (M10).

Slots come from the channel's publishing profile: `settings.publish_times`
(a list of "HH:MM" local times, default three spread slots) in the
profile's timezone (default Europe/Istanbul). The next due slot is the
first slot strictly after the last publication (or now, when nothing
was published yet). Pure functions — no I/O — so scheduling behavior
is fully unit-testable.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_PUBLISH_TIMES = ("09:00", "14:00", "20:00")
# Shorts (dikey) yayınlar kendi prime time'ında çıkar: öğle, ikindi ve
# akşam zirvesi. Yatay videolar klasik dilimlerde kalır.
DEFAULT_VERTICAL_PUBLISH_TIMES = ("12:00", "17:00", "21:00")
DEFAULT_TIMEZONE = "Europe/Istanbul"


class ScheduleError(Exception):
    """Invalid schedule configuration."""


def parse_publish_times(raw) -> tuple[time, ...]:
    """'HH:MM' list -> sorted time tuple; validates values."""
    if raw is None:
        return tuple(_parse_slot(slot) for slot in DEFAULT_PUBLISH_TIMES)
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ScheduleError("publish_times bos olamaz.")
    slots = tuple(sorted(_parse_slot(slot) for slot in raw))
    if len(set(slots)) != len(slots):
        raise ScheduleError("publish_times yinelenen saat iceriyor.")
    return slots


def _parse_slot(value) -> time:
    if isinstance(value, time):
        return value  # hazir time nesnesi (slots_for_orientation ciktisi)
    try:
        text = str(value).strip()
        hours, minutes = text.split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError) as exc:
        raise ScheduleError(f"Gecersiz saat dilimi: {value!r}") from exc


def slots_for_orientation(
    settings: dict | None, orientation: str
) -> tuple[time, ...]:
    """Yön bazlı yayın saatleri: dikey (shorts) saatleri profil
    ayarından, ayarlanmamışsa shorts prime time varsayılanından gelir;
    yatay videolar klasik publish_times dilimlerini kullanır."""
    raw = settings or {}
    if orientation == "vertical":
        source = raw.get("publish_times_vertical")
        if source is None:
            source = list(DEFAULT_VERTICAL_PUBLISH_TIMES)
        return parse_publish_times(source)
    return parse_publish_times(raw.get("publish_times"))


def next_due_time(
    *,
    now_utc: datetime,
    timezone_name: str,
    publish_times,
    last_published_at: datetime | None,
) -> datetime:
    """Next slot (UTC) strictly after the reference point.

    Reference = last publication when present (so publishing resumes
    on schedule after any pause), otherwise now.
    """
    tz = ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    slots = parse_publish_times(publish_times)
    reference_utc = last_published_at or now_utc
    reference_local = reference_utc.astimezone(tz)

    # Bugunun kalan slotlari, sonra yarindan itibaren.
    for offset_days in (0, 1, 2):
        day = reference_local.date() + timedelta(days=offset_days)
        for slot in slots:
            candidate_local = datetime.combine(day, slot, tzinfo=tz)
            if candidate_local <= reference_local:
                continue
            return candidate_local.astimezone(ZoneInfo("UTC"))
    # Slot listesi bos olamaz (parse_publish_times garanti eder).
    raise ScheduleError("Uygun saat dilimi bulunamadi.")


def is_due(
    *,
    now_utc: datetime,
    timezone_name: str,
    publish_times,
    last_published_at: datetime | None,
) -> bool:
    """True when the channel missed its slot and should publish now."""
    if last_published_at is None:
        return True  # hic yayinlanmadi: ilk slot hemen
    due = next_due_time(
        now_utc=now_utc,
        timezone_name=timezone_name,
        publish_times=publish_times,
        last_published_at=last_published_at,
    )
    return due <= now_utc
