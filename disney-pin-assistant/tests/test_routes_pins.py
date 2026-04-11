import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.database import get_db
from src.models import Base, Pin, PinStatus, VisionExtraction, ListingDraft, ExportStatus
from src.routes.pins import router as pins_router
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest_asyncio.fixture
async def test_app():
    from src.models import CatalogEntry, CatalogMatch, MatchStatus

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.include_router(pins_router)
    app.dependency_overrides[get_db] = override_get_db

    async with session_factory() as session:
        pin = Pin(batch_id="test-batch", status=PinStatus.PRICED, photo_type="front", image_paths=["img/pin1.jpg"])
        session.add(pin)
        await session.flush()

        extraction = VisionExtraction(pin_id=pin.id, characters=["Mickey Mouse"], franchise="Disney",
                                       pin_type="limited_edition", confidence_score=0.95,
                                       suggested_search_terms=["mickey", "disney pin"])
        session.add(extraction)

        entry = CatalogEntry(canonical_name="Mickey 50th Anniversary", franchise="Disney",
                              release_year=2005, edition_size=1500, image_path="catalog/mickey.jpg",
                              source="pintradingdb")
        session.add(entry)
        await session.flush()

        cm = CatalogMatch(pin_id=pin.id, catalog_entry_id=entry.id, match_confidence=0.92,
                          match_reasoning="character + franchise match", rank=1, status=MatchStatus.SUGGESTED)
        session.add(cm)

        draft = ListingDraft(pin_id=pin.id, title="Mickey Mouse LE Pin", description="A limited edition Mickey Mouse pin.",
                              suggested_price=25.00, quick_sale_price=20.00, price_confidence="high",
                              tags_keywords=["mickey", "disney", "limited edition"], export_status=ExportStatus.DRAFT)
        session.add(draft)
        await session.commit()

    yield app

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_batch_pins(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/batch/test-batch/pins")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "priced"
    assert data[0]["batch_id"] == "test-batch"
    assert data[0]["extraction"] is not None
    assert data[0]["listing_draft"] is not None


@pytest.mark.asyncio
async def test_approve_pin(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/pins/1/approve")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"


@pytest.mark.asyncio
async def test_update_pin_draft(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/api/pins/1",
            json={"title": "Updated Title", "suggested_price": 30.00},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["listing_draft"]["title"] == "Updated Title"
    assert data["listing_draft"]["suggested_price"] == 30.00


@pytest.mark.asyncio
async def test_pin_dict_includes_full_catalog_match_details(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/pins/1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["catalog_matches"]) == 1
    match = data["catalog_matches"][0]
    assert match["canonical_name"] == "Mickey 50th Anniversary"
    assert match["image_path"] == "catalog/mickey.jpg"
    assert match["release_year"] == 2005
    assert match["edition_size"] == 1500
    assert match["source"] == "pintradingdb"


@pytest.mark.asyncio
async def test_pin_dict_includes_no_catalog_match_flag(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/pins/1")
    data = response.json()
    assert "no_catalog_match" in data
    assert data["no_catalog_match"] is False


@pytest.mark.asyncio
async def test_update_pin_response_includes_risk_badge(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/api/pins/1", json={"title": "Updated Title", "suggested_price": 30.00})
    assert response.status_code == 200
    data = response.json()
    assert "risk_badge" in data
    assert data["risk_badge"] in {"ready", "ambiguous_match", "low_extraction", "no_match", "approved", "exported"}


@pytest.mark.asyncio
async def test_batch_pins_include_risk_badge(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/batch/test-batch/pins")
    data = response.json()
    assert len(data) == 1
    assert "risk_badge" in data[0]
    assert data[0]["risk_badge"] in {"ready", "ambiguous_match", "low_extraction", "no_match", "approved", "exported"}
