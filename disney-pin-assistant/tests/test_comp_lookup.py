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


# --- Bug fixes: sale-date parsing + per-listing parsed fields ---

def test_parse_sale_date_iso():
    from src.pipeline.comp_lookup import _parse_sale_date
    assert _parse_sale_date("2026-03-10", date(2026, 4, 12)) == date(2026, 3, 10)


def test_parse_sale_date_short_month_name():
    from src.pipeline.comp_lookup import _parse_sale_date
    assert _parse_sale_date("Mar 10, 2026", date(2026, 4, 12)) == date(2026, 3, 10)


def test_parse_sale_date_long_month_name():
    from src.pipeline.comp_lookup import _parse_sale_date
    assert _parse_sale_date("March 10, 2026", date(2026, 4, 12)) == date(2026, 3, 10)


def test_parse_sale_date_slash():
    from src.pipeline.comp_lookup import _parse_sale_date
    assert _parse_sale_date("3/10/2026", date(2026, 4, 12)) == date(2026, 3, 10)


def test_parse_sale_date_unknown_falls_back_to_today():
    from src.pipeline.comp_lookup import _parse_sale_date
    today = date(2026, 4, 12)
    assert _parse_sale_date("not a date", today) == today


@pytest.mark.asyncio
async def test_cache_miss_parses_each_listing_title(session_factory, monkeypatch):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus
    from src.config import settings

    monkeypatch.setattr(settings, "collection_parse_labels", True)

    pin_id = await _make_pin(session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000,
    })
    fake_response = {
        "aggregates": {},
        "products": [
            {"title": "Stitch pin A", "sale_price": 10.0, "date_sold": "Mar 1, 2026"},
            {"title": "Stitch pin B", "sale_price": 20.0, "date_sold": "Mar 5, 2026"},
        ],
    }

    parse_calls: list[str] = []

    async def fake_parse(title, desc):
        parse_calls.append(title)
        return {"characters": ["Stitch"], "franchise": "Lilo & Stitch"}

    with patch(
        "src.pipeline.comp_lookup.sold_data_client.fetch_sold_listings",
        new=AsyncMock(return_value=fake_response),
    ), patch(
        "src.pipeline.comp_lookup.parse_listing_label", new=fake_parse,
    ):
        result = await lookup_comps_for_pin(session_factory, pin_id, today=date(2026, 4, 12))

    assert result.status == LookupStatus.API_CALLED
    assert parse_calls == ["Stitch pin A", "Stitch pin B"]

    async with session_factory() as db:
        listings = (await db.execute(select(EbayListing))).scalars().all()
        assert len(listings) == 2
        for l in listings:
            assert l.parsed_fields == {"characters": ["Stitch"], "franchise": "Lilo & Stitch"}


@pytest.mark.asyncio
async def test_parse_labels_disabled_stores_none(session_factory, monkeypatch):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus
    from src.config import settings

    monkeypatch.setattr(settings, "collection_parse_labels", False)

    pin_id = await _make_pin(session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000,
    })
    fake_response = {
        "aggregates": {},
        "products": [
            {"title": "Stitch pin A", "sale_price": 10.0, "date_sold": "Mar 1, 2026"},
        ],
    }
    with patch(
        "src.pipeline.comp_lookup.sold_data_client.fetch_sold_listings",
        new=AsyncMock(return_value=fake_response),
    ), patch(
        "src.pipeline.comp_lookup.parse_listing_label",
        new=AsyncMock(side_effect=AssertionError("should not be called")),
    ):
        result = await lookup_comps_for_pin(session_factory, pin_id, today=date(2026, 4, 12))

    assert result.status == LookupStatus.API_CALLED
    async with session_factory() as db:
        listings = (await db.execute(select(EbayListing))).scalars().all()
        assert len(listings) == 1
        assert listings[0].parsed_fields is None
