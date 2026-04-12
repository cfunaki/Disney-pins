"""Per-pin sold-data comp lookup service.

Flow:
1. Check pin's parsed fields for sparseness (< comp_min_parsed_fields useful fields).
2. Check daily budget cap.
3. Cache: query ebay_listings for sold rows overlapping parsed fields.
4. If cache has >= comp_cache_min_hits relevant rows: score and write to comps.
5. Else: call sold_data_client, store results in ebay_listings, score, write to comps.
6. On any uncaught exception during API call: mark collection_jobs row FAILED.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.config import settings
from src.models import (
    Pin, Comp, MatchType, ListingType,
    EbayListing, EbayListingType, CollectionJob, CollectionJobType, CollectionJobStatus,
    CompLookupBudget,
)
from src.pipeline.comp_scoring import field_overlap_score, score_comp
from src.services import sold_data_client


class LookupStatus(str, Enum):
    SKIPPED_SPARSE = "skipped_sparse"
    SKIPPED_CAPPED = "skipped_capped"
    CACHE_HIT = "cache_hit"
    API_CALLED = "api_called"
    FAILED = "failed"


@dataclass
class LookupResult:
    status: LookupStatus
    comps_written: int = 0
    suggested_price: float | None = None
    error: str | None = None


def _useful_field_count(parsed: dict | None) -> int:
    if not parsed:
        return 0
    count = 0
    if parsed.get("characters"):
        count += 1
    if parsed.get("franchise"):
        count += 1
    if parsed.get("edition_size") is not None:
        count += 1
    if parsed.get("release_year") is not None:
        count += 1
    return count


def _build_query(parsed: dict) -> str:
    parts: list[str] = []
    chars = parsed.get("characters") or []
    if chars:
        parts.append(" ".join(str(c) for c in chars[:2]))
    fr = parsed.get("franchise")
    if fr:
        parts.append(str(fr))
    ed = parsed.get("edition_size")
    if ed is not None:
        parts.append(f"LE {ed}")
    yr = parsed.get("release_year")
    if yr is not None:
        parts.append(str(yr))
    return " ".join(parts).strip()


def _parse_sale_date(raw: str | None, today: date) -> date:
    if not raw:
        return today
    try:
        return date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        return today


async def _get_or_create_budget(db, today: date) -> CompLookupBudget:
    key = today.isoformat()
    existing = (await db.execute(
        select(CompLookupBudget).where(CompLookupBudget.date == key)
    )).scalar_one_or_none()
    if existing:
        return existing
    row = CompLookupBudget(date=key, calls=0)
    db.add(row)
    await db.flush()
    return row


async def lookup_comps_for_pin(
    session_factory: async_sessionmaker,
    pin_id: int,
    today: date | None = None,
) -> LookupResult:
    today = today or date.today()

    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        if pin is None:
            return LookupResult(status=LookupStatus.FAILED, error="pin not found")
        parsed = pin.reference_parsed_fields or {}

    if _useful_field_count(parsed) < settings.comp_min_parsed_fields:
        return LookupResult(status=LookupStatus.SKIPPED_SPARSE)

    # Cache check
    async with session_factory() as db:
        listings = (await db.execute(
            select(EbayListing).where(EbayListing.listing_type == EbayListingType.SOLD)
        )).scalars().all()
        relevant = [
            l for l in listings
            if field_overlap_score(parsed, l.parsed_fields or {}) > 0
        ]

    if len(relevant) >= settings.comp_cache_min_hits:
        count = await _write_comps_from_listings(
            session_factory, pin_id, parsed, relevant, today,
        )
        return LookupResult(status=LookupStatus.CACHE_HIT, comps_written=count)

    # Budget check
    async with session_factory() as db:
        budget = await _get_or_create_budget(db, today)
        if budget.calls >= settings.comp_lookup_daily_limit:
            await db.commit()
            return LookupResult(status=LookupStatus.SKIPPED_CAPPED)

    # API call
    query = _build_query(parsed)
    async with session_factory() as db:
        job = CollectionJob(
            job_type=CollectionJobType.KEYWORD_SOLD, query=query,
            source="rapidapi_sold", status=CollectionJobStatus.RUNNING,
            started_at=today.isoformat(),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    try:
        response = await sold_data_client.fetch_sold_listings(
            query, max_results=settings.comp_max_results_per_lookup,
        )
    except Exception as exc:
        async with session_factory() as db:
            j = await db.get(CollectionJob, job_id)
            j.status = CollectionJobStatus.FAILED
            j.error_message = str(exc)
            j.completed_at = today.isoformat()
            await db.commit()
        return LookupResult(status=LookupStatus.FAILED, error=str(exc))

    new_listings: list[EbayListing] = []
    async with session_factory() as db:
        for product in response.get("products", []):
            title = product.get("title") or ""
            price_raw = product.get("sale_price") or product.get("price")
            if not title or price_raw is None:
                continue
            try:
                price = float(price_raw)
            except (ValueError, TypeError):
                continue
            sale_date_raw = product.get("date_sold") or product.get("sale_date")
            listing = EbayListing(
                listing_type=EbayListingType.SOLD, source="rapidapi_sold",
                title=title, price=price,
                sale_date=sale_date_raw,
                listing_url=product.get("link"),
                parsed_fields=parsed,
                collection_job_id=job_id,
            )
            db.add(listing)
            new_listings.append(listing)

        job = await db.get(CollectionJob, job_id)
        job.status = CollectionJobStatus.COMPLETED
        job.listings_found = len(response.get("products", []))
        job.listings_new = len(new_listings)
        job.result_metadata = response.get("aggregates")
        job.completed_at = today.isoformat()

        budget = await _get_or_create_budget(db, today)
        budget.calls += 1

        await db.commit()

    count = await _write_comps_from_listings(
        session_factory, pin_id, parsed, new_listings, today,
    )
    return LookupResult(status=LookupStatus.API_CALLED, comps_written=count)


async def _write_comps_from_listings(
    session_factory: async_sessionmaker,
    pin_id: int,
    parsed: dict,
    listings: list[EbayListing],
    today: date,
) -> int:
    # Extract pure data from listings before any cross-session work to avoid
    # detached-instance issues after commit.
    listing_data = [
        {
            "sale_date_raw": l.sale_date,
            "title": l.title,
            "price": l.price,
            "parsed_fields": l.parsed_fields or {},
        }
        for l in listings
    ]
    scored: list[dict] = []
    for d in listing_data:
        sd = _parse_sale_date(d["sale_date_raw"], today)
        weight = score_comp(
            parsed, d["parsed_fields"], sale_date=sd, today=today,
            half_life_days=settings.comp_recency_half_life_days,
        )
        if weight <= 0:
            continue
        scored.append({
            "sale_date": d["sale_date_raw"], "title": d["title"],
            "price": d["price"], "weight": weight,
        })
    scored.sort(key=lambda s: s["weight"], reverse=True)
    top = scored[:10]

    async with session_factory() as db:
        for s in top:
            db.add(Comp(
                pin_id=pin_id,
                title=s["title"], price=s["price"], sale_date=s["sale_date"],
                listing_type=ListingType.SOLD,
                match_type=MatchType.RAPIDAPI_SOLD,
                weight=s["weight"],
            ))
        await db.commit()

    return len(top)
