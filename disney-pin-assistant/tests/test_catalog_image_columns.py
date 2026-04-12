import json
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.models import Base, CatalogEntry


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_catalog_entry_has_image_path(db_session):
    entry = CatalogEntry(
        canonical_name="Test Pin",
        image_path="catalog_images/12345.jpg",
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)

    assert entry.image_path == "catalog_images/12345.jpg"


@pytest.mark.asyncio
async def test_catalog_entry_has_clip_embedding(db_session):
    embedding = json.dumps([0.1] * 512)
    entry = CatalogEntry(
        canonical_name="Test Pin With Embedding",
        clip_embedding=embedding,
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)

    assert entry.clip_embedding is not None
    roundtripped = json.loads(entry.clip_embedding)
    assert len(roundtripped) == 512
    assert roundtripped[0] == pytest.approx(0.1)
