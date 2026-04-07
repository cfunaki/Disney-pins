import io
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.database import get_db
from src.models import Base, Pin, PinStatus, CatalogEntry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

@pytest_asyncio.fixture
async def full_test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Seed catalog
    async with session_factory() as session:
        entry = CatalogEntry(
            canonical_name="Mickey Mouse Epcot Food & Wine 2019 LE 3000",
            characters=["Mickey Mouse"], franchise="Mickey & Friends",
            event="Epcot Food & Wine Festival", edition_size=3000,
            release_year=2019, pin_type="limited edition",
            source="test", evidence_strength="high",
        )
        session.add(entry)
        await session.commit()
    async def override_get_db():
        async with session_factory() as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db
    yield app, session_factory
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.mark.asyncio
async def test_full_pipeline(full_test_app):
    test_app, session_factory = full_test_app
    mock_vision = {
        "characters": ["Mickey Mouse"], "franchise": "Mickey & Friends",
        "collection_or_series": None, "text_on_pin": "Epcot",
        "visible_dates": "2019", "event_clues": "Food & Wine Festival",
        "pin_type": "limited edition", "edition_size": 3000,
        "condition_observations": "Excellent",
        "suggested_search_terms": ["mickey mouse food wine 2019 le pin"],
        "confidence_score": 0.9,
    }
    mock_comps = [
        {"itemId": "111", "title": "Mickey Food Wine 2019 Pin LE 3000",
         "price": {"value": "24.99", "currency": "USD"},
         "condition": "New", "itemEndDate": "2026-03-15"},
    ]
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Upload
        response = await client.post(
            "/api/upload",
            files=[("files", ("pin.jpg", io.BytesIO(b"fake"), "image/jpeg"))],
            data={"photo_type": "front"},
        )
        assert response.status_code == 200
        batch_id = response.json()["batch_id"]

        # Step 2: Process (with mocked external calls)
        with patch("src.pipeline.vision.call_vision_api", new_callable=AsyncMock, return_value=mock_vision), \
             patch("src.pipeline.comps.ebay_search", new_callable=AsyncMock, return_value=mock_comps):
            from src.pipeline.orchestrator import process_batch
            await process_batch(session_factory, batch_id)

        # Step 3: Check results
        response = await client.get(f"/api/batch/{batch_id}/pins")
        assert response.status_code == 200
        pins = response.json()
        assert len(pins) == 1
        pin = pins[0]
        assert pin["extraction"] is not None
        assert pin["extraction"]["characters"] == ["Mickey Mouse"]
        assert pin["listing_draft"] is not None
        assert "Mickey Mouse" in pin["listing_draft"]["title"]
        assert pin["listing_draft"]["suggested_price"] is not None

        # Step 4: Approve
        response = await client.post(f"/api/pins/{pin['id']}/approve")
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

        # Step 5: Export
        response = await client.get(f"/api/batch/{batch_id}/export")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "Mickey Mouse" in response.text
