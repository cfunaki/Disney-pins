import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.main import app
from src.database import get_db
from src.models import Base, CatalogEntry
from src.routes.catalog import router as catalog_router


@pytest_asyncio.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.include_router(catalog_router)
    app.dependency_overrides[get_db] = override_get_db

    async with factory() as session:
        for i in range(25):
            session.add(CatalogEntry(
                canonical_name=f"Mickey Pin {i:02d}",
                franchise="Disney",
                release_year=2000 + i,
                edition_size=1000 + i,
                image_path=f"catalog/mickey-{i:02d}.jpg",
                source="pintradingdb",
            ))
        await session.commit()

    yield app
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_returns_image_path_and_release_year(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/catalog/search?q=Mickey")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) > 0
    assert "image_path" in entries[0]
    assert "release_year" in entries[0]
    assert entries[0]["image_path"].startswith("catalog/")


@pytest.mark.asyncio
async def test_search_returns_at_most_20(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/catalog/search?q=Mickey")
    entries = response.json()
    assert len(entries) == 20


@pytest.mark.asyncio
async def test_search_offset_pagination(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page_one = (await client.get("/api/catalog/search?q=Mickey&offset=0")).json()
        page_two = (await client.get("/api/catalog/search?q=Mickey&offset=20")).json()
    assert len(page_one) == 20
    assert len(page_two) == 5
    page_one_ids = {e["id"] for e in page_one}
    page_two_ids = {e["id"] for e in page_two}
    assert page_one_ids.isdisjoint(page_two_ids)
