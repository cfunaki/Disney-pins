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
