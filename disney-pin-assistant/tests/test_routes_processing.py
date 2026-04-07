import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.database import get_db
from src.models import Base, Pin, PinStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

@pytest_asyncio.fixture
async def test_app_with_pins():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        for i in range(3):
            pin = Pin(batch_id="test-batch", status=PinStatus.UNPROCESSED, photo_type="front", image_paths=[f"/fake/pin{i}.jpg"])
            session.add(pin)
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
async def test_batch_progress(test_app_with_pins):
    test_app, _ = test_app_with_pins
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/batch/test-batch/progress")
    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == "test-batch"
    assert data["total"] == 3
    assert data["processed"] == 0
    assert data["status_counts"]["unprocessed"] == 3
