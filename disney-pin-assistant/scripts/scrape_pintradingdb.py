"""CLI for scraping PinTradingDB pin data and images into a catalog."""

import argparse
import asyncio
import json
import os
import sys

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


async def discover_pin_ids(
    start_page: int,
    end_page: int,
    limiter: RateLimiter,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Paginate through list pages and collect all pin IDs."""
    all_ids: list[str] = []
    seen: set[str] = set()

    for page_num in range(start_page, end_page + 1):
        print(f"[discover] Fetching list page {page_num}/{end_page}...")
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

        print(f"[discover] Page {page_num}: found {len(page_ids)} pins ({len(new_ids)} new), total so far: {len(all_ids)}")

    return all_ids


async def scrape(args: argparse.Namespace) -> None:
    output_path = args.output
    image_dir = os.path.abspath(args.image_dir)

    # Resume: load existing entries and build skip set
    existing: dict[str, dict] = {}
    if args.resume:
        existing = load_existing(output_path)
        if existing:
            print(f"[resume] Loaded {len(existing)} existing entries, skipping those IDs.")

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

        total = len(pin_ids)
        fetched = 0
        skipped = 0
        burst_pause = args.burst_pause

        est_seconds = total * (2 / args.rate)  # ~2 requests per pin (detail + image)
        est_minutes = est_seconds / 60
        print(f"[scraper] Processing {total} pins (est. {est_minutes:.0f} min at {args.rate} RPS)...")

        for i, pin_id in enumerate(pin_ids, start=1):
            if args.resume and pin_id in entries:
                skipped += 1
                continue

            html = await fetch_pin_detail(pin_id, limiter, client=client)
            if html is None:
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

            processed = fetched + skipped
            if processed % 50 == 0 and processed > 0:
                print(
                    f"[progress] Processed {processed}/{total} "
                    f"| Entries collected: {len(entries)}"
                )

            if fetched % 200 == 0 and fetched > 0:
                save_entries(output_path, entries)
                print(f"[checkpoint] Saved {len(entries)} entries to {output_path}")

            # Burst pause: rest every N pins to stay under rate limit windows
            if burst_pause > 0 and fetched > 0 and fetched % args.burst_size == 0:
                print(f"[pause] Cooling down {burst_pause}s after {fetched} pins...")
                await asyncio.sleep(burst_pause)

    # Final save
    save_entries(output_path, entries)
    print(f"\n[done] Total entries collected: {len(entries)}")
    print(f"[done] Output saved to: {output_path}")
    print(
        f"\nTo import into the catalog, run:\n"
        f"  python scripts/import_catalog.py --input {output_path}"
    )


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
        help="First list page to scrape (default: 1).",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=100,
        metavar="PAGE",
        help="Last list page to scrape (default: 100).",
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
