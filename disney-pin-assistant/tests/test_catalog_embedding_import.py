import json
import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from src.models import Base, CatalogEntry
from src.main import app
from src.database import get_db
import io


@pytest_asyncio.fixture
async def test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_json_import_stores_image_path_and_embedding(test_db):
    entries = [
        {
            "canonical_name": "Test Pin With Image",
            "characters": ["Mickey Mouse"],
            "source": "pintradingdb",
            "source_reference_id": "12345",
            "image_path": "catalog_images/12345.jpg",
        }
    ]

    mock_embedding = [0.1] * 512
    with patch("src.routes.catalog.generate_embedding_for_entry", return_value=mock_embedding):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            file_content = json.dumps(entries).encode()
            response = await client.post(
                "/api/catalog/import/json",
                files={"file": ("catalog.json", io.BytesIO(file_content), "application/json")},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 1

    # Verify image_path and embedding were stored
    async with test_db() as db:
        result = await db.execute(select(CatalogEntry))
        entry = result.scalar_one()
        assert entry.image_path == "catalog_images/12345.jpg"
        assert entry.clip_embedding is not None
        loaded = json.loads(entry.clip_embedding)
        assert len(loaded) == 512
