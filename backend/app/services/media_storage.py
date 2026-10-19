"""Media storage layout under MEDIA_ROOT.

The studio keeps every artifact on a labelled folder tree so nothing
mixes: downloads (raw source videos), edited (work-in-progress
cuts), clips (finished shorts ready to publish), stock (private clip
stock), tmp (scratch; the worker's cleanup pass prunes it). Folder
names are ASCII by project convention.

Container path is configured via MEDIA_ROOT (deployment mounts
/mnt/usb/Autoshorts_Studio there); empty value keeps the feature off
(local runs and tests create nothing).
"""
from __future__ import annotations

from pathlib import Path

MEDIA_SUBDIRS = ("downloads", "edited", "clips", "stock", "tmp")


def ensure_media_tree(root: str | Path) -> dict[str, Path]:
    """Create the labelled folder tree under root; return name -> path."""
    base = Path(root)
    paths: dict[str, Path] = {}
    for name in MEDIA_SUBDIRS:
        path = base / name
        path.mkdir(parents=True, exist_ok=True)
        paths[name] = path
    return paths


def media_subdir(root: str | Path, name: str) -> Path:
    """Resolve one labelled subfolder (must exist in MEDIA_SUBDIRS)."""
    if name not in MEDIA_SUBDIRS:
        raise ValueError(f"Bilinmeyen medya klasoru: {name}")
    return Path(root) / name
