"""PinPics scraper utilities including rate limiter."""

import asyncio
import time


class RateLimiter:
    """Token-bucket rate limiter for async request throttling."""

    def __init__(self, requests_per_second: float = 2.0):
        self.requests_per_second = requests_per_second
        self._min_interval = 1.0 / requests_per_second
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until the next request slot is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            wait = self._min_interval - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
