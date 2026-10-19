"""Safe temporary-file cleanup for media scratch directories.

Deletes only files that live INSIDE the given root (resolved-path
check prevents escapes) and only those older than the age threshold.
Empty subdirectories are removed bottom-up; the root itself is never
deleted.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path


class CleanupError(Exception):
    """Refused cleanup (missing/invalid root)."""


def cleanup_temp_dir(
    root: Path | str,
    max_age_hours: float,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Remove stale files under root; return the removed relative paths."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise CleanupError(f"Geçici dizin yok: {root_path}")

    reference = now or datetime.now(UTC)
    removed: list[str] = []

    def _is_stale(path: Path) -> bool:
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except OSError:
            return False
        return mtime < reference - timedelta(hours=max_age_hours)

    files = sorted(
        (p for p in root_path.rglob("*") if p.is_file()),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for path in files:
        # Yol kaçış kontrolü: yalnızca kök içindeki dosyalar.
        try:
            resolved = path.resolve()
            resolved.relative_to(root_path)
        except ValueError:
            continue
        if _is_stale(path):
            try:
                path.unlink()
                removed.append(str(path.relative_to(root_path)))
            except OSError:
                continue

    # Boş alt dizinleri kökten uzağa doğru temizle (kök kalır).
    dirs = sorted(
        (p for p in root_path.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for directory in dirs:
        try:
            next(directory.iterdir())
        except StopIteration:
            try:
                directory.rmdir()
            except OSError:
                pass
        except OSError:
            continue

    return removed
