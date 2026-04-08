"""CLI for scraping PinPics pin data into a catalog JSON file."""

import argparse
import asyncio
import json
import os
import sys

# Ensure the scripts directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

from scraper.pinpics_fetcher import RateLimiter, fetch_pin_page
from scraper.pinpics_parser import parse_pin_page
from scraper.normalizer import normalize_entry

CATEGORY_RANGES = {
    "le-2021": (140000, 145000),
    "le-2022": (145000, 150000),
    "le-2023": (150000, 155000),
    "le-2024": (155000, 160000),
    "hm-recent": (135000, 140000),
    "rack-common": (120000, 130000),
}

DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(__file__), "scraper", "output", "pinpics_catalog.json"
)


def load_existing(output_path: str) -> dict[int, dict]:
    """Load existing output file and return a dict keyed by source_reference_id."""
    if not os.path.exists(output_path):
        return {}
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        return {int(e["source_reference_id"]): e for e in entries if "source_reference_id" in e}
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"[warning] Could not load existing output ({exc}), starting fresh.")
        return {}


def save_entries(output_path: str, entries: list[dict]) -> None:
    """Write entries list to the output JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


async def scrape(args: argparse.Namespace) -> None:
    # Determine pin ID range
    if args.category:
        start, end = CATEGORY_RANGES[args.category]
    else:
        start, end = args.start, args.end

    output_path = args.output

    # Resume: load existing entries and build skip set
    existing: dict[int, dict] = {}
    if args.resume:
        existing = load_existing(output_path)
        if existing:
            print(f"[resume] Loaded {len(existing)} existing entries, skipping those IDs.")

    entries: list[dict] = list(existing.values())
    skipped = 0

    limiter = RateLimiter(requests_per_second=args.rate)

    total_range = end - start
    fetched = 0

    print(f"[scraper] Scraping pin IDs {start}–{end} ({total_range} pins)")

    for pin_id in range(start, end):
        if args.resume and pin_id in existing:
            skipped += 1
            continue

        html = await fetch_pin_page(pin_id, limiter)
        if html is None:
            fetched += 1
        else:
            raw = parse_pin_page(html, str(pin_id))
            normalized = normalize_entry(raw)
            entries.append(normalized)
            fetched += 1

        processed = fetched + skipped
        if processed % 100 == 0:
            print(
                f"[progress] Processed {processed}/{total_range} "
                f"| Entries collected: {len(entries)}"
            )

        if fetched % 500 == 0 and fetched > 0:
            save_entries(output_path, entries)
            print(f"[checkpoint] Saved {len(entries)} entries to {output_path}")

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
        prog="scrape_pinpics",
        description="Scrape PinPics pin data into a catalog JSON file.",
    )

    range_group = parser.add_mutually_exclusive_group(required=True)
    range_group.add_argument(
        "--category",
        choices=list(CATEGORY_RANGES.keys()),
        help="Predefined category range to scrape.",
    )

    start_end = parser.add_argument_group("custom range (required if --category not used)")
    range_group.add_argument(
        "--start",
        type=int,
        metavar="START_ID",
        help="Start pin ID (inclusive).",
    )

    parser.add_argument(
        "--end",
        type=int,
        metavar="END_ID",
        help="End pin ID (exclusive). Required when --start is used.",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=1.0,
        metavar="RPS",
        help="Requests per second (default: 1.0).",
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
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Validate: if --start is given, --end is required
    if args.start is not None and args.end is None:
        parser.error("--end is required when --start is specified.")
    if args.start is not None and args.end is not None and args.end <= args.start:
        parser.error("--end must be greater than --start.")

    asyncio.run(scrape(args))


if __name__ == "__main__":
    main()
