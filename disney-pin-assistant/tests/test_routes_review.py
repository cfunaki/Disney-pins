import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.main import app
from src.database import get_db
from src.models import (
    Base, Pin, PinStatus, VisionExtraction, CatalogEntry,
    CatalogMatch, MatchStatus, ListingDraft, ExportStatus,
)
from src.routes.pins import router as pins_router


@pytest_asyncio.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.include_router(pins_router)
    app.dependency_overrides[get_db] = override_get_db

    async with session_factory() as session:
        pin = Pin(batch_id="b", status=PinStatus.MATCHED, image_paths=["x.jpg"])
        session.add(pin)
        await session.flush()

        extraction = VisionExtraction(
            pin_id=pin.id, characters=["Mickey Mouse"], franchise="Disney",
            pin_type="limited edition", edition_size=1500, visible_dates="2005",
            event_clues="50th Anniversary", confidence_score=0.9,
        )
        session.add(extraction)

        entry_a = CatalogEntry(canonical_name="Mickey 50th Anniversary", franchise="Disney",
                                release_year=2005, edition_size=1500, source="pintradingdb")
        entry_b = CatalogEntry(canonical_name="Mickey Halloween 2010", franchise="Disney",
                                release_year=2010, edition_size=500, source="pintradingdb")
        session.add_all([entry_a, entry_b])
        await session.flush()

        match_a = CatalogMatch(pin_id=pin.id, catalog_entry_id=entry_a.id,
                                match_confidence=0.95, rank=1, status=MatchStatus.SUGGESTED)
        match_b = CatalogMatch(pin_id=pin.id, catalog_entry_id=entry_b.id,
                                match_confidence=0.60, rank=2, status=MatchStatus.SUGGESTED)
        session.add_all([match_a, match_b])

        draft = ListingDraft(pin_id=pin.id, title="OLD TITLE", export_status=ExportStatus.DRAFT)
        session.add(draft)

        await session.commit()
        # Stash ids on the app for tests to use
        app.state.test_pin_id = pin.id
        app.state.test_entry_a_id = entry_a.id
        app.state.test_entry_b_id = entry_b.id

    yield app

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_select_match_marks_chosen_accepted_and_others_rejected(test_app):
    pin_id = test_app.state.test_pin_id
    entry_b_id = test_app.state.test_entry_b_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/pins/{pin_id}/match/select",
            json={"catalog_entry_id": entry_b_id},
        )
    assert response.status_code == 200
    data = response.json()
    matches = {m["catalog_entry_id"]: m["status"] for m in data["catalog_matches"]}
    assert matches[entry_b_id] == "accepted"
    # The other match should be rejected
    other_id = test_app.state.test_entry_a_id
    assert matches[other_id] == "rejected"


@pytest.mark.asyncio
async def test_select_match_regenerates_listing_draft(test_app):
    pin_id = test_app.state.test_pin_id
    entry_b_id = test_app.state.test_entry_b_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/pins/{pin_id}/match/select",
            json={"catalog_entry_id": entry_b_id},
        )
    data = response.json()
    # Old title was "OLD TITLE"; the regenerated title should be different
    assert data["listing_draft"]["title"] != "OLD TITLE"
    assert "Mickey" in data["listing_draft"]["title"]


@pytest.mark.asyncio
async def test_select_match_404_when_catalog_entry_unknown(test_app):
    pin_id = test_app.state.test_pin_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/pins/{pin_id}/match/select",
            json={"catalog_entry_id": 99999},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_select_match_404_when_pin_not_found(test_app):
    entry_a_id = test_app.state.test_entry_a_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/pins/99999/match/select",
            json={"catalog_entry_id": entry_a_id},
        )
    assert response.status_code == 404
    assert "Pin not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_select_match_inserts_new_candidate_when_not_already_present(test_app):
    pin_id = test_app.state.test_pin_id
    # Seed a third catalog entry that is NOT currently linked to the pin via CatalogMatch
    from src.database import get_db
    override = test_app.dependency_overrides[get_db]
    agen = override()
    session = await agen.__anext__()
    try:
        entry_c = CatalogEntry(
            canonical_name="Manually Picked Pin",
            franchise="Disney",
            release_year=2020,
            edition_size=250,
            source="pintradingdb",
        )
        session.add(entry_c)
        await session.commit()
        entry_c_id = entry_c.id
    finally:
        try:
            await agen.__anext__()
        except StopAsyncIteration:
            pass

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/pins/{pin_id}/match/select",
            json={"catalog_entry_id": entry_c_id},
        )
    assert response.status_code == 200
    data = response.json()
    # The new entry should be present as a candidate and marked accepted
    matches_by_entry = {m["catalog_entry_id"]: m for m in data["catalog_matches"]}
    assert entry_c_id in matches_by_entry
    assert matches_by_entry[entry_c_id]["status"] == "accepted"
    # All other previously-suggested candidates should now be rejected
    for entry_id, match in matches_by_entry.items():
        if entry_id != entry_c_id:
            assert match["status"] == "rejected"


@pytest.mark.asyncio
async def test_match_none_sets_no_catalog_match_and_rejects_all(test_app):
    pin_id = test_app.state.test_pin_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/pins/{pin_id}/match/none")
    assert response.status_code == 200
    data = response.json()
    assert data["no_catalog_match"] is True
    assert all(m["status"] == "rejected" for m in data["catalog_matches"])


@pytest.mark.asyncio
async def test_match_none_regenerates_draft_from_extraction(test_app):
    pin_id = test_app.state.test_pin_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/pins/{pin_id}/match/none")
    data = response.json()
    assert data["listing_draft"]["title"] != "OLD TITLE"
    # Title should still mention Mickey because the extraction still has it
    assert "Mickey" in data["listing_draft"]["title"]


@pytest.mark.asyncio
async def test_mark_no_match_404_when_pin_not_found(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/pins/99999/match/none")
    assert response.status_code == 404
    assert "Pin not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_patch_extraction_updates_fields_and_returns_pin(test_app):
    pin_id = test_app.state.test_pin_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/pins/{pin_id}/extraction",
            json={"characters": ["Donald Duck"], "edition_size": 999},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["extraction"]["characters"] == ["Donald Duck"]
    assert data["extraction"]["edition_size"] == 999
    # Other fields stay
    assert data["extraction"]["franchise"] == "Disney"


@pytest.mark.asyncio
async def test_patch_extraction_does_not_regenerate_draft(test_app):
    pin_id = test_app.state.test_pin_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/pins/{pin_id}/extraction",
            json={"characters": ["Donald Duck"]},
        )
    data = response.json()
    # Draft should still be the old one — re-match is explicit
    assert data["listing_draft"]["title"] == "OLD TITLE"


@pytest.mark.asyncio
async def test_patch_extraction_404_when_pin_not_found(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/pins/99999/extraction",
            json={"characters": ["Donald Duck"]},
        )
    assert response.status_code == 404
    assert "Pin not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_patch_extraction_404_when_extraction_missing(test_app):
    from src.database import get_db
    override = test_app.dependency_overrides[get_db]
    agen = override()
    session = await agen.__anext__()
    try:
        bare_pin = Pin(batch_id="b", status=PinStatus.UNPROCESSED, image_paths=[])
        session.add(bare_pin)
        await session.commit()
        bare_pin_id = bare_pin.id
    finally:
        try:
            await agen.__anext__()
        except StopAsyncIteration:
            pass

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/pins/{bare_pin_id}/extraction",
            json={"characters": ["x"]},
        )
    assert response.status_code == 404
    assert "Extraction not found for pin" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rematch_replaces_existing_candidates(test_app, monkeypatch):
    """Re-match should delete old CatalogMatch rows and insert fresh ones."""
    pin_id = test_app.state.test_pin_id

    async def fake_find(db, extraction, query_embedding=None, max_results=5):
        return [
            {
                "catalog_entry_id": test_app.state.test_entry_b_id,
                "canonical_name": "Mickey Halloween 2010",
                "confidence": 0.77,
                "visual_similarity": 0.77,
                "reasoning": "stubbed",
            }
        ]
    monkeypatch.setattr("src.routes.pins.find_catalog_matches_hybrid", fake_find)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/pins/{pin_id}/rematch")
    assert response.status_code == 200
    data = response.json()
    assert len(data["catalog_matches"]) == 1
    assert data["catalog_matches"][0]["canonical_name"] == "Mickey Halloween 2010"


@pytest.mark.asyncio
async def test_rematch_does_not_regenerate_draft(test_app, monkeypatch):
    pin_id = test_app.state.test_pin_id

    async def fake_find(db, extraction, query_embedding=None, max_results=5):
        return []
    monkeypatch.setattr("src.routes.pins.find_catalog_matches_hybrid", fake_find)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/pins/{pin_id}/rematch")
    data = response.json()
    assert data["listing_draft"]["title"] == "OLD TITLE"


@pytest.mark.asyncio
async def test_rematch_404_when_pin_not_found(test_app, monkeypatch):
    async def fake_find(db, extraction, query_embedding=None, max_results=5):
        return []
    monkeypatch.setattr("src.routes.pins.find_catalog_matches_hybrid", fake_find)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/pins/99999/rematch")
    assert response.status_code == 404
    assert "Pin not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rematch_404_when_extraction_missing(test_app, monkeypatch):
    async def fake_find(db, extraction, query_embedding=None, max_results=5):
        return []
    monkeypatch.setattr("src.routes.pins.find_catalog_matches_hybrid", fake_find)

    # Create a bare pin without an extraction, using the session-access pattern
    # already established in test_patch_extraction_404_when_extraction_missing
    from src.database import get_db
    override = test_app.dependency_overrides[get_db]
    agen = override()
    session = await agen.__anext__()
    try:
        bare_pin = Pin(batch_id="b", status=PinStatus.UNPROCESSED, image_paths=[])
        session.add(bare_pin)
        await session.commit()
        bare_pin_id = bare_pin.id
    finally:
        try:
            await agen.__anext__()
        except StopAsyncIteration:
            pass

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/pins/{bare_pin_id}/rematch")
    assert response.status_code == 404
    assert "Extraction not found for pin" in response.json()["detail"]


@pytest.mark.asyncio
async def test_regenerate_draft_endpoint_rebuilds_draft(test_app):
    pin_id = test_app.state.test_pin_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Capture upstream state before regenerating the draft
        pre_response = await client.get(f"/api/pins/{pin_id}")
        assert pre_response.status_code == 200
        pre_data = pre_response.json()
        pre_no_catalog_match = pre_data["no_catalog_match"]
        pre_catalog_matches = [
            {"catalog_entry_id": m["catalog_entry_id"], "status": m["status"]}
            for m in pre_data["catalog_matches"]
        ]

        response = await client.post(f"/api/pins/{pin_id}/draft/regenerate")

    assert response.status_code == 200
    data = response.json()

    # Draft title should be rebuilt
    assert data["listing_draft"]["title"] != "OLD TITLE"
    assert "Mickey" in data["listing_draft"]["title"]

    # Upstream match state must be unchanged
    assert data["no_catalog_match"] == pre_no_catalog_match
    assert len(data["catalog_matches"]) == len(pre_catalog_matches)
    post_matches = {m["catalog_entry_id"]: m["status"] for m in data["catalog_matches"]}
    for pre_match in pre_catalog_matches:
        assert post_matches[pre_match["catalog_entry_id"]] == pre_match["status"]


@pytest.mark.asyncio
async def test_regenerate_draft_404_when_pin_not_found(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/pins/99999/draft/regenerate")
    assert response.status_code == 404
    assert "Pin not found" in response.json()["detail"]
