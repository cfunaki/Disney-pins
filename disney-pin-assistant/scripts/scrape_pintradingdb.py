"""CLI for scraping PinTradingDB pin data and images into a catalog."""

import argparse
import asyncio
import json
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(__file__))

from scraper.pinpics_fetcher import RateLimiter
from scraper.pintradingdb_fetcher import (
    create_fetcher_client,
    fetch_pin_list_page,
    fetch_pin_detail,
    download_pin_image,
)
from scraper.pintradingdb_parser import parse_pin_detail, extract_pin_ids_from_list
from scraper.normalizer import normalize_entry

DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(__file__), "scraper", "output", "pintradingdb_catalog.json"
)
DEFAULT_IMAGE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "catalog_images"
)
DEFAULT_ID_CACHE = os.path.join(
    os.path.dirname(__file__), "scraper", "output", "pin_ids_cache.json"
)


def load_existing(output_path: str) -> dict[str, dict]:
    """Load existing output file and return a dict keyed by source_reference_id."""
    if not os.path.exists(output_path):
        return {}
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        return {str(e["source_reference_id"]): e for e in entries if "source_reference_id" in e}
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"[warning] Could not load existing output ({exc}), starting fresh.")
        return {}


def save_entries(output_path: str, entries: dict[str, dict]) -> None:
    """Write entries dict values to the output JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(list(entries.values()), f, indent=2, ensure_ascii=False)


def load_id_cache(cache_path: str) -> list[str]:
    """Load cached pin IDs from a previous discovery run."""
    if not os.path.exists(cache_path):
        return []
    try:
        with open(cache_path, "r") as f:
            data = json.load(f)
        return data.get("pin_ids", [])
    except (json.JSONDecodeError, KeyError):
        return []


def save_id_cache(cache_path: str, pin_ids: list[str]) -> None:
    """Save discovered pin IDs to cache."""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump({
            "pin_ids": pin_ids,
            "count": len(pin_ids),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, f, indent=2)


def format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    hours = seconds / 3600
    return f"{hours:.1f}h"


async def discover_new_pins(
    cached_ids: set[str],
    limiter: RateLimiter,
    client: httpx.AsyncClient,
) -> list[str]:
    """Scan from page 1 (newest) until we hit pins already in the cache.

    Returns only the new pin IDs not in the cache, in newest-first order.
    Stops after a full page where 80%+ of IDs are already known.
    """
    new_ids: list[str] = []
    page_num = 0

    while True:
        page_num += 1
        html = await fetch_pin_list_page(page_num, limiter, client=client)
        if html is None:
            break

        page_ids = extract_pin_ids_from_list(html)
        if not page_ids:
            break

        page_new = [pid for pid in page_ids if pid not in cached_ids]
        new_ids.extend(page_new)

        overlap_count = len(page_ids) - len(page_new)
        print(f"[discover] Page {page_num}: {len(page_new)} new, {overlap_count} known")

        if overlap_count >= len(page_ids) * 0.8:
            print(f"[discover] Caught up with cached IDs, stopping.")
            break

    return new_ids


async def discover_all_pins(
    start_page: int,
    end_page: int,
    limiter: RateLimiter,
    client: httpx.AsyncClient,
) -> list[str]:
    """Full discovery: paginate through all list pages.

    PinTradingDB page 1 = newest pins, page 574 = oldest.
    """
    all_ids: list[str] = []
    seen: set[str] = set()
    total_pages = end_page - start_page + 1

    for page_num in range(start_page, end_page + 1):
        page_index = page_num - start_page + 1
        html = await fetch_pin_list_page(page_num, limiter, client=client)
        if html is None:
            print(f"[discover] No response for page {page_num}, stopping.")
            break

        page_ids = extract_pin_ids_from_list(html)
        if not page_ids:
            print(f"[discover] Empty page {page_num}, stopping.")
            break

        new_ids = [pid for pid in page_ids if pid not in seen]
        seen.update(new_ids)
        all_ids.extend(new_ids)

        if page_index % 10 == 0 or page_num == end_page:
            print(f"[discover] {page_index}/{total_pages} pages, {len(all_ids)} pins found")

    return all_ids


async def resolve_pin_ids(
    args: argparse.Namespace,
    limiter: RateLimiter,
    client: httpx.AsyncClient,
) -> list[str]:
    """Determine which pin IDs to scrape, using cache when available."""

    if args.pin_ids:
        pin_ids = [pid.strip() for pid in args.pin_ids.split(",") if pid.strip()]
        print(f"[scraper] Using {len(pin_ids)} provided pin IDs.")
        return pin_ids

    cache_path = args.id_cache
    cached_ids = load_id_cache(cache_path)

    if cached_ids:
        print(f"[cache] Loaded {len(cached_ids)} cached pin IDs.")

        print(f"[discover] Checking for new pins...")
        new_ids = await discover_new_pins(set(cached_ids), limiter, client)

        if new_ids:
            print(f"[discover] Found {len(new_ids)} new pins.")
            cached_ids = new_ids + cached_ids
            save_id_cache(cache_path, cached_ids)
            print(f"[cache] Updated cache: {len(cached_ids)} total pin IDs.")
        else:
            print(f"[discover] No new pins found.")

        return cached_ids

    print(f"[discover] No ID cache found. Running full discovery (pages {args.start_page}–{args.end_page})...")
    print(f"[discover] This takes ~30 min on first run. Subsequent runs will be instant.")
    all_ids = await discover_all_pins(args.start_page, args.end_page, limiter, client)
    print(f"[discover] Found {len(all_ids)} pin IDs total.")

    save_id_cache(cache_path, all_ids)
    print(f"[cache] Saved ID cache to {cache_path}")

    return all_ids


async def scrape(args: argparse.Namespace) -> None:
    output_path = args.output
    image_dir = os.path.abspath(args.image_dir)

    existing = load_existing(output_path)
    if existing:
        print(f"[resume] Found {len(existing)} already-scraped entries.")

    entries: dict[str, dict] = dict(existing)
    limiter = RateLimiter(requests_per_second=args.rate)

    async with create_fetcher_client() as client:
        pin_ids = await resolve_pin_ids(args, limiter, client)

        to_scrape = [pid for pid in pin_ids if pid not in existing]
        if len(pin_ids) != len(to_scrape):
            print(f"[resume] {len(pin_ids) - len(to_scrape)} already scraped, {len(to_scrape)} remaining.")

        total = len(to_scrape)
        if total == 0:
            print("[scraper] Nothing to scrape — all pins already collected.")
            return

        burst_pause = args.burst_pause
        secs_per_pin = 2 / args.rate
        burst_overhead = burst_pause / args.burst_size if args.burst_size > 0 else 0
        est_seconds = total * (secs_per_pin + burst_overhead)
        print(f"[scraper] Processing {total} pins (est. {format_eta(est_seconds)} at {args.rate} RPS)...")

        fetched = 0
        errors = 0
        start_time = time.monotonic()

        for i, pin_id in enumerate(to_scrape, start=1):
            html = await fetch_pin_detail(pin_id, limiter, client=client)
            if html is None:
                errors += 1
                fetched += 1
            else:
                raw = parse_pin_detail(html, pin_id)
                normalized = normalize_entry(raw)

                image_url = raw.get("reference_image_url")
                if image_url:
                    image_path = await download_pin_image(
                        image_url, pin_id, image_dir, limiter, client=client,
                    )
                    if image_path:
                        normalized["image_path"] = image_path

                entries[pin_id] = normalized
                fetched += 1

            if fetched % 10 == 0 and fetched > 0:
                elapsed = time.monotonic() - start_time
                rate = fetched / elapsed if elapsed > 0 else 0
                remaining = (total - fetched) / rate if rate > 0 else 0
                print(
                    f"[progress] {fetched}/{total} pins "
                    f"({fetched * 100 // total}%) "
                    f"| {len(entries)} collected "
                    f"| {errors} errors "
                    f"| ETA: {format_eta(remaining)}"
                )

            if fetched % 100 == 0 and fetched > 0:
                save_entries(output_path, entries)
                print(f"[checkpoint] Saved {len(entries)} entries")

            if burst_pause > 0 and fetched > 0 and fetched % args.burst_size == 0:
                print(f"[pause] Cooling down {burst_pause:.0f}s...")
                await asyncio.sleep(burst_pause)

    save_entries(output_path, entries)
    elapsed = time.monotonic() - start_time
    print(f"\n[done] Scraped {fetched} pins in {format_eta(elapsed)}")
    print(f"[done] Total entries: {len(entries)} ({errors} errors)")
    print(f"[done] Output: {output_path}")


async def status(args: argparse.Namespace) -> None:
    """Show scrape progress without making any requests."""
    existing = load_existing(args.output)
    cached_ids = load_id_cache(args.id_cache)

    print(f"Scraped entries: {len(existing)}")
    print(f"Cached pin IDs:  {len(cached_ids)}")

    if cached_ids:
        remaining = [pid for pid in cached_ids if pid not in existing]
        pct = (len(existing) / len(cached_ids)) * 100 if cached_ids else 0
        print(f"Remaining:       {len(remaining)}")
        print(f"Progress:        {pct:.1f}%")

        if remaining:
            secs_per_pin = 2 / args.rate
            burst_overhead = args.burst_pause / args.burst_size if args.burst_size > 0 else 0
            est = len(remaining) * (secs_per_pin + burst_overhead)
            print(f"Est. time left:  {format_eta(est)}")

    if os.path.exists(args.image_dir):
        image_count = len([f for f in os.listdir(args.image_dir) if f.endswith(('.jpg', '.png', '.gif'))])
        print(f"Images on disk:  {image_count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrape_pintradingdb",
        description="Scrape PinTradingDB pin data and images into a catalog JSON file.",
    )

    sub = parser.add_subparsers(dest="command")

    scrape_parser = sub.add_parser("scrape", help="Scrape pins (default if no subcommand)")
    _add_common_args(scrape_parser)
    scrape_parser.add_argument(
        "--pin-ids", type=str, default=None, metavar="ID1,ID2,...",
        help="Comma-separated pin IDs to scrape directly (skips discovery).",
    )

    status_parser = sub.add_parser("status", help="Show scrape progress")
    _add_common_args(status_parser)

    return parser


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--start-page", type=int, default=1, metavar="PAGE",
        help="First list page (default: 1 = newest pins).",
    )
    parser.add_argument(
        "--end-page", type=int, default=574, metavar="PAGE",
        help="Last list page (default: 574 = all pages).",
    )
    parser.add_argument(
        "--rate", type=float, default=0.33, metavar="RPS",
        help="Requests per second (default: 0.33).",
    )
    parser.add_argument(
        "--burst-size", type=int, default=20, metavar="N",
        help="Pins between burst pauses (default: 20).",
    )
    parser.add_argument(
        "--burst-pause", type=float, default=10.0, metavar="SECONDS",
        help="Seconds to pause after each burst (default: 10).",
    )
    parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT, metavar="FILE",
        help=f"Output JSON path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--image-dir", type=str, default=DEFAULT_IMAGE_DIR, metavar="DIR",
        help=f"Image download directory (default: {DEFAULT_IMAGE_DIR}).",
    )
    parser.add_argument(
        "--id-cache", type=str, default=DEFAULT_ID_CACHE, metavar="FILE",
        help=f"Pin ID cache path (default: {DEFAULT_ID_CACHE}).",
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "status":
        asyncio.run(status(args))
    else:
        asyncio.run(scrape(args))


if __name__ == "__main__":
    main()
