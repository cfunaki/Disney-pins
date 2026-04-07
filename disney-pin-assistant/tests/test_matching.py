import pytest
import pytest_asyncio
from sqlalchemy import select
from src.models import Base, CatalogEntry, CatalogMatch
from src.pipeline.matching import find_catalog_matches

@pytest_asyncio.fixture
async def seeded_db(db_session):
    entries = [
        CatalogEntry(
            canonical_name="Mickey Mouse Epcot Food & Wine 2019 LE 3000",
            characters=["Mickey Mouse"], franchise="Mickey & Friends",
            event="Epcot Food & Wine Festival", edition_size=3000,
            release_year=2019, pin_type="limited edition",
            source="pinpics", evidence_strength="high",
        ),
        CatalogEntry(
            canonical_name="Mickey Mouse Classic Pose Pin",
            characters=["Mickey Mouse"], franchise="Mickey & Friends",
            pin_type="rack", source="pinpics", evidence_strength="medium",
        ),
        CatalogEntry(
            canonical_name="Stitch Surfing Pin",
            characters=["Stitch"], franchise="Lilo & Stitch",
            pin_type="enamel", source="pinpics", evidence_strength="medium",
        ),
    ]
    db_session.add_all(entries)
    await db_session.commit()
    return db_session

@pytest.mark.asyncio
async def test_find_matches_exact(seeded_db):
    extraction = {
        "characters": ["Mickey Mouse"], "franchise": "Mickey & Friends",
        "event_clues": "Food & Wine Festival", "edition_size": 3000,
        "pin_type": "limited edition", "text_on_pin": None,
        "collection_or_series": None, "visible_dates": "2019",
        "suggested_search_terms": [],
    }
    matches = await find_catalog_matches(seeded_db, extraction, max_results=3)
    assert len(matches) >= 1
    assert matches[0]["canonical_name"] == "Mickey Mouse Epcot Food & Wine 2019 LE 3000"
    assert matches[0]["confidence"] > 0.7

@pytest.mark.asyncio
async def test_find_matches_partial(seeded_db):
    extraction = {
        "characters": ["Mickey Mouse"], "franchise": "Mickey & Friends",
        "event_clues": None, "edition_size": None, "pin_type": "rack",
        "text_on_pin": None, "collection_or_series": None,
        "visible_dates": None, "suggested_search_terms": [],
    }
    matches = await find_catalog_matches(seeded_db, extraction, max_results=3)
    assert len(matches) >= 1
    rack_match = next(m for m in matches if "Classic Pose" in m["canonical_name"])
    le_match = next(m for m in matches if "Food & Wine" in m["canonical_name"])
    assert rack_match["confidence"] >= le_match["confidence"]

@pytest.mark.asyncio
async def test_find_matches_no_results(seeded_db):
    extraction = {
        "characters": ["Elsa"], "franchise": "Frozen",
        "event_clues": None, "edition_size": None, "pin_type": "enamel",
        "text_on_pin": None, "collection_or_series": None,
        "visible_dates": None, "suggested_search_terms": [],
    }
    matches = await find_catalog_matches(seeded_db, extraction, max_results=3)
    assert len(matches) == 0
