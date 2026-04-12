import pytest
from sqlalchemy import select

from src.models import (
    Pin,
    PinStatus,
    VisionExtraction,
    CatalogEntry,
    CatalogMatch,
    MatchStatus,
    Comp,
    ListingType,
    MatchType,
    ListingDraft,
    ExportStatus,
)


@pytest.mark.asyncio
async def test_pin_no_catalog_match_defaults_false_in_db(db_session):
    pin = Pin(batch_id="batch-nocat", status=PinStatus.UNPROCESSED, image_paths=[])
    db_session.add(pin)
    await db_session.commit()
    await db_session.refresh(pin)
    assert pin.no_catalog_match is False


@pytest.mark.asyncio
async def test_pin_no_catalog_match_persists_true(db_session):
    pin = Pin(
        batch_id="batch-nocat2",
        status=PinStatus.UNPROCESSED,
        image_paths=[],
        no_catalog_match=True,
    )
    db_session.add(pin)
    await db_session.commit()
    result = await db_session.execute(select(Pin).where(Pin.id == pin.id))
    assert result.scalar_one().no_catalog_match is True


@pytest.mark.asyncio
async def test_create_pin(db_session):
    pin = Pin(
        batch_id="batch-001",
        status=PinStatus.UNPROCESSED,
        photo_type="front",
        seller_notes="Mint condition",
        image_paths=["img1.jpg", "img2.jpg"],
    )
    db_session.add(pin)
    await db_session.commit()

    result = await db_session.execute(select(Pin).where(Pin.id == pin.id))
    saved = result.scalar_one()

    assert saved.batch_id == "batch-001"
    assert saved.status == PinStatus.UNPROCESSED
    assert saved.photo_type == "front"
    assert saved.seller_notes == "Mint condition"
    assert saved.image_paths == ["img1.jpg", "img2.jpg"]
    assert saved.created_at is not None


@pytest.mark.asyncio
async def test_pin_status_transitions(db_session):
    pin = Pin(batch_id="batch-002", status=PinStatus.UNPROCESSED)
    db_session.add(pin)
    await db_session.commit()

    pin.status = PinStatus.EXTRACTED
    await db_session.commit()

    result = await db_session.execute(select(Pin).where(Pin.id == pin.id))
    saved = result.scalar_one()
    assert saved.status == PinStatus.EXTRACTED


@pytest.mark.asyncio
async def test_vision_extraction_relationship(db_session):
    pin = Pin(batch_id="batch-003", status=PinStatus.UNPROCESSED)
    db_session.add(pin)
    await db_session.commit()

    extraction = VisionExtraction(
        pin_id=pin.id,
        characters=["Mickey Mouse"],
        franchise="Disney Classic",
        confidence_score=0.92,
        suggested_search_terms=["mickey", "classic"],
    )
    db_session.add(extraction)
    await db_session.commit()

    result = await db_session.execute(select(VisionExtraction).where(VisionExtraction.pin_id == pin.id))
    saved = result.scalar_one()

    assert saved.pin_id == pin.id
    assert saved.characters == ["Mickey Mouse"]
    assert saved.confidence_score == 0.92

    # Verify relationship navigation
    await db_session.refresh(pin, ["extraction"])
    assert pin.extraction is not None
    assert pin.extraction.id == saved.id


@pytest.mark.asyncio
async def test_catalog_entry_and_match(db_session):
    pin = Pin(batch_id="batch-004", status=PinStatus.MATCHED)
    db_session.add(pin)
    await db_session.commit()

    entry = CatalogEntry(
        canonical_name="Mickey Mouse 50th Anniversary Pin",
        characters=["Mickey Mouse"],
        franchise="Disney Classic",
        edition_size=5000,
    )
    db_session.add(entry)
    await db_session.commit()

    match = CatalogMatch(
        pin_id=pin.id,
        catalog_entry_id=entry.id,
        match_confidence=0.85,
        match_reasoning="Character and edition size match",
        rank=1,
        status=MatchStatus.SUGGESTED,
    )
    db_session.add(match)
    await db_session.commit()

    result = await db_session.execute(select(CatalogMatch).where(CatalogMatch.pin_id == pin.id))
    saved = result.scalar_one()

    assert saved.match_confidence == 0.85
    assert saved.rank == 1
    assert saved.status == MatchStatus.SUGGESTED


@pytest.mark.asyncio
async def test_comp_creation(db_session):
    pin = Pin(batch_id="batch-005", status=PinStatus.PRICED)
    db_session.add(pin)
    await db_session.commit()

    comp = Comp(
        pin_id=pin.id,
        title="Disney Mickey Pin - Sold Listing",
        price=24.99,
        listing_type=ListingType.SOLD,
        match_type=MatchType.EXACT,
        sale_date="2026-03-15",
        condition="New",
    )
    db_session.add(comp)
    await db_session.commit()

    result = await db_session.execute(select(Comp).where(Comp.pin_id == pin.id))
    saved = result.scalar_one()

    assert saved.price == 24.99
    assert saved.listing_type == ListingType.SOLD
    assert saved.match_type == MatchType.EXACT


@pytest.mark.asyncio
async def test_listing_draft_creation(db_session):
    pin = Pin(batch_id="batch-006", status=PinStatus.APPROVED)
    db_session.add(pin)
    await db_session.commit()

    draft = ListingDraft(
        pin_id=pin.id,
        title="Mickey Mouse 50th Anniversary LE Pin",
        description="Limited edition pin in excellent condition.",
        suggested_price=29.99,
        quick_sale_price=19.99,
        price_confidence="medium",
        tags_keywords=["mickey", "anniversary", "limited edition"],
        export_status=ExportStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.commit()

    result = await db_session.execute(select(ListingDraft).where(ListingDraft.pin_id == pin.id))
    saved = result.scalar_one()

    assert saved.title == "Mickey Mouse 50th Anniversary LE Pin"
    assert saved.suggested_price == 29.99
    assert saved.tags_keywords == ["mickey", "anniversary", "limited edition"]
    assert saved.export_status == ExportStatus.DRAFT
