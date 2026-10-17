"""Token-bucket rate limiter for download bandwidth control.

Milestone 6 acceptance requires download speed limiting to be
measurable: callers await wait_for(n_bytes) before consuming each
chunk, and the bucket paces the stream to the configured bytes/second
(with a one-second burst allowance). Zero rate disables limiting.
"""
from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, bytes_per_second: int) -> None:
        self._rate = max(0, int(bytes_per_second))
        self._capacity = float(self._rate)  # 1 saniyelik burs
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def rate(self) -> int:
        return self._rate

    def _refill(self, now: float) -> None:
        if self._rate <= 0:
            return
        self._tokens = min(
            self._capacity, self._tokens + (now - self._last) * self._rate
        )
        self._last = now

    async def wait_for(self, n_bytes: int) -> None:
        """Pace n_bytes of consumption; sleeps when the budget is short."""
        if self._rate <= 0 or n_bytes <= 0:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                self._refill(now)
                if self._tokens >= n_bytes:
                    self._tokens -= n_bytes
                    return
                deficit = n_bytes - self._tokens
                await asyncio.sleep(deficit / self._rate)

    async def pace(
        self, total_bytes: int, chunk_size: int = 64 * 1024
    ) -> float:
        """Simulate pacing total_bytes in chunks; returns elapsed seconds.

        Used by tests to measure the enforced rate and by callers as a
        reference pattern for chunked transfers.
        """
        started = time.monotonic()
        remaining = total_bytes
        while remaining > 0:
            take = min(chunk_size, remaining)
            await self.wait_for(take)
            remaining -= take
        return time.monotonic() - started
