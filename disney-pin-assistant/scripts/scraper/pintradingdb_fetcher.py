"""HTTP fetcher for PinTradingDB with rate limiting and retry logic."""

import asyncio
import os

import httpx

from scraper.pinpics_fetcher import RateLimiter

PINTRADINGDB_BASE = "https://pintradingdb.com"
LIST_URL = f"{PINTRADINGDB_BASE}/ajaxPinList.php"
DETAIL_URL = f"{PINTRADINGDB_BASE}/pin"
USER_AGENT = "DisneyPinAssistant/1.0 (personal pin catalog project)"


async def _fetch_url(
    url: str,
    limiter: RateLimiter,
    max_retries: int = 3,
    label: str = "",
) -> httpx.Response | None:
    """Shared fetch helper: returns Response on 200, None on 404, retries on errors.

    Handles 429 with exponential backoff and retries on timeout/other errors.
    """
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(max_retries):
        await limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 200:
                return response

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                backoff = 2 ** attempt
                print(
                    f"[pintradingdb] 429 rate limited for {label!r}, "
                    f"backing off {backoff}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(backoff)
                continue

            print(
                f"[pintradingdb] Unexpected status {response.status_code} for {label!r} "
                f"(attempt {attempt + 1}/{max_retries})"
            )

        except httpx.TimeoutException:
            print(f"[pintradingdb] Timeout fetching {label!r} (attempt {attempt + 1}/{max_retries})")
        except Exception as exc:
            print(f"[pintradingdb] Error fetching {label!r}: {exc} (attempt {attempt + 1}/{max_retries})")

    print(f"[pintradingdb] Giving up on {label!r} after {max_retries} attempts")
    return None


async def fetch_pin_list_page(
    page_number: int,
    limiter: RateLimiter,
    max_retries: int = 3,
) -> str | None:
    """Fetch the paginated AJAX pin list for a given page number.

    Returns HTML string on 200, None on 404 or after exhausting retries.
    """
    url = f"{LIST_URL}?pinPage={page_number}"
    response = await _fetch_url(url, limiter, max_retries, label=f"list page {page_number}")
    return response.text if response is not None else None


async def fetch_pin_detail(
    pin_id: str,
    limiter: RateLimiter,
    max_retries: int = 3,
) -> str | None:
    """Fetch the detail page for a given PinTradingDB pin ID.

    Returns HTML string on 200, None on 404 or after exhausting retries.
    """
    url = f"{DETAIL_URL}/{pin_id}"
    response = await _fetch_url(url, limiter, max_retries, label=f"pin {pin_id}")
    return response.text if response is not None else None


async def download_pin_image(
    image_url: str,
    pin_id: str,
    output_dir: str,
    limiter: RateLimiter,
    max_retries: int = 3,
) -> str | None:
    """Download a pin image to {output_dir}/{pin_id}{ext}.

    Skips the download if the file already exists.
    Returns the local file path on success, None on failure.
    """
    _, ext = os.path.splitext(image_url.split("?")[0])
    if not ext:
        ext = ".jpg"

    dest_path = os.path.join(output_dir, f"{pin_id}{ext}")

    if os.path.exists(dest_path):
        print(f"[pintradingdb] Image already exists, skipping: {dest_path}")
        return dest_path

    response = await _fetch_url(image_url, limiter, max_retries, label=f"image for pin {pin_id}")
    if response is None:
        return None

    os.makedirs(output_dir, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(response.content)

    print(f"[pintradingdb] Saved image: {dest_path}")
    return dest_path
