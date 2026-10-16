"""System resource endpoints (Raspberry Pi health).

Real measurements via psutil. The first cpu_percent() call after process
start returns 0.0 (no baseline yet); the app seeds a baseline during
startup so polled values are meaningful immediately.
"""
from __future__ import annotations

import psutil
from fastapi import APIRouter

router = APIRouter(tags=["system"])


def _first_temperature() -> float | None:
    # sensors_temperatures exists on Linux only (the Pi reports cpu_thermal).
    get_temps = getattr(psutil, "sensors_temperatures", None)
    if get_temps is None:
        return None
    temps = get_temps()
    for entries in (temps or {}).values():
        for entry in entries:
            if entry.current is not None:
                return round(entry.current, 1)
    return None


@router.get("/system")
async def system_resources() -> dict:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": memory.percent,
        "memory_total_mb": round(memory.total / 1024**2),
        "disk_percent": disk.percent,
        "disk_total_gb": round(disk.total / 1024**3),
        "temperature_c": _first_temperature(),
    }
