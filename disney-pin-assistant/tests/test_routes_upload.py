import io
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.database import get_db
from src.models import Base
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
    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.mark.asyncio
async def test_upload_single_photo(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fake_image = io.BytesIO(b"fake image data")
        response = await client.post(
            "/api/upload",
            files=[("files", ("pin1.jpg", fake_image, "image/jpeg"))],
            data={"photo_type": "front"},
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data["pins"]) == 1
    assert data["pins"][0]["status"] == "unprocessed"
    assert data["batch_id"] is not None

@pytest.mark.asyncio
async def test_upload_multiple_photos(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = [
            ("files", ("pin1.jpg", io.BytesIO(b"img1"), "image/jpeg")),
            ("files", ("pin2.jpg", io.BytesIO(b"img2"), "image/jpeg")),
            ("files", ("pin3.jpg", io.BytesIO(b"img3"), "image/jpeg")),
        ]
        response = await client.post("/api/upload", files=files)
    assert response.status_code == 200
    data = response.json()
    assert len(data["pins"]) == 3
    assert all(p["status"] == "unprocessed" for p in data["pins"])
