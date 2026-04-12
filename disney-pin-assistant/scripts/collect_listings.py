"""Collect eBay listings into the ebay_listings table.

Usage:
    python scripts/collect_listings.py active-seller --seller pins-n-things
    python scripts/collect_listings.py active-search --query "disney pin"
    python scripts/collect_listings.py sold --query "disney pin LE"
    python scripts/collect_listings.py promote --job-id 1 --batch-name my-batch
"""

import argparse
import asyncio
import json
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete

from src.config import settings
from src.database import async_session
from src.models import (
    CollectionJob,
    CollectionJobStatus,
    CollectionJobType,
    Comp,
    EbayListing,
    EbayListingType,
    Pin,
    PinStatus,
)
from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus
from src.pipeline.reference_label import parse_listing_label
from src.services.ebay_client import (
    browse_api_item_detail,
    browse_api_search,
    browse_api_seller_search,
)
from src.services.rapidapi_client import fetch_sold_listings

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


def _extract_price(detail: dict) -> float | None:
    price = detail.get("price") or {}
    if isinstance(price, dict) and price.get("value"):
        try:
            return float(price["value"])
        except (ValueError, TypeError):
            return None
    return None


@asynccontextmanager
async def _default_session_factory():
    async with async_session() as session:
        yield session


def _make_session_factory():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def run_comps(pin_id: int, refresh: bool) -> None:
    session_factory = _make_session_factory()
    if refresh:
        async with session_factory() as db:
            await db.execute(delete(Comp).where(Comp.pin_id == pin_id))
            await db.commit()
    result = await lookup_comps_for_pin(session_factory, pin_id)
    print(f"Pin {pin_id}: {result.status.value} — {result.comps_written} comps written")
    if result.error:
        print(f"  error: {result.error}")


async def run_active_seller(
    seller: str,
    query: str = "disney",
    data_dir: Path = Path("data"),
    session_factory: Callable = _default_session_factory,
    parse_labels: bool = True,
) -> dict:
    """Collect active listings from a specific seller."""
    result = {"listings_found": 0, "listings_new": 0, "listings_updated": 0, "errors": 0}

    # 1. Paginate through seller listings
    all_summaries: list[dict] = []
    offset = 0
    while True:
        page = await browse_api_seller_search(
            seller=seller, query=query, limit=PAGE_SIZE, offset=offset,
        )
        if not page:
            break
        all_summaries.extend(page)
        offset += PAGE_SIZE
        if len(page) < PAGE_SIZE:
            break

    result["listings_found"] = len(all_summaries)

    async with session_factory() as db:
        # 2. Create job
        job = CollectionJob(
            job_type=CollectionJobType.SELLER_ACTIVE,
            query=seller,
            source="browse_api",
            status=CollectionJobStatus.RUNNING,
            started_at=_utcnow_iso(),
        )
        db.add(job)
        await db.commit()

        try:
            # 3. Load existing listings for dedup
            existing_result = await db.execute(
                select(EbayListing).where(EbayListing.ebay_item_id.isnot(None))
            )
            existing_by_id = {l.ebay_item_id: l for l in existing_result.scalars().all()}

            # 4. Process each listing
            raw_details: list[dict] = []
            for item_summary in all_summaries:
                item_id = item_summary.get("itemId")
                if not item_id:
                    continue

                try:
                    detail = await browse_api_item_detail(item_id)
                except Exception as exc:
                    print(f"[warn] get_item failed for {item_id}: {exc}", file=sys.stderr)
                    result["errors"] += 1
                    continue

                raw_details.append(detail)

                raw_title = detail.get("title") or item_summary.get("title") or ""
                raw_description = detail.get("description")
                listing_url = detail.get("itemWebUrl") or item_summary.get("itemWebUrl")
                price = _extract_price(detail)
                seller_name = (detail.get("seller") or {}).get("username", seller)
                condition = detail.get("condition")
                image_url = _extract_primary_image_url(detail)

                parsed = None
                if parse_labels:
                    try:
                        parsed = await parse_listing_label(raw_title, raw_description)
                    except Exception as exc:
                        print(f"[warn] label parser failed for {item_id}: {exc}", file=sys.stderr)

                # Upsert
                existing = existing_by_id.get(item_id)
                if existing is not None:
                    existing.title = raw_title
                    existing.price = price or existing.price
                    existing.listing_url = listing_url
                    existing.seller = seller_name
                    existing.condition = condition
                    existing.image_url = image_url
                    if parsed is not None:
                        existing.parsed_fields = parsed
                    existing.updated_at = _utcnow_iso()
                    result["listings_updated"] += 1
                else:
                    # Download image for new listings
                    local_image = None
                    if image_url:
                        dest = data_dir / "images" / "active" / _safe_filename(item_id)
                        try:
                            await _download_image(image_url, dest)
                            local_image = str(dest)
                        except Exception as exc:
                            print(f"[warn] image download failed for {item_id}: {exc}", file=sys.stderr)
                            result["errors"] += 1

                    listing = EbayListing(
                        listing_type=EbayListingType.ACTIVE,
                        source="browse_api",
                        ebay_item_id=item_id,
                        title=raw_title,
                        price=price or 0.0,
                        seller=seller_name,
                        condition=condition,
                        image_url=image_url,
                        local_image_path=local_image,
                        listing_url=listing_url,
                        parsed_fields=parsed,
                        collection_job_id=job.id,
                    )
                    db.add(listing)
                    existing_by_id[item_id] = listing
                    result["listings_new"] += 1

            # 5. Archive raw response
            raw_dir = data_dir / "raw" / "browse_api" / datetime.now(timezone.utc).strftime("%Y-%m-%d")
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"job_{job.id}.json"
            raw_path.write_text(json.dumps(raw_details, indent=2))

            # 6. Finalize job
            job.listings_found = result["listings_found"]
            job.listings_new = result["listings_new"]
            job.status = CollectionJobStatus.COMPLETED
            job.completed_at = _utcnow_iso()
        except Exception as exc:
            job.status = CollectionJobStatus.FAILED
            job.error_message = str(exc)
            job.completed_at = _utcnow_iso()
            raise
        finally:
            await db.commit()

    return result


async def run_active_search(
    query: str,
    category: str | None = None,
    data_dir: Path = Path("data"),
    session_factory: Callable = _default_session_factory,
    parse_labels: bool = True,
) -> dict:
    """Collect active listings by keyword search.

    Note: browse_api_search does not support offset/pagination, so this
    collects at most 200 results (one page). For exhaustive collection,
    use active-seller with a known seller username.
    """
    result = {"listings_found": 0, "listings_new": 0, "listings_updated": 0, "errors": 0}

    # 1. Fetch listings via keyword search (single page, max 200)
    filters = f"categoryId:{{{category}}}" if category else None
    all_summaries: list[dict] = await browse_api_search(
        query=query, filters=filters, limit=200
    )

    result["listings_found"] = len(all_summaries)

    async with session_factory() as db:
        # 2. Create job
        job = CollectionJob(
            job_type=CollectionJobType.KEYWORD_ACTIVE,
            query=query,
            category_id=category,
            source="browse_api",
            status=CollectionJobStatus.RUNNING,
            started_at=_utcnow_iso(),
        )
        db.add(job)
        await db.commit()

        try:
            # 3. Load existing listings for dedup
            existing_result = await db.execute(
                select(EbayListing).where(EbayListing.ebay_item_id.isnot(None))
            )
            existing_by_id = {l.ebay_item_id: l for l in existing_result.scalars().all()}

            # 4. Process each listing
            raw_details: list[dict] = []
            for item_summary in all_summaries:
                item_id = item_summary.get("itemId")
                if not item_id:
                    continue

                try:
                    detail = await browse_api_item_detail(item_id)
                except Exception as exc:
                    print(f"[warn] get_item failed for {item_id}: {exc}", file=sys.stderr)
                    result["errors"] += 1
                    continue

                raw_details.append(detail)

                raw_title = detail.get("title") or item_summary.get("title") or ""
                raw_description = detail.get("description")
                listing_url = detail.get("itemWebUrl") or item_summary.get("itemWebUrl")
                price = _extract_price(detail)
                seller_name = (detail.get("seller") or {}).get("username")
                condition = detail.get("condition")
                image_url = _extract_primary_image_url(detail)

                parsed = None
                if parse_labels:
                    try:
                        parsed = await parse_listing_label(raw_title, raw_description)
                    except Exception as exc:
                        print(f"[warn] label parser failed for {item_id}: {exc}", file=sys.stderr)

                # Upsert
                existing = existing_by_id.get(item_id)
                if existing is not None:
                    existing.title = raw_title
                    existing.price = price or existing.price
                    existing.listing_url = listing_url
                    existing.seller = seller_name
                    existing.condition = condition
                    existing.image_url = image_url
                    if parsed is not None:
                        existing.parsed_fields = parsed
                    existing.updated_at = _utcnow_iso()
                    result["listings_updated"] += 1
                else:
                    # Download image for new listings
                    local_image = None
                    if image_url:
                        dest = data_dir / "images" / "active" / _safe_filename(item_id)
                        try:
                            await _download_image(image_url, dest)
                            local_image = str(dest)
                        except Exception as exc:
                            print(f"[warn] image download failed for {item_id}: {exc}", file=sys.stderr)
                            result["errors"] += 1

                    listing = EbayListing(
                        listing_type=EbayListingType.ACTIVE,
                        source="browse_api",
                        ebay_item_id=item_id,
                        title=raw_title,
                        price=price or 0.0,
                        seller=seller_name,
                        condition=condition,
                        image_url=image_url,
                        local_image_path=local_image,
                        listing_url=listing_url,
                        parsed_fields=parsed,
                        collection_job_id=job.id,
                    )
                    db.add(listing)
                    existing_by_id[item_id] = listing
                    result["listings_new"] += 1

            # 5. Archive raw response
            raw_dir = data_dir / "raw" / "browse_api" / datetime.now(timezone.utc).strftime("%Y-%m-%d")
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"job_{job.id}.json"
            raw_path.write_text(json.dumps(raw_details, indent=2))

            # 6. Finalize job
            job.listings_found = result["listings_found"]
            job.listings_new = result["listings_new"]
            job.status = CollectionJobStatus.COMPLETED
            job.completed_at = _utcnow_iso()
        except Exception as exc:
            job.status = CollectionJobStatus.FAILED
            job.error_message = str(exc)
            job.completed_at = _utcnow_iso()
            raise
        finally:
            await db.commit()

    return result


async def run_sold(
    query: str,
    max_results: int = 240,
    category: str | None = None,
    data_dir: Path = Path("data"),
    session_factory: Callable = _default_session_factory,
    parse_labels: bool = True,
) -> dict:
    """Collect sold listings via RapidAPI."""
    result = {"listings_found": 0, "listings_new": 0, "listings_skipped": 0, "errors": 0}

    api_result = await fetch_sold_listings(
        keywords=query, max_results=max_results, category_id=category,
    )

    products = api_result["products"]
    result["listings_found"] = len(products)

    async with session_factory() as db:
        job = CollectionJob(
            job_type=CollectionJobType.KEYWORD_SOLD,
            query=query,
            category_id=category,
            source="rapidapi_sold",
            status=CollectionJobStatus.RUNNING,
            started_at=_utcnow_iso(),
            result_metadata=api_result["aggregates"],
        )
        db.add(job)
        await db.commit()

        try:
            # Load existing sold listings for soft dedup
            existing_sold = await db.execute(
                select(EbayListing).where(EbayListing.listing_type == EbayListingType.SOLD)
            )
            dedup_set: set[tuple[str, float, str]] = set()
            for row in existing_sold.scalars().all():
                dedup_set.add((row.title, row.price, row.sale_date or ""))

            for product in products:
                title = product.get("title", "")
                sale_price_str = product.get("sale_price", "0")
                try:
                    sale_price = float(sale_price_str)
                except (ValueError, TypeError):
                    sale_price = 0.0
                date_sold = product.get("date_sold", "")
                link = product.get("link")

                dedup_key = (title, sale_price, date_sold)
                if dedup_key in dedup_set:
                    result["listings_skipped"] += 1
                    continue

                parsed = None
                if parse_labels:
                    try:
                        parsed = await parse_listing_label(title, None)
                    except Exception as exc:
                        print(f"[warn] label parser failed: {exc}", file=sys.stderr)
                        result["errors"] += 1

                listing = EbayListing(
                    listing_type=EbayListingType.SOLD,
                    source="rapidapi_sold",
                    title=title,
                    price=sale_price,
                    sale_date=date_sold,
                    listing_url=link,
                    parsed_fields=parsed,
                    collection_job_id=job.id,
                )
                db.add(listing)
                dedup_set.add(dedup_key)
                result["listings_new"] += 1

            # Archive raw response
            raw_dir = data_dir / "raw" / "rapidapi_sold" / datetime.now(timezone.utc).strftime("%Y-%m-%d")
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"job_{job.id}.json").write_text(json.dumps(api_result, indent=2))

            job.listings_found = result["listings_found"]
            job.listings_new = result["listings_new"]
            job.status = CollectionJobStatus.COMPLETED
            job.completed_at = _utcnow_iso()
        except Exception as exc:
            job.status = CollectionJobStatus.FAILED
            job.error_message = str(exc)
            job.completed_at = _utcnow_iso()
            raise
        finally:
            await db.commit()

    return result


async def run_promote(
    batch_name: str,
    job_id: int | None = None,
    seller: str | None = None,
    session_factory: Callable = _default_session_factory,
) -> dict:
    """Promote collected listings to Pin rows for pipeline processing."""
    result = {"promoted": 0, "skipped": 0}

    async with session_factory() as db:
        # Build query based on filter
        query = select(EbayListing)
        if job_id is not None:
            query = query.where(EbayListing.collection_job_id == job_id)
        elif seller is not None:
            query = query.where(EbayListing.seller == seller)
        else:
            raise ValueError("Must provide either --job-id or --seller")

        listings = (await db.execute(query)).scalars().all()

        # Load existing pins for dedup
        existing_pins = await db.execute(
            select(Pin.reference_external_id).where(
                Pin.reference_external_id.isnot(None)
            )
        )
        existing_ext_ids: set[str] = {row[0] for row in existing_pins.fetchall()}

        for listing in listings:
            # Skip if already promoted (by ebay_item_id)
            if listing.ebay_item_id and listing.ebay_item_id in existing_ext_ids:
                result["skipped"] += 1
                continue

            image_paths = [listing.local_image_path] if listing.local_image_path else []
            pin = Pin(
                batch_id=batch_name,
                status=PinStatus.UNPROCESSED,
                image_paths=image_paths,
                reference_source=listing.source,
                reference_external_id=listing.ebay_item_id,
                reference_url=listing.listing_url,
                reference_raw_title=listing.title,
                reference_parsed_fields=listing.parsed_fields,
                reference_ingested_at=_utcnow_iso(),
            )
            db.add(pin)
            if listing.ebay_item_id:
                existing_ext_ids.add(listing.ebay_item_id)
            result["promoted"] += 1

        await db.commit()

    return result


# ── CLI ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_listings",
        description="Collect eBay listings into the ebay_listings table.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # active-seller
    p_seller = sub.add_parser("active-seller", help="Collect active listings from a seller")
    p_seller.add_argument("--seller", required=True)
    p_seller.add_argument("--query", default="disney")
    p_seller.add_argument("--no-parse", action="store_true", help="Skip label parsing")

    # active-search (Task 6)
    p_search = sub.add_parser("active-search", help="Collect active listings by keyword")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--category", default=None)
    p_search.add_argument("--no-parse", action="store_true")

    # sold (Task 7)
    p_sold = sub.add_parser("sold", help="Collect sold listings via RapidAPI")
    p_sold.add_argument("--query", required=True)
    p_sold.add_argument("--max-results", type=int, default=240, choices=[60, 120, 240])
    p_sold.add_argument("--category", default=None)
    p_sold.add_argument("--no-parse", action="store_true")

    # promote (Task 8)
    p_promote = sub.add_parser("promote", help="Promote listings to pins")
    p_promote.add_argument("--job-id", type=int, default=None)
    p_promote.add_argument("--seller", default=None)
    p_promote.add_argument("--batch-name", required=True, dest="batch_name")

    # comps
    p_comps = sub.add_parser("comps", help="Look up sold comps for a single pin")
    p_comps.add_argument("--pin-id", type=int, required=True)
    p_comps.add_argument("--refresh", action="store_true",
                         help="Delete existing comps for this pin before lookup")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    data_dir = Path(settings.collection_data_dir)

    if args.command == "active-seller":
        result = asyncio.run(run_active_seller(
            seller=args.seller,
            query=args.query,
            data_dir=data_dir,
            parse_labels=not args.no_parse,
        ))
        print(f"Active seller collection complete: {result}")

    elif args.command == "active-search":
        result = asyncio.run(run_active_search(
            query=args.query,
            category=args.category,
            data_dir=data_dir,
            parse_labels=not args.no_parse,
        ))
        print(f"Active search collection complete: {result}")

    elif args.command == "sold":
        result = asyncio.run(run_sold(
            query=args.query,
            max_results=args.max_results,
            category=args.category,
            data_dir=data_dir,
            parse_labels=not args.no_parse,
        ))
        print(f"Sold collection complete: {result}")

    elif args.command == "promote":
        result = asyncio.run(run_promote(
            job_id=args.job_id,
            seller=args.seller,
            batch_name=args.batch_name,
        ))
        print(f"Promote complete: {result}")

    elif args.command == "comps":
        asyncio.run(run_comps(pin_id=args.pin_id, refresh=args.refresh))


if __name__ == "__main__":
    main()
