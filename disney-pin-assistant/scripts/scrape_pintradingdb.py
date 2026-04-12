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


def format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    hours = seconds / 3600
    return f"{hours:.1f}h"


async def discover_pin_ids(
    start_page: int,
    end_page: int,
    limiter: RateLimiter,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Paginate through list pages and collect all pin IDs.

    PinTradingDB returns page 1 = newest pins, page 574 = oldest.
    So start_page=1 gives reverse chronological order (newest first).
    """
    all_ids: list[str] = []
    seen: set[str] = set()
    total_pages = end_page - start_page + 1

    for page_num in range(start_page, end_page + 1):
        page_index = page_num - start_page + 1
        print(f"[discover] Fetching list page {page_num} ({page_index}/{total_pages})...")
        html = await fetch_pin_list_page(page_num, limiter, client=client)
        if html is None:
            print(f"[discover] No response for page {page_num}, stopping discovery.")
            break

        page_ids = extract_pin_ids_from_list(html)
        if not page_ids:
            print(f"[discover] No pin IDs found on page {page_num}, stopping discovery.")
            break

        new_ids = [pid for pid in page_ids if pid not in seen]
        seen.update(new_ids)
        all_ids.extend(new_ids)

        if page_index % 10 == 0 or page_num == end_page:
            print(f"[discover] Progress: {page_index}/{total_pages} pages, {len(all_ids)} pins found")

    return all_ids


async def scrape(args: argparse.Namespace) -> None:
    output_path = args.output
    image_dir = os.path.abspath(args.image_dir)

    # Resume: load existing entries and build skip set
    existing: dict[str, dict] = {}
    if args.resume:
        existing = load_existing(output_path)
        if existing:
            print(f"[resume] Loaded {len(existing)} existing entries, will skip those IDs.")

    entries: dict[str, dict] = dict(existing)

    limiter = RateLimiter(requests_per_second=args.rate)

    async with create_fetcher_client() as client:
        # Determine pin IDs to process
        if args.pin_ids:
            pin_ids = [pid.strip() for pid in args.pin_ids.split(",") if pid.strip()]
            print(f"[scraper] Using {len(pin_ids)} provided pin IDs.")
        else:
            print(f"[scraper] Discovering pin IDs from pages {args.start_page}–{args.end_page}...")
            pin_ids = await discover_pin_ids(args.start_page, args.end_page, limiter, client=client)
            print(f"[scraper] Discovered {len(pin_ids)} pin IDs total.")

        # Filter out already-scraped IDs when resuming
        if args.resume and existing:
            to_scrape = [pid for pid in pin_ids if pid not in existing]
            print(f"[resume] {len(pin_ids) - len(to_scrape)} already scraped, {len(to_scrape)} remaining.")
        else:
            to_scrape = pin_ids

        total = len(to_scrape)
        if total == 0:
            print("[scraper] Nothing to scrape — all pins already collected.")
            return

        burst_pause = args.burst_pause
        # Estimate: ~2 requests/pin at args.rate RPS + burst pauses
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

                # Download image if available
                image_url = raw.get("reference_image_url")
                if image_url:
                    image_path = await download_pin_image(
                        image_url, pin_id, image_dir, limiter, client=client,
                    )
                    if image_path:
                        normalized["image_path"] = image_path

                entries[pin_id] = normalized
                fetched += 1

            # Progress every 10 pins
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

            # Checkpoint save every 100 pins
            if fetched % 100 == 0 and fetched > 0:
                save_entries(output_path, entries)
                print(f"[checkpoint] Saved {len(entries)} entries")

            # Burst pause
            if burst_pause > 0 and fetched > 0 and fetched % args.burst_size == 0:
                print(f"[pause] Cooling down {burst_pause:.0f}s...")
                await asyncio.sleep(burst_pause)

    # Final save
    save_entries(output_path, entries)
    elapsed = time.monotonic() - start_time
    print(f"\n[done] Scraped {fetched} pins in {format_eta(elapsed)}")
    print(f"[done] Total entries: {len(entries)} ({errors} errors)")
    print(f"[done] Output: {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrape_pintradingdb",
        description="Scrape PinTradingDB pin data and images into a catalog JSON file.",
    )

    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        metavar="PAGE",
        help="First list page to scrape (default: 1 = newest pins).",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=574,
        metavar="PAGE",
        help="Last list page to scrape (default: 574 = all pages).",
    )
    parser.add_argument(
        "--pin-ids",
        type=str,
        default=None,
        metavar="ID1,ID2,...",
        help="Comma-separated pin IDs to scrape directly (skips list page discovery).",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=0.33,
        metavar="RPS",
        help="Requests per second (default: 0.33 — tested optimal for PinTradingDB).",
    )
    parser.add_argument(
        "--burst-size",
        type=int,
        default=20,
        metavar="N",
        help="Number of pins to process before pausing (default: 20).",
    )
    parser.add_argument(
        "--burst-pause",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="Seconds to pause after each burst (default: 10). Set to 0 to disable.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip pin IDs already present in the output file.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        metavar="FILE",
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--image-dir",
        type=str,
        default=DEFAULT_IMAGE_DIR,
        metavar="DIR",
        help=f"Directory for downloaded images (default: {DEFAULT_IMAGE_DIR}).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(scrape(args))


if __name__ == "__main__":
    main()
