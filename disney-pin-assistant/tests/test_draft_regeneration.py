import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.models import (
    Base, Pin, PinStatus, VisionExtraction, CatalogEntry,
    CatalogMatch, MatchStatus, ListingDraft, ExportStatus,
)
from src.pipeline.draft_regeneration import regenerate_draft_for_pin


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed(session, *, accepted_match: bool = False, no_catalog_match: bool = False):
    pin = Pin(batch_id="b", status=PinStatus.MATCHED, image_paths=["x.jpg"], no_catalog_match=no_catalog_match)
    session.add(pin)
    await session.flush()

    extraction = VisionExtraction(
        pin_id=pin.id, characters=["Mickey Mouse"], franchise="Disney",
        pin_type="limited edition", edition_size=1500, visible_dates="2005",
        event_clues="50th Anniversary", confidence_score=0.9,
    )
    session.add(extraction)

    entry_a = CatalogEntry(canonical_name="Mickey 50th Anniversary", franchise="Disney", release_year=2005, edition_size=1500)
    entry_b = CatalogEntry(canonical_name="Mickey Halloween", franchise="Disney", release_year=2010, edition_size=500)
    session.add_all([entry_a, entry_b])
    await session.flush()

    match_a = CatalogMatch(pin_id=pin.id, catalog_entry_id=entry_a.id, match_confidence=0.95, rank=1,
                            status=MatchStatus.ACCEPTED if accepted_match else MatchStatus.SUGGESTED)
    match_b = CatalogMatch(pin_id=pin.id, catalog_entry_id=entry_b.id, match_confidence=0.60, rank=2, status=MatchStatus.SUGGESTED)
    session.add_all([match_a, match_b])
    await session.commit()
    return pin.id, entry_a.id, entry_b.id


@pytest.mark.asyncio
async def test_regenerate_uses_accepted_match_when_present(db_session):
    pin_id, entry_a_id, _ = await _seed(db_session, accepted_match=True)
    draft = await regenerate_draft_for_pin(db_session, pin_id)
    await db_session.commit()
    assert draft is not None
    assert "Mickey" in draft.title
    assert "2005" in draft.title
    assert draft.export_status == ExportStatus.DRAFT


@pytest.mark.asyncio
async def test_regenerate_falls_back_to_top_match_when_none_accepted(db_session):
    pin_id, entry_a_id, _ = await _seed(db_session, accepted_match=False)
    draft = await regenerate_draft_for_pin(db_session, pin_id)
    await db_session.commit()
    # Top match (rank 1) should be entry A — release year 2005
    assert "2005" in draft.title


@pytest.mark.asyncio
async def test_regenerate_uses_extraction_only_when_no_catalog_match(db_session):
    pin_id, _, _ = await _seed(db_session, no_catalog_match=True)
    draft = await regenerate_draft_for_pin(db_session, pin_id)
    await db_session.commit()
    # No catalog match → year comes from extraction (2005), title still mentions Mickey
    assert "Mickey" in draft.title
    assert draft is not None


@pytest.mark.asyncio
async def test_regenerate_replaces_existing_draft(db_session):
    pin_id, _, _ = await _seed(db_session, accepted_match=True)
    # Insert a stale draft first
    stale = ListingDraft(pin_id=pin_id, title="OLD TITLE", description="old", export_status=ExportStatus.DRAFT)
    db_session.add(stale)
    await db_session.commit()

    draft = await regenerate_draft_for_pin(db_session, pin_id)
    assert draft.title != "OLD TITLE"
    assert "Mickey" in draft.title


@pytest.mark.asyncio
async def test_regenerate_ignores_rejected_match_in_fallback(db_session):
    pin_id, entry_a_id, entry_b_id = await _seed(db_session, accepted_match=False)
    # Reject the top match (entry A, rank 1)
    from sqlalchemy import update
    await db_session.execute(
        update(CatalogMatch)
        .where(CatalogMatch.catalog_entry_id == entry_a_id)
        .values(status=MatchStatus.REJECTED)
    )
    await db_session.commit()
    draft = await regenerate_draft_for_pin(db_session, pin_id)
    await db_session.commit()
    # Should now use entry B (Mickey Halloween, 2010), not the rejected entry A (2005)
    assert "2010" in draft.title or "Halloween" in draft.title or "2010" in str(draft.item_specifics)
