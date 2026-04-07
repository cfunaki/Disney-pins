import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from src.database import get_db
from src.models import Base, Pin, PinStatus, ListingDraft, ExportStatus
from src.routes.export import router as export_router
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest_asyncio.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(export_router)
    app.dependency_overrides[get_db] = override_get_db

    # Seed test data
    async with session_factory() as session:
        pin = Pin(
            batch_id="export-batch",
            status=PinStatus.APPROVED,
            photo_type="front",
            image_paths=["img/pin1.jpg"],
        )
        session.add(pin)
        await session.flush()

        draft = ListingDraft(
            pin_id=pin.id,
            title="Mickey Mouse LE Pin",
            description="A limited edition Mickey Mouse pin.",
            suggested_price=25.00,
            quick_sale_price=20.00,
            price_confidence="high",
            tags_keywords=["mickey", "disney", "limited edition"],
            export_status=ExportStatus.APPROVED,
        )
        session.add(draft)
        await session.commit()

    yield app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_export_csv(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/batch/export-batch/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    body = resp.text
    assert "Mickey Mouse LE Pin" in body
    assert "25.0" in body


@pytest.mark.asyncio
async def test_export_empty_batch(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/batch/nonexistent/export")
    assert resp.status_code == 200
    body = resp.text
    lines = [line for line in body.strip().split("\n") if line]
    assert len(lines) == 1  # headers only
