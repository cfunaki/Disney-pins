import io
import json
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.main import app
from src.database import get_db
from src.models import Base, CatalogEntry


@pytest_asyncio.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


SAMPLE_ENTRIES = [
    {
        "canonical_name": "Mickey Mouse Club Pin",
        "source": "pinpics",
        "source_reference_id": "PP-001",
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
    },
    {
        "canonical_name": "Cinderella Castle Pin",
        "source": "pinpics",
        "source_reference_id": "PP-002",
        "characters": ["Cinderella"],
        "franchise": "Cinderella",
    },
]


@pytest.mark.asyncio
async def test_json_import_deduplicates_by_source_ref(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First import: 2 entries
        payload = json.dumps(SAMPLE_ENTRIES).encode("utf-8")
        response = await client.post(
            "/api/catalog/import/json",
            files={"file": ("catalog.json", io.BytesIO(payload), "application/json")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 2
        assert data["skipped"] == 0

        # Second import: same 2 entries — both should be skipped
        payload = json.dumps(SAMPLE_ENTRIES).encode("utf-8")
        response = await client.post(
            "/api/catalog/import/json",
            files={"file": ("catalog.json", io.BytesIO(payload), "application/json")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 0
        assert data["skipped"] == 2

    # Verify only 2 entries in DB total
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        stats = await client.get("/api/catalog/stats")
        assert stats.status_code == 200
        assert stats.json()["total_entries"] == 2


@pytest.mark.asyncio
async def test_json_import_handles_within_batch_duplicates(test_app):
    """Entries duplicated within a single batch should only be imported once."""
    duplicated_batch = SAMPLE_ENTRIES + SAMPLE_ENTRIES  # 4 items, 2 unique
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = json.dumps(duplicated_batch).encode("utf-8")
        response = await client.post(
            "/api/catalog/import/json",
            files={"file": ("catalog.json", io.BytesIO(payload), "application/json")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["imported"] == 2
        assert data["skipped"] == 2

        stats = await client.get("/api/catalog/stats")
        assert stats.json()["total_entries"] == 2


@pytest.mark.asyncio
async def test_json_import_allows_entries_without_source_ref(test_app):
    """Entries with no source_reference_id should always be imported (no dedup key)."""
    entries = [
        {"canonical_name": "Unknown Pin A", "source": "manual"},
        {"canonical_name": "Unknown Pin B", "source": "manual"},
    ]
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(2):
            payload = json.dumps(entries).encode("utf-8")
            response = await client.post(
                "/api/catalog/import/json",
                files={"file": ("catalog.json", io.BytesIO(payload), "application/json")},
            )
            assert response.status_code == 200
            assert response.json()["imported"] == 2

        # All 4 rows exist because there's no ref ID to deduplicate on
        stats = await client.get("/api/catalog/stats")
        assert stats.json()["total_entries"] == 4
