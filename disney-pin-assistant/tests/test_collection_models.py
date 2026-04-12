import pytest
from sqlalchemy import select
from src.models import (
    EbayListing,
    CollectionJob,
    EbayListingType,
    CollectionJobType,
    CollectionJobStatus,
)


def test_ebay_listing_type_enum_values():
    assert EbayListingType.ACTIVE.value == "active"
    assert EbayListingType.SOLD.value == "sold"


def test_collection_job_type_enum_values():
    assert CollectionJobType.SELLER_ACTIVE.value == "seller_active"
    assert CollectionJobType.KEYWORD_ACTIVE.value == "keyword_active"
    assert CollectionJobType.KEYWORD_SOLD.value == "keyword_sold"


def test_collection_job_status_enum_values():
    assert CollectionJobStatus.PENDING.value == "pending"
    assert CollectionJobStatus.RUNNING.value == "running"
    assert CollectionJobStatus.COMPLETED.value == "completed"
    assert CollectionJobStatus.FAILED.value == "failed"


@pytest.mark.asyncio
async def test_collection_job_round_trip(db_session):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE,
        query="pins-n-things",
        source="browse_api",
        status=CollectionJobStatus.PENDING,
    )
    db_session.add(job)
    await db_session.commit()

    result = await db_session.execute(select(CollectionJob))
    row = result.scalars().first()
    assert row is not None
    assert row.query == "pins-n-things"
    assert row.job_type == CollectionJobType.SELLER_ACTIVE
    assert row.status == CollectionJobStatus.PENDING
    assert row.listings_found == 0
    assert row.listings_new == 0


@pytest.mark.asyncio
async def test_ebay_listing_round_trip(db_session):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE,
        query="test",
        source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing = EbayListing(
        listing_type=EbayListingType.ACTIVE,
        source="browse_api",
        ebay_item_id="v1|123|0",
        title="Disney Stitch Pin LE 500",
        price=24.99,
        seller="pins-n-things",
        collection_job_id=job.id,
    )
    db_session.add(listing)
    await db_session.commit()

    result = await db_session.execute(select(EbayListing))
    row = result.scalars().first()
    assert row is not None
    assert row.title == "Disney Stitch Pin LE 500"
    assert row.price == 24.99
    assert row.listing_type == EbayListingType.ACTIVE
    assert row.ebay_item_id == "v1|123|0"
    assert row.collection_job_id == job.id
    assert row.currency == "USD"


@pytest.mark.asyncio
async def test_ebay_listing_relationship_to_job(db_session):
    job = CollectionJob(
        job_type=CollectionJobType.KEYWORD_SOLD,
        query="disney pin",
        source="rapidapi_sold",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing = EbayListing(
        listing_type=EbayListingType.SOLD,
        source="rapidapi_sold",
        title="Maleficent Pin",
        price=15.00,
        sale_date="2026-03-15",
        collection_job_id=job.id,
    )
    db_session.add(listing)
    await db_session.commit()

    await db_session.refresh(job, attribute_names=["listings"])
    assert len(job.listings) == 1
    assert job.listings[0].title == "Maleficent Pin"
