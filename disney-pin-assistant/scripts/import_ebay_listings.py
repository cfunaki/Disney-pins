"""Import eBay seller listings as catalog entries and ground truth.

Usage:
    python scripts/import_ebay_listings.py --seller <username> [--max 200] [--sold-only] [--rate 2.0]
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ebay_import.finding_api import fetch_sold_listings
from scripts.ebay_import.listing_parser import parse_listing
from scripts.scraper.pinpics_fetcher import RateLimiter
from src.services.ebay_client import browse_api_seller_search, browse_api_item_detail

OUTPUT_DIR = Path(__file__).resolve().parent / "ebay_import" / "output"
SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"
GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "evaluation" / "ground_truth.json"


def load_existing_ids(ground_truth_path: Path) -> set[str]:
    """Load existing eBay item IDs from ground truth file for deduplication."""
    if not ground_truth_path.exists():
        return set()
    data = json.loads(ground_truth_path.read_text())
    ids = set()
    for pin in data.get("pins", []):
        ref_id = pin.get("source_reference_id")
        if ref_id:
            ids.add(ref_id)
    return ids


def item_id_to_filename(item_id: str) -> str:
    """Convert eBay item ID to safe filename: v1|123|0 -> v1-123-0.jpg"""
    return item_id.replace("|", "-") + ".jpg"


async def download_image(url: str, dest: Path, limiter: RateLimiter) -> bool:
    """Download an image, return True on success."""
    if dest.exists():
        return True
    await limiter.acquire()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                dest.write_bytes(response.content)
                return True
            print(f"[download] Status {response.status_code} for {url}")
            return False
    except Exception as exc:
        print(f"[download] Error downloading {url}: {exc}")
        return False


def build_catalog_entry(parsed: dict) -> dict:
    """Convert parsed listing to catalog import format."""
    return {
        "canonical_name": parsed["canonical_name"],
        "characters": parsed["characters"],
        "franchise": parsed["franchise"],
        "pin_type": parsed["pin_type"],
        "edition_size": parsed["edition_size"],
        "release_year": parsed["release_year"],
        "source": "ebay",
        "source_reference_id": parsed["source_reference_id"],
        "reference_image_url": parsed["image_url"],
        "evidence_strength": "high",
    }


def build_ground_truth_entry(parsed: dict, image_filename: str) -> dict:
    """Convert parsed listing to ground truth format."""
    return {
        "image_file": image_filename,
        "reference_title": parsed["canonical_name"],
        "reference_description": parsed["description"],
        "reference_price": parsed["price"],
        "expected_characters": parsed["characters"],
        "expected_franchise": parsed["franchise"],
        "expected_pin_type": parsed["pin_type"],
        "expected_edition_size": parsed["edition_size"],
        "expected_event": parsed.get("event"),
        "notes": parsed["status"],
        "source_reference_id": parsed["source_reference_id"],
    }


async def fetch_active_with_details(
    seller: str, limiter: RateLimiter, max_items: int
) -> list[dict]:
    """Fetch active listings and enrich each with item detail."""
    print(f"[active] Searching active listings for seller: {seller}")
    summaries = await browse_api_seller_search(seller, limit=min(max_items, 200))
    print(f"[active] Found {len(summaries)} active listings")

    detailed = []
    for summary in summaries[:max_items]:
        item_id = summary.get("itemId", "")
        if not item_id:
            continue
        await limiter.acquire()
        try:
            detail = await browse_api_item_detail(item_id)
            detailed.append(detail)
        except Exception as exc:
            print(f"[active] Error fetching detail for {item_id}: {exc}")
            continue

    return detailed


async def run(seller: str, max_items: int, sold_only: bool, rate: float) -> None:
    """Main import workflow."""
    app_id = os.environ.get("EBAY_CLIENT_ID", "")
    if not app_id:
        print("Error: EBAY_CLIENT_ID environment variable is required")
        sys.exit(1)

    limiter = RateLimiter(requests_per_second=rate)

    # Load existing IDs for deduplication
    existing_ids = load_existing_ids(GROUND_TRUTH_PATH)
    print(f"[dedup] Found {len(existing_ids)} existing entries")

    all_parsed: list[dict] = []

    # Fetch sold listings via Finding API
    print(f"\n--- Fetching sold listings for seller: {seller} ---")
    sold_items = await fetch_sold_listings(seller, app_id, max_items=max_items, rate_limiter=limiter)
    print(f"[sold] Retrieved {len(sold_items)} sold listings")

    # Enrich sold items with Browse API item detail for structured fields
    print(f"[sold] Enriching sold listings with item details...")
    for item in sold_items:
        item_id = item.get("itemId", "")
        if item_id in existing_ids:
            continue
        # Try to get full item details (localizedAspects) via Browse API
        await limiter.acquire()
        try:
            detail = await browse_api_item_detail(item_id)
            # Merge: keep sold price from Finding API, add detail fields
            detail["price"] = item.get("price", detail.get("price", {}))
            parsed = parse_listing(detail, status="sold")
        except Exception:
            # Fall back to Finding API data (sparse but usable)
            parsed = parse_listing(item, status="sold")
        all_parsed.append(parsed)

    # Fetch active listings via Browse API (unless --sold-only)
    if not sold_only:
        remaining = max_items - len(all_parsed)
        if remaining > 0:
            print(f"\n--- Fetching active listings for seller: {seller} ---")
            active_items = await fetch_active_with_details(seller, limiter, remaining)
            for item in active_items:
                item_id = item.get("itemId", "")
                if item_id in existing_ids:
                    continue
                parsed = parse_listing(item, status="active")
                all_parsed.append(parsed)

    print(f"\n[total] {len(all_parsed)} new listings to process")

    if not all_parsed:
        print("No new listings found. Exiting.")
        return

    # Ensure output directories exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Download images and build output
    catalog_entries = []
    ground_truth_entries = []
    downloaded = 0
    skipped_images = 0

    for parsed in all_parsed:
        image_filename = item_id_to_filename(parsed["source_reference_id"])
        image_dest = SAMPLE_DATA_DIR / image_filename

        if parsed["image_url"]:
            success = await download_image(parsed["image_url"], image_dest, limiter)
            if success:
                downloaded += 1
            else:
                skipped_images += 1
        else:
            skipped_images += 1

        catalog_entries.append(build_catalog_entry(parsed))
        ground_truth_entries.append(build_ground_truth_entry(parsed, image_filename))

    # Write catalog JSON
    catalog_path = OUTPUT_DIR / "ebay_catalog.json"
    catalog_path.write_text(json.dumps(catalog_entries, indent=2))
    print(f"\n[output] Catalog: {catalog_path} ({len(catalog_entries)} entries)")

    # Merge with existing ground truth
    existing_gt = {"pins": []}
    if GROUND_TRUTH_PATH.exists():
        existing_gt = json.loads(GROUND_TRUTH_PATH.read_text())

    existing_gt["pins"].extend(ground_truth_entries)
    GROUND_TRUTH_PATH.write_text(json.dumps(existing_gt, indent=2))
    print(f"[output] Ground truth: {GROUND_TRUTH_PATH} ({len(existing_gt['pins'])} total entries)")
    print(f"[output] Images: {downloaded} downloaded, {skipped_images} skipped")


def main():
    parser = argparse.ArgumentParser(description="Import eBay seller listings")
    parser.add_argument("--seller", required=True, help="eBay seller username")
    parser.add_argument("--max", type=int, default=200, help="Maximum listings to pull (default: 200)")
    parser.add_argument("--sold-only", action="store_true", help="Skip active listings, only pull sold")
    parser.add_argument("--rate", type=float, default=2.0, help="Requests per second (default: 2.0)")
    args = parser.parse_args()

    asyncio.run(run(args.seller, args.max, args.sold_only, args.rate))


if __name__ == "__main__":
    main()
