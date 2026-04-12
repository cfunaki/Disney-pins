import json
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.models import Base, Pin, PinStatus, CatalogEntry
from src.pipeline.orchestrator import process_single_pin


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
    async with session_factory() as db:
        entry = CatalogEntry(
            canonical_name="Mickey Mouse Test Pin",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            pin_type="limited edition",
            source="pintradingdb",
            source_reference_id="100",
            evidence_strength="high",
            clip_embedding=json.dumps([1.0] + [0.0] * 511),
            image_path="catalog_images/100.jpg",
        )
        db.add(entry)
        pin = Pin(
            batch_id="test-batch",
            status=PinStatus.UNPROCESSED,
            image_paths=["uploads/test_pin.jpg"],
        )
        db.add(pin)
        await db.commit()
        pin_id = pin.id
    return session_factory, pin_id


@pytest.mark.asyncio
async def test_orchestrator_uses_hybrid_matching(seeded_factory):
    session_factory, pin_id = seeded_factory

    mock_extraction = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "pin_type": "limited edition",
        "edition_size": None,
        "event_clues": None,
        "visible_dates": None,
        "text_on_pin": None,
        "collection_or_series": None,
        "condition_observations": "",
        "suggested_search_terms": ["mickey mouse pin"],
        "confidence_score": 0.9,
    }
    mock_embedding = [1.0] + [0.0] * 511

    with patch("src.pipeline.orchestrator.extract_pin_metadata", new_callable=AsyncMock, return_value=mock_extraction), \
         patch("src.pipeline.orchestrator.compute_clip_embedding", return_value=mock_embedding), \
         patch("src.pipeline.orchestrator.search_comps", new_callable=AsyncMock, return_value=[]), \
         patch("src.pipeline.orchestrator.filter_comps", return_value=[]):

        await process_single_pin(session_factory, pin_id)

    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        assert pin.status != PinStatus.UNPROCESSED
        assert pin.status != PinStatus.EXTRACTED
