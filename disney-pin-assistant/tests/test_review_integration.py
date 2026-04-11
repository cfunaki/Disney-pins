import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.main import app
from src.database import get_db
from src.models import (
    Base, Pin, PinStatus, VisionExtraction, CatalogEntry,
    CatalogMatch, MatchStatus, ListingDraft, ExportStatus,
)
from src.routes.pins import router as pins_router


@pytest_asyncio.fixture
async def integration_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.include_router(pins_router)
    app.dependency_overrides[get_db] = override_get_db

    async with factory() as session:
        pin = Pin(batch_id="b", status=PinStatus.MATCHED, image_paths=["x.jpg"])
        session.add(pin)
        await session.flush()

        extraction = VisionExtraction(
            pin_id=pin.id, characters=["Mickey"], franchise="Disney",
            pin_type="limited edition", edition_size=1500, visible_dates="2005",
            event_clues="50th Anniversary", confidence_score=0.9,
        )
        session.add(extraction)

        top_entry = CatalogEntry(canonical_name="Mickey 50th Anniversary", franchise="Disney",
                                  release_year=2005, edition_size=1500, source="pintradingdb")
        better_entry = CatalogEntry(canonical_name="Mickey Halloween 2010", franchise="Disney",
                                     release_year=2010, edition_size=500, source="pintradingdb")
        session.add_all([top_entry, better_entry])
        await session.flush()

        m1 = CatalogMatch(pin_id=pin.id, catalog_entry_id=top_entry.id,
                          match_confidence=0.92, rank=1, status=MatchStatus.SUGGESTED)
        m2 = CatalogMatch(pin_id=pin.id, catalog_entry_id=better_entry.id,
                          match_confidence=0.71, rank=2, status=MatchStatus.SUGGESTED)
        session.add_all([m1, m2])

        draft = ListingDraft(pin_id=pin.id, title="Disney Mickey 50th Anniversary 2005 Pin LE/1500",
                              description="Mickey 50th Anniversary", export_status=ExportStatus.DRAFT)
        session.add(draft)

        await session.commit()
        app.state.pin_id = pin.id
        app.state.better_entry_id = better_entry.id

    yield app
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_user_accepts_different_match_draft_regenerates(integration_app):
    pin_id = integration_app.state.pin_id
    better_id = integration_app.state.better_entry_id

    transport = ASGITransport(app=integration_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get(f"/api/pins/{pin_id}")).json()
        assert "2005" in before["listing_draft"]["title"]

        resp = await client.post(
            f"/api/pins/{pin_id}/match/select",
            json={"catalog_entry_id": better_id},
        )
        assert resp.status_code == 200
        after = resp.json()

        accepted = [m for m in after["catalog_matches"] if m["status"] == "accepted"]
        assert len(accepted) == 1
        assert accepted[0]["catalog_entry_id"] == better_id

        assert "2010" in after["listing_draft"]["title"]
        assert "2005" not in after["listing_draft"]["title"]
