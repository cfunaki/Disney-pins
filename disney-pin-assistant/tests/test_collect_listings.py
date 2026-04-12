import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from sqlalchemy import select

from src.models import EbayListing, CollectionJob, CollectionJobStatus, EbayListingType, CollectionJobType

# Import the script by path (scripts/ isn't a package).
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "collect_listings",
    Path(__file__).resolve().parents[1] / "scripts" / "collect_listings.py",
)
collect_listings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collect_listings)


def _session_wrapper(session):
    @asynccontextmanager
    async def _cm():
        yield session
    return _cm()


@pytest.mark.asyncio
async def test_active_seller_creates_listings_and_job(db_session, tmp_path):
    summaries = [
        {"itemId": "v1|1|0", "title": "Stitch Pin", "itemWebUrl": "https://ebay.com/1"},
        {"itemId": "v1|2|0", "title": "Goofy Pin LE 500", "itemWebUrl": "https://ebay.com/2"},
    ]

    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return summaries if offset == 0 else []

    async def fake_item_detail(item_id):
        return {
            "itemId": item_id,
            "title": next(s["title"] for s in summaries if s["itemId"] == item_id),
            "description": "test desc",
            "image": {"imageUrl": f"https://cdn/{item_id}.jpg"},
            "price": {"value": "19.99", "currency": "USD"},
            "seller": {"username": "pins-n-things"},
            "condition": "New",
        }

    async def fake_download(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"\xff\xd8\xff\xe0")
        return dest

    async def fake_parse(title, description):
        return {"characters": ["Stitch"] if "Stitch" in title else ["Goofy"]}

    with patch.object(collect_listings, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(collect_listings, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(collect_listings, "_download_image", new=AsyncMock(side_effect=fake_download)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(side_effect=fake_parse)):
        result = await collect_listings.run_active_seller(
            seller="pins-n-things",
            query="disney",
            data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=True,
        )

    assert result["listings_new"] == 2
    assert result["listings_found"] == 2

    # Check job was created
    jobs = (await db_session.execute(select(CollectionJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status == CollectionJobStatus.COMPLETED
    assert jobs[0].listings_new == 2

    # Check listings were created
    listings = (await db_session.execute(select(EbayListing))).scalars().all()
    assert len(listings) == 2
    for listing in listings:
        assert listing.listing_type == EbayListingType.ACTIVE
        assert listing.source == "browse_api"
        assert listing.seller == "pins-n-things"
        assert listing.parsed_fields is not None


@pytest.mark.asyncio
async def test_active_seller_upserts_existing_listing(db_session, tmp_path):
    # Pre-create a job and listing
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE, query="test", source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    existing = EbayListing(
        listing_type=EbayListingType.ACTIVE,
        source="browse_api",
        ebay_item_id="v1|1|0",
        title="Old Title",
        price=10.00,
        seller="pins-n-things",
        collection_job_id=job.id,
    )
    db_session.add(existing)
    await db_session.commit()

    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return [{"itemId": "v1|1|0", "title": "New Title", "itemWebUrl": "https://ebay.com/1"}] if offset == 0 else []

    async def fake_item_detail(item_id):
        return {
            "title": "New Title", "description": None,
            "image": {"imageUrl": "https://cdn/1.jpg"},
            "price": {"value": "29.99", "currency": "USD"},
            "seller": {"username": "pins-n-things"},
        }

    with patch.object(collect_listings, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(collect_listings, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(collect_listings, "_download_image", new=AsyncMock()), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value={})):
        result = await collect_listings.run_active_seller(
            seller="pins-n-things",
            query="disney",
            data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=False,
        )

    assert result["listings_new"] == 0
    assert result["listings_updated"] == 1

    await db_session.refresh(existing)
    assert existing.title == "New Title"
    assert existing.price == 29.99


@pytest.mark.asyncio
async def test_active_seller_archives_raw_response(db_session, tmp_path):
    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return [{"itemId": "v1|1|0", "title": "Pin", "itemWebUrl": "https://ebay.com/1"}] if offset == 0 else []

    async def fake_item_detail(item_id):
        return {"title": "Pin", "image": {"imageUrl": "https://cdn/1.jpg"}, "price": {"value": "5.00"}, "seller": {"username": "test"}}

    async def fake_download(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"\xff\xd8")
        return dest

    with patch.object(collect_listings, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(collect_listings, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(collect_listings, "_download_image", new=AsyncMock(side_effect=fake_download)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value=None)):
        await collect_listings.run_active_seller(
            seller="test", query="disney", data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=False,
        )

    raw_dir = tmp_path / "raw" / "browse_api"
    json_files = list(raw_dir.rglob("*.json"))
    assert len(json_files) == 1
    data = json.loads(json_files[0].read_text())
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_active_search_creates_listings(db_session, tmp_path):
    summaries = [
        {"itemId": "v1|10|0", "title": "WDI Pin LE 300", "itemWebUrl": "https://ebay.com/10"},
    ]

    async def fake_search(query, filters=None, limit=50):
        return summaries

    async def fake_item_detail(item_id):
        return {
            "title": "WDI Pin LE 300", "description": None,
            "image": {"imageUrl": "https://cdn/10.jpg"},
            "price": {"value": "45.00", "currency": "USD"},
            "seller": {"username": "some-seller"},
        }

    async def fake_download(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"\xff\xd8")
        return dest

    with patch.object(collect_listings, "browse_api_search", new=AsyncMock(side_effect=fake_search)), \
         patch.object(collect_listings, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(collect_listings, "_download_image", new=AsyncMock(side_effect=fake_download)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value={"characters": ["WDI"]})):
        result = await collect_listings.run_active_search(
            query="WDI pin",
            data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=True,
        )

    assert result["listings_new"] == 1

    jobs = (await db_session.execute(select(CollectionJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].job_type == CollectionJobType.KEYWORD_ACTIVE

    listings = (await db_session.execute(select(EbayListing))).scalars().all()
    assert len(listings) == 1
    assert listings[0].title == "WDI Pin LE 300"


@pytest.mark.asyncio
async def test_sold_creates_listings_from_rapidapi(db_session, tmp_path):
    api_result = {
        "aggregates": {
            "average_price": 22.50, "median_price": 20.00,
            "min_price": 10.00, "max_price": 35.00, "results": 2,
        },
        "products": [
            {"title": "Stitch LE 500 Pin", "sale_price": "25.00", "date_sold": "Mar 10, 2026", "link": "https://ebay.com/sold/1"},
            {"title": "Stitch Pin Lot", "sale_price": "20.00", "date_sold": "Mar 08, 2026", "link": "https://ebay.com/sold/2"},
        ],
    }

    with patch.object(collect_listings, "fetch_sold_listings", new=AsyncMock(return_value=api_result)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value={"characters": ["Stitch"]})):
        result = await collect_listings.run_sold(
            query="Stitch LE 500",
            data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=True,
        )

    assert result["listings_new"] == 2
    assert result["listings_skipped"] == 0

    jobs = (await db_session.execute(select(CollectionJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].job_type == CollectionJobType.KEYWORD_SOLD
    assert jobs[0].result_metadata["average_price"] == 22.50

    listings = (await db_session.execute(select(EbayListing))).scalars().all()
    assert len(listings) == 2
    for listing in listings:
        assert listing.listing_type == EbayListingType.SOLD
        assert listing.source == "rapidapi_sold"
        assert listing.local_image_path is None  # no image download for sold


@pytest.mark.asyncio
async def test_sold_deduplicates_on_title_price_date(db_session, tmp_path):
    # Pre-create a sold listing
    job = CollectionJob(
        job_type=CollectionJobType.KEYWORD_SOLD, query="test", source="rapidapi_sold",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    existing = EbayListing(
        listing_type=EbayListingType.SOLD,
        source="rapidapi_sold",
        title="Stitch LE 500 Pin",
        price=25.00,
        sale_date="Mar 10, 2026",
        collection_job_id=job.id,
    )
    db_session.add(existing)
    await db_session.commit()

    api_result = {
        "aggregates": {"average_price": 25.00, "median_price": 25.00, "min_price": 25.00, "max_price": 25.00, "results": 2},
        "products": [
            {"title": "Stitch LE 500 Pin", "sale_price": "25.00", "date_sold": "Mar 10, 2026", "link": "https://ebay.com/1"},
            {"title": "New Pin", "sale_price": "30.00", "date_sold": "Mar 11, 2026", "link": "https://ebay.com/2"},
        ],
    }

    with patch.object(collect_listings, "fetch_sold_listings", new=AsyncMock(return_value=api_result)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value={})):
        result = await collect_listings.run_sold(
            query="Stitch", data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=False,
        )

    assert result["listings_new"] == 1
    assert result["listings_skipped"] == 1

    listings = (await db_session.execute(select(EbayListing))).scalars().all()
    assert len(listings) == 2  # 1 existing + 1 new


from src.models import Pin, PinStatus


@pytest.mark.asyncio
async def test_promote_creates_pins_from_listings(db_session, tmp_path):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE, query="test", source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing1 = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|1|0", title="Stitch Pin",
        price=19.99, seller="pins-n-things",
        local_image_path=str(tmp_path / "img1.jpg"),
        listing_url="https://ebay.com/1",
        parsed_fields={"characters": ["Stitch"]},
        collection_job_id=job.id,
    )
    listing2 = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|2|0", title="Goofy Pin",
        price=14.99, seller="pins-n-things",
        local_image_path=str(tmp_path / "img2.jpg"),
        listing_url="https://ebay.com/2",
        parsed_fields={"characters": ["Goofy"]},
        collection_job_id=job.id,
    )
    db_session.add_all([listing1, listing2])
    await db_session.commit()

    result = await collect_listings.run_promote(
        job_id=job.id,
        batch_name="test-batch",
        session_factory=lambda: _session_wrapper(db_session),
    )

    assert result["promoted"] == 2
    assert result["skipped"] == 0

    pins = (await db_session.execute(select(Pin).where(Pin.batch_id == "test-batch"))).scalars().all()
    assert len(pins) == 2
    for pin in pins:
        assert pin.status == PinStatus.UNPROCESSED
        assert pin.reference_source == "browse_api"
        assert pin.reference_external_id in {"v1|1|0", "v1|2|0"}


@pytest.mark.asyncio
async def test_promote_skips_already_promoted(db_session, tmp_path):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE, query="test", source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|1|0", title="Stitch Pin",
        price=19.99, collection_job_id=job.id,
    )
    db_session.add(listing)
    await db_session.commit()

    # Pre-create a pin with the same external ID
    pin = Pin(
        batch_id="old-batch", status=PinStatus.PRICED, image_paths=[],
        reference_source="ebay_browse", reference_external_id="v1|1|0",
    )
    db_session.add(pin)
    await db_session.commit()

    result = await collect_listings.run_promote(
        job_id=job.id,
        batch_name="new-batch",
        session_factory=lambda: _session_wrapper(db_session),
    )

    assert result["promoted"] == 0
    assert result["skipped"] == 1


@pytest.mark.asyncio
async def test_promote_by_seller(db_session, tmp_path):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE, query="test", source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing1 = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|1|0", title="Pin A", price=10.00,
        seller="target-seller", collection_job_id=job.id,
    )
    listing2 = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|2|0", title="Pin B", price=20.00,
        seller="other-seller", collection_job_id=job.id,
    )
    db_session.add_all([listing1, listing2])
    await db_session.commit()

    result = await collect_listings.run_promote(
        seller="target-seller",
        batch_name="promote-test",
        session_factory=lambda: _session_wrapper(db_session),
    )

    assert result["promoted"] == 1
    assert result["skipped"] == 0

    pins = (await db_session.execute(select(Pin).where(Pin.batch_id == "promote-test"))).scalars().all()
    assert len(pins) == 1
    assert pins[0].reference_raw_title == "Pin A"


@pytest.mark.asyncio
async def test_comps_subcommand_invokes_lookup(session_factory, monkeypatch):
    from src.models import Pin, PinStatus

    async with session_factory() as db:
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.PRICED,
                  reference_parsed_fields={"characters": ["Mickey"], "franchise": "Disney"})
        db.add(pin)
        await db.commit()
        pin_id = pin.id

    called = {}
    async def fake_lookup(sf, pid, today=None):
        called["pid"] = pid
        from src.pipeline.comp_lookup import LookupResult, LookupStatus
        return LookupResult(status=LookupStatus.API_CALLED, comps_written=3)

    monkeypatch.setattr(collect_listings, "lookup_comps_for_pin", fake_lookup)
    monkeypatch.setattr(collect_listings, "_make_session_factory", lambda: session_factory)

    await collect_listings.run_comps(pin_id=pin_id, refresh=False)
    assert called["pid"] == pin_id
