"""HTTP fetcher for PinPics with rate limiting and retry logic."""

import asyncio
import time

import httpx

PINPICS_URL = "https://www.pinpics.com/pinMT.php"
USER_AGENT = "DisneyPinAssistant/1.0 (personal pin catalog project)"


class RateLimiter:
    """Enforces a minimum interval between requests."""

    def __init__(self, requests_per_second: float = 1.0):
        self._interval = 1.0 / requests_per_second
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            wait = self._interval - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


async def fetch_pin_page(
    pin_id: int,
    limiter: RateLimiter,
    max_retries: int = 3,
) -> str | None:
    """Fetch the HTML page for a given PinPics pin ID.

    Returns HTML string on success, None on 404 or after exhausting retries.
    """
    url = f"{PINPICS_URL}?pinID={pin_id}"
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(max_retries):
        await limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 200:
                return response.text

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                backoff = 2 ** attempt
                print(f"[fetcher] 429 rate limited for pin {pin_id}, backing off {backoff}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(backoff)
                continue

            print(f"[fetcher] Unexpected status {response.status_code} for pin {pin_id} (attempt {attempt + 1}/{max_retries})")

        except httpx.TimeoutException:
            print(f"[fetcher] Timeout fetching pin {pin_id} (attempt {attempt + 1}/{max_retries})")
        except Exception as exc:
            print(f"[fetcher] Error fetching pin {pin_id}: {exc} (attempt {attempt + 1}/{max_retries})")

    print(f"[fetcher] Giving up on pin {pin_id} after {max_retries} attempts")
    return None
