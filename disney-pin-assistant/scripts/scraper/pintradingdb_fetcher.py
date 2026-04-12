"""HTTP fetcher for PinTradingDB with rate limiting and retry logic."""

import asyncio
import os
from contextlib import asynccontextmanager

import httpx

from scraper.pinpics_fetcher import RateLimiter

PINTRADINGDB_BASE = "https://pintradingdb.com"
LIST_URL = f"{PINTRADINGDB_BASE}/ajaxPinList.php"
DETAIL_URL = f"{PINTRADINGDB_BASE}/pin"
USER_AGENT = "DisneyPinAssistant/1.0 (personal pin catalog project)"


@asynccontextmanager
async def create_fetcher_client(timeout: float = 30.0):
    """Create a shared httpx client for all fetcher operations.

    Usage:
        async with create_fetcher_client() as client:
            html = await fetch_pin_detail(pin_id, limiter, client=client)
    """
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        http2=False,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
    ) as client:
        yield client


async def _fetch_url(
    url: str,
    limiter: RateLimiter,
    max_retries: int = 5,
    label: str = "",
    client: httpx.AsyncClient | None = None,
) -> httpx.Response | None:
    """Shared fetch helper with persistent client, Retry-After, and exponential backoff."""

    async def _do_request(c: httpx.AsyncClient) -> httpx.Response | None:
        for attempt in range(max_retries):
            await limiter.acquire()
            try:
                response = await c.get(url)

                if response.status_code == 200:
                    return response

                if response.status_code == 404:
                    return None

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            backoff = float(retry_after)
                        except ValueError:
                            backoff = 5.0 * (attempt + 1)
                    else:
                        backoff = 5.0 * (attempt + 1)
                    print(
                        f"[pintradingdb] 429 rate limited for {label!r}, "
                        f"waiting {backoff:.0f}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(backoff)
                    continue

                print(
                    f"[pintradingdb] Unexpected status {response.status_code} for {label!r} "
                    f"(attempt {attempt + 1}/{max_retries})"
                )

            except httpx.TimeoutException:
                backoff = 2.0 * (attempt + 1)
                print(f"[pintradingdb] Timeout fetching {label!r}, waiting {backoff:.0f}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(backoff)
            except Exception as exc:
                print(f"[pintradingdb] Error fetching {label!r}: {exc} (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(2.0)

        print(f"[pintradingdb] Giving up on {label!r} after {max_retries} attempts")
        return None

    if client is not None:
        return await _do_request(client)

    # Fallback: create a one-off client (backwards compat)
    async with create_fetcher_client() as c:
        return await _do_request(c)


async def fetch_pin_list_page(
    page_number: int,
    limiter: RateLimiter,
    max_retries: int = 5,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Fetch the paginated AJAX pin list for a given page number."""
    url = f"{LIST_URL}?pinPage={page_number}"
    response = await _fetch_url(url, limiter, max_retries, label=f"list page {page_number}", client=client)
    return response.text if response is not None else None


async def fetch_pin_detail(
    pin_id: str,
    limiter: RateLimiter,
    max_retries: int = 5,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Fetch the detail page for a given PinTradingDB pin ID."""
    url = f"{DETAIL_URL}/{pin_id}"
    response = await _fetch_url(url, limiter, max_retries, label=f"pin {pin_id}", client=client)
    return response.text if response is not None else None


async def download_pin_image(
    image_url: str,
    pin_id: str,
    output_dir: str,
    limiter: RateLimiter,
    max_retries: int = 5,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Download a pin image to {output_dir}/{pin_id}{ext}.

    Skips the download if the file already exists.
    """
    _, ext = os.path.splitext(image_url.split("?")[0])
    if not ext:
        ext = ".jpg"

    dest_path = os.path.join(output_dir, f"{pin_id}{ext}")

    if os.path.exists(dest_path):
        return dest_path

    response = await _fetch_url(image_url, limiter, max_retries, label=f"image for pin {pin_id}", client=client)
    if response is None:
        return None

    os.makedirs(output_dir, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(response.content)

    return dest_path
