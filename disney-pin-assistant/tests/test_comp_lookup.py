from datetime import date
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select

from src.models import (
    Pin, PinStatus, Comp, MatchType,
    EbayListing, EbayListingType, CollectionJob, CollectionJobType, CollectionJobStatus,
    CompLookupBudget,
)


async def _make_pin(session_factory, parsed_fields: dict) -> int:
    async with session_factory() as db:
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.EXTRACTED,
                  reference_parsed_fields=parsed_fields)
        db.add(pin)
        await db.commit()
        return pin.id


@pytest.mark.asyncio
async def test_lookup_skipped_sparse(session_factory):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus
    pin_id = await _make_pin(session_factory, {"characters": ["Mickey"]})
    result = await lookup_comps_for_pin(session_factory, pin_id, today=date(2026, 4, 12))
    assert result.status == LookupStatus.SKIPPED_SPARSE


@pytest.mark.asyncio
async def test_lookup_skipped_capped(session_factory, monkeypatch):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus
    from src.config import settings
    monkeypatch.setattr(settings, "comp_lookup_daily_limit", 1)

    async with session_factory() as db:
        db.add(CompLookupBudget(date="2026-04-12", calls=1))
        await db.commit()

    pin_id = await _make_pin(session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000,
    })
    result = await lookup_comps_for_pin(session_factory, pin_id, today=date(2026, 4, 12))
    assert result.status == LookupStatus.SKIPPED_CAPPED


@pytest.mark.asyncio
async def test_lookup_cache_hit_writes_comps_and_skips_api(session_factory):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus

    async with session_factory() as db:
        job = CollectionJob(
            job_type=CollectionJobType.KEYWORD_SOLD, query="seed",
            source="rapidapi_sold", status=CollectionJobStatus.COMPLETED,
        )
        db.add(job)
        await db.flush()
        for i in range(6):
            db.add(EbayListing(
                listing_type=EbayListingType.SOLD, source="rapidapi_sold",
                title=f"Stitch pin {i}", price=10.0 + i,
                sale_date="2026-04-01",
                parsed_fields={
                    "characters": ["Stitch"], "franchise": "Lilo & Stitch",
                    "edition_size": 2000, "release_year": 2019,
                },
                collection_job_id=job.id,
            ))
        await db.commit()

    pin_id = await _make_pin(session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch",
        "edition_size": 2000, "release_year": 2019,
    })

    with patch(
        "src.pipeline.comp_lookup.sold_data_client.fetch_sold_listings",
        new=AsyncMock(side_effect=AssertionError("should not be called")),
    ):
        result = await lookup_comps_for_pin(session_factory, pin_id, today=date(2026, 4, 12))
    assert result.status == LookupStatus.CACHE_HIT

    async with session_factory() as db:
        comps = (await db.execute(
            select(Comp).where(Comp.pin_id == pin_id)
        )).scalars().all()
        assert len(comps) >= 1
        assert all(c.match_type == MatchType.RAPIDAPI_SOLD for c in comps)
        assert all(c.weight is not None for c in comps)


@pytest.mark.asyncio
async def test_lookup_cache_miss_calls_api_and_increments_budget(session_factory):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus

    pin_id = await _make_pin(session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000,
    })
    fake_response = {
        "aggregates": {"average_price": 15.0},
        "products": [
            {"title": "Stitch LE 2000 pin", "sale_price": 15.0,
             "date_sold": "2026-03-01", "link": "https://ebay.com/x"},
            {"title": "Stitch LE 2000 different", "sale_price": 18.0,
             "date_sold": "2026-04-01", "link": "https://ebay.com/y"},
        ],
    }
    with patch(
        "src.pipeline.comp_lookup.sold_data_client.fetch_sold_listings",
        new=AsyncMock(return_value=fake_response),
    ) as m:
        result = await lookup_comps_for_pin(session_factory, pin_id, today=date(2026, 4, 12))

    assert result.status == LookupStatus.API_CALLED
    m.assert_awaited_once()

    async with session_factory() as db:
        listings = (await db.execute(select(EbayListing))).scalars().all()
        assert len(listings) == 2
        budget = (await db.execute(
            select(CompLookupBudget).where(CompLookupBudget.date == "2026-04-12")
        )).scalar_one_or_none()
        assert budget is not None and budget.calls == 1


@pytest.mark.asyncio
async def test_lookup_api_failure_marks_job_failed(session_factory):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus

    pin_id = await _make_pin(session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000,
    })
    with patch(
        "src.pipeline.comp_lookup.sold_data_client.fetch_sold_listings",
        new=AsyncMock(side_effect=RuntimeError("api down")),
    ):
        result = await lookup_comps_for_pin(session_factory, pin_id, today=date(2026, 4, 12))
    assert result.status == LookupStatus.FAILED

    async with session_factory() as db:
        jobs = (await db.execute(select(CollectionJob))).scalars().all()
        assert any(j.status == CollectionJobStatus.FAILED for j in jobs)
