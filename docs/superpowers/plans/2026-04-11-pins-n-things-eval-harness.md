# pins-n-things Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Phase-1 evaluation harness that ingests live pins-n-things eBay listings, parses each listing title into a structured reference label, and surfaces tool-vs-reference disagreements inside the existing human review UI.

**Architecture:** Add seven nullable `reference_*` columns to `Pin` (one migration, no new tables). A new CLI (`scripts/import_ebay_seller.py`) pulls listings via the existing `src/services/ebay_client.py`, downloads the primary image, calls a new `src/pipeline/reference_label.py` parser (Claude Haiku 4.5) to extract structured metadata from the title/description, creates `Pin` rows in a named batch, and triggers the existing `process_batch` orchestrator. A new `renderReferenceLabel(pin)` block in `static/review.js`, backed by a shared Python diff helper `src/pipeline/reference_diff.py` (unit-tested there, mirrored in JS as a thin wrapper), renders the disagreement overlay in the right pane of `review.html`.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy async, Pydantic settings, `anthropic` SDK (Claude Haiku 4.5), `httpx`, vanilla JS + Jinja templates, `pytest` + `pytest-asyncio` with SQLite in-memory.

**Working directory for all relative paths below:** `disney-pin-assistant/`. Any path prefixed with `docs/` is relative to the repo root.

**Spec:** `docs/superpowers/specs/2026-04-11-pins-n-things-eval-harness-design.md`

**Prerequisites (from spec):** plan execution is blocked until (1) production eBay keys are activated, (2) the human review UI plan has shipped (`review.html`, `review.js`, `_pin_to_dict`, `Pin.no_catalog_match`), and (3) `ANTHROPIC_API_KEY` is present. Unit tests in every task below run without any real network, so development can begin immediately against recorded fixtures.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/pipeline/reference_label.py` | `parse_listing_label(title, description)` — single async function calling Claude Haiku 4.5. |
| `src/pipeline/reference_diff.py` | Pure field-by-field diff between a parsed reference label dict and the tool-side view of a pin. Tested in Python; JS mirrors the shape. |
| `scripts/import_ebay_seller.py` | CLI: enumerate seller listings, download images, parse labels, create `Pin` rows in a named batch, enqueue processing. |
| `tests/test_reference_columns.py` | Round-trip test for the new `Pin.reference_*` columns. |
| `tests/test_pin_to_dict_reference_fields.py` | `_pin_to_dict` serializer includes/omits reference fields correctly. |
| `tests/test_reference_label_parser.py` | Mocked-Anthropic tests of the parser contract. |
| `tests/test_ebay_client_seller_pagination.py` | Mocked-httpx test for the `offset` extension to `browse_api_seller_search`. |
| `tests/test_reference_diff.py` | Unit tests for per-field diff semantics. |
| `tests/test_import_ebay_seller.py` | CLI orchestration tests with all outbound calls mocked. |
| `docs/superpowers/manual/2026-04-11-reference-label-smoke.md` | Manual smoke checklist used at the end of the plan. |

**Modified files:**

| Path | Change |
|---|---|
| `src/models.py` | Add seven nullable `reference_*` columns to `Pin`. |
| `src/database.py` | Add `ensure_reference_label_columns(engine)` following the existing `ensure_review_ui_columns` pattern. |
| `src/main.py` | Call `ensure_reference_label_columns` in `lifespan`. |
| `src/routes/pins.py` | Extend `_pin_to_dict` to include the seven reference fields when `reference_source` is non-null. |
| `src/services/ebay_client.py` | Add `offset` parameter to `browse_api_seller_search` for pagination. |
| `src/templates/review.html` | Add a conditional `<section>` block in the right pane for the reference-label overlay. |
| `static/review.js` | Add `renderReferenceLabel(pin)` and call it from `renderDetail`. |
| `static/style.css` | Classes for the reference section, diff rows, status icons, muted state. |

---

## Task 1: Add reference columns to `Pin` + idempotent migration

Seven nullable columns on `Pin`. Round-trip test confirms the ORM can insert and reload them. The migration function mirrors the existing `ensure_review_ui_columns` pattern exactly so an existing on-disk DB picks up the new columns on next startup.

**Files:**
- Modify: `src/models.py:67-85`
- Modify: `src/database.py:14-22`
- Modify: `src/main.py:5` and `src/main.py:14-19`
- Create: `tests/test_reference_columns.py`

- [ ] **Step 1: Write the failing round-trip test**

Create `tests/test_reference_columns.py`:

```python
import pytest
from sqlalchemy import select
from src.models import Pin, PinStatus


@pytest.mark.asyncio
async def test_pin_reference_fields_round_trip(db_session):
    pin = Pin(
        batch_id="pnt-eval-2026-04-11",
        status=PinStatus.UNPROCESSED,
        image_paths=["uploads/x.jpg"],
        reference_source="ebay_browse",
        reference_external_id="v1|123|0",
        reference_url="https://www.ebay.com/itm/123",
        reference_raw_title="DSSH Maleficent dragon LE250 new",
        reference_raw_description="boilerplate shipping info",
        reference_parsed_fields={"characters": ["Maleficent"], "edition_size": 250},
        reference_ingested_at="2026-04-11T12:00:00+00:00",
    )
    db_session.add(pin)
    await db_session.commit()

    result = await db_session.execute(select(Pin).where(Pin.batch_id == "pnt-eval-2026-04-11"))
    loaded = result.scalar_one()

    assert loaded.reference_source == "ebay_browse"
    assert loaded.reference_external_id == "v1|123|0"
    assert loaded.reference_url == "https://www.ebay.com/itm/123"
    assert loaded.reference_raw_title == "DSSH Maleficent dragon LE250 new"
    assert loaded.reference_raw_description == "boilerplate shipping info"
    assert loaded.reference_parsed_fields == {"characters": ["Maleficent"], "edition_size": 250}
    assert loaded.reference_ingested_at == "2026-04-11T12:00:00+00:00"


@pytest.mark.asyncio
async def test_pin_reference_fields_default_to_none(db_session):
    pin = Pin(batch_id="normal", status=PinStatus.UNPROCESSED, image_paths=["x.jpg"])
    db_session.add(pin)
    await db_session.commit()

    result = await db_session.execute(select(Pin).where(Pin.batch_id == "normal"))
    loaded = result.scalar_one()

    assert loaded.reference_source is None
    assert loaded.reference_parsed_fields is None
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd disney-pin-assistant && uv run pytest tests/test_reference_columns.py -v`

Expected: `AttributeError: 'Pin' object has no attribute 'reference_source'` (or SQLAlchemy equivalent). The failure should come from the model, not the test harness.

- [ ] **Step 3: Add reference columns to the Pin model**

Edit `src/models.py`. Replace lines 67–85 with:

```python
class Pin(Base):
    __tablename__ = "pins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False)
    status = Column(Enum(PinStatus), nullable=False, default=PinStatus.UNPROCESSED)
    photo_type = Column(String(50), nullable=True)
    seller_notes = Column(Text, nullable=True)
    image_paths = Column(JSON, default=list)
    no_catalog_match = Column(Boolean, default=False, server_default="0", nullable=False)
    reference_source = Column(String(50), nullable=True)
    reference_external_id = Column(String(100), nullable=True)
    reference_url = Column(String(500), nullable=True)
    reference_raw_title = Column(Text, nullable=True)
    reference_raw_description = Column(Text, nullable=True)
    reference_parsed_fields = Column(JSON, nullable=True)
    reference_ingested_at = Column(String, nullable=True)
    created_at = Column(String, default=lambda: _utcnow().isoformat())
    updated_at = Column(String, default=lambda: _utcnow().isoformat(), onupdate=lambda: _utcnow().isoformat())

    # Relationships
    extraction = relationship("VisionExtraction", back_populates="pin", uselist=False)
    catalog_matches = relationship("CatalogMatch", back_populates="pin")
    comps = relationship("Comp", back_populates="pin")
    listing_draft = relationship("ListingDraft", back_populates="pin", uselist=False)
```

`reference_ingested_at` is stored as ISO-string to match the existing `created_at`/`updated_at` convention in this repo rather than introducing a `DateTime` column type (the schema is `sqlite+aiosqlite`, and SQLAlchemy `String` round-trips cleanly with `datetime.isoformat()`).

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd disney-pin-assistant && uv run pytest tests/test_reference_columns.py -v`

Expected: 2 passed.

- [ ] **Step 5: Add the idempotent migration**

Edit `src/database.py`. Append a new function after `ensure_review_ui_columns`:

```python
async def ensure_reference_label_columns(engine):
    """Idempotent migration for the pins-n-things reference-label columns."""
    new_columns = {
        "reference_source":          "TEXT",
        "reference_external_id":     "TEXT",
        "reference_url":             "TEXT",
        "reference_raw_title":       "TEXT",
        "reference_raw_description": "TEXT",
        "reference_parsed_fields":   "JSON",
        "reference_ingested_at":     "TEXT",
    }
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(pins)"))
        existing = {row[1] for row in result.fetchall()}
        for name, sql_type in new_columns.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE pins ADD COLUMN {name} {sql_type}"))
```

- [ ] **Step 6: Wire the migration into app startup**

Edit `src/main.py`:

1. On line 5 change:
```python
from src.database import engine, ensure_review_ui_columns
```
to:
```python
from src.database import engine, ensure_review_ui_columns, ensure_reference_label_columns
```

2. In the `lifespan` function, after line 18 (`await ensure_review_ui_columns(engine)`) add:
```python
    await ensure_reference_label_columns(engine)
```

- [ ] **Step 7: Re-run the whole test suite to confirm no regressions**

Run: `cd disney-pin-assistant && uv run pytest -x`

Expected: all previously passing tests still pass. New tests pass.

- [ ] **Step 8: Commit**

```bash
git add disney-pin-assistant/src/models.py \
        disney-pin-assistant/src/database.py \
        disney-pin-assistant/src/main.py \
        disney-pin-assistant/tests/test_reference_columns.py
git commit -m "feat(eval): add reference-label columns to Pin + idempotent migration"
```

---

## Task 2: Extend `_pin_to_dict` with conditional reference fields

The serializer includes the seven reference columns only when `reference_source` is non-null. Normal uploads get zero new keys in their payload.

**Files:**
- Modify: `src/routes/pins.py:254-313`
- Create: `tests/test_pin_to_dict_reference_fields.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pin_to_dict_reference_fields.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.models import Pin, PinStatus, CatalogMatch
from src.routes.pins import _pin_to_dict


async def _load(db_session, batch_id):
    result = await db_session.execute(
        select(Pin).options(
            selectinload(Pin.extraction),
            selectinload(Pin.listing_draft),
            selectinload(Pin.catalog_matches).selectinload(CatalogMatch.catalog_entry),
            selectinload(Pin.comps),
        ).where(Pin.batch_id == batch_id)
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_pin_to_dict_omits_reference_fields_for_normal_uploads(db_session):
    pin = Pin(batch_id="normal", status=PinStatus.UNPROCESSED, image_paths=["x.jpg"])
    db_session.add(pin)
    await db_session.commit()

    loaded = await _load(db_session, "normal")
    data = _pin_to_dict(loaded)

    for key in (
        "reference_source", "reference_external_id", "reference_url",
        "reference_raw_title", "reference_raw_description",
        "reference_parsed_fields", "reference_ingested_at",
    ):
        assert key not in data, f"{key} should be absent for non-reference pins"


@pytest.mark.asyncio
async def test_pin_to_dict_includes_reference_fields_when_present(db_session):
    pin = Pin(
        batch_id="pnt",
        status=PinStatus.UNPROCESSED,
        image_paths=["x.jpg"],
        reference_source="ebay_browse",
        reference_external_id="v1|999|0",
        reference_url="https://www.ebay.com/itm/999",
        reference_raw_title="Stitch LE 500",
        reference_raw_description=None,
        reference_parsed_fields={"characters": ["Stitch"], "edition_size": 500},
        reference_ingested_at="2026-04-11T12:00:00+00:00",
    )
    db_session.add(pin)
    await db_session.commit()

    loaded = await _load(db_session, "pnt")
    data = _pin_to_dict(loaded)

    assert data["reference_source"] == "ebay_browse"
    assert data["reference_external_id"] == "v1|999|0"
    assert data["reference_url"] == "https://www.ebay.com/itm/999"
    assert data["reference_raw_title"] == "Stitch LE 500"
    assert data["reference_raw_description"] is None
    assert data["reference_parsed_fields"] == {"characters": ["Stitch"], "edition_size": 500}
    assert data["reference_ingested_at"] == "2026-04-11T12:00:00+00:00"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd disney-pin-assistant && uv run pytest tests/test_pin_to_dict_reference_fields.py -v`

Expected: the "includes" test fails because `_pin_to_dict` doesn't set the keys. The "omits" test may already pass — that's fine.

- [ ] **Step 3: Extend `_pin_to_dict`**

Edit `src/routes/pins.py`. At the end of `_pin_to_dict` (after the `comps` loop on line 312 and before `return data` on line 313), insert:

```python
    if pin.reference_source is not None:
        data["reference_source"] = pin.reference_source
        data["reference_external_id"] = pin.reference_external_id
        data["reference_url"] = pin.reference_url
        data["reference_raw_title"] = pin.reference_raw_title
        data["reference_raw_description"] = pin.reference_raw_description
        data["reference_parsed_fields"] = pin.reference_parsed_fields
        data["reference_ingested_at"] = pin.reference_ingested_at
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `cd disney-pin-assistant && uv run pytest tests/test_pin_to_dict_reference_fields.py -v`

Expected: 2 passed.

- [ ] **Step 5: Run the full test suite**

Run: `cd disney-pin-assistant && uv run pytest -x`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/src/routes/pins.py \
        disney-pin-assistant/tests/test_pin_to_dict_reference_fields.py
git commit -m "feat(eval): serialize reference fields in _pin_to_dict when present"
```

---

## Task 3: Reference label parser (`src/pipeline/reference_label.py`)

Single async function `parse_listing_label(title, description)` that calls Claude Haiku 4.5 and returns a dict. Uncertain fields are omitted by the model. Whole-call failures return `None` (caller stores `reference_parsed_fields = null` on the Pin).

**Files:**
- Create: `src/pipeline/reference_label.py`
- Create: `tests/test_reference_label_parser.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reference_label_parser.py`:

```python
import json
from unittest.mock import AsyncMock, patch
import pytest

from src.pipeline.reference_label import parse_listing_label


def _fake_response(text_payload: str):
    class _Block:
        text = text_payload
    class _Resp:
        content = [_Block()]
    return _Resp()


@pytest.mark.asyncio
async def test_parser_returns_dict_on_valid_json():
    payload = {
        "characters": ["Lilo", "Stitch"],
        "franchise": "Lilo & Stitch",
        "series_or_collection": "Hidden Mickey Series 1",
        "release_year": 2019,
        "edition_size": 2000,
        "is_limited_edition": True,
        "confidence_notes": "clear title",
    }
    with patch(
        "src.pipeline.reference_label.client.messages.create",
        new=AsyncMock(return_value=_fake_response(json.dumps(payload))),
    ):
        result = await parse_listing_label(
            "Lilo Stitch LE 2000 Hidden Mickey Series 1 2019", None,
        )
    assert result == payload


@pytest.mark.asyncio
async def test_parser_omits_uncertain_fields():
    payload = {"characters": ["Maleficent"], "confidence_notes": "no year visible"}
    with patch(
        "src.pipeline.reference_label.client.messages.create",
        new=AsyncMock(return_value=_fake_response(json.dumps(payload))),
    ):
        result = await parse_listing_label("Maleficent pin", None)
    assert result == payload
    assert "release_year" not in result


@pytest.mark.asyncio
async def test_parser_returns_none_on_unparseable_json():
    with patch(
        "src.pipeline.reference_label.client.messages.create",
        new=AsyncMock(return_value=_fake_response("not json at all")),
    ):
        result = await parse_listing_label("nonsense title", None)
    assert result is None


@pytest.mark.asyncio
async def test_parser_retries_once_then_raises():
    mock = AsyncMock(side_effect=[RuntimeError("boom1"), RuntimeError("boom2")])
    with patch("src.pipeline.reference_label.client.messages.create", new=mock):
        with pytest.raises(RuntimeError):
            await parse_listing_label("any", None)
    assert mock.await_count == 2


@pytest.mark.asyncio
async def test_parser_retries_once_then_succeeds():
    payload = {"characters": ["Pluto"]}
    mock = AsyncMock(side_effect=[RuntimeError("boom"), _fake_response(json.dumps(payload))])
    with patch("src.pipeline.reference_label.client.messages.create", new=mock):
        result = await parse_listing_label("Pluto pin", None)
    assert result == payload
    assert mock.await_count == 2
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd disney-pin-assistant && uv run pytest tests/test_reference_label_parser.py -v`

Expected: `ModuleNotFoundError: No module named 'src.pipeline.reference_label'`.

- [ ] **Step 3: Write the parser**

Create `src/pipeline/reference_label.py`:

```python
"""Reference-label parser: noisy eBay listing title → structured dict.

Used only by scripts/import_ebay_seller.py at ingest time. Calls Claude
Haiku 4.5 with temperature=0. Fields the model is not confident about are
omitted from the output.
"""

import json
from src.services.anthropic_client import client

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = """You parse noisy eBay listing titles and descriptions for Disney trading pins into a structured metadata object.

Return JSON with any of these keys, AND ONLY these keys:
- characters: array of Disney character names appearing on the pin
- franchise: string (e.g. "Classic Disney", "Star Wars", "Pixar", "Lilo & Stitch")
- series_or_collection: string (e.g. "Hidden Mickey Series 1")
- release_year: integer
- edition_size: integer (the numeric edition cap, e.g. 2000 for LE 2000)
- is_limited_edition: boolean
- pin_type: string (e.g. "hidden_mickey", "cast_exclusive", "jumbo")
- event: string (e.g. "D23 Expo 2019")
- exclusive_source: string (e.g. "DSSH", "WDI", "Disneyland Paris")
- confidence_notes: free text — always include this field

Omit any key you are not confident about. Do not guess. An omitted key means "not extracted" and is more useful than a wrong guess.

Respond with a single JSON object and no other text. No markdown fences."""


async def parse_listing_label(title: str, description: str | None = None) -> dict | None:
    """Extract structured metadata from a noisy listing title/description.

    Returns a dict of confident fields on success.
    Returns None when the model returns unparseable JSON.
    Raises on transport errors after one retry.
    """
    user_content = f"Title: {title}"
    if description:
        user_content += f"\n\nDescription: {description}"

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=400,
                temperature=0,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            break
        except Exception as exc:  # noqa: BLE001 — retry any transport/API error once
            last_error = exc
            continue
    else:
        assert last_error is not None
        raise last_error

    raw_text = response.content[0].text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return None
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd disney-pin-assistant && uv run pytest tests/test_reference_label_parser.py -v`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/pipeline/reference_label.py \
        disney-pin-assistant/tests/test_reference_label_parser.py
git commit -m "feat(eval): add Claude-Haiku reference-label parser"
```

---

## Task 4: eBay client — add `offset` pagination to `browse_api_seller_search`

The existing function hardcodes offset=0 and limit=50. The harness needs to page through the full catalog. One small extension: add `offset: int = 0` to the function signature and wire it into the request params. Existing callers (if any) are unaffected because `offset` defaults to 0.

**Files:**
- Modify: `src/services/ebay_client.py:39-55`
- Create: `tests/test_ebay_client_seller_pagination.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ebay_client_seller_pagination.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.services import ebay_client


@pytest.mark.asyncio
async def test_seller_search_passes_offset_param():
    ebay_client._token_cache["access_token"] = "fake"
    ebay_client._token_cache["expires_at"] = 9999999999

    captured = {}

    async def _fake_get(self, url, headers=None, params=None):
        captured["url"] = url
        captured["params"] = params
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"itemSummaries": [{"itemId": "v1|1|0"}]})
        return resp

    with patch("httpx.AsyncClient.get", new=_fake_get):
        items = await ebay_client.browse_api_seller_search(
            seller="pins-n-things", limit=200, offset=400,
        )

    assert items == [{"itemId": "v1|1|0"}]
    assert captured["params"]["offset"] == "400"
    assert captured["params"]["limit"] == "200"
    assert captured["params"]["filter"] == "sellers:{pins-n-things}"


@pytest.mark.asyncio
async def test_seller_search_defaults_offset_to_zero():
    ebay_client._token_cache["access_token"] = "fake"
    ebay_client._token_cache["expires_at"] = 9999999999

    captured = {}

    async def _fake_get(self, url, headers=None, params=None):
        captured["params"] = params
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"itemSummaries": []})
        return resp

    with patch("httpx.AsyncClient.get", new=_fake_get):
        await ebay_client.browse_api_seller_search(seller="x")

    assert captured["params"]["offset"] == "0"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd disney-pin-assistant && uv run pytest tests/test_ebay_client_seller_pagination.py -v`

Expected: `TypeError: browse_api_seller_search() got an unexpected keyword argument 'offset'`.

- [ ] **Step 3: Extend `browse_api_seller_search`**

Edit `src/services/ebay_client.py`. Replace lines 39–55 with:

```python
async def browse_api_seller_search(
    seller: str, limit: int = 50, offset: int = 0,
) -> list[dict]:
    """Search active listings by seller username.

    `offset` supports pagination for callers that need to enumerate a seller's
    full active catalog (e.g. the pins-n-things eval harness).
    """
    token = await get_ebay_token()
    params = {
        "q": "disney pin",
        "filter": f"sellers:{{{seller}}}",
        "limit": str(limit),
        "offset": str(offset),
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("itemSummaries", [])
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd disney-pin-assistant && uv run pytest tests/test_ebay_client_seller_pagination.py -v`

Expected: 2 passed.

- [ ] **Step 5: Run the full test suite**

Run: `cd disney-pin-assistant && uv run pytest -x`

Expected: all pass. (No existing caller passes `offset` or relies on the old signature.)

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/src/services/ebay_client.py \
        disney-pin-assistant/tests/test_ebay_client_seller_pagination.py
git commit -m "feat(eval): add offset pagination to browse_api_seller_search"
```

---

## Task 5: Reference diff helper (`src/pipeline/reference_diff.py`)

A pure Python module with per-field diff functions. Unit-tested here; `renderReferenceLabel` in `review.js` mirrors the same logic as a thin wrapper (no JS test harness in this repo).

Diff semantics from the spec:
- `characters`: normalize lowercase + strip, compare as **sets**; partial overlap is `MISMATCH`.
- String fields (`franchise`, `series_or_collection`, `event`, `exclusive_source`, `pin_type`, `canonical_name`): case-insensitive substring in either direction = `AGREE`.
- Numeric fields (`release_year`, `edition_size`): exact equality.
- Booleans (`is_limited_edition`): exact equality.
- One side present, other missing = `ONE_SIDE_ONLY`.
- Neither side present = `MUTED`.

**Files:**
- Create: `src/pipeline/reference_diff.py`
- Create: `tests/test_reference_diff.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reference_diff.py`:

```python
from src.pipeline.reference_diff import (
    DiffStatus, diff_pin_fields, GRADED_FIELDS, UNGRADED_FIELDS,
)


def _base_tool():
    return {
        "characters": ["Lilo", "Stitch"],
        "franchise": "Classic Disney",
        "canonical_name": None,
        "series_or_collection": None,
        "release_year": None,
        "edition_size": None,
        "event": None,
        "pin_type": None,
        "exclusive_source": None,
        "is_limited_edition": None,
    }


def test_character_sets_agree_when_equal():
    ref = {"characters": ["stitch", "lilo"]}
    diff = diff_pin_fields(tool=_base_tool(), reference=ref)
    assert diff["characters"].status is DiffStatus.AGREE


def test_character_sets_disagree_on_partial_overlap():
    ref = {"characters": ["Lilo"]}
    diff = diff_pin_fields(tool=_base_tool(), reference=ref)
    assert diff["characters"].status is DiffStatus.MISMATCH


def test_string_substring_either_direction_agrees():
    tool = _base_tool()
    tool["series_or_collection"] = "Hidden Mickey 2023 Series 1"
    ref = {"series_or_collection": "Hidden Mickey"}
    diff = diff_pin_fields(tool=tool, reference=ref)
    assert diff["series_or_collection"].status is DiffStatus.AGREE


def test_string_no_overlap_mismatches():
    tool = _base_tool()
    tool["franchise"] = "Star Wars"
    ref = {"franchise": "Classic Disney"}
    diff = diff_pin_fields(tool=tool, reference=ref)
    assert diff["franchise"].status is DiffStatus.MISMATCH


def test_numeric_exact_equality():
    tool = _base_tool()
    tool["release_year"] = 2019
    ref = {"release_year": 2019}
    diff = diff_pin_fields(tool=tool, reference=ref)
    assert diff["release_year"].status is DiffStatus.AGREE

    ref2 = {"release_year": 2020}
    diff2 = diff_pin_fields(tool=tool, reference=ref2)
    assert diff2["release_year"].status is DiffStatus.MISMATCH


def test_one_side_only_when_tool_has_and_reference_missing():
    tool = _base_tool()
    tool["edition_size"] = 2000
    diff = diff_pin_fields(tool=tool, reference={})
    assert diff["edition_size"].status is DiffStatus.ONE_SIDE_ONLY


def test_muted_when_neither_side_present():
    diff = diff_pin_fields(tool=_base_tool(), reference={})
    assert diff["event"].status is DiffStatus.MUTED


def test_graded_fields_excludes_bucket_c():
    assert "canonical_name" in GRADED_FIELDS
    assert "characters" in GRADED_FIELDS
    assert "event" in UNGRADED_FIELDS
    assert "pin_type" in UNGRADED_FIELDS
    assert "exclusive_source" in UNGRADED_FIELDS
    assert not (GRADED_FIELDS & UNGRADED_FIELDS)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd disney-pin-assistant && uv run pytest tests/test_reference_diff.py -v`

Expected: `ModuleNotFoundError: No module named 'src.pipeline.reference_diff'`.

- [ ] **Step 3: Write the diff helper**

Create `src/pipeline/reference_diff.py`:

```python
"""Per-field diff between a tool-side pin view and a parsed reference label.

Shared logic so that:
- server-side code (if ever added) can reuse the same rules, and
- the JS `renderReferenceLabel` in static/review.js can mirror the same
  field list without drifting.

Tested in tests/test_reference_diff.py; the JS side is a thin visual wrapper.
"""

from dataclasses import dataclass
from enum import Enum


class DiffStatus(str, Enum):
    AGREE = "agree"
    MISMATCH = "mismatch"
    ONE_SIDE_ONLY = "one_side_only"
    MUTED = "muted"


@dataclass(frozen=True)
class FieldDiff:
    field: str
    status: DiffStatus
    tool_value: object
    reference_value: object


# Bucket A (image-inferable) + Bucket B (catalog-derived) — graded.
GRADED_FIELDS: frozenset[str] = frozenset({
    "characters",
    "franchise",
    "canonical_name",
    "series_or_collection",
    "release_year",
    "edition_size",
    "is_limited_edition",
})

# Bucket C — rendered but noise.
UNGRADED_FIELDS: frozenset[str] = frozenset({
    "event",
    "pin_type",
    "exclusive_source",
})

ALL_FIELDS: tuple[str, ...] = tuple(GRADED_FIELDS | UNGRADED_FIELDS)


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)) and len(value) == 0:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def _norm_list(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(v).strip().lower() for v in value if str(v).strip()}


def _compare_characters(tool: object, reference: object) -> DiffStatus:
    return DiffStatus.AGREE if _norm_list(tool) == _norm_list(reference) else DiffStatus.MISMATCH


def _compare_string(tool: object, reference: object) -> DiffStatus:
    a = str(tool).strip().lower()
    b = str(reference).strip().lower()
    if a == b or a in b or b in a:
        return DiffStatus.AGREE
    return DiffStatus.MISMATCH


def _compare_exact(tool: object, reference: object) -> DiffStatus:
    return DiffStatus.AGREE if tool == reference else DiffStatus.MISMATCH


_COMPARATORS = {
    "characters": _compare_characters,
    "franchise": _compare_string,
    "canonical_name": _compare_string,
    "series_or_collection": _compare_string,
    "event": _compare_string,
    "pin_type": _compare_string,
    "exclusive_source": _compare_string,
    "release_year": _compare_exact,
    "edition_size": _compare_exact,
    "is_limited_edition": _compare_exact,
}


def diff_pin_fields(tool: dict, reference: dict) -> dict[str, FieldDiff]:
    """Return a per-field diff for every known field in ALL_FIELDS.

    `tool` is the flattened tool-side view (vision + matched catalog entry).
    `reference` is the parser output dict from `parse_listing_label`.
    """
    out: dict[str, FieldDiff] = {}
    for field in ALL_FIELDS:
        t = tool.get(field)
        r = reference.get(field)
        t_present = _present(t)
        r_present = _present(r)
        if not t_present and not r_present:
            status = DiffStatus.MUTED
        elif t_present != r_present:
            status = DiffStatus.ONE_SIDE_ONLY
        else:
            status = _COMPARATORS[field](t, r)
        out[field] = FieldDiff(field=field, status=status, tool_value=t, reference_value=r)
    return out
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd disney-pin-assistant && uv run pytest tests/test_reference_diff.py -v`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/pipeline/reference_diff.py \
        disney-pin-assistant/tests/test_reference_diff.py
git commit -m "feat(eval): add reference-diff helper with unit tests"
```

---

## Task 6: Ingestion CLI (`scripts/import_ebay_seller.py`)

The orchestration layer. Pulls seller listings through `browse_api_seller_search`, fetches full details, downloads the primary image, parses the reference label, creates `Pin` rows in a batch, optionally triggers `process_batch`. Idempotent by `(reference_source, reference_external_id)`: re-runs refresh `reference_parsed_fields` and add new pins without touching existing images.

CLI is factored into an `async def run(args)` function so tests can exercise it without argparse/process boundaries.

**Files:**
- Create: `scripts/import_ebay_seller.py`
- Create: `tests/test_import_ebay_seller.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_import_ebay_seller.py`:

```python
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select
from src.models import Pin

# Import the CLI module by path since scripts/ isn't a package.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "import_ebay_seller",
    Path(__file__).resolve().parents[1] / "scripts" / "import_ebay_seller.py",
)
import_ebay_seller = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(import_ebay_seller)  # type: ignore[union-attr]


def _mk_args(**overrides):
    defaults = dict(
        seller="pins-n-things",
        batch_name="pnt-test",
        max=None,
        skip_processing=True,
        dry_run=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_run_creates_pins_from_seller_listings(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ebay_seller, "UPLOAD_ROOT", tmp_path)

    summaries = [
        {"itemId": "v1|1|0", "title": "Lilo Stitch pin", "itemWebUrl": "https://ebay.com/1"},
        {"itemId": "v1|2|0", "title": "Maleficent LE 250", "itemWebUrl": "https://ebay.com/2"},
    ]

    async def fake_seller_search(seller, limit, offset):
        return summaries if offset == 0 else []

    async def fake_item_detail(item_id):
        return {
            "itemId": item_id,
            "title": next(s["title"] for s in summaries if s["itemId"] == item_id),
            "description": "shipping boilerplate",
            "image": {"imageUrl": f"https://cdn/{item_id}.jpg"},
        }

    async def fake_download(url, dest):
        Path(dest).write_bytes(b"\xff\xd8\xff\xe0")  # tiny JPEG header
        return dest

    async def fake_parse(title, description):
        return {"characters": ["Stitch" if "Stitch" in title else "Maleficent"]}

    with patch.object(import_ebay_seller, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(import_ebay_seller, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(import_ebay_seller, "_download_image", new=AsyncMock(side_effect=fake_download)), \
         patch.object(import_ebay_seller, "parse_listing_label", new=AsyncMock(side_effect=fake_parse)):
        summary = await import_ebay_seller.run(
            _mk_args(), session_factory=lambda: db_session_wrapper(db_session),
        )

    assert summary["new"] == 2
    assert summary["refreshed"] == 0

    result = await db_session.execute(select(Pin).where(Pin.batch_id == "pnt-test"))
    pins = result.scalars().all()
    assert len(pins) == 2
    for pin in pins:
        assert pin.reference_source == "ebay_browse"
        assert pin.reference_external_id in {"v1|1|0", "v1|2|0"}
        assert pin.reference_raw_title.startswith(("Lilo", "Maleficent"))
        assert pin.reference_parsed_fields is not None
        assert len(pin.image_paths) == 1


@pytest.mark.asyncio
async def test_run_refreshes_parsed_fields_on_duplicate(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ebay_seller, "UPLOAD_ROOT", tmp_path)

    existing = Pin(
        batch_id="pnt-test",
        image_paths=[str(tmp_path / "old.jpg")],
        reference_source="ebay_browse",
        reference_external_id="v1|1|0",
        reference_url="https://ebay.com/1",
        reference_raw_title="old title",
        reference_parsed_fields={"characters": ["Old"]},
        reference_ingested_at="2020-01-01T00:00:00",
    )
    db_session.add(existing)
    await db_session.commit()

    async def fake_seller_search(seller, limit, offset):
        return [{"itemId": "v1|1|0", "title": "new title", "itemWebUrl": "https://ebay.com/1"}] if offset == 0 else []

    async def fake_item_detail(_):
        return {"title": "new title", "description": None, "image": {"imageUrl": "https://cdn/1.jpg"}}

    async def fake_parse(title, description):
        return {"characters": ["New"]}

    with patch.object(import_ebay_seller, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(import_ebay_seller, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(import_ebay_seller, "_download_image", new=AsyncMock()), \
         patch.object(import_ebay_seller, "parse_listing_label", new=AsyncMock(side_effect=fake_parse)):
        summary = await import_ebay_seller.run(
            _mk_args(), session_factory=lambda: db_session_wrapper(db_session),
        )

    assert summary["new"] == 0
    assert summary["refreshed"] == 1

    await db_session.refresh(existing)
    assert existing.reference_parsed_fields == {"characters": ["New"]}
    assert existing.reference_raw_title == "new title"
    # Image was NOT re-downloaded for a duplicate
    assert existing.image_paths == [str(tmp_path / "old.jpg")]


@pytest.mark.asyncio
async def test_run_dry_run_writes_nothing(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(import_ebay_seller, "UPLOAD_ROOT", tmp_path)

    async def fake_seller_search(seller, limit, offset):
        return [{"itemId": "v1|1|0", "title": "x", "itemWebUrl": "https://ebay.com/1"}] if offset == 0 else []

    with patch.object(import_ebay_seller, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(import_ebay_seller, "browse_api_item_detail", new=AsyncMock(return_value={"title": "x", "image": {"imageUrl": "https://cdn/x.jpg"}})), \
         patch.object(import_ebay_seller, "_download_image", new=AsyncMock()) as dl, \
         patch.object(import_ebay_seller, "parse_listing_label", new=AsyncMock(return_value={})):
        summary = await import_ebay_seller.run(
            _mk_args(dry_run=True), session_factory=lambda: db_session_wrapper(db_session),
        )

    assert summary["dry_run"] is True
    dl.assert_not_called()
    result = await db_session.execute(select(Pin))
    assert result.scalars().all() == []


# --- session factory adapter so run() can reuse an existing db_session ---

from contextlib import asynccontextmanager

def db_session_wrapper(session):
    """Return an async context manager that yields the already-open test session.

    run() expects `session_factory()` to be an async context manager producing
    an AsyncSession. Tests reuse the conftest `db_session` fixture so the
    assertions below can see the same rows.
    """
    @asynccontextmanager
    async def _cm():
        yield session
    return _cm()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd disney-pin-assistant && uv run pytest tests/test_import_ebay_seller.py -v`

Expected: `FileNotFoundError` on the import_module call because `scripts/import_ebay_seller.py` doesn't exist yet.

- [ ] **Step 3: Write the CLI**

Create `scripts/import_ebay_seller.py`:

```python
"""Ingest a seller's live eBay listings into a named Pin batch.

Usage:
    python scripts/import_ebay_seller.py \
        --seller pins-n-things \
        --batch-name pnt-eval-2026-04-11 \
        [--max 500] \
        [--skip-processing] \
        [--dry-run]

Each listing becomes one Pin row tagged with reference_source='ebay_browse'.
Re-runs against the same --batch-name refresh reference_parsed_fields on
existing rows (matched by reference_external_id) without re-downloading
images.

Designed to be called from the command line OR imported and driven
synchronously via `run(args)` for tests.
"""

import argparse
import asyncio
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from sqlalchemy import select

# Make `from src.xxx import ...` work when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database import async_session
from src.models import Pin, PinStatus
from src.pipeline.orchestrator import process_batch
from src.pipeline.reference_label import parse_listing_label
from src.services.ebay_client import (
    browse_api_item_detail,
    browse_api_seller_search,
)

UPLOAD_ROOT: Path = Path("uploads")
PAGE_SIZE: int = 200
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(item_id: str) -> str:
    return _SAFE_FILENAME.sub("_", item_id) + ".jpg"


async def _download_image(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)
    return dest


def _extract_primary_image_url(detail: dict) -> str | None:
    image = detail.get("image") or {}
    if isinstance(image, dict) and image.get("imageUrl"):
        return image["imageUrl"]
    extras = detail.get("additionalImages") or []
    if extras and isinstance(extras, list):
        first = extras[0]
        if isinstance(first, dict):
            return first.get("imageUrl")
    return None


@asynccontextmanager
async def _default_session_factory():
    async with async_session() as session:
        yield session


async def run(
    args: argparse.Namespace,
    session_factory: Callable[[], "asyncio.AbstractAsyncContextManager"] = _default_session_factory,
) -> dict:
    """Execute one ingest run. Returns a summary dict."""
    summary = {
        "seller": args.seller,
        "batch_name": args.batch_name,
        "seen": 0,
        "new": 0,
        "refreshed": 0,
        "image_errors": 0,
        "parser_failures": 0,
        "dry_run": bool(args.dry_run),
        "processing_enqueued": False,
    }

    # 1. Enumerate.
    all_summaries: list[dict] = []
    offset = 0
    while True:
        page = await browse_api_seller_search(
            seller=args.seller, limit=PAGE_SIZE, offset=offset,
        )
        if not page:
            break
        all_summaries.extend(page)
        offset += PAGE_SIZE
        if args.max is not None and len(all_summaries) >= args.max:
            all_summaries = all_summaries[: args.max]
            break
        if len(page) < PAGE_SIZE:
            break

    summary["seen"] = len(all_summaries)

    if args.dry_run:
        for s in all_summaries:
            print(f"[dry-run] would ingest {s.get('itemId')} — {s.get('title')}")
        return summary

    # 2. Open a DB session and iterate.
    async with session_factory() as db:
        # Preload existing pins in this batch keyed by external id.
        result = await db.execute(
            select(Pin).where(
                Pin.batch_id == args.batch_name,
                Pin.reference_source == "ebay_browse",
            )
        )
        existing_by_id = {p.reference_external_id: p for p in result.scalars().all()}

        for item_summary in all_summaries:
            item_id = item_summary.get("itemId")
            if not item_id:
                continue

            try:
                detail = await browse_api_item_detail(item_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] get_item failed for {item_id}: {exc}", file=sys.stderr)
                continue

            raw_title = detail.get("title") or item_summary.get("title") or ""
            raw_description = detail.get("description")
            listing_url = detail.get("itemWebUrl") or item_summary.get("itemWebUrl")

            try:
                parsed = await parse_listing_label(raw_title, raw_description)
            except Exception as exc:  # noqa: BLE001
                summary["parser_failures"] += 1
                print(f"[warn] label parser failed for {item_id}: {exc}", file=sys.stderr)
                parsed = None

            existing = existing_by_id.get(item_id)
            if existing is not None:
                # Refresh in place — do NOT re-download the image.
                existing.reference_raw_title = raw_title
                existing.reference_raw_description = raw_description
                existing.reference_url = listing_url
                existing.reference_parsed_fields = parsed
                existing.reference_ingested_at = _utcnow_iso()
                summary["refreshed"] += 1
                continue

            # New pin → download image, then create row.
            image_url = _extract_primary_image_url(detail)
            if not image_url:
                summary["image_errors"] += 1
                print(f"[warn] no image URL for {item_id}", file=sys.stderr)
                continue

            dest = UPLOAD_ROOT / args.batch_name / _safe_filename(item_id)
            try:
                await _download_image(image_url, dest)
            except Exception as exc:  # noqa: BLE001
                summary["image_errors"] += 1
                print(f"[warn] image download failed for {item_id}: {exc}", file=sys.stderr)
                continue

            pin = Pin(
                batch_id=args.batch_name,
                status=PinStatus.UNPROCESSED,
                image_paths=[str(dest)],
                reference_source="ebay_browse",
                reference_external_id=item_id,
                reference_url=listing_url,
                reference_raw_title=raw_title,
                reference_raw_description=raw_description,
                reference_parsed_fields=parsed,
                reference_ingested_at=_utcnow_iso(),
            )
            db.add(pin)
            summary["new"] += 1

        await db.commit()

    # 3. Enqueue processing unless opted out.
    if not args.skip_processing and (summary["new"] > 0 or summary["refreshed"] > 0):
        await process_batch(async_session, args.batch_name)
        summary["processing_enqueued"] = True

    return summary


def _print_summary(summary: dict) -> None:
    print(f"""pins-n-things ingestion complete
  batch: {summary['batch_name']}
  listings seen: {summary['seen']}
  new pins created: {summary['new']}
  duplicates refreshed: {summary['refreshed']}
  image errors: {summary['image_errors']}
  label parser failures: {summary['parser_failures']}
  processing: {'enqueued' if summary['processing_enqueued'] else 'skipped'}
""")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_ebay_seller",
        description="Ingest a seller's live eBay listings into a named Pin batch.",
    )
    parser.add_argument("--seller", required=True, help="eBay username (Browse API sellers filter)")
    parser.add_argument("--batch-name", required=True, dest="batch_name",
                        help="Human-readable batch label. Re-runs refresh existing pins.")
    parser.add_argument("--max", type=int, default=None,
                        help="Cap on listings to ingest (default: unlimited)")
    parser.add_argument("--skip-processing", action="store_true",
                        help="Do not enqueue vision/match pipeline after ingest")
    parser.add_argument("--dry-run", action="store_true",
                        help="Hit the API, parse labels, print what would be created, write nothing")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = asyncio.run(run(args))
    _print_summary(summary)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd disney-pin-assistant && uv run pytest tests/test_import_ebay_seller.py -v`

Expected: 3 passed.

- [ ] **Step 5: Run the full test suite**

Run: `cd disney-pin-assistant && uv run pytest -x`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/scripts/import_ebay_seller.py \
        disney-pin-assistant/tests/test_import_ebay_seller.py
git commit -m "feat(eval): add scripts/import_ebay_seller.py CLI"
```

---

## Task 7: Review UI scaffold — HTML + CSS

Add a conditional `<section>` in the right pane and the CSS classes used by the diff rows. No JS changes in this task — the section is empty scaffolding that the next task fills in.

**Files:**
- Modify: `src/templates/review.html` (right-pane detail area)
- Modify: `static/style.css` (append diff classes)

- [ ] **Step 1: Add the HTML scaffold**

Edit `src/templates/review.html`. Locate the right-pane detail container (around line 26–31, the `<div id="detail-content">` block) and ensure there is **no** conditional Jinja inside it — the section is built by JS. We only need a placeholder `<div>` that `renderDetail` can populate. The existing `<div id="detail-content">` already serves this purpose, so no HTML edit is needed here **except** adding a tiny SVG/icon fragment if we decide to use an inline icon in the next task.

For this task: **no HTML changes**. Leave review.html alone. The scaffold lives entirely in JS + CSS. Mark the step complete.

- [ ] **Step 2: Append CSS classes for the reference section**

Edit `static/style.css`. Append to the end of the file:

```css
/* ── Reference label diff overlay (pins-n-things eval harness) ─────── */

.reference-section {
  margin-top: 16px;
  padding: 12px 14px;
  border: 1px solid var(--border, #d8d8d8);
  border-radius: 6px;
  background: #fafafa;
}

.reference-section summary {
  cursor: pointer;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.reference-section .ref-ebay-link {
  font-size: 12px;
  text-decoration: none;
}

.reference-raw-title {
  font-style: italic;
  color: #555;
  margin: 8px 0 12px 0;
}

.reference-diff-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.reference-diff-table th,
.reference-diff-table td {
  text-align: left;
  padding: 4px 6px;
  border-bottom: 1px solid #eee;
  vertical-align: top;
}

.reference-diff-table th {
  font-weight: 600;
  color: #666;
  width: 28%;
}

.diff-status {
  display: inline-block;
  width: 14px;
  text-align: center;
  margin-right: 4px;
}

.diff-agree { color: #2e7d32; }
.diff-mismatch { color: #c62828; }
.diff-one-side { color: #ef6c00; }
.diff-muted { color: #aaa; }

.diff-row.diff-muted td {
  color: #aaa;
}
```

- [ ] **Step 3: Smoke-check the stylesheet loads**

Run: `cd disney-pin-assistant && uv run pytest -x` (make sure nothing regressed even though this is a CSS-only change).

Run: `cd disney-pin-assistant && uv run uvicorn src.main:app --reload` in a second terminal, open `http://localhost:8000/queue/<any-existing-batch-id>`, verify the page still renders without console errors. (Nothing visible yet — we just want to confirm we didn't break the existing layout.)

- [ ] **Step 4: Commit**

```bash
git add disney-pin-assistant/static/style.css
git commit -m "feat(eval): add CSS scaffolding for reference diff overlay"
```

---

## Task 8: Review UI — `renderReferenceLabel` in `review.js`

The visible piece. `renderDetail` calls `renderReferenceLabel(pin)` at the end of its `innerHTML` template. The function is a no-op when `pin.reference_source` is missing, so normal uploads stay untouched.

Diff logic mirrors `src/pipeline/reference_diff.py` exactly — same field list, same comparator rules, same status values.

**Files:**
- Modify: `static/review.js:222-235` (wire the call into `renderDetail`)
- Append to: `static/review.js` (new functions at the bottom)
- Create: `docs/superpowers/manual/2026-04-11-reference-label-smoke.md`

- [ ] **Step 1: Append the diff logic and renderer to `review.js`**

At the end of `static/review.js`, append:

```javascript
// ── Reference label diff overlay ───────────────────────────────────
// Mirrors src/pipeline/reference_diff.py. Field list and comparator rules
// MUST stay in sync with that module.

const REFERENCE_GRADED_FIELDS = [
  "characters",
  "franchise",
  "canonical_name",
  "series_or_collection",
  "release_year",
  "edition_size",
  "is_limited_edition",
];

const REFERENCE_UNGRADED_FIELDS = [
  "event",
  "pin_type",
  "exclusive_source",
];

const REFERENCE_ALL_FIELDS = [
  ...REFERENCE_GRADED_FIELDS,
  ...REFERENCE_UNGRADED_FIELDS,
];

const REFERENCE_FIELD_LABELS = {
  characters: "Characters",
  franchise: "Franchise",
  canonical_name: "Canonical name",
  series_or_collection: "Series",
  release_year: "Year",
  edition_size: "Edition size",
  is_limited_edition: "LE flag",
  event: "Event",
  pin_type: "Pin type",
  exclusive_source: "Exclusive source",
};

function _refPresent(value) {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value) && value.length === 0) return false;
  if (typeof value === "string" && value.trim() === "") return false;
  return true;
}

function _refNormList(value) {
  if (!Array.isArray(value)) return new Set();
  return new Set(
    value
      .map((v) => String(v).trim().toLowerCase())
      .filter((v) => v.length > 0),
  );
}

function _refSetsEqual(a, b) {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

function _refCompareField(field, tool, reference) {
  if (field === "characters") {
    return _refSetsEqual(_refNormList(tool), _refNormList(reference)) ? "agree" : "mismatch";
  }
  if (["franchise", "canonical_name", "series_or_collection", "event", "pin_type", "exclusive_source"].includes(field)) {
    const a = String(tool).trim().toLowerCase();
    const b = String(reference).trim().toLowerCase();
    if (a === b || a.includes(b) || b.includes(a)) return "agree";
    return "mismatch";
  }
  // release_year, edition_size, is_limited_edition
  return tool === reference ? "agree" : "mismatch";
}

function diffReferenceFields(tool, reference) {
  const out = {};
  for (const field of REFERENCE_ALL_FIELDS) {
    const t = tool[field];
    const r = reference[field];
    const tP = _refPresent(t);
    const rP = _refPresent(r);
    let status;
    if (!tP && !rP) {
      status = "muted";
    } else if (tP !== rP) {
      status = "one_side_only";
    } else {
      status = _refCompareField(field, t, r);
    }
    out[field] = { field, status, tool: t, reference: r };
  }
  return out;
}

function _flattenToolSide(pin) {
  const extraction = pin.extraction || {};
  const topMatch = (pin.catalog_matches || [])
    .slice()
    .sort((a, b) => b.match_confidence - a.match_confidence)[0];
  const entry = topMatch || {};
  return {
    characters: extraction.characters || [],
    franchise: extraction.franchise || null,
    canonical_name: pin.no_catalog_match ? null : (entry.canonical_name || null),
    series_or_collection: pin.no_catalog_match ? null : (entry.series_or_collection || null),
    release_year: pin.no_catalog_match ? null : (entry.release_year ?? null),
    edition_size: pin.no_catalog_match ? null : (entry.edition_size ?? null),
    is_limited_edition: extraction.edition_size != null ? true : null,
    event: null,
    pin_type: extraction.pin_type || null,
    exclusive_source: null,
  };
}

function _formatRefValue(value) {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

const _REF_STATUS_ICON = {
  agree: "✓",
  mismatch: "✗",
  one_side_only: "⚠",
  muted: "·",
};

function renderReferenceLabel(pin) {
  if (!pin.reference_source) return "";

  const parsed = pin.reference_parsed_fields || {};
  const tool = _flattenToolSide(pin);
  const diff = diffReferenceFields(tool, parsed);

  const hasMismatch = Object.values(diff).some((d) => d.status === "mismatch");
  const openAttr = hasMismatch ? " open" : "";
  const rawTitle = pin.reference_raw_title || "";
  const ebayLink = pin.reference_url
    ? `<a class="ref-ebay-link" href="${escapeHtml(pin.reference_url)}" target="_blank" rel="noopener">↗ eBay</a>`
    : "";

  const rows = REFERENCE_ALL_FIELDS.map((field) => {
    const d = diff[field];
    const cls = `diff-row diff-${d.status.replace("_", "-")}`;
    const icon = _REF_STATUS_ICON[d.status];
    return `
      <tr class="${cls}">
        <th>${escapeHtml(REFERENCE_FIELD_LABELS[field])}</th>
        <td>${escapeHtml(_formatRefValue(d.reference))}</td>
        <td><span class="diff-status diff-${d.status.replace("_", "-")}">${icon}</span>${escapeHtml(_formatRefValue(d.tool))}</td>
      </tr>`;
  }).join("");

  return `
    <details class="reference-section"${openAttr}>
      <summary>
        <span>Reference label (${escapeHtml(pin.reference_source)})</span>
        ${ebayLink}
      </summary>
      <div class="reference-raw-title">"${escapeHtml(rawTitle)}"</div>
      <table class="reference-diff-table">
        <thead>
          <tr><th></th><th>Parsed reference</th><th>Tool extraction</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </details>`;
}
```

- [ ] **Step 2: Wire `renderReferenceLabel` into `renderDetail`**

Edit `static/review.js`. Replace the existing `renderDetail` function (lines 222–235) with:

```javascript
function renderDetail(pin) {
  const container = document.getElementById("detail-content");
  delete container.dataset.visualSelectedId;
  container.innerHTML = `
    ${renderDetailHeader(pin)}
    <div class="detail-section" id="match-section">${renderMatchSection(pin)}</div>
    <div class="detail-section" id="extraction-section">${renderExtractionSection(pin)}</div>
    <div class="detail-section" id="draft-section">${renderDraftSection(pin)}</div>
    ${renderReferenceLabel(pin)}
  `;
  _applyBackgrounds(container);
  wireMatchSection(pin);
  wireExtractionSection(pin);
  wireDraftSection(pin);
}
```

- [ ] **Step 3: Create the manual smoke checklist**

Create `docs/superpowers/manual/2026-04-11-reference-label-smoke.md`:

```markdown
# Reference Label Overlay — Manual Smoke Checklist

Scope: verify the new reference-label diff overlay renders correctly inside the existing human review UI. Run after any change to `static/review.js`, `static/style.css`, or `src/routes/pins.py:_pin_to_dict`.

## Setup

1. Ensure prod eBay keys and `ANTHROPIC_API_KEY` are set in `disney-pin-assistant/.env`.
2. Run `python scripts/import_ebay_seller.py --seller pins-n-things --batch-name pnt-smoke --max 5`.
3. Wait for the run to report `processing: enqueued` and the orchestrator to finish (tail the server log).
4. Open `http://localhost:8000/queue/pnt-smoke` in a browser.

## Checks

- [ ] The reference section appears **only** for pins that came from the ingest script. Any other batch shows no new section.
- [ ] On at least one pin, all diff rows show `✓` and the section is **collapsed** by default.
- [ ] On at least one pin, the section is **expanded** by default because it contains a `✗`.
- [ ] The raw title under the section header matches the actual eBay listing title.
- [ ] Clicking `↗ eBay` opens the real listing in a new tab.
- [ ] Characters render as a comma-separated list, booleans as `yes/no`, numeric fields as digits.
- [ ] No console errors in the browser devtools.
- [ ] Regression: normal uploads (manually uploaded pins) still render cleanly with no empty reference section.
```

- [ ] **Step 4: Smoke-test locally**

Run: `cd disney-pin-assistant && uv run pytest -x`

Expected: all existing tests still pass (no Python code changed in this task except the CSS file, which pytest doesn't care about).

Start the server: `cd disney-pin-assistant && uv run uvicorn src.main:app --reload`

Manually exercise the checklist above if production eBay keys are available; otherwise seed the DB with a hand-crafted pin that has `reference_source='ebay_browse'` set and page through to verify the overlay.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/static/review.js \
        disney-pin-assistant/src/templates/review.html \
        docs/superpowers/manual/2026-04-11-reference-label-smoke.md
git commit -m "feat(eval): reference-label diff overlay in review UI"
```

(Note: `review.html` may have no changes if Task 7 Step 1's decision to leave it alone stood. If so, drop it from the `git add` above.)

---

## Task 9: Full-suite verification + end-of-plan sanity check

No new code. Run all tests, confirm the import path works from the CLI, and commit nothing (unless something needs fixing).

- [ ] **Step 1: Run the entire test suite**

Run: `cd disney-pin-assistant && uv run pytest -v`

Expected: every test from tasks 1–6 plus all pre-existing tests pass. If anything fails, fix it in the relevant task's code and add a new commit there, not here.

- [ ] **Step 2: Sanity-check the CLI help output**

Run: `cd disney-pin-assistant && uv run python scripts/import_ebay_seller.py --help`

Expected: argparse prints `--seller`, `--batch-name`, `--max`, `--skip-processing`, `--dry-run` with the descriptions from `build_parser`.

- [ ] **Step 3: Confirm `ensure_reference_label_columns` runs on an existing DB**

If a local `pins.db` exists with the old schema, start the server once:

Run: `cd disney-pin-assistant && uv run uvicorn src.main:app --reload`

Expected: no startup errors. Stop the server. `sqlite3 pins.db "PRAGMA table_info(pins)"` should show the seven new columns.

If no local `pins.db` exists, skip this step — the unit tests in Task 1 already cover the ORM-level contract.

- [ ] **Step 4: Done**

No commit. The plan is complete when all three steps above succeed.

---

## Self-review notes

Scan against the spec:

- ✅ Schema changes (spec §Schema changes) — Task 1.
- ✅ `_pin_to_dict` extension (spec §`_pin_to_dict` extension) — Task 2.
- ✅ Reference label parser (spec §Reference label parser) — Task 3.
- ✅ eBay client extension (spec §Reuse vs. new code) — Task 4 (offset only; the existing file already has `browse_api_seller_search` and `browse_api_item_detail`, so we add the smallest change that unblocks pagination).
- ✅ Diff logic tested in Python (spec §Testing strategy: Unit tests) — Task 5.
- ✅ CLI ingestion (spec §Ingestion component) — Task 6, including idempotent refresh, dry-run, skip-processing, rate-limit behavior (httpx surfaces 401/429/5xx as exceptions, tests exercise the dedupe path).
- ✅ Review UI CSS + HTML scaffold (spec §Review UI diff overlay: Implementation footprint) — Task 7.
- ✅ `renderReferenceLabel` JS with field list mirroring the Python helper — Task 8.
- ✅ Manual smoke checklist (spec §Testing strategy: Integration smoke tests) — Task 8.
- ✅ Prerequisites (production keys, human review UI shipped, `ANTHROPIC_API_KEY`) — called out at the top.

Known deliberate deviations from the spec:

- The spec example migration uses `try/except OperationalError`; this plan uses the `PRAGMA table_info` pattern instead, matching `ensure_review_ui_columns` in `src/database.py`. Same effect, consistent with existing code.
- `reference_ingested_at` is stored as an ISO string rather than a `DateTime` column, matching `created_at`/`updated_at` in the same table.
- No separate `image_download` service module — the CLI inlines a ~10-line `_download_image` helper. YAGNI.
- The plan does not add a "Python mirror of the JS diff logic used as the source of truth" — instead, the Python `reference_diff.py` and the JS `diffReferenceFields` are two implementations of the same contract. The Python one is tested; the JS one is small enough that visual smoke-testing is sufficient. The spec allows this explicitly.
