# Human Review UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current minimal queue + detail pages with a two-pane review workspace where the user can browse a batch, compare their photo against catalog candidates, accept/reject matches, edit vision extraction, and approve listings — all without leaving one screen.

**Architecture:** Single new template `review.html` with vanilla JS (`review.js`) holding in-memory state and re-rendering scoped DOM containers on mutation. Six new FastAPI endpoints handle match selection, no-match marking, extraction patching, re-matching, and draft regeneration. One small DB column (`Pin.no_catalog_match`) added. Listing-draft regeneration is extracted from the orchestrator into a reusable helper so the new endpoints can call it.

**Tech Stack:** FastAPI, SQLAlchemy (async), SQLite, Jinja2, vanilla JS, pytest + httpx + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-10-human-review-ui-design.md`

**Working directory for all paths:** `disney-pin-assistant/` (the project subdirectory). All file paths below are relative to that directory unless they start with `docs/`.

---

## File Structure

**New files:**
- `src/templates/review.html` — single template for the two-pane workspace
- `static/review.js` — workspace state + rendering
- `src/pipeline/draft_regeneration.py` — `regenerate_draft_for_pin(db, pin_id)` helper, extracted from orchestrator
- `tests/test_routes_review.py` — tests for the new endpoints
- `tests/test_draft_regeneration.py` — tests for the helper
- `tests/test_review_integration.py` — end-to-end "user accepts a different match" test
- `docs/superpowers/plans/2026-04-10-human-review-ui-smoke-checklist.md` — manual smoke test checklist

**Deleted files:**
- `src/templates/queue.html`
- `src/templates/detail.html`

**Modified files:**
- `src/models.py` — add `Pin.no_catalog_match` column
- `src/routes/pages.py` — point `/queue/{batch_id}` at `review.html`, remove `/pins/{pin_id}` page route
- `src/routes/pins.py` — extend `_pin_to_dict`, add 5 new endpoints
- `src/routes/catalog.py` — extend `/search` with `offset` + extra fields
- `src/database.py` — add migration for new column on startup (if not already present)
- `static/style.css` — new styles for two-pane layout, candidate strip, risk badges
- `static/app.js` — leave alone (upload page still uses it)

---

## Task 1: Add `Pin.no_catalog_match` column

**Files:**
- Modify: `src/models.py`
- Modify: `src/database.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Read current `Pin` model and `database.py` startup**

Run: `grep -n "class Pin" src/models.py`
Run: `cat src/database.py`

Note where `Pin` is defined and how the engine creates tables. SQLite is created via `Base.metadata.create_all` so adding a column to a fresh DB requires no migration, but the existing dev DB (`pins.db`) needs an `ALTER TABLE`.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_models.py`:

```python
import pytest
from src.models import Pin, PinStatus


def test_pin_no_catalog_match_defaults_false():
    pin = Pin(batch_id="b", status=PinStatus.UNPROCESSED, image_paths=[])
    assert pin.no_catalog_match is False


def test_pin_no_catalog_match_can_be_set_true():
    pin = Pin(batch_id="b", status=PinStatus.UNPROCESSED, image_paths=[], no_catalog_match=True)
    assert pin.no_catalog_match is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_pin_no_catalog_match_defaults_false -v`
Expected: FAIL with `AttributeError` or `TypeError` about `no_catalog_match`.

- [ ] **Step 4: Add the column to the model**

Edit `src/models.py`. In the `Pin` class, after the `image_paths` line:

```python
no_catalog_match = Column(Boolean, default=False, nullable=False)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_models.py::test_pin_no_catalog_match_defaults_false tests/test_models.py::test_pin_no_catalog_match_can_be_set_true -v`
Expected: PASS

- [ ] **Step 6: Add startup migration to `database.py`**

In `src/database.py`, find the engine startup function (or add one if it doesn't exist). Add an idempotent ALTER TABLE that adds the column to the existing dev DB. Use this exact pattern with a try/except that catches `OperationalError` (the column already exists case):

```python
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

async def ensure_review_ui_columns(engine):
    """Idempotent migration for the human review UI feature."""
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE pins ADD COLUMN no_catalog_match BOOLEAN DEFAULT 0 NOT NULL"))
        except OperationalError:
            pass  # column already exists
```

Then call `ensure_review_ui_columns(engine)` from wherever `Base.metadata.create_all` is called on app startup.

- [ ] **Step 7: Verify migration runs cleanly on the existing dev DB**

Run: `python -c "import asyncio; from src.database import engine, ensure_review_ui_columns; asyncio.run(ensure_review_ui_columns(engine))"`
Expected: Exits cleanly with no error. Run it twice in a row to confirm idempotency.

- [ ] **Step 8: Commit**

```bash
git add src/models.py src/database.py tests/test_models.py
git commit -m "feat(models): add Pin.no_catalog_match column for review UI"
```

---

## Task 2: Risk badge classification helper

**Files:**
- Create: `src/pipeline/risk_badges.py`
- Test: `tests/test_risk_badges.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_risk_badges.py`:

```python
from src.pipeline.risk_badges import classify_pin_risk


def _pin(**kwargs):
    return {
        "status": "matched",
        "no_catalog_match": False,
        "extraction": {"confidence_score": 0.9},
        "catalog_matches": [
            {"match_confidence": 0.92, "rank": 1},
            {"match_confidence": 0.55, "rank": 2},
        ],
        **kwargs,
    }


def test_ready_when_high_confidence_and_clear_winner():
    assert classify_pin_risk(_pin()) == "ready"


def test_no_match_when_no_candidates():
    assert classify_pin_risk(_pin(catalog_matches=[])) == "no_match"


def test_no_match_when_user_marked_no_catalog_match():
    assert classify_pin_risk(_pin(no_catalog_match=True)) == "no_match"


def test_ambiguous_when_top_score_below_0_9():
    assert classify_pin_risk(_pin(catalog_matches=[
        {"match_confidence": 0.85, "rank": 1},
        {"match_confidence": 0.40, "rank": 2},
    ])) == "ambiguous_match"


def test_ambiguous_when_top_two_within_0_1():
    assert classify_pin_risk(_pin(catalog_matches=[
        {"match_confidence": 0.95, "rank": 1},
        {"match_confidence": 0.88, "rank": 2},
    ])) == "ambiguous_match"


def test_low_extraction_when_extraction_confidence_below_0_6():
    assert classify_pin_risk(_pin(extraction={"confidence_score": 0.4})) == "low_extraction"


def test_severity_no_match_beats_ambiguous():
    assert classify_pin_risk(_pin(catalog_matches=[], extraction={"confidence_score": 0.4})) == "no_match"


def test_severity_ambiguous_beats_low_extraction():
    pin = _pin(
        extraction={"confidence_score": 0.4},
        catalog_matches=[
            {"match_confidence": 0.85, "rank": 1},
            {"match_confidence": 0.40, "rank": 2},
        ],
    )
    assert classify_pin_risk(pin) == "ambiguous_match"


def test_approved_status_overrides_other_signals():
    assert classify_pin_risk(_pin(status="approved")) == "approved"


def test_exported_status_overrides_other_signals():
    assert classify_pin_risk(_pin(status="exported")) == "exported"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_risk_badges.py -v`
Expected: FAIL — `ModuleNotFoundError: src.pipeline.risk_badges`

- [ ] **Step 3: Implement the helper**

Create `src/pipeline/risk_badges.py`:

```python
"""Classify a pin into a single user-facing risk badge."""

AMBIGUOUS_TOP_SCORE_THRESHOLD = 0.9
AMBIGUOUS_GAP_THRESHOLD = 0.1
LOW_EXTRACTION_THRESHOLD = 0.6


def classify_pin_risk(pin: dict) -> str:
    """Return one of: ready, ambiguous_match, low_extraction, no_match, approved, exported.

    `pin` is the dict produced by `_pin_to_dict` in src/routes/pins.py.
    Severity order (highest first): exported, approved, no_match, ambiguous_match, low_extraction, ready.
    """
    status = pin.get("status")
    if status == "exported":
        return "exported"
    if status == "approved":
        return "approved"

    if pin.get("no_catalog_match"):
        return "no_match"

    matches = pin.get("catalog_matches") or []
    if not matches:
        return "no_match"

    sorted_matches = sorted(matches, key=lambda m: m.get("match_confidence", 0), reverse=True)
    top = sorted_matches[0].get("match_confidence", 0)
    second = sorted_matches[1].get("match_confidence", 0) if len(sorted_matches) > 1 else 0

    if top < AMBIGUOUS_TOP_SCORE_THRESHOLD or (top - second) < AMBIGUOUS_GAP_THRESHOLD:
        return "ambiguous_match"

    extraction = pin.get("extraction") or {}
    if extraction.get("confidence_score", 1.0) < LOW_EXTRACTION_THRESHOLD:
        return "low_extraction"

    return "ready"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_risk_badges.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/risk_badges.py tests/test_risk_badges.py
git commit -m "feat(pipeline): add risk badge classification helper"
```

---

## Task 3: Listing draft regeneration helper

**Files:**
- Create: `src/pipeline/draft_regeneration.py`
- Test: `tests/test_draft_regeneration.py`

This extracts the draft-creation logic from `src/pipeline/orchestrator.py:95-111` into a function that can be called from the new endpoints. The helper takes a pin id and rebuilds the `ListingDraft` from the pin's current accepted match (or top match) and current extraction.

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft_regeneration.py`:

```python
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
    assert draft is not None
    assert "Mickey" in draft.title
    assert "2005" in draft.title
    assert draft.export_status == ExportStatus.DRAFT


@pytest.mark.asyncio
async def test_regenerate_falls_back_to_top_match_when_none_accepted(db_session):
    pin_id, entry_a_id, _ = await _seed(db_session, accepted_match=False)
    draft = await regenerate_draft_for_pin(db_session, pin_id)
    # Top match (rank 1) should be entry A — release year 2005
    assert "2005" in draft.title


@pytest.mark.asyncio
async def test_regenerate_uses_extraction_only_when_no_catalog_match(db_session):
    pin_id, _, _ = await _seed(db_session, no_catalog_match=True)
    draft = await regenerate_draft_for_pin(db_session, pin_id)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_draft_regeneration.py -v`
Expected: FAIL — `ModuleNotFoundError: src.pipeline.draft_regeneration`

- [ ] **Step 3: Implement the helper**

Create `src/pipeline/draft_regeneration.py`:

```python
"""Regenerate a pin's listing draft from its current accepted match (or top match)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Pin, VisionExtraction, CatalogMatch, CatalogEntry,
    MatchStatus, ListingDraft, ExportStatus,
)
from src.pipeline.listing import generate_listing_draft


def _extraction_to_dict(extraction: VisionExtraction) -> dict:
    return {
        "characters": extraction.characters or [],
        "franchise": extraction.franchise,
        "collection_or_series": extraction.collection_or_series,
        "text_on_pin": extraction.text_on_pin,
        "visible_dates": extraction.visible_dates,
        "event_clues": extraction.event_clues,
        "pin_type": extraction.pin_type,
        "edition_size": extraction.edition_size,
        "condition_observations": extraction.condition_observations,
        "suggested_search_terms": extraction.suggested_search_terms or [],
        "confidence_score": extraction.confidence_score,
    }


def _catalog_entry_to_match_dict(entry: CatalogEntry) -> dict:
    return {
        "catalog_entry_id": entry.id,
        "canonical_name": entry.canonical_name,
        "characters": entry.characters,
        "franchise": entry.franchise,
        "event": entry.event,
        "edition_size": entry.edition_size,
        "release_year": entry.release_year,
        "pin_type": entry.pin_type,
    }


async def _resolve_match_entry(db: AsyncSession, pin_id: int, no_catalog_match: bool) -> CatalogEntry | None:
    """Return the catalog entry to use for draft generation, or None if there is none."""
    if no_catalog_match:
        return None

    result = await db.execute(
        select(CatalogMatch)
        .where(CatalogMatch.pin_id == pin_id)
        .where(CatalogMatch.status == MatchStatus.ACCEPTED)
        .limit(1)
    )
    accepted = result.scalar_one_or_none()
    if accepted:
        return await db.get(CatalogEntry, accepted.catalog_entry_id)

    # Fall back to top-ranked suggested match
    result = await db.execute(
        select(CatalogMatch)
        .where(CatalogMatch.pin_id == pin_id)
        .order_by(CatalogMatch.rank.asc())
        .limit(1)
    )
    top = result.scalar_one_or_none()
    if top:
        return await db.get(CatalogEntry, top.catalog_entry_id)

    return None


async def regenerate_draft_for_pin(db: AsyncSession, pin_id: int) -> ListingDraft | None:
    """Rebuild the listing draft for a pin in place. Returns the (new or updated) ListingDraft."""
    pin = await db.get(Pin, pin_id)
    if not pin:
        return None

    extraction_result = await db.execute(
        select(VisionExtraction).where(VisionExtraction.pin_id == pin_id)
    )
    extraction = extraction_result.scalar_one_or_none()
    if not extraction:
        return None

    extraction_dict = _extraction_to_dict(extraction)
    entry = await _resolve_match_entry(db, pin_id, pin.no_catalog_match)
    catalog_match_dict = _catalog_entry_to_match_dict(entry) if entry else None

    draft_data = generate_listing_draft(extraction_dict, catalog_match_dict, pricing=None)

    existing_result = await db.execute(
        select(ListingDraft).where(ListingDraft.pin_id == pin_id)
    )
    draft = existing_result.scalar_one_or_none()

    if draft is None:
        draft = ListingDraft(pin_id=pin_id, export_status=ExportStatus.DRAFT)
        db.add(draft)

    draft.title = draft_data["title"]
    draft.description = draft_data["description"]
    draft.item_specifics = draft_data["item_specifics"]
    draft.suggested_price = draft_data["suggested_price"]
    draft.quick_sale_price = draft_data["quick_sale_price"]
    draft.price_confidence = draft_data["price_confidence"]
    draft.pricing_reasoning = draft_data.get("pricing_reasoning")
    draft.tags_keywords = draft_data["tags_keywords"]
    # Preserve export_status if already approved/exported — only reset DRAFT
    if draft.export_status == ExportStatus.DRAFT:
        draft.export_status = ExportStatus.DRAFT

    await db.commit()
    return draft
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_draft_regeneration.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/draft_regeneration.py tests/test_draft_regeneration.py
git commit -m "feat(pipeline): add reusable draft regeneration helper"
```

---

## Task 4: Extend `_pin_to_dict` with catalog candidate details

**Files:**
- Modify: `src/routes/pins.py`
- Test: `tests/test_routes_pins.py`

The detail pane needs each catalog match to include `canonical_name`, `image_path`, `release_year`, `edition_size`, and `source` so the right pane can render candidate cards without per-candidate API calls. The queue list also needs the risk badge per pin (from Task 2).

- [ ] **Step 1: Add a failing test**

Append to `tests/test_routes_pins.py`. First, extend the `test_app` fixture to seed catalog matches with full catalog entries. Replace the existing fixture body with:

```python
@pytest_asyncio.fixture
async def test_app():
    from src.models import CatalogEntry, CatalogMatch, MatchStatus

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
        pin = Pin(batch_id="test-batch", status=PinStatus.PRICED, photo_type="front", image_paths=["img/pin1.jpg"])
        session.add(pin)
        await session.flush()

        extraction = VisionExtraction(pin_id=pin.id, characters=["Mickey Mouse"], franchise="Disney",
                                       pin_type="limited_edition", confidence_score=0.95,
                                       suggested_search_terms=["mickey", "disney pin"])
        session.add(extraction)

        entry = CatalogEntry(canonical_name="Mickey 50th Anniversary", franchise="Disney",
                              release_year=2005, edition_size=1500, image_path="catalog/mickey.jpg",
                              source="pintradingdb")
        session.add(entry)
        await session.flush()

        cm = CatalogMatch(pin_id=pin.id, catalog_entry_id=entry.id, match_confidence=0.92,
                          match_reasoning="character + franchise match", rank=1, status=MatchStatus.SUGGESTED)
        session.add(cm)

        draft = ListingDraft(pin_id=pin.id, title="Mickey Mouse LE Pin", description="A limited edition Mickey Mouse pin.",
                              suggested_price=25.00, quick_sale_price=20.00, price_confidence="high",
                              tags_keywords=["mickey", "disney", "limited edition"], export_status=ExportStatus.DRAFT)
        session.add(draft)
        await session.commit()

    yield app

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

Then add this new test:

```python
@pytest.mark.asyncio
async def test_pin_dict_includes_full_catalog_match_details(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/pins/1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["catalog_matches"]) == 1
    match = data["catalog_matches"][0]
    assert match["canonical_name"] == "Mickey 50th Anniversary"
    assert match["image_path"] == "catalog/mickey.jpg"
    assert match["release_year"] == 2005
    assert match["edition_size"] == 1500
    assert match["source"] == "pintradingdb"


@pytest.mark.asyncio
async def test_pin_dict_includes_no_catalog_match_flag(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/pins/1")
    data = response.json()
    assert "no_catalog_match" in data
    assert data["no_catalog_match"] is False


@pytest.mark.asyncio
async def test_batch_pins_include_risk_badge(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/batch/test-batch/pins")
    data = response.json()
    assert len(data) == 1
    assert "risk_badge" in data[0]
    assert data[0]["risk_badge"] in {"ready", "ambiguous_match", "low_extraction", "no_match", "approved", "exported"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_pins.py::test_pin_dict_includes_full_catalog_match_details tests/test_routes_pins.py::test_pin_dict_includes_no_catalog_match_flag tests/test_routes_pins.py::test_batch_pins_include_risk_badge -v`
Expected: FAIL — missing `canonical_name`, `image_path`, `no_catalog_match`, `risk_badge` keys.

- [ ] **Step 3: Update `_pin_to_dict` and the list endpoint**

In `src/routes/pins.py`, update the imports at the top:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from src.database import get_db
from src.models import Pin, PinStatus, ListingDraft, ExportStatus, CatalogMatch, CatalogEntry, MatchStatus
from src.schemas import PinUpdateRequest
from src.pipeline.risk_badges import classify_pin_risk
```

Update `list_batch_pins` to also `selectinload` the catalog entries via the matches:

```python
@router.get("/batch/{batch_id}/pins")
async def list_batch_pins(batch_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Pin).options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches).selectinload(CatalogMatch.catalog_entry),
            selectinload(Pin.comps),
        ).where(Pin.batch_id == batch_id)
    )
    pins = result.scalars().all()
    dicts = [_pin_to_dict(pin) for pin in pins]
    for d in dicts:
        d["risk_badge"] = classify_pin_risk(d)
    return dicts
```

Same for `get_pin_detail`:

```python
@router.get("/pins/{pin_id}")
async def get_pin_detail(pin_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Pin).options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches).selectinload(CatalogMatch.catalog_entry),
            selectinload(Pin.comps),
        ).where(Pin.id == pin_id)
    )
    pin = result.scalar_one_or_none()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    data = _pin_to_dict(pin)
    data["risk_badge"] = classify_pin_risk(data)
    return data
```

Replace the `_pin_to_dict` function with this version (note the new `no_catalog_match` field on the pin and the enriched match dicts):

```python
def _pin_to_dict(pin: Pin) -> dict:
    data = {
        "id": pin.id,
        "batch_id": pin.batch_id,
        "status": pin.status.value,
        "photo_type": pin.photo_type,
        "seller_notes": pin.seller_notes,
        "image_paths": pin.image_paths,
        "no_catalog_match": pin.no_catalog_match,
        "extraction": None,
        "catalog_matches": [],
        "comps": [],
        "listing_draft": None,
    }
    if pin.extraction:
        data["extraction"] = {
            "characters": pin.extraction.characters,
            "franchise": pin.extraction.franchise,
            "pin_type": pin.extraction.pin_type,
            "confidence_score": pin.extraction.confidence_score,
            "suggested_search_terms": pin.extraction.suggested_search_terms,
            "text_on_pin": pin.extraction.text_on_pin,
            "visible_dates": pin.extraction.visible_dates,
            "event_clues": pin.extraction.event_clues,
            "edition_size": pin.extraction.edition_size,
            "condition_observations": pin.extraction.condition_observations,
            "collection_or_series": pin.extraction.collection_or_series,
        }
    for match in pin.catalog_matches:
        entry = match.catalog_entry
        data["catalog_matches"].append({
            "catalog_entry_id": match.catalog_entry_id,
            "match_confidence": match.match_confidence,
            "match_reasoning": match.match_reasoning,
            "rank": match.rank,
            "status": match.status.value,
            "canonical_name": entry.canonical_name if entry else None,
            "image_path": entry.image_path if entry else None,
            "release_year": entry.release_year if entry else None,
            "edition_size": entry.edition_size if entry else None,
            "source": entry.source if entry else None,
        })
    if pin.listing_draft:
        data["listing_draft"] = {
            "title": pin.listing_draft.title,
            "description": pin.listing_draft.description,
            "suggested_price": pin.listing_draft.suggested_price,
            "quick_sale_price": pin.listing_draft.quick_sale_price,
            "price_confidence": pin.listing_draft.price_confidence,
            "tags_keywords": pin.listing_draft.tags_keywords,
            "export_status": pin.listing_draft.export_status.value,
        }
    for comp in pin.comps:
        data["comps"].append({
            "title": comp.title,
            "price": comp.price,
            "listing_type": comp.listing_type.value,
            "excluded": comp.excluded,
        })
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routes_pins.py -v`
Expected: All tests in the file PASS (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/routes/pins.py tests/test_routes_pins.py
git commit -m "feat(api): include catalog match details and risk badge in pin responses"
```

---

## Task 5: `POST /api/pins/{id}/match/select` endpoint

**Files:**
- Modify: `src/routes/pins.py`
- Modify: `src/schemas.py`
- Test: `tests/test_routes_review.py`

- [ ] **Step 1: Create the test file with a failing test**

Create `tests/test_routes_review.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_review.py -v`
Expected: FAIL — endpoint does not exist (404 from FastAPI route resolution).

- [ ] **Step 3: Add the request schema**

Append to `src/schemas.py`:

```python
class MatchSelectRequest(BaseModel):
    catalog_entry_id: int


class ExtractionPatchRequest(BaseModel):
    characters: list[str] | None = None
    franchise: str | None = None
    pin_type: str | None = None
    edition_size: int | None = None
    visible_dates: str | None = None
    event_clues: str | None = None
```

- [ ] **Step 4: Add the endpoint**

In `src/routes/pins.py`, add the import:

```python
from src.schemas import PinUpdateRequest, MatchSelectRequest, ExtractionPatchRequest
from src.pipeline.draft_regeneration import regenerate_draft_for_pin
```

Then add this endpoint after `update_pin`:

```python
@router.post("/pins/{pin_id}/match/select")
async def select_match(pin_id: int, body: MatchSelectRequest, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    # Verify the catalog entry exists
    entry = await db.get(CatalogEntry, body.catalog_entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Catalog entry not found")

    # Find all matches for this pin
    result = await db.execute(select(CatalogMatch).where(CatalogMatch.pin_id == pin_id))
    matches = result.scalars().all()

    # Verify the chosen match is one of this pin's candidates
    chosen = next((m for m in matches if m.catalog_entry_id == body.catalog_entry_id), None)
    if not chosen:
        raise HTTPException(status_code=404, detail="Catalog entry is not a candidate for this pin")

    for m in matches:
        m.status = MatchStatus.ACCEPTED if m.id == chosen.id else MatchStatus.REJECTED

    pin.no_catalog_match = False
    await db.commit()

    # Regenerate draft from the new accepted match
    await regenerate_draft_for_pin(db, pin_id)

    # Re-fetch and return the full pin dict
    return await get_pin_detail(pin_id, db)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_routes_review.py::test_select_match_marks_chosen_accepted_and_others_rejected tests/test_routes_review.py::test_select_match_regenerates_listing_draft tests/test_routes_review.py::test_select_match_404_when_catalog_entry_unknown -v`
Expected: All 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/routes/pins.py src/schemas.py tests/test_routes_review.py
git commit -m "feat(api): add POST /api/pins/{id}/match/select"
```

---

## Task 6: `POST /api/pins/{id}/match/none` endpoint

**Files:**
- Modify: `src/routes/pins.py`
- Test: `tests/test_routes_review.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_routes_review.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_review.py::test_match_none_sets_no_catalog_match_and_rejects_all tests/test_routes_review.py::test_match_none_regenerates_draft_from_extraction -v`
Expected: FAIL — endpoint not found.

- [ ] **Step 3: Add the endpoint**

In `src/routes/pins.py`, add after the `select_match` endpoint:

```python
@router.post("/pins/{pin_id}/match/none")
async def mark_no_match(pin_id: int, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    result = await db.execute(select(CatalogMatch).where(CatalogMatch.pin_id == pin_id))
    matches = result.scalars().all()
    for m in matches:
        m.status = MatchStatus.REJECTED

    pin.no_catalog_match = True
    await db.commit()

    await regenerate_draft_for_pin(db, pin_id)
    return await get_pin_detail(pin_id, db)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routes_review.py::test_match_none_sets_no_catalog_match_and_rejects_all tests/test_routes_review.py::test_match_none_regenerates_draft_from_extraction -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/routes/pins.py tests/test_routes_review.py
git commit -m "feat(api): add POST /api/pins/{id}/match/none"
```

---

## Task 7: `POST /api/pins/{id}/extraction` endpoint

**Files:**
- Modify: `src/routes/pins.py`
- Test: `tests/test_routes_review.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_routes_review.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_review.py::test_patch_extraction_updates_fields_and_returns_pin tests/test_routes_review.py::test_patch_extraction_does_not_regenerate_draft -v`
Expected: FAIL — endpoint not found.

- [ ] **Step 3: Add the endpoint**

In `src/routes/pins.py`, add after `mark_no_match`:

```python
@router.post("/pins/{pin_id}/extraction")
async def patch_extraction(pin_id: int, body: ExtractionPatchRequest, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    from src.models import VisionExtraction
    result = await db.execute(select(VisionExtraction).where(VisionExtraction.pin_id == pin_id))
    extraction = result.scalar_one_or_none()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found for pin")

    if body.characters is not None:
        extraction.characters = body.characters
    if body.franchise is not None:
        extraction.franchise = body.franchise
    if body.pin_type is not None:
        extraction.pin_type = body.pin_type
    if body.edition_size is not None:
        extraction.edition_size = body.edition_size
    if body.visible_dates is not None:
        extraction.visible_dates = body.visible_dates
    if body.event_clues is not None:
        extraction.event_clues = body.event_clues

    await db.commit()
    return await get_pin_detail(pin_id, db)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routes_review.py::test_patch_extraction_updates_fields_and_returns_pin tests/test_routes_review.py::test_patch_extraction_does_not_regenerate_draft -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/routes/pins.py tests/test_routes_review.py
git commit -m "feat(api): add POST /api/pins/{id}/extraction"
```

---

## Task 8: `POST /api/pins/{id}/rematch` endpoint

**Files:**
- Modify: `src/routes/pins.py`
- Test: `tests/test_routes_review.py`

This endpoint reruns the matcher with the current extraction. It does **not** regenerate the draft — that happens when the user accepts a new candidate.

- [ ] **Step 1: Add failing test**

Append to `tests/test_routes_review.py`:

```python
@pytest.mark.asyncio
async def test_rematch_replaces_existing_candidates(test_app, monkeypatch):
    """Re-match should delete old CatalogMatch rows and insert fresh ones."""
    pin_id = test_app.state.test_pin_id

    # Stub the matcher to return a controlled list
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
    # Only the stubbed match should remain
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
    # Draft is still the old one — re-match alone doesn't trigger regen
    assert data["listing_draft"]["title"] == "OLD TITLE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_review.py::test_rematch_replaces_existing_candidates tests/test_routes_review.py::test_rematch_does_not_regenerate_draft -v`
Expected: FAIL — endpoint not found.

- [ ] **Step 3: Add the endpoint**

In `src/routes/pins.py`, add to the imports at the top:

```python
from src.pipeline.matching import find_catalog_matches_hybrid
from src.pipeline.image_matching import compute_clip_embedding
from src.pipeline.draft_regeneration import _extraction_to_dict
```

Then add the endpoint after `patch_extraction`:

```python
@router.post("/pins/{pin_id}/rematch")
async def rematch_pin(pin_id: int, db: AsyncSession = Depends(get_db)):
    from src.models import VisionExtraction

    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")

    extraction_result = await db.execute(
        select(VisionExtraction).where(VisionExtraction.pin_id == pin_id)
    )
    extraction = extraction_result.scalar_one_or_none()
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found for pin")

    extraction_dict = _extraction_to_dict(extraction)

    # Compute query embedding from the user's photo (best-effort)
    query_embedding = None
    try:
        if pin.image_paths:
            query_embedding = compute_clip_embedding(pin.image_paths[0])
    except Exception as exc:
        print(f"[rematch] CLIP embedding failed for pin {pin_id}: {exc}")

    new_matches = await find_catalog_matches_hybrid(
        db, extraction_dict,
        query_embedding=query_embedding,
        max_results=5,
    )

    # Delete existing CatalogMatch rows for this pin
    existing = await db.execute(select(CatalogMatch).where(CatalogMatch.pin_id == pin_id))
    for old in existing.scalars().all():
        await db.delete(old)

    # Insert new ones
    for rank, match in enumerate(new_matches, 1):
        cm = CatalogMatch(
            pin_id=pin_id,
            catalog_entry_id=match["catalog_entry_id"],
            match_confidence=match.get("visual_similarity", match["confidence"]),
            match_reasoning=match.get("reasoning"),
            rank=rank,
            status=MatchStatus.SUGGESTED,
        )
        db.add(cm)

    pin.no_catalog_match = False
    await db.commit()
    return await get_pin_detail(pin_id, db)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routes_review.py::test_rematch_replaces_existing_candidates tests/test_routes_review.py::test_rematch_does_not_regenerate_draft -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/routes/pins.py tests/test_routes_review.py
git commit -m "feat(api): add POST /api/pins/{id}/rematch"
```

---

## Task 9: `POST /api/pins/{id}/draft/regenerate` endpoint

**Files:**
- Modify: `src/routes/pins.py`
- Test: `tests/test_routes_review.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_routes_review.py`:

```python
@pytest.mark.asyncio
async def test_regenerate_draft_endpoint_rebuilds_draft(test_app):
    pin_id = test_app.state.test_pin_id
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/pins/{pin_id}/draft/regenerate")
    assert response.status_code == 200
    data = response.json()
    assert data["listing_draft"]["title"] != "OLD TITLE"
    assert "Mickey" in data["listing_draft"]["title"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_routes_review.py::test_regenerate_draft_endpoint_rebuilds_draft -v`
Expected: FAIL — endpoint not found.

- [ ] **Step 3: Add the endpoint**

In `src/routes/pins.py`, add after `rematch_pin`:

```python
@router.post("/pins/{pin_id}/draft/regenerate")
async def regenerate_draft(pin_id: int, db: AsyncSession = Depends(get_db)):
    pin = await db.get(Pin, pin_id)
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    await regenerate_draft_for_pin(db, pin_id)
    return await get_pin_detail(pin_id, db)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_routes_review.py::test_regenerate_draft_endpoint_rebuilds_draft -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/routes/pins.py tests/test_routes_review.py
git commit -m "feat(api): add POST /api/pins/{id}/draft/regenerate"
```

---

## Task 10: Extend catalog search with pagination + image fields

**Files:**
- Modify: `src/routes/catalog.py`
- Test: `tests/test_catalog_search.py`

- [ ] **Step 1: Create the failing test**

Create `tests/test_catalog_search.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.main import app
from src.database import get_db
from src.models import Base, CatalogEntry
from src.routes.catalog import router as catalog_router


@pytest_asyncio.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.include_router(catalog_router)
    app.dependency_overrides[get_db] = override_get_db

    async with factory() as session:
        for i in range(25):
            session.add(CatalogEntry(
                canonical_name=f"Mickey Pin {i:02d}",
                franchise="Disney",
                release_year=2000 + i,
                edition_size=1000 + i,
                image_path=f"catalog/mickey-{i:02d}.jpg",
                source="pintradingdb",
            ))
        await session.commit()

    yield app
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_returns_image_path_and_release_year(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/catalog/search?q=Mickey")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) > 0
    assert "image_path" in entries[0]
    assert "release_year" in entries[0]
    assert entries[0]["image_path"].startswith("catalog/")


@pytest.mark.asyncio
async def test_search_returns_at_most_20(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/catalog/search?q=Mickey")
    entries = response.json()
    assert len(entries) == 20


@pytest.mark.asyncio
async def test_search_offset_pagination(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page_one = (await client.get("/api/catalog/search?q=Mickey&offset=0")).json()
        page_two = (await client.get("/api/catalog/search?q=Mickey&offset=20")).json()
    assert len(page_one) == 20
    assert len(page_two) == 5
    page_one_ids = {e["id"] for e in page_one}
    page_two_ids = {e["id"] for e in page_two}
    assert page_one_ids.isdisjoint(page_two_ids)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_catalog_search.py -v`
Expected: FAIL — `image_path` not in response, no `offset` support.

- [ ] **Step 3: Update `search_catalog`**

In `src/routes/catalog.py`, replace the existing `search_catalog` function:

```python
@router.get("/search")
async def search_catalog(q: str, offset: int = 0, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CatalogEntry)
        .where(CatalogEntry.canonical_name.ilike(f"%{q}%"))
        .order_by(CatalogEntry.canonical_name.asc())
        .offset(offset)
        .limit(20)
    )
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "canonical_name": e.canonical_name,
            "characters": e.characters,
            "franchise": e.franchise,
            "event": e.event,
            "edition_size": e.edition_size,
            "pin_type": e.pin_type,
            "evidence_strength": e.evidence_strength,
            "image_path": e.image_path,
            "release_year": e.release_year,
            "source": e.source,
        }
        for e in entries
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_catalog_search.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/routes/catalog.py tests/test_catalog_search.py
git commit -m "feat(api): paginate catalog search and include image path"
```

---

## Task 11: New `review.html` template

**Files:**
- Create: `src/templates/review.html`
- Modify: `src/routes/pages.py`

This task creates an empty shell. The two panes are styled containers with mount points for `review.js` to render into. No JS in the template — all logic lives in `static/review.js`.

- [ ] **Step 1: Create the template**

Create `src/templates/review.html`:

```html
{% extends "base.html" %}
{% block content %}
<div id="review-app" data-batch-id="{{ batch_id }}">
  <header class="review-header">
    <div>
      <strong>Review Queue</strong>
      <span class="batch-id">Batch {{ batch_id }}</span>
      <span id="review-counts" class="review-counts"></span>
    </div>
  </header>

  <div class="review-workspace">
    <aside class="queue-pane">
      <div class="queue-controls">
        <input id="queue-filter" type="text" placeholder="Filter…">
        <select id="queue-sort">
          <option value="risk">Sort: Risk ↓</option>
          <option value="status">Sort: Status</option>
          <option value="price">Sort: Price ↓</option>
          <option value="order">Sort: Order added</option>
        </select>
      </div>
      <ul id="queue-list" class="queue-list"></ul>
    </aside>

    <section class="detail-pane">
      <div id="detail-empty" class="detail-empty">
        Select a pin from the queue.
      </div>
      <div id="detail-content" class="detail-content" hidden></div>
    </section>
  </div>
</div>
<script src="/static/review.js"></script>
{% endblock %}
```

- [ ] **Step 2: Update the queue page route**

In `src/routes/pages.py`, replace the `queue_page` function:

```python
@router.get("/queue/{batch_id}")
async def queue_page(request: Request, batch_id: str):
    return templates.TemplateResponse("review.html", {"request": request, "batch_id": batch_id})
```

Also delete the `detail_page` function (`/pins/{pin_id}` page route) entirely. The `_pin_to_dict` JSON endpoint stays — only the HTML page goes away.

- [ ] **Step 3: Manually verify the template loads**

Run: `uvicorn src.main:app --reload --port 8000` in one terminal, then in another:
`curl -s http://localhost:8000/queue/test | grep "Review Queue"`
Expected: One match, page renders the new template.

- [ ] **Step 4: Commit**

```bash
git add src/templates/review.html src/routes/pages.py
git commit -m "feat(ui): scaffold new review.html two-pane template"
```

---

## Task 12: `review.js` skeleton — state + queue list rendering

**Files:**
- Create: `static/review.js`

- [ ] **Step 1: Create the file with state, fetch, and queue rendering**

Create `static/review.js`:

```javascript
"use strict";

const state = {
  batchId: null,
  pins: [],
  selectedPinId: null,
  sortBy: "risk",
  filter: "",
};

const RISK_RANK = {
  no_match: 0,
  ambiguous_match: 1,
  low_extraction: 2,
  ready: 3,
  approved: 4,
  exported: 5,
};

const RISK_LABELS = {
  ready: { text: "✓ ready", cls: "badge-ready" },
  ambiguous_match: { text: "⚠ ambiguous match", cls: "badge-ambiguous" },
  low_extraction: { text: "⚠ low extraction", cls: "badge-low-extraction" },
  no_match: { text: "✗ no match", cls: "badge-no-match" },
  approved: { text: "✓ approved", cls: "badge-approved" },
  exported: { text: "→ exported", cls: "badge-exported" },
};

function init() {
  const root = document.getElementById("review-app");
  if (!root) return;
  state.batchId = root.dataset.batchId;
  document.getElementById("queue-filter").addEventListener("input", (e) => {
    state.filter = e.target.value.toLowerCase();
    renderQueueList();
  });
  document.getElementById("queue-sort").addEventListener("change", (e) => {
    state.sortBy = e.target.value;
    renderQueueList();
  });
  loadBatch();
}

async function loadBatch() {
  const response = await fetch(`/api/batch/${state.batchId}/pins`);
  state.pins = await response.json();
  renderCounts();
  renderQueueList();
}

function renderCounts() {
  const total = state.pins.length;
  const approved = state.pins.filter((p) => p.status === "approved" || p.status === "exported").length;
  document.getElementById("review-counts").textContent = `· ${total} pins · ${approved} approved`;
}

function pinTitle(pin) {
  if (pin.listing_draft && pin.listing_draft.title) return pin.listing_draft.title;
  const matches = pin.catalog_matches || [];
  if (matches.length > 0 && matches[0].canonical_name) return matches[0].canonical_name;
  return "(unknown)";
}

function pinThumbnail(pin) {
  if (pin.image_paths && pin.image_paths.length > 0) {
    return `/uploads/${pin.image_paths[0].replace(/^.*uploads\//, "")}`;
  }
  return "";
}

function sortedFilteredPins() {
  let pins = state.pins.slice();
  if (state.filter) {
    pins = pins.filter((p) => pinTitle(p).toLowerCase().includes(state.filter));
  }
  pins.sort((a, b) => {
    if (state.sortBy === "risk") {
      return (RISK_RANK[a.risk_badge] ?? 99) - (RISK_RANK[b.risk_badge] ?? 99);
    }
    if (state.sortBy === "price") {
      const pa = (a.listing_draft && a.listing_draft.suggested_price) || 0;
      const pb = (b.listing_draft && b.listing_draft.suggested_price) || 0;
      return pb - pa;
    }
    if (state.sortBy === "status") {
      return (a.status || "").localeCompare(b.status || "");
    }
    return a.id - b.id;
  });
  return pins;
}

function renderQueueList() {
  const list = document.getElementById("queue-list");
  list.innerHTML = "";
  for (const pin of sortedFilteredPins()) {
    const li = document.createElement("li");
    li.className = "queue-row" + (pin.id === state.selectedPinId ? " selected" : "");
    li.dataset.pinId = pin.id;
    const badge = RISK_LABELS[pin.risk_badge] || { text: pin.risk_badge || "—", cls: "" };
    const price = pin.listing_draft && pin.listing_draft.suggested_price
      ? `$${pin.listing_draft.suggested_price.toFixed(0)}` : "—";
    li.innerHTML = `
      <img class="queue-thumb" src="${pinThumbnail(pin)}" alt="" onerror="this.style.visibility='hidden'">
      <div class="queue-row-body">
        <div class="queue-title">${escapeHtml(pinTitle(pin))}</div>
        <div class="queue-meta">
          <span class="badge ${badge.cls}">${badge.text}</span>
          <span class="queue-price">${price}</span>
        </div>
      </div>`;
    li.addEventListener("click", () => selectPin(pin.id));
    list.appendChild(li);
  }
}

async function selectPin(pinId) {
  state.selectedPinId = pinId;
  renderQueueList();
  // Detail rendering added in Task 13
  document.getElementById("detail-empty").hidden = true;
  document.getElementById("detail-content").hidden = false;
  document.getElementById("detail-content").textContent = `Loading pin ${pinId}…`;
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

init();
```

- [ ] **Step 2: Manually verify the queue renders**

Run: `uvicorn src.main:app --reload --port 8000`
Open: `http://localhost:8000/queue/<an-existing-batch-id>` in a browser
Expected: Queue list on the left shows rows with thumbnails, titles, badges, and prices. Clicking a row selects it (highlighted) and shows "Loading pin N…" in the right pane.

If you don't have an existing batch, upload a few photos through `/` first.

- [ ] **Step 3: Commit**

```bash
git add static/review.js
git commit -m "feat(ui): review.js skeleton with queue list rendering"
```

---

## Task 13: Detail pane — header + match review section

**Files:**
- Modify: `static/review.js`

- [ ] **Step 1: Add detail-pane rendering**

In `static/review.js`, replace the `selectPin` function and add the detail rendering helpers below it:

```javascript
async function selectPin(pinId) {
  state.selectedPinId = pinId;
  renderQueueList();
  document.getElementById("detail-empty").hidden = true;
  document.getElementById("detail-content").hidden = false;
  document.getElementById("detail-content").innerHTML = '<div class="loading">Loading…</div>';
  const response = await fetch(`/api/pins/${pinId}`);
  const pin = await response.json();
  // Replace the pin in state so future re-renders use the fresh copy
  const idx = state.pins.findIndex((p) => p.id === pin.id);
  if (idx >= 0) state.pins[idx] = pin;
  renderDetail(pin);
}

function renderDetail(pin) {
  const container = document.getElementById("detail-content");
  container.innerHTML = `
    ${renderDetailHeader(pin)}
    <div class="detail-section" id="match-section">${renderMatchSection(pin)}</div>
    <div class="detail-section" id="extraction-section"><!-- Task 14 --></div>
    <div class="detail-section" id="draft-section"><!-- Task 15 --></div>
  `;
  wireMatchSection(pin);
}

function renderDetailHeader(pin) {
  const badge = RISK_LABELS[pin.risk_badge] || { text: "", cls: "" };
  const title = pinTitle(pin);
  const reason = riskReason(pin);
  return `
    <div class="detail-header">
      <div>
        <div class="detail-title">Pin #${pin.id} · ${escapeHtml(title)}</div>
        <div class="detail-subtitle"><span class="badge ${badge.cls}">${badge.text}</span> ${escapeHtml(reason)}</div>
      </div>
      <div class="detail-actions">
        <button class="btn-approve" data-action="approve">Approve</button>
        <button class="btn-skip" data-action="skip">Skip</button>
      </div>
    </div>`;
}

function riskReason(pin) {
  if (pin.risk_badge === "ambiguous_match" && pin.catalog_matches && pin.catalog_matches.length >= 2) {
    const sorted = pin.catalog_matches.slice().sort((a, b) => b.match_confidence - a.match_confidence);
    const gap = (sorted[0].match_confidence - sorted[1].match_confidence).toFixed(2);
    return `Top two within ${gap}`;
  }
  if (pin.risk_badge === "low_extraction") {
    return `Vision confidence ${(pin.extraction.confidence_score * 100).toFixed(0)}%`;
  }
  if (pin.risk_badge === "no_match") {
    return pin.no_catalog_match ? "Marked no catalog match" : "Matcher returned no candidates";
  }
  return "";
}

function userPhoto(pin) {
  if (pin.image_paths && pin.image_paths.length > 0) {
    return `/uploads/${pin.image_paths[0].replace(/^.*uploads\//, "")}`;
  }
  return "";
}

function catalogPhoto(match) {
  if (!match || !match.image_path) return "";
  return `/${match.image_path}`;
}

function renderMatchSection(pin) {
  const matches = (pin.catalog_matches || []).slice().sort((a, b) => b.match_confidence - a.match_confidence);
  const accepted = matches.find((m) => m.status === "accepted");
  const selected = accepted || matches[0] || null;

  if (matches.length === 0) {
    return `
      <div class="section-label">Section 1 · Match Review</div>
      <div class="empty-match">
        <p>No catalog candidates found for this pin.</p>
        <div class="match-actions">
          <button class="btn-danger" data-match-action="none">✗ Mark as no match</button>
          <button class="btn-neutral" data-match-action="search">🔍 Search catalog…</button>
        </div>
      </div>`;
  }

  const candidatesHtml = matches.map((m, i) => {
    const letter = String.fromCharCode(65 + i);
    const isSelected = selected && m.catalog_entry_id === selected.catalog_entry_id;
    const isAccepted = m.status === "accepted";
    return `
      <div class="candidate-card${isSelected ? " selected" : ""}${isAccepted ? " accepted" : ""}"
           data-catalog-entry-id="${m.catalog_entry_id}">
        <div class="candidate-image" style="background-image:url('${catalogPhoto(m)}')">${letter} · ${m.match_confidence.toFixed(2)}${isAccepted ? " ✓" : ""}</div>
        <div class="candidate-name">${escapeHtml(m.canonical_name || "(no name)")}</div>
      </div>`;
  }).join("");

  const selectedHtml = selected ? `
    <div class="compare-pane">
      <div class="compare-label">Selected Catalog Match</div>
      <div class="compare-image" style="background-image:url('${catalogPhoto(selected)}')"></div>
      <div class="compare-meta">
        <strong>${escapeHtml(selected.canonical_name || "")}</strong><br>
        <span class="muted">${escapeHtml(selected.source || "")} · ${selected.edition_size ? "LE " + selected.edition_size : ""} · ${selected.release_year || ""}</span>
      </div>
    </div>` : "";

  return `
    <div class="section-label">Section 1 · Match Review</div>
    <div class="compare-row">
      <div class="compare-pane">
        <div class="compare-label">Your Photo</div>
        <div class="compare-image" style="background-image:url('${userPhoto(pin)}')"></div>
      </div>
      ${selectedHtml}
    </div>
    <div class="match-actions">
      <button class="btn-success" data-match-action="accept">✓ Accept this match</button>
      <button class="btn-danger" data-match-action="none">✗ None of these</button>
      <button class="btn-neutral" data-match-action="search">🔍 Search catalog…</button>
    </div>
    <div class="section-label">Top ${matches.length} candidates · click to compare</div>
    <div class="candidate-strip">${candidatesHtml}</div>
  `;
}

function wireMatchSection(pin) {
  const container = document.getElementById("detail-content");
  container.querySelectorAll(".candidate-card").forEach((card) => {
    card.addEventListener("click", () => {
      const id = parseInt(card.dataset.catalogEntryId, 10);
      // Just visual: mark as selected; accept happens via Accept button (Task 16)
      container.querySelectorAll(".candidate-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      // Re-render compare pane with this match
      const match = pin.catalog_matches.find((m) => m.catalog_entry_id === id);
      if (match) {
        const compareRow = container.querySelector(".compare-row");
        const compareCol = compareRow.querySelectorAll(".compare-pane")[1];
        if (compareCol) {
          compareCol.querySelector(".compare-image").style.backgroundImage = `url('${catalogPhoto(match)}')`;
          compareCol.querySelector(".compare-meta").innerHTML =
            `<strong>${escapeHtml(match.canonical_name || "")}</strong><br>` +
            `<span class="muted">${escapeHtml(match.source || "")} · ${match.edition_size ? "LE " + match.edition_size : ""} · ${match.release_year || ""}</span>`;
        }
      }
      // Stash the visually-selected id on the container so Accept knows what to send
      container.dataset.visualSelectedId = id;
    });
  });
}
```

- [ ] **Step 2: Manually verify**

Run: `uvicorn src.main:app --reload --port 8000`
Open the queue page, click a pin. Expected: right pane shows pin id + title + risk badge in the header, then the Section 1 — Match Review block with your photo on the left, the top match on the right, action buttons, and a horizontal candidate strip below. Clicking a candidate card highlights it and swaps the right-side image.

- [ ] **Step 3: Commit**

```bash
git add static/review.js
git commit -m "feat(ui): review detail pane header + match review section"
```

---

## Task 14: Detail pane — extraction edit section

**Files:**
- Modify: `static/review.js`

- [ ] **Step 1: Add the extraction render and wire**

In `static/review.js`, replace the extraction-section placeholder in `renderDetail` with a real call:

```javascript
function renderDetail(pin) {
  const container = document.getElementById("detail-content");
  container.innerHTML = `
    ${renderDetailHeader(pin)}
    <div class="detail-section" id="match-section">${renderMatchSection(pin)}</div>
    <div class="detail-section" id="extraction-section">${renderExtractionSection(pin)}</div>
    <div class="detail-section" id="draft-section"><!-- Task 15 --></div>
  `;
  wireMatchSection(pin);
  wireExtractionSection(pin);
}
```

Add these two functions after `wireMatchSection`:

```javascript
function renderExtractionSection(pin) {
  const e = pin.extraction || {};
  return `
    <div class="section-label">Section 2 · Vision Extraction</div>
    <div class="extraction-form">
      <div class="form-grid">
        <label>Characters
          <input data-field="characters" value="${escapeHtml((e.characters || []).join(", "))}">
        </label>
        <label>Franchise
          <input data-field="franchise" value="${escapeHtml(e.franchise || "")}">
        </label>
        <label>Pin Type
          <input data-field="pin_type" value="${escapeHtml(e.pin_type || "")}">
        </label>
        <label>Edition Size
          <input data-field="edition_size" type="number" value="${e.edition_size != null ? e.edition_size : ""}">
        </label>
        <label>Visible Dates
          <input data-field="visible_dates" value="${escapeHtml(e.visible_dates || "")}">
        </label>
        <label>Event Clues
          <input data-field="event_clues" value="${escapeHtml(e.event_clues || "")}">
        </label>
      </div>
      <div class="extraction-footer">
        <span class="muted">Vision confidence: ${e.confidence_score != null ? (e.confidence_score * 100).toFixed(0) + "%" : "—"}</span>
        <button class="btn-neutral" data-action="save-rematch">💾 Save & Re-match</button>
      </div>
    </div>
  `;
}

function wireExtractionSection(pin) {
  const container = document.getElementById("detail-content");
  const button = container.querySelector('[data-action="save-rematch"]');
  if (!button) return;
  button.addEventListener("click", async () => {
    const inputs = container.querySelectorAll('#extraction-section [data-field]');
    const body = {};
    inputs.forEach((inp) => {
      const f = inp.dataset.field;
      if (f === "characters") {
        body.characters = inp.value.split(",").map((s) => s.trim()).filter(Boolean);
      } else if (f === "edition_size") {
        body.edition_size = inp.value ? parseInt(inp.value, 10) : null;
      } else {
        body[f] = inp.value || null;
      }
    });
    button.disabled = true;
    button.textContent = "Saving + re-matching…";
    try {
      await fetch(`/api/pins/${pin.id}/extraction`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const rematch = await fetch(`/api/pins/${pin.id}/rematch`, { method: "POST" });
      const updated = await rematch.json();
      const idx = state.pins.findIndex((p) => p.id === updated.id);
      if (idx >= 0) state.pins[idx] = updated;
      renderQueueList();
      renderDetail(updated);
    } finally {
      button.disabled = false;
    }
  });
}
```

- [ ] **Step 2: Manually verify**

Reload the queue page, select a pin, edit a field (e.g., change Characters), click "Save & Re-match". Expected: button shows "Saving + re-matching…", then the detail pane re-renders with the new candidates from the matcher.

- [ ] **Step 3: Commit**

```bash
git add static/review.js
git commit -m "feat(ui): extraction edit section with save and re-match"
```

---

## Task 15: Detail pane — listing draft section

**Files:**
- Modify: `static/review.js`

- [ ] **Step 1: Add the draft render and wire**

In `static/review.js`, update `renderDetail`:

```javascript
function renderDetail(pin) {
  const container = document.getElementById("detail-content");
  container.innerHTML = `
    ${renderDetailHeader(pin)}
    <div class="detail-section" id="match-section">${renderMatchSection(pin)}</div>
    <div class="detail-section" id="extraction-section">${renderExtractionSection(pin)}</div>
    <div class="detail-section" id="draft-section">${renderDraftSection(pin)}</div>
  `;
  wireMatchSection(pin);
  wireExtractionSection(pin);
  wireDraftSection(pin);
}
```

Add these functions after `wireExtractionSection`:

```javascript
function renderDraftSection(pin) {
  const d = pin.listing_draft || {};
  const accepted = (pin.catalog_matches || []).find((m) => m.status === "accepted");
  const banner = accepted
    ? `<div class="draft-banner">↻ Auto-regenerated from accepted match (${escapeHtml(accepted.canonical_name || "")})</div>`
    : (pin.no_catalog_match
        ? `<div class="draft-banner">↻ Generated from extraction (no catalog match)</div>`
        : "");
  return `
    <div class="section-label">Section 3 · Listing Draft</div>
    <div class="draft-form">
      ${banner}
      <label>Title (max 80)
        <input data-draft-field="title" maxlength="80" value="${escapeHtml(d.title || "")}">
      </label>
      <label>Description
        <textarea data-draft-field="description">${escapeHtml(d.description || "")}</textarea>
      </label>
      <div class="form-grid form-grid-3">
        <label>Suggested $
          <input data-draft-field="suggested_price" type="number" step="0.01" value="${d.suggested_price != null ? d.suggested_price : ""}">
        </label>
        <label>Quick Sale $
          <span class="readonly">${d.quick_sale_price != null ? "$" + d.quick_sale_price.toFixed(2) : "—"}</span>
        </label>
        <label>Confidence
          <span class="readonly">${escapeHtml(d.price_confidence || "—")}</span>
        </label>
      </div>
      <label>Tags
        <input data-draft-field="tags_keywords" value="${escapeHtml((d.tags_keywords || []).join(", "))}">
      </label>
      <div class="draft-footer">
        <button class="btn-neutral" data-action="regenerate">↻ Regenerate from match</button>
        <button class="btn-neutral" data-action="save-draft">💾 Save draft</button>
      </div>
    </div>
  `;
}

function wireDraftSection(pin) {
  const container = document.getElementById("detail-content");

  const regenBtn = container.querySelector('[data-action="regenerate"]');
  if (regenBtn) {
    regenBtn.addEventListener("click", async () => {
      regenBtn.disabled = true;
      try {
        const resp = await fetch(`/api/pins/${pin.id}/draft/regenerate`, { method: "POST" });
        const updated = await resp.json();
        replacePinInStateAndRender(updated);
      } finally {
        regenBtn.disabled = false;
      }
    });
  }

  const saveBtn = container.querySelector('[data-action="save-draft"]');
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const body = collectDraftFields(container);
      saveBtn.disabled = true;
      try {
        const resp = await fetch(`/api/pins/${pin.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const updated = await resp.json();
        replacePinInStateAndRender(updated);
      } finally {
        saveBtn.disabled = false;
      }
    });
  }
}

function collectDraftFields(container) {
  const inputs = container.querySelectorAll('#draft-section [data-draft-field]');
  const body = {};
  inputs.forEach((inp) => {
    const f = inp.dataset.draftField;
    if (f === "tags_keywords") {
      body.tags_keywords = inp.value.split(",").map((s) => s.trim()).filter(Boolean);
    } else if (f === "suggested_price") {
      body.suggested_price = inp.value ? parseFloat(inp.value) : null;
    } else {
      body[f] = inp.value || null;
    }
  });
  return body;
}

function replacePinInStateAndRender(pin) {
  // Compute risk badge client-side from the returned data if missing (server already adds it)
  const idx = state.pins.findIndex((p) => p.id === pin.id);
  if (idx >= 0) state.pins[idx] = pin;
  renderQueueList();
  renderCounts();
  renderDetail(pin);
}
```

- [ ] **Step 2: Manually verify**

Reload, select a pin, edit the title, click "Save draft" → page updates with new title in both the queue list and the draft form. Click "Regenerate from match" → draft refreshes to the auto-generated version.

- [ ] **Step 3: Commit**

```bash
git add static/review.js
git commit -m "feat(ui): listing draft section with save and regenerate"
```

---

## Task 16: Wire match-section actions (accept / none / approve / skip)

**Files:**
- Modify: `static/review.js`

- [ ] **Step 1: Extend `wireMatchSection` and add header action wiring**

At the bottom of `wireMatchSection` (before its closing `}`), append:

```javascript
  const headerActions = container.querySelector(".detail-actions");
  if (headerActions) {
    const approveBtn = headerActions.querySelector('[data-action="approve"]');
    const skipBtn = headerActions.querySelector('[data-action="skip"]');
    if (approveBtn) {
      approveBtn.addEventListener("click", async () => {
        // Save any dirty draft edits first
        const body = collectDraftFields(container);
        await fetch(`/api/pins/${pin.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const resp = await fetch(`/api/pins/${pin.id}/approve`, { method: "POST" });
        await resp.json();
        // Reload the whole batch so counts and badges update
        await loadBatch();
        if (state.selectedPinId) {
          const refreshed = state.pins.find((p) => p.id === state.selectedPinId);
          if (refreshed) renderDetail(refreshed);
        }
      });
    }
    if (skipBtn) {
      skipBtn.addEventListener("click", async () => {
        await fetch(`/api/pins/${pin.id}/skip`, { method: "POST" });
        await loadBatch();
      });
    }
  }

  const matchActions = container.querySelectorAll(".match-actions [data-match-action]");
  matchActions.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.matchAction;
      btn.disabled = true;
      try {
        if (action === "accept") {
          const visualId = parseInt(container.dataset.visualSelectedId || "0", 10);
          // Default to top match if user hasn't clicked a candidate
          const sorted = (pin.catalog_matches || []).slice().sort((a, b) => b.match_confidence - a.match_confidence);
          const chosen = visualId || (sorted[0] && sorted[0].catalog_entry_id);
          if (!chosen) return;
          const resp = await fetch(`/api/pins/${pin.id}/match/select`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ catalog_entry_id: chosen }),
          });
          const updated = await resp.json();
          replacePinInStateAndRender(updated);
        } else if (action === "none") {
          const resp = await fetch(`/api/pins/${pin.id}/match/none`, { method: "POST" });
          const updated = await resp.json();
          replacePinInStateAndRender(updated);
        } else if (action === "search") {
          openCatalogSearchModal(pin);
        }
      } finally {
        btn.disabled = false;
      }
    });
  });
```

Add a stub for `openCatalogSearchModal` (full implementation in Task 17):

```javascript
function openCatalogSearchModal(pin) {
  alert("Catalog search modal — implemented in next task");
}
```

- [ ] **Step 2: Manually verify**

Reload, click into a pin with multiple candidates. Click candidate B in the strip → it highlights. Click "Accept this match" → request fires, pin updates, B is now marked accepted, draft auto-regenerates with B's data.

Click "None of these" on another pin → marked no match, draft regenerates from extraction only.

Click "Approve" in the header → pin status flips to approved, queue list badge updates, counts increment.

- [ ] **Step 3: Commit**

```bash
git add static/review.js
git commit -m "feat(ui): wire accept/none/approve/skip actions"
```

---

## Task 17: Catalog search modal

**Files:**
- Modify: `static/review.js`
- Modify: `src/templates/review.html`

- [ ] **Step 1: Add the modal markup to the template**

In `src/templates/review.html`, add this markup right before the closing `</div>` of `#review-app`:

```html
  <div id="catalog-modal" class="modal" hidden>
    <div class="modal-backdrop"></div>
    <div class="modal-body">
      <div class="modal-header">
        <strong>Search catalog</strong>
        <button class="modal-close" type="button">×</button>
      </div>
      <input id="catalog-search-input" type="text" placeholder="Search by name or character…">
      <div id="catalog-results" class="catalog-results"></div>
      <button id="catalog-load-more" class="btn-neutral" hidden>Load more</button>
    </div>
  </div>
```

- [ ] **Step 2: Replace the modal stub in `review.js`**

Replace `openCatalogSearchModal` with a real implementation:

```javascript
let catalogSearchOffset = 0;
let catalogSearchQuery = "";
let catalogModalPin = null;

function openCatalogSearchModal(pin) {
  catalogModalPin = pin;
  catalogSearchOffset = 0;
  catalogSearchQuery = "";
  const modal = document.getElementById("catalog-modal");
  const input = document.getElementById("catalog-search-input");
  const results = document.getElementById("catalog-results");
  const loadMore = document.getElementById("catalog-load-more");
  input.value = "";
  results.innerHTML = "";
  loadMore.hidden = true;
  modal.hidden = false;
  input.focus();
}

function closeCatalogSearchModal() {
  document.getElementById("catalog-modal").hidden = true;
  catalogModalPin = null;
}

async function runCatalogSearch(append = false) {
  const results = document.getElementById("catalog-results");
  if (!append) {
    results.innerHTML = "<div class='loading'>Searching…</div>";
    catalogSearchOffset = 0;
  }
  const resp = await fetch(`/api/catalog/search?q=${encodeURIComponent(catalogSearchQuery)}&offset=${catalogSearchOffset}`);
  const entries = await resp.json();
  if (!append) results.innerHTML = "";
  for (const e of entries) {
    const card = document.createElement("div");
    card.className = "catalog-result";
    card.innerHTML = `
      <div class="catalog-thumb" style="background-image:url('/${e.image_path || ""}')"></div>
      <div class="catalog-info">
        <strong>${escapeHtml(e.canonical_name || "")}</strong>
        <div class="muted">${escapeHtml(e.franchise || "")} · ${e.release_year || ""} ${e.edition_size ? "· LE " + e.edition_size : ""}</div>
      </div>
      <button class="btn-success">Use this</button>`;
    card.querySelector("button").addEventListener("click", async () => {
      if (!catalogModalPin) return;
      const r = await fetch(`/api/pins/${catalogModalPin.id}/match/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ catalog_entry_id: e.id }),
      });
      if (r.status === 404) {
        // The entry isn't a candidate for this pin yet — we need a separate flow.
        // For now, surface the limitation.
        alert("This catalog entry is not currently a candidate for this pin. Use Save & Re-match after editing extraction.");
      } else {
        const updated = await r.json();
        replacePinInStateAndRender(updated);
        closeCatalogSearchModal();
      }
    });
    results.appendChild(card);
  }
  document.getElementById("catalog-load-more").hidden = entries.length < 20;
}
```

Add modal wiring at the bottom of `init()`:

```javascript
  document.querySelector("#catalog-modal .modal-close").addEventListener("click", closeCatalogSearchModal);
  document.querySelector("#catalog-modal .modal-backdrop").addEventListener("click", closeCatalogSearchModal);
  const searchInput = document.getElementById("catalog-search-input");
  let timer = null;
  searchInput.addEventListener("input", (e) => {
    catalogSearchQuery = e.target.value;
    clearTimeout(timer);
    timer = setTimeout(() => runCatalogSearch(false), 250);
  });
  document.getElementById("catalog-load-more").addEventListener("click", () => {
    catalogSearchOffset += 20;
    runCatalogSearch(true);
  });
```

- [ ] **Step 3: Address the "selected entry not a candidate" gap**

The 404 path above is real: `select_match` requires the entry to already be one of the pin's candidates. To support picking a fully arbitrary catalog entry, the API needs to insert a new `CatalogMatch` row first.

In `src/routes/pins.py`, modify `select_match` so that if the chosen entry is not in the candidate list, it inserts a new `CatalogMatch` row for it (rank = current_max_rank + 1, status = ACCEPTED) instead of returning 404. Replace the current 404 branch:

```python
    chosen = next((m for m in matches if m.catalog_entry_id == body.catalog_entry_id), None)
    if not chosen:
        # User picked an entry from manual search — add it as a new candidate
        max_rank = max((m.rank for m in matches), default=0)
        chosen = CatalogMatch(
            pin_id=pin_id,
            catalog_entry_id=body.catalog_entry_id,
            match_confidence=0.0,
            match_reasoning="manually selected by user",
            rank=max_rank + 1,
            status=MatchStatus.ACCEPTED,
        )
        db.add(chosen)
        matches.append(chosen)
```

Update the 404 test in `tests/test_routes_review.py` to reflect this — the only remaining 404 path is "catalog entry id doesn't exist at all". The existing test `test_select_match_404_when_catalog_entry_unknown` already covers that case. Add a new test:

```python
@pytest.mark.asyncio
async def test_select_match_inserts_new_candidate_when_not_already_present(test_app):
    pin_id = test_app.state.test_pin_id
    transport = ASGITransport(app=test_app)
    # Create a brand-new catalog entry that is not a candidate for this pin
    from src.models import CatalogEntry
    from sqlalchemy.ext.asyncio import AsyncSession
    # Use the dependency override session
    new_entry_id = None
    for override in test_app.dependency_overrides.values():
        async for session in override():
            entry = CatalogEntry(canonical_name="Manual Pick", franchise="Disney", source="manual")
            session.add(entry)
            await session.commit()
            new_entry_id = entry.id
            break
        break

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post(f"/api/pins/{pin_id}/match/select", json={"catalog_entry_id": new_entry_id})
    assert resp.status_code == 200
    data = resp.json()
    accepted = [m for m in data["catalog_matches"] if m["status"] == "accepted"]
    assert len(accepted) == 1
    assert accepted[0]["catalog_entry_id"] == new_entry_id
```

Now update the existing `test_select_match_404_when_catalog_entry_unknown` — its expectation stays correct (404 is still returned for unknown id).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_routes_review.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Manually verify**

Reload, select a pin, click "🔍 Search catalog…", type a name, click "Use this" on a result. Pin updates with the new accepted match.

- [ ] **Step 6: Commit**

```bash
git add static/review.js src/templates/review.html src/routes/pins.py tests/test_routes_review.py
git commit -m "feat(ui): catalog search modal with manual match insertion"
```

---

## Task 18: Keyboard shortcuts

**Files:**
- Modify: `static/review.js`

- [ ] **Step 1: Add keydown handler**

In `static/review.js`, add at the bottom of `init()`:

```javascript
  document.addEventListener("keydown", (e) => {
    // Ignore when typing in inputs/textareas
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    // Ignore when modal is open
    if (!document.getElementById("catalog-modal").hidden) return;

    const sorted = sortedFilteredPins();
    const idx = sorted.findIndex((p) => p.id === state.selectedPinId);

    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = sorted[Math.min(idx + 1, sorted.length - 1)];
      if (next) selectPin(next.id);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = sorted[Math.max(idx - 1, 0)];
      if (prev) selectPin(prev.id);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const btn = document.querySelector('.detail-actions [data-action="approve"]');
      if (btn) btn.click();
    }
  });
```

- [ ] **Step 2: Manually verify**

Reload. Click into the queue list area (not an input). Press ↓/↑ — selection moves. Press Enter — current pin gets approved.

- [ ] **Step 3: Commit**

```bash
git add static/review.js
git commit -m "feat(ui): keyboard shortcuts (up/down/enter)"
```

---

## Task 19: Two-pane styles in `style.css`

**Files:**
- Modify: `static/style.css`

- [ ] **Step 1: Read the existing stylesheet**

Run: `wc -l static/style.css`
Skim it to see the existing classes so the new styles don't collide.

- [ ] **Step 2: Append the review styles**

Append the following block to `static/style.css`:

```css
/* ── Review workspace ──────────────────────────────────────── */

#review-app { display: flex; flex-direction: column; height: calc(100vh - 80px); }

.review-header {
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #e0e0e0;
  background: #fafafa;
  display: flex;
  align-items: center;
  gap: 1rem;
}
.review-header .batch-id { color: #888; margin-left: 0.5rem; font-size: 0.85rem; }
.review-counts { color: #666; margin-left: 0.5rem; font-size: 0.85rem; }

.review-workspace { flex: 1; display: flex; min-height: 0; }

.queue-pane {
  width: 38%;
  min-width: 320px;
  border-right: 1px solid #e0e0e0;
  background: #fafafa;
  display: flex;
  flex-direction: column;
}
.queue-controls {
  display: flex;
  gap: 0.4rem;
  padding: 0.6rem 0.8rem;
  border-bottom: 1px solid #eee;
}
.queue-controls input { flex: 1; padding: 0.3rem 0.5rem; font-size: 0.85rem; }
.queue-controls select { padding: 0.3rem; font-size: 0.8rem; }

.queue-list { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; }
.queue-row {
  display: flex;
  gap: 0.6rem;
  padding: 0.6rem 0.8rem;
  border-bottom: 1px solid #eee;
  cursor: pointer;
  align-items: center;
}
.queue-row:hover { background: #f0f0f0; }
.queue-row.selected { background: #e6f0ff; border-left: 3px solid #3b6ef0; padding-left: calc(0.8rem - 3px); }
.queue-thumb { width: 48px; height: 48px; object-fit: cover; border-radius: 4px; background: #ccc; flex-shrink: 0; }
.queue-row-body { flex: 1; min-width: 0; }
.queue-title { font-weight: 600; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.queue-meta { display: flex; gap: 0.5rem; font-size: 0.7rem; color: #666; margin-top: 0.2rem; align-items: center; }

.badge { padding: 1px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 500; }
.badge-ready { background: #d4edda; color: #155724; }
.badge-ambiguous { background: #fff3cd; color: #856404; }
.badge-low-extraction { background: #fff3cd; color: #856404; }
.badge-no-match { background: #f8d7da; color: #721c24; }
.badge-approved { background: #cce5ff; color: #004085; }
.badge-exported { background: #d1ecf1; color: #0c5460; }

.detail-pane { flex: 1; overflow-y: auto; background: #fff; }
.detail-empty { padding: 3rem; text-align: center; color: #888; font-size: 0.9rem; }
.detail-content { padding: 0; }

.detail-header {
  padding: 0.8rem 1rem;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 1;
}
.detail-title { font-weight: 600; font-size: 0.95rem; }
.detail-subtitle { font-size: 0.75rem; color: #666; margin-top: 0.2rem; }
.detail-actions { display: flex; gap: 0.4rem; }

.detail-section { padding: 1rem; border-bottom: 1px solid #f0f0f0; }
.section-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #888;
  margin-bottom: 0.5rem;
}

.compare-row { display: flex; gap: 1rem; margin-bottom: 0.8rem; }
.compare-pane { flex: 1; }
.compare-label { font-size: 0.7rem; color: #888; margin-bottom: 0.3rem; text-transform: uppercase; letter-spacing: 0.05em; }
.compare-image {
  width: 100%;
  height: 240px;
  background-color: #222;
  background-size: contain;
  background-position: center;
  background-repeat: no-repeat;
  border-radius: 6px;
}
.compare-meta { font-size: 0.78rem; margin-top: 0.4rem; line-height: 1.4; color: #444; }

.match-actions { display: flex; gap: 0.5rem; margin: 0.6rem 0 0.8rem; }
.btn-success { background: #28a745; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; font-size: 0.85rem; }
.btn-danger { background: #dc3545; color: white; border: none; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; font-size: 0.85rem; }
.btn-neutral { background: #f0f0f0; color: #333; border: 1px solid #ccc; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; font-size: 0.85rem; }
.btn-success:disabled, .btn-danger:disabled, .btn-neutral:disabled { opacity: 0.6; cursor: not-allowed; }

.candidate-strip { display: flex; gap: 0.5rem; overflow-x: auto; padding-bottom: 0.4rem; }
.candidate-card {
  min-width: 130px;
  border: 2px solid #ddd;
  border-radius: 6px;
  padding: 0.4rem;
  cursor: pointer;
  background: #fff;
  flex-shrink: 0;
}
.candidate-card.selected { border-color: #3b6ef0; background: #e6f0ff; }
.candidate-card.accepted { border-color: #28a745; }
.candidate-image {
  height: 90px;
  background-color: #aaa;
  background-size: contain;
  background-position: center;
  background-repeat: no-repeat;
  border-radius: 4px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  text-shadow: 1px 1px 2px rgba(0,0,0,0.6);
}
.candidate-name { font-size: 0.7rem; margin-top: 0.3rem; line-height: 1.3; color: #444; }

.empty-match { padding: 1.5rem; text-align: center; color: #666; }
.empty-match p { margin-bottom: 0.8rem; }

.extraction-form, .draft-form { background: #fafafa; border: 1px solid #eee; border-radius: 6px; padding: 0.8rem; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem 1rem; }
.form-grid-3 { grid-template-columns: 1fr 1fr 1fr; }
.form-grid label, .draft-form label { display: block; font-size: 0.8rem; }
.form-grid label { font-size: 0.75rem; color: #666; }
.form-grid input, .draft-form input, .draft-form textarea { width: 100%; padding: 0.3rem 0.5rem; font-size: 0.85rem; box-sizing: border-box; margin-top: 0.2rem; }
.draft-form textarea { min-height: 80px; }
.extraction-footer, .draft-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 0.8rem; }
.muted { color: #888; font-size: 0.75rem; }
.readonly { display: block; padding: 0.3rem 0; color: #555; font-size: 0.85rem; }

.draft-banner {
  background: #e6f0ff;
  color: #3b6ef0;
  padding: 0.4rem 0.6rem;
  border-radius: 4px;
  font-size: 0.75rem;
  margin-bottom: 0.6rem;
}

/* ── Modal ─────────────────────────────────────────────────── */
.modal { position: fixed; inset: 0; z-index: 100; }
.modal[hidden] { display: none; }
.modal-backdrop { position: absolute; inset: 0; background: rgba(0,0,0,0.4); }
.modal-body {
  position: relative;
  background: #fff;
  max-width: 600px;
  margin: 5vh auto;
  padding: 1rem;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.2);
}
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem; }
.modal-close { background: none; border: none; font-size: 1.4rem; cursor: pointer; }
.catalog-results { max-height: 50vh; overflow-y: auto; margin-top: 0.6rem; }
.catalog-result { display: flex; gap: 0.6rem; padding: 0.5rem; border-bottom: 1px solid #eee; align-items: center; }
.catalog-thumb { width: 60px; height: 60px; background-color: #ccc; background-size: contain; background-position: center; background-repeat: no-repeat; border-radius: 4px; flex-shrink: 0; }
.catalog-info { flex: 1; font-size: 0.85rem; }

.loading { padding: 2rem; text-align: center; color: #888; }
```

- [ ] **Step 2: Manually verify the page renders cleanly**

Reload `http://localhost:8000/queue/<batch>` in a browser. Expected: Two-pane layout fills the screen, queue rows are styled, badges are colored, candidate cards line up in a horizontal strip, the detail header sticks to the top of the right pane.

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat(ui): two-pane workspace styles"
```

---

## Task 20: Delete obsolete templates

**Files:**
- Delete: `src/templates/queue.html`
- Delete: `src/templates/detail.html`

The `/queue/{batch_id}` route now points at `review.html` (Task 11) and the `/pins/{pin_id}` page route was removed, so these files are dead.

- [ ] **Step 1: Verify nothing else references them**

Run: `grep -rn "queue.html\|detail.html" src/ static/`
Expected: No results (or only self-references in the files about to be deleted).

- [ ] **Step 2: Delete the files**

```bash
git rm src/templates/queue.html src/templates/detail.html
```

- [ ] **Step 3: Run all tests to confirm nothing broke**

Run: `pytest -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(ui): remove obsolete queue.html and detail.html templates"
```

---

## Task 21: End-to-end integration test

**Files:**
- Create: `tests/test_review_integration.py`

A single test that exercises the cascade: a pin starts with the matcher's top pick, the user selects a different candidate, and the listing draft regenerates from the new entry.

- [ ] **Step 1: Write the test**

Create `tests/test_review_integration.py`:

```python
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
async def integration_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.include_router(pins_router)
    app.dependency_overrides[get_db] = override_get_db

    async with factory() as session:
        pin = Pin(batch_id="b", status=PinStatus.MATCHED, image_paths=["x.jpg"])
        session.add(pin)
        await session.flush()

        extraction = VisionExtraction(
            pin_id=pin.id, characters=["Mickey"], franchise="Disney",
            pin_type="limited edition", edition_size=1500, visible_dates="2005",
            event_clues="50th Anniversary", confidence_score=0.9,
        )
        session.add(extraction)

        top_entry = CatalogEntry(canonical_name="Mickey 50th Anniversary", franchise="Disney",
                                  release_year=2005, edition_size=1500, source="pintradingdb")
        better_entry = CatalogEntry(canonical_name="Mickey Halloween 2010", franchise="Disney",
                                     release_year=2010, edition_size=500, source="pintradingdb")
        session.add_all([top_entry, better_entry])
        await session.flush()

        m1 = CatalogMatch(pin_id=pin.id, catalog_entry_id=top_entry.id,
                          match_confidence=0.92, rank=1, status=MatchStatus.SUGGESTED)
        m2 = CatalogMatch(pin_id=pin.id, catalog_entry_id=better_entry.id,
                          match_confidence=0.71, rank=2, status=MatchStatus.SUGGESTED)
        session.add_all([m1, m2])

        # Simulate the orchestrator's initial draft from the top match
        draft = ListingDraft(pin_id=pin.id, title="Disney Mickey 50th Anniversary 2005 Pin LE/1500",
                              description="Mickey 50th Anniversary", export_status=ExportStatus.DRAFT)
        session.add(draft)

        await session.commit()
        app.state.pin_id = pin.id
        app.state.better_entry_id = better_entry.id

    yield app
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_user_accepts_different_match_draft_regenerates(integration_app):
    pin_id = integration_app.state.pin_id
    better_id = integration_app.state.better_entry_id

    transport = ASGITransport(app=integration_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Sanity: original draft references year 2005
        before = (await client.get(f"/api/pins/{pin_id}")).json()
        assert "2005" in before["listing_draft"]["title"]

        # Accept the second candidate (Mickey Halloween 2010)
        resp = await client.post(
            f"/api/pins/{pin_id}/match/select",
            json={"catalog_entry_id": better_id},
        )
        assert resp.status_code == 200
        after = resp.json()

        # The accepted match should be the new one
        accepted = [m for m in after["catalog_matches"] if m["status"] == "accepted"]
        assert len(accepted) == 1
        assert accepted[0]["catalog_entry_id"] == better_id

        # Listing draft should now reference the new match's year (2010)
        assert "2010" in after["listing_draft"]["title"]
        assert "2005" not in after["listing_draft"]["title"]
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_review_integration.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_review_integration.py
git commit -m "test(review): end-to-end accept-different-match cascade"
```

---

## Task 22: Manual smoke checklist

**Files:**
- Create: `docs/superpowers/plans/2026-04-10-human-review-ui-smoke-checklist.md`

- [ ] **Step 1: Write the checklist**

Create `docs/superpowers/plans/2026-04-10-human-review-ui-smoke-checklist.md`:

```markdown
# Human Review UI — Manual Smoke Checklist

Walk through this list after any change touching the review workspace, the new endpoints, or the draft regeneration helper.

1. [ ] Upload a small batch (3–5 pins) via the home page; wait for processing to complete.
2. [ ] Open `/queue/<batch-id>` — two-pane layout renders, queue list shows all pins with thumbnails, badges, and prices.
3. [ ] Click a row → right pane loads with header, match review, extraction, and draft sections.
4. [ ] Click a different candidate card in the strip → compare slot updates with the new image and metadata.
5. [ ] Click "✓ Accept this match" with the second candidate selected → pin updates, draft auto-regenerates, queue badge changes.
6. [ ] Edit a field in the extraction form (e.g., Characters) → click "💾 Save & Re-match" → spinner button text appears, then candidate strip refreshes.
7. [ ] On a different pin, click "✗ None of these" → pin gets the no-match badge, draft regenerates from extraction only.
8. [ ] Click "🔍 Search catalog…" → modal opens, type a query, click "Use this" on a result → modal closes, pin updates with the manually picked match.
9. [ ] Click "↻ Regenerate from match" in the draft section → draft refreshes.
10. [ ] Click "Approve" in the header → pin status flips to approved, queue counts increment, badge updates.
11. [ ] Use ↑/↓ to navigate the queue and Enter to approve — keyboard shortcuts work outside of input fields.
12. [ ] Verify the existing CSV export still works at `/api/batch/<batch-id>/export`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-10-human-review-ui-smoke-checklist.md
git commit -m "docs: add manual smoke checklist for human review UI"
```

- [ ] **Step 3: Run the full test suite as a final gate**

Run: `pytest -v`
Expected: All tests pass (existing + new).

- [ ] **Step 4: Walk through the smoke checklist by hand**

Open the app, work through the 12 items above, fix any issues found.
