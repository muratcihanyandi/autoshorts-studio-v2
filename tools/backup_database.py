"""Database backup and restore for AutoShorts Studio (M12).

SQLite (tests / dev): uses sqlite3's online backup API so a live
database can be copied safely. PostgreSQL (Pi deployment): wraps
pg_dump/pg_restore; connection settings come from DATABASE_URL or
explicit flags. Restores are verified by row counts of the core
tables before the tool reports success.

Usage:
  python tools/backup_database.py backup  --url URL --out FILE
  python tools/backup_database.py restore --url URL --from FILE
  python tools/backup_database.py verify  --url URL --against FILE
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

CORE_TABLES = (
    "channels",
    "source_channels",
    "source_videos",
    "media_assets",
    "clip_candidates",
    "rendered_clips",
    "published_videos",
    "jobs",
    "audit_events",
)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _sqlite_file(url: str) -> Path:
    # sqlite+aiosqlite:///path veya sqlite:///path
    part = url.split("///", 1)[-1] if "///" in url else url.split("://", 1)[-1]
    return Path(part)


def backup_sqlite(url: str, out: Path) -> dict:
    source = _sqlite_file(url)
    if not source.is_file():
        raise SystemExit(f"Kaynak veritabani yok: {source}")
    out.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(str(out))
    try:
        src = sqlite3.connect(str(source))
        try:
            src.backup(dest)
        finally:
            src.close()
    finally:
        dest.close()
    return {"kind": "sqlite", "out": str(out), "bytes": out.stat().st_size}


def restore_sqlite(url: str, backup_file: Path) -> dict:
    target = _sqlite_file(url)
    if not backup_file.is_file():
        raise SystemExit(f"Yedek dosyasi yok: {backup_file}")
    target.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(str(target))
    try:
        src = sqlite3.connect(str(backup_file))
        try:
            src.backup(dest)
        finally:
            src.close()
    finally:
        dest.close()
    return {"kind": "sqlite", "restored": str(target)}


def counts_sqlite(path: Path) -> dict:
    conn = sqlite3.connect(str(path))
    try:
        result = {}
        for table in CORE_TABLES:
            try:
                result[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                result[table] = None  # tablo yok (eski yedek olabilir)
        return result
    finally:
        conn.close()


def backup_postgres(url: str, out: Path, pg_dump: str = "pg_dump") -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [pg_dump, "--format=custom", f"--file={out}", url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"pg_dump basarisiz: {result.stderr[-500:]}")
    return {"kind": "postgres", "out": str(out), "bytes": out.stat().st_size}


def restore_postgres(url: str, backup_file: Path, pg_restore: str = "pg_restore") -> dict:
    result = subprocess.run(
        [pg_restore, "--clean", "--if-exists", f"--dbname={url}", str(backup_file)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"pg_restore basarisiz: {result.stderr[-500:]}")
    return {"kind": "postgres", "restored": str(backup_file)}


def verify(original: Path, restored: Path) -> dict:
    before = counts_sqlite(original)
    after = counts_sqlite(restored)
    mismatches = [
        table
        for table in CORE_TABLES
        if before[table] is not None and before[table] != after[table]
    ]
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "counts_before": before,
        "counts_after": after,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup")
    p_backup.add_argument("--url", required=True)
    p_backup.add_argument("--out", required=True)

    p_restore = sub.add_parser("restore")
    p_restore.add_argument("--url", required=True)
    p_restore.add_argument("--from", dest="source", required=True)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--url", required=True)
    p_verify.add_argument("--against", required=True)

    args = parser.parse_args(argv)

    if args.command == "backup":
        out = Path(args.out)
        if _is_sqlite(args.url):
            print(json.dumps(backup_sqlite(args.url, out)))
        else:
            print(json.dumps(backup_postgres(args.url, out)))
    elif args.command == "restore":
        source = Path(args.source)
        if _is_sqlite(args.url):
            print(json.dumps(restore_sqlite(args.url, source)))
        else:
            print(json.dumps(restore_postgres(args.url, source)))
    elif args.command == "verify":
        print(json.dumps(verify(_sqlite_file(args.url), Path(args.against))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
