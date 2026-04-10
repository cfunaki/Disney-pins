import json
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.models import Base, CatalogEntry
from src.pipeline.matching import find_catalog_matches_hybrid


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


@pytest_asyncio.fixture
async def seeded_db_with_embeddings(db_session):
    entries = [
        CatalogEntry(
            canonical_name="Mickey Mouse 50th Anniversary LE 3000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            edition_size=3000,
            release_year=2023,
            pin_type="limited edition",
            source="pinpics",
            evidence_strength="high",
            source_reference_id="100",
            clip_embedding=json.dumps([0.9, 0.1, 0.0] + [0.0] * 509),
        ),
        CatalogEntry(
            canonical_name="Mickey Mouse Holiday LE 3000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            edition_size=3000,
            release_year=2023,
            pin_type="limited edition",
            source="pinpics",
            evidence_strength="high",
            source_reference_id="101",
            clip_embedding=json.dumps([0.1, 0.9, 0.0] + [0.0] * 509),
        ),
        CatalogEntry(
            canonical_name="Stitch Surfing Pin",
            characters=["Stitch"],
            franchise="Lilo & Stitch",
            pin_type="enamel",
            source="pinpics",
            evidence_strength="medium",
            source_reference_id="102",
            clip_embedding=json.dumps([0.1, 0.9, 0.0] + [0.0] * 509),
        ),
    ]
    db_session.add_all(entries)
    await db_session.commit()
    return db_session


MICKEY_EXTRACTION = {
    "characters": ["Mickey Mouse"],
    "franchise": "Mickey & Friends",
    "edition_size": 3000,
    "pin_type": "limited edition",
    "visible_dates": "2023",
    "event_clues": None,
    "text_on_pin": None,
    "collection_or_series": None,
    "suggested_search_terms": [],
}

QUERY_EMBEDDING_CLOSE_TO_A = [0.95, 0.05, 0.0] + [0.0] * 509


@pytest.mark.asyncio
async def test_hybrid_reranks_by_visual_similarity(seeded_db_with_embeddings):
    """Entry A should rank first because query embedding is closest to it."""
    matches = await find_catalog_matches_hybrid(
        seeded_db_with_embeddings,
        MICKEY_EXTRACTION,
        query_embedding=QUERY_EMBEDDING_CLOSE_TO_A,
        max_results=5,
    )
    assert len(matches) >= 1
    assert matches[0]["source_reference_id"] == "100"


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_text_only_without_embedding(seeded_db_with_embeddings):
    """When query_embedding=None, results should be returned without visual_similarity field."""
    matches = await find_catalog_matches_hybrid(
        seeded_db_with_embeddings,
        MICKEY_EXTRACTION,
        query_embedding=None,
        max_results=5,
    )
    assert len(matches) >= 1
    for match in matches:
        assert "visual_similarity" not in match


@pytest.mark.asyncio
async def test_hybrid_excludes_stitch_for_mickey_query(seeded_db_with_embeddings):
    """Mickey-specific extraction should not return the Stitch pin."""
    matches = await find_catalog_matches_hybrid(
        seeded_db_with_embeddings,
        MICKEY_EXTRACTION,
        query_embedding=QUERY_EMBEDDING_CLOSE_TO_A,
        max_results=5,
    )
    source_ids = [m["source_reference_id"] for m in matches]
    assert "102" not in source_ids
