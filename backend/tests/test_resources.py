"""Rate limiter and temp cleanup (Milestone 6 resource management)."""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.rate_limiter import TokenBucket
from app.services.temp_cleanup import CleanupError, cleanup_temp_dir


class TestTokenBucket:
    def test_measured_rate_limits_throughput(self):
        async def scenario() -> float:
            # 250 KB/s burs ile 500 KB -> ~1 sn (1 sn burs dahil).
            bucket = TokenBucket(bytes_per_second=250_000)
            return await bucket.pace(500_000, chunk_size=50_000)

        elapsed = asyncio.run(scenario())
        # Burs 250 KB anında; kalan 250 KB 1 sn sürer -> ~1.0 sn alt sınır.
        assert elapsed >= 0.9
        # Makul üst sınır: uyuma ölçümü + tolerans (asla 10x yavaş olmasın).
        assert elapsed < 5.0

    def test_zero_rate_disables_limiting(self):
        async def scenario() -> float:
            bucket = TokenBucket(bytes_per_second=0)
            return await bucket.pace(10_000_000, chunk_size=1024 * 1024)

        elapsed = asyncio.run(scenario())
        assert elapsed < 0.5

    def test_single_wait_within_burst_is_immediate(self):
        async def scenario() -> float:
            bucket = TokenBucket(bytes_per_second=100_000)
            started = asyncio.get_running_loop().time()
            await bucket.wait_for(100_000)  # tam burs
            return asyncio.get_running_loop().time() - started

        assert asyncio.run(scenario()) < 0.2


class TestTempCleanup:
    def _touch(self, path: Path, age_hours: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"gecici")
        stamp = datetime.now(UTC) - timedelta(hours=age_hours)
        mtime = stamp.timestamp()
        os.utime(path, (mtime, mtime))

    def test_removes_only_stale_files_inside_root(self, tmp_path):
        root = tmp_path / "media-tmp"
        stale = root / "a" / "eski.bin"
        fresh = root / "a" / "yeni.bin"
        self._touch(stale, age_hours=48)
        self._touch(fresh, age_hours=1)

        removed = cleanup_temp_dir(root, max_age_hours=24)

        assert removed == [str(Path("a") / "eski.bin")]
        assert not stale.exists()
        assert fresh.exists()
        assert root.is_dir()  # kök asla silinmez

    def test_empty_dirs_are_pruned(self, tmp_path):
        root = tmp_path / "media-tmp"
        stale = root / "bos-klasor" / "eski.bin"
        self._touch(stale, age_hours=48)

        cleanup_temp_dir(root, max_age_hours=24)

        assert not (root / "bos-klasor").exists()
        assert root.is_dir()

    def test_missing_root_raises(self, tmp_path):
        try:
            cleanup_temp_dir(tmp_path / "yok", max_age_hours=1)
            raised = False
        except CleanupError:
            raised = True
        assert raised
