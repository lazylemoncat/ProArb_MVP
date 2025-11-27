from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """Simple per-worker rate limiter based on minimum interval."""

    def __init__(self, max_per_second: float):
        self._min_interval = 1.0 / max(max_per_second, 0.0001)
        self._lock = asyncio.Lock()
        self._next_time = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next_time:
                await asyncio.sleep(self._next_time - now)
            self._next_time = time.monotonic() + self._min_interval
