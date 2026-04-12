"""Ingest a seller's live eBay listings into a named Pin batch.

Usage:
    python scripts/import_ebay_seller.py \\
        --seller pins-n-things \\
        --batch-name pnt-eval-2026-04-11 \\
        [--max 500] \\
        [--skip-processing] \\
        [--dry-run]

Each listing becomes one Pin row tagged with reference_source='ebay_browse'.
Re-runs against the same --batch-name refresh reference_parsed_fields on
existing rows (matched by reference_external_id) without re-downloading
images.
"""

import argparse
import asyncio
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
from sqlalchemy import select

# Make `from src.xxx import ...` work when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database import async_session
from src.models import Pin, PinStatus
from src.pipeline.orchestrator import process_batch
from src.pipeline.reference_label import parse_listing_label
from src.services.ebay_client import (
    browse_api_item_detail,
    browse_api_seller_search,
)

UPLOAD_ROOT: Path = Path("uploads")
PAGE_SIZE: int = 200
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(item_id: str) -> str:
    return _SAFE_FILENAME.sub("_", item_id) + ".jpg"


async def _download_image(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)
    return dest


def _extract_primary_image_url(detail: dict) -> str | None:
    image = detail.get("image") or {}
    if isinstance(image, dict) and image.get("imageUrl"):
        return image["imageUrl"]
    extras = detail.get("additionalImages") or []
    if extras and isinstance(extras, list):
        first = extras[0]
        if isinstance(first, dict):
            return first.get("imageUrl")
    return None


@asynccontextmanager
async def _default_session_factory():
    async with async_session() as session:
        yield session


async def run(
    args: argparse.Namespace,
    session_factory: Callable[[], "asyncio.AbstractAsyncContextManager"] = _default_session_factory,
) -> dict:
    """Execute one ingest run. Returns a summary dict."""
    summary = {
        "seller": args.seller,
        "batch_name": args.batch_name,
        "seen": 0,
        "new": 0,
        "refreshed": 0,
        "image_errors": 0,
        "parser_failures": 0,
        "dry_run": bool(args.dry_run),
        "processing_enqueued": False,
    }

    # 1. Enumerate.
    all_summaries: list[dict] = []
    offset = 0
    while True:
        page = await browse_api_seller_search(
            seller=args.seller, query=args.query, limit=PAGE_SIZE, offset=offset,
        )
        if not page:
            break
        all_summaries.extend(page)
        offset += PAGE_SIZE
        if args.max is not None and len(all_summaries) >= args.max:
            all_summaries = all_summaries[: args.max]
            break
        if len(page) < PAGE_SIZE:
            break

    summary["seen"] = len(all_summaries)

    if args.dry_run:
        for s in all_summaries:
            print(f"[dry-run] would ingest {s.get('itemId')} — {s.get('title')}")
        return summary

    # 2. Open a DB session and iterate.
    async with session_factory() as db:
        result = await db.execute(
            select(Pin).where(
                Pin.batch_id == args.batch_name,
                Pin.reference_source == "ebay_browse",
            )
        )
        existing_by_id = {p.reference_external_id: p for p in result.scalars().all()}

        for item_summary in all_summaries:
            item_id = item_summary.get("itemId")
            if not item_id:
                continue

            try:
                detail = await browse_api_item_detail(item_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] get_item failed for {item_id}: {exc}", file=sys.stderr)
                continue

            raw_title = detail.get("title") or item_summary.get("title") or ""
            raw_description = detail.get("description")
            listing_url = detail.get("itemWebUrl") or item_summary.get("itemWebUrl")

            try:
                parsed = await parse_listing_label(raw_title, raw_description)
            except Exception as exc:  # noqa: BLE001
                summary["parser_failures"] += 1
                print(f"[warn] label parser failed for {item_id}: {exc}", file=sys.stderr)
                parsed = None

            existing = existing_by_id.get(item_id)
            if existing is not None:
                existing.reference_raw_title = raw_title
                existing.reference_raw_description = raw_description
                existing.reference_url = listing_url
                existing.reference_parsed_fields = parsed
                existing.reference_ingested_at = _utcnow_iso()
                summary["refreshed"] += 1
                continue

            image_url = _extract_primary_image_url(detail)
            if not image_url:
                summary["image_errors"] += 1
                print(f"[warn] no image URL for {item_id}", file=sys.stderr)
                continue

            dest = UPLOAD_ROOT / args.batch_name / _safe_filename(item_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                await _download_image(image_url, dest)
            except Exception as exc:  # noqa: BLE001
                summary["image_errors"] += 1
                print(f"[warn] image download failed for {item_id}: {exc}", file=sys.stderr)
                continue

            pin = Pin(
                batch_id=args.batch_name,
                status=PinStatus.UNPROCESSED,
                image_paths=[str(dest)],
                reference_source="ebay_browse",
                reference_external_id=item_id,
                reference_url=listing_url,
                reference_raw_title=raw_title,
                reference_raw_description=raw_description,
                reference_parsed_fields=parsed,
                reference_ingested_at=_utcnow_iso(),
            )
            db.add(pin)
            summary["new"] += 1

        await db.commit()

    if not args.skip_processing and (summary["new"] > 0 or summary["refreshed"] > 0):
        await process_batch(async_session, args.batch_name)
        summary["processing_enqueued"] = True

    return summary


def _print_summary(summary: dict) -> None:
    print(f"""pins-n-things ingestion complete
  batch: {summary['batch_name']}
  listings seen: {summary['seen']}
  new pins created: {summary['new']}
  duplicates refreshed: {summary['refreshed']}
  image errors: {summary['image_errors']}
  label parser failures: {summary['parser_failures']}
  processing: {'enqueued' if summary['processing_enqueued'] else 'skipped'}
""")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_ebay_seller",
        description="Ingest a seller's live eBay listings into a named Pin batch.",
    )
    parser.add_argument("--seller", required=True, help="eBay username (Browse API sellers filter)")
    parser.add_argument("--batch-name", required=True, dest="batch_name",
                        help="Human-readable batch label. Re-runs refresh existing pins.")
    parser.add_argument("--max", type=int, default=None,
                        help="Cap on listings to ingest (default: unlimited)")
    parser.add_argument("--skip-processing", action="store_true",
                        help="Do not enqueue vision/match pipeline after ingest")
    parser.add_argument("--query", default="disney",
                        help="Browse API search query (default: 'disney')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Hit the API, parse labels, print what would be created, write nothing")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = asyncio.run(run(args))
    _print_summary(summary)


if __name__ == "__main__":
    main()
