"""End-to-end test for hybrid text + image matching pipeline."""
import json
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from src.models import Base, Pin, PinStatus, CatalogEntry, CatalogMatch


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_factory(session_factory):
    """Seed with two Mickey pins that have identical text attributes but different embeddings."""
    async with session_factory() as db:
        # Pin A: "50th anniversary" design — embedding points in direction A
        entry_a = CatalogEntry(
            canonical_name="Mickey Mouse 50th Anniversary LE 2000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            edition_size=2000,
            release_year=2023,
            pin_type="limited edition",
            source="pintradingdb",
            source_reference_id="A",
            evidence_strength="high",
            clip_embedding=json.dumps([0.9, 0.1] + [0.0] * 510),
            image_path="catalog_images/A.jpg",
        )
        # Pin B: "Holiday" design — embedding points in direction B
        entry_b = CatalogEntry(
            canonical_name="Mickey Mouse Holiday Cheer LE 2000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            edition_size=2000,
            release_year=2023,
            pin_type="limited edition",
            source="pintradingdb",
            source_reference_id="B",
            evidence_strength="high",
            clip_embedding=json.dumps([0.1, 0.9] + [0.0] * 510),
            image_path="catalog_images/B.jpg",
        )
        pin = Pin(
            batch_id="integration-test",
            status=PinStatus.UNPROCESSED,
            image_paths=["uploads/user_pin.jpg"],
        )
        db.add_all([entry_a, entry_b, pin])
        await db.commit()
        pin_id = pin.id
    return session_factory, pin_id


@pytest.mark.asyncio
async def test_hybrid_pipeline_identifies_correct_pin(seeded_factory):
    """The user's pin looks like pin A (50th anniversary).
    Both pins have identical text attributes, so text matching alone can't distinguish them.
    CLIP embedding should identify the correct one."""
    session_factory, pin_id = seeded_factory

    mock_extraction = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "edition_size": 2000,
        "pin_type": "limited edition",
        "visible_dates": "2023",
        "event_clues": None,
        "text_on_pin": None,
        "collection_or_series": None,
        "condition_observations": "",
        "suggested_search_terms": ["mickey mouse anniversary pin"],
        "confidence_score": 0.9,
    }
    # User's photo embedding is close to pin A
    mock_embedding = [0.95, 0.05] + [0.0] * 510

    with patch("src.pipeline.orchestrator.extract_pin_metadata", new_callable=AsyncMock, return_value=mock_extraction), \
         patch("src.pipeline.orchestrator.compute_clip_embedding", return_value=mock_embedding), \
         patch("src.pipeline.orchestrator.search_comps", new_callable=AsyncMock, return_value=[]), \
         patch("src.pipeline.orchestrator.filter_comps", return_value=[]):

        from src.pipeline.orchestrator import process_single_pin
        await process_single_pin(session_factory, pin_id)

    # Verify: pin A should be the top match
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        assert pin.status in (PinStatus.MATCHED, PinStatus.PRICED)

        result = await db.execute(
            select(CatalogMatch)
            .where(CatalogMatch.pin_id == pin_id)
            .order_by(CatalogMatch.rank)
        )
        matches = result.scalars().all()
        assert len(matches) >= 1

        top_match = matches[0]
        top_entry = await db.get(CatalogEntry, top_match.catalog_entry_id)
        assert top_entry.source_reference_id == "A"
