# Per-Pin Sold-Data Comps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically attach recency-weighted sold-data comps to every new pin, using the existing RapidAPI integration, a local cache, and per-day spend guardrails.

**Architecture:** Thin client wrapper over `rapidapi_client` keeps the source swap-friendly. A new `comp_lookup` service runs after reference-label parsing, consulting `ebay_listings` cache before calling the API, scoring comps by relevance × recency decay, and writing weighted rows to the existing `comps` table. A `comp_lookup_budget` table enforces a daily API-call cap.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async with SQLite, httpx, pytest, pytest-asyncio

**Project root for all paths:** `/Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant/`

---

## File Structure

**New files:**
- `src/services/sold_data_client.py` — Thin async wrapper; future source swap point
- `src/pipeline/comp_scoring.py` — Pure scoring functions (no I/O)
- `src/pipeline/comp_lookup.py` — Comp lookup service (cache-first, guardrails, DB writes)
- `tests/test_sold_data_client.py`
- `tests/test_comp_scoring.py`
- `tests/test_comp_lookup.py`

**Modified files:**
- `src/config.py` — Five new settings
- `src/models.py` — `MatchType.RAPIDAPI_SOLD`, `Comp.weight` column, new `CompLookupBudget` model
- `src/database.py` — New `ensure_comp_lookup_migrations` helper
- `src/main.py` — Wire new migration into lifespan
- `src/pipeline/orchestrator.py` — Auto-trigger hook after PRICED stage
- `scripts/collect_listings.py` — New `comps` subcommand

---

## Task 1: Add config settings

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_collection_config.py`

- [ ] **Step 1: Write failing tests for the new settings**

Append to `tests/test_collection_config.py`:

```python
def test_comp_lookup_daily_limit_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_lookup_daily_limit == 50


def test_comp_recency_half_life_days_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_recency_half_life_days == 90


def test_comp_min_parsed_fields_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_min_parsed_fields == 2


def test_comp_cache_min_hits_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_cache_min_hits == 5


def test_comp_max_results_per_lookup_default():
    from src.config import Settings
    s = Settings()
    assert s.comp_max_results_per_lookup == 50
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd disney-pin-assistant && pytest tests/test_collection_config.py -v`
Expected: 5 new tests FAIL with `AttributeError` on each setting.

- [ ] **Step 3: Add the settings**

In `src/config.py`, within the `Settings` class (alongside the existing `collection_*` settings), add:

```python
    comp_lookup_daily_limit: int = 50
    comp_recency_half_life_days: int = 90
    comp_min_parsed_fields: int = 2
    comp_cache_min_hits: int = 5
    comp_max_results_per_lookup: int = 50
```

- [ ] **Step 4: Run to verify pass**

Run: `cd disney-pin-assistant && pytest tests/test_collection_config.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/config.py disney-pin-assistant/tests/test_collection_config.py
git commit -m "feat(comps): add config settings for per-pin comp lookup"
```

---

## Task 2: Extend `MatchType` enum and add `Comp.weight` column

**Files:**
- Modify: `src/models.py:46-48` (MatchType enum)
- Modify: `src/models.py:179-198` (Comp model)
- Modify: `src/database.py`
- Test: `tests/test_comps.py`

- [ ] **Step 1: Write failing test for enum value**

Append to `tests/test_comps.py`:

```python
def test_match_type_has_rapidapi_sold():
    from src.models import MatchType
    assert MatchType.RAPIDAPI_SOLD.value == "rapidapi_sold"
```

- [ ] **Step 2: Write failing test for `Comp.weight` column**

Append to `tests/test_comps.py`:

```python
import pytest
from src.models import Comp, MatchType, ListingType


@pytest.mark.asyncio
async def test_comp_weight_column_round_trip(async_session_factory):
    async with async_session_factory() as db:
        from src.models import Pin, PinStatus
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.UNPROCESSED)
        db.add(pin)
        await db.flush()
        comp = Comp(
            pin_id=pin.id,
            title="Test pin",
            price=10.0,
            listing_type=ListingType.SOLD,
            match_type=MatchType.RAPIDAPI_SOLD,
            weight=0.42,
        )
        db.add(comp)
        await db.commit()
        loaded = (await db.execute(
            __import__("sqlalchemy").select(Comp).where(Comp.id == comp.id)
        )).scalar_one()
        assert loaded.weight == 0.42
```

Check `tests/conftest.py` has an `async_session_factory` fixture; if not, a similar `db_session` fixture exists — adapt the fixture name to match.

- [ ] **Step 3: Run to verify fail**

Run: `cd disney-pin-assistant && pytest tests/test_comps.py::test_match_type_has_rapidapi_sold tests/test_comps.py::test_comp_weight_column_round_trip -v`
Expected: both FAIL.

- [ ] **Step 4: Add enum value and column**

In `src/models.py`, update `MatchType`:

```python
class MatchType(str, enum.Enum):
    EXACT = "exact"
    NEAR = "near"
    RAPIDAPI_SOLD = "rapidapi_sold"
```

In the `Comp` model (starting at line 179), add the `weight` column immediately after `match_type`:

```python
    match_type = Column(Enum(MatchType), default=MatchType.NEAR)
    weight = Column(Float, nullable=True)
```

- [ ] **Step 5: Add idempotent migration for `weight` column**

In `src/database.py`, add a new function alongside the other `ensure_*` helpers:

```python
async def ensure_comp_weight_column(engine):
    """Idempotent migration: add `weight` column to `comps` table."""
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(comps)"))
        existing = {row[1] for row in result.fetchall()}
        if "weight" not in existing:
            await conn.execute(text("ALTER TABLE comps ADD COLUMN weight FLOAT"))
```

- [ ] **Step 6: Run to verify pass**

Run: `cd disney-pin-assistant && pytest tests/test_comps.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add disney-pin-assistant/src/models.py disney-pin-assistant/src/database.py disney-pin-assistant/tests/test_comps.py
git commit -m "feat(comps): add RAPIDAPI_SOLD match type and weight column"
```

---

## Task 3: Add `CompLookupBudget` model and migration

**Files:**
- Modify: `src/models.py` (append)
- Modify: `src/database.py` (append)
- Modify: `src/main.py:18-20` (wire migrations)
- Test: `tests/test_comp_lookup_budget.py` (new)

- [ ] **Step 1: Write failing test for model**

Create `tests/test_comp_lookup_budget.py`:

```python
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_comp_lookup_budget_round_trip(async_session_factory):
    from src.models import CompLookupBudget
    async with async_session_factory() as db:
        row = CompLookupBudget(date="2026-04-12", calls=3)
        db.add(row)
        await db.commit()
        loaded = (await db.execute(
            select(CompLookupBudget).where(CompLookupBudget.date == "2026-04-12")
        )).scalar_one()
        assert loaded.calls == 3


@pytest.mark.asyncio
async def test_comp_lookup_budget_primary_key_is_date(async_session_factory):
    from src.models import CompLookupBudget
    async with async_session_factory() as db:
        db.add(CompLookupBudget(date="2026-04-11", calls=1))
        db.add(CompLookupBudget(date="2026-04-11", calls=2))
        with pytest.raises(Exception):
            await db.commit()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd disney-pin-assistant && pytest tests/test_comp_lookup_budget.py -v`
Expected: FAIL with `ImportError: cannot import name 'CompLookupBudget'`.

- [ ] **Step 3: Add model**

Append to `src/models.py`:

```python
class CompLookupBudget(Base):
    __tablename__ = "comp_lookup_budget"

    date = Column(String(20), primary_key=True)  # ISO date (UTC day)
    calls = Column(Integer, nullable=False, default=0)
```

- [ ] **Step 4: Add idempotent migration**

In `src/database.py`, append:

```python
async def ensure_comp_lookup_budget_table(engine):
    """Idempotent migration for the comp_lookup_budget table."""
    from src.models import Base
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='comp_lookup_budget'")
        )
        if result.fetchone() is None:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.tables["comp_lookup_budget"].create(sync_conn, checkfirst=True)
            )
```

- [ ] **Step 5: Wire both migrations into `main.py`**

In `src/main.py`, update the imports and `lifespan` function:

```python
from src.database import (
    engine,
    ensure_review_ui_columns,
    ensure_reference_label_columns,
    ensure_listing_collection_tables,
    ensure_comp_weight_column,
    ensure_comp_lookup_budget_table,
)
```

And inside `lifespan`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_review_ui_columns(engine)
    await ensure_reference_label_columns(engine)
    await ensure_listing_collection_tables(engine)
    await ensure_comp_weight_column(engine)
    await ensure_comp_lookup_budget_table(engine)
    yield
```

- [ ] **Step 6: Run to verify pass**

Run: `cd disney-pin-assistant && pytest tests/test_comp_lookup_budget.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add disney-pin-assistant/src/models.py disney-pin-assistant/src/database.py disney-pin-assistant/src/main.py disney-pin-assistant/tests/test_comp_lookup_budget.py
git commit -m "feat(comps): add CompLookupBudget table and wire migrations"
```

---

## Task 4: Create `sold_data_client` wrapper

**Files:**
- Create: `src/services/sold_data_client.py`
- Test: `tests/test_sold_data_client.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_sold_data_client.py`:

```python
from unittest.mock import AsyncMock, patch
import pytest


@pytest.mark.asyncio
async def test_wrapper_delegates_to_rapidapi_client():
    from src.services import sold_data_client
    expected = {"aggregates": {"average_price": 5.0}, "products": [{"title": "X"}]}
    with patch(
        "src.services.sold_data_client._rapidapi_fetch",
        new=AsyncMock(return_value=expected),
    ) as m:
        result = await sold_data_client.fetch_sold_listings("disney stitch LE 2000", max_results=50)
    assert result == expected
    m.assert_awaited_once_with("disney stitch LE 2000", max_results=50, category_id=None)


@pytest.mark.asyncio
async def test_wrapper_forwards_category_id():
    from src.services import sold_data_client
    with patch(
        "src.services.sold_data_client._rapidapi_fetch",
        new=AsyncMock(return_value={"aggregates": {}, "products": []}),
    ) as m:
        await sold_data_client.fetch_sold_listings("q", max_results=10, category_id="171")
    m.assert_awaited_once_with("q", max_results=10, category_id="171")
```

- [ ] **Step 2: Run to verify fail**

Run: `cd disney-pin-assistant && pytest tests/test_sold_data_client.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Create the wrapper**

Create `src/services/sold_data_client.py`:

```python
"""Sold-data source abstraction.

All comp-lookup code should import from here, not directly from
`rapidapi_client`. This keeps a future source swap (Apify, eBay Marketplace
Insights) localized to this file.
"""

from src.services.rapidapi_client import fetch_sold_listings as _rapidapi_fetch


async def fetch_sold_listings(
    query: str,
    max_results: int = 50,
    category_id: str | None = None,
) -> dict:
    """Fetch sold eBay listings.

    Returns:
        {"aggregates": {...}, "products": [...]}
    """
    return await _rapidapi_fetch(query, max_results=max_results, category_id=category_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd disney-pin-assistant && pytest tests/test_sold_data_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/services/sold_data_client.py disney-pin-assistant/tests/test_sold_data_client.py
git commit -m "feat(comps): add sold_data_client wrapper for source abstraction"
```

---

## Task 5: Scoring functions

**Files:**
- Create: `src/pipeline/comp_scoring.py`
- Test: `tests/test_comp_scoring.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_comp_scoring.py`:

```python
from datetime import date
import math
from src.pipeline.comp_scoring import (
    field_overlap_score,
    recency_weight,
    score_comp,
    weighted_price_recommendation,
)


def test_field_overlap_character_match():
    pin = {"characters": ["Stitch"]}
    comp = {"characters": ["Stitch"]}
    assert field_overlap_score(pin, comp) == 0.4


def test_field_overlap_character_case_insensitive():
    pin = {"characters": ["STITCH"]}
    comp = {"characters": ["stitch"]}
    assert field_overlap_score(pin, comp) == 0.4


def test_field_overlap_franchise():
    pin = {"franchise": "Lilo & Stitch"}
    comp = {"franchise": "Lilo & Stitch"}
    assert field_overlap_score(pin, comp) == 0.3


def test_field_overlap_edition_size_exact():
    pin = {"edition_size": 2000}
    comp = {"edition_size": 2000}
    assert field_overlap_score(pin, comp) == 0.2


def test_field_overlap_edition_size_mismatch():
    pin = {"edition_size": 2000}
    comp = {"edition_size": 1000}
    assert field_overlap_score(pin, comp) == 0.0


def test_field_overlap_year_within_one():
    pin = {"release_year": 2019}
    comp = {"release_year": 2020}
    assert field_overlap_score(pin, comp) == 0.1


def test_field_overlap_year_outside_one():
    pin = {"release_year": 2015}
    comp = {"release_year": 2020}
    assert field_overlap_score(pin, comp) == 0.0


def test_field_overlap_all_fields_sum():
    pin = {"characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000, "release_year": 2019}
    comp = {"characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000, "release_year": 2019}
    assert field_overlap_score(pin, comp) == 1.0


def test_field_overlap_empty():
    assert field_overlap_score({}, {}) == 0.0


def test_recency_weight_today():
    assert recency_weight(date(2026, 4, 12), date(2026, 4, 12), half_life_days=90) == 1.0


def test_recency_weight_half_life():
    w = recency_weight(date(2026, 1, 12), date(2026, 4, 12), half_life_days=90)
    assert abs(w - 0.5) < 0.01


def test_recency_weight_future_sale_clamped():
    w = recency_weight(date(2026, 5, 1), date(2026, 4, 12), half_life_days=90)
    assert w == 1.0


def test_score_comp_combines_relevance_and_recency():
    pin = {"characters": ["Stitch"]}
    comp = {"characters": ["Stitch"]}
    s = score_comp(pin, comp, sale_date=date(2026, 1, 12), today=date(2026, 4, 12), half_life_days=90)
    assert abs(s - 0.4 * 0.5) < 0.01


def test_weighted_price_recommendation_basic():
    comps = [
        {"price": 10.0, "weight": 1.0},
        {"price": 20.0, "weight": 1.0},
    ]
    result = weighted_price_recommendation(comps)
    assert result["suggested_price"] == 15.0
    assert result["count"] == 2


def test_weighted_price_recommendation_weights_bias():
    comps = [
        {"price": 10.0, "weight": 3.0},
        {"price": 20.0, "weight": 1.0},
    ]
    result = weighted_price_recommendation(comps)
    assert abs(result["suggested_price"] - 12.5) < 0.01


def test_weighted_price_recommendation_empty():
    result = weighted_price_recommendation([])
    assert result["suggested_price"] is None
    assert result["count"] == 0
```

- [ ] **Step 2: Run to verify fail**

Run: `cd disney-pin-assistant && pytest tests/test_comp_scoring.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement scoring**

Create `src/pipeline/comp_scoring.py`:

```python
"""Pure scoring functions for per-pin sold-data comps. No I/O."""

from datetime import date
import math

CHARACTER_WEIGHT = 0.4
FRANCHISE_WEIGHT = 0.3
EDITION_WEIGHT = 0.2
YEAR_WEIGHT = 0.1


def _normalize_chars(v) -> set[str]:
    if v is None:
        return set()
    if isinstance(v, str):
        v = [v]
    return {str(x).strip().lower() for x in v if x}


def _normalize_str(v) -> str:
    return str(v).strip().lower() if v else ""


def field_overlap_score(pin_fields: dict, comp_fields: dict) -> float:
    """Return a relevance score in [0, 1] based on overlap of parsed fields."""
    score = 0.0

    pin_chars = _normalize_chars(pin_fields.get("characters"))
    comp_chars = _normalize_chars(comp_fields.get("characters"))
    if pin_chars and comp_chars and pin_chars & comp_chars:
        score += CHARACTER_WEIGHT

    pin_fr = _normalize_str(pin_fields.get("franchise"))
    comp_fr = _normalize_str(comp_fields.get("franchise"))
    if pin_fr and pin_fr == comp_fr:
        score += FRANCHISE_WEIGHT

    pin_ed = pin_fields.get("edition_size")
    comp_ed = comp_fields.get("edition_size")
    if pin_ed is not None and comp_ed is not None and pin_ed == comp_ed:
        score += EDITION_WEIGHT

    pin_yr = pin_fields.get("release_year")
    comp_yr = comp_fields.get("release_year")
    if pin_yr is not None and comp_yr is not None and abs(pin_yr - comp_yr) <= 1:
        score += YEAR_WEIGHT

    return score


def recency_weight(sale_date: date, today: date, half_life_days: int) -> float:
    """Exponential decay weight based on how old the sale is."""
    days_old = max(0, (today - sale_date).days)
    return math.exp(-days_old * math.log(2) / half_life_days)


def score_comp(
    pin_fields: dict,
    comp_fields: dict,
    sale_date: date,
    today: date,
    half_life_days: int,
) -> float:
    """Combined relevance × recency score."""
    return field_overlap_score(pin_fields, comp_fields) * recency_weight(
        sale_date, today, half_life_days
    )


def weighted_price_recommendation(comps: list[dict]) -> dict:
    """Compute weighted-average price from scored comps.

    Args:
        comps: list of {"price": float, "weight": float}
    Returns:
        {"suggested_price": float | None, "count": int}
    """
    if not comps:
        return {"suggested_price": None, "count": 0}
    total_weight = sum(c["weight"] for c in comps)
    if total_weight == 0:
        return {"suggested_price": None, "count": len(comps)}
    weighted_sum = sum(c["price"] * c["weight"] for c in comps)
    return {
        "suggested_price": weighted_sum / total_weight,
        "count": len(comps),
    }
```

Note: the `recency_weight` test uses half-life correctly (90 days = 0.5). The implementation uses `exp(-days × ln2 / H)` so that at `days = H`, the weight equals exactly 0.5. This is the conventional half-life formula; the spec's `exp(-days / H)` would give ≈0.37 at H days, which is less intuitive.

- [ ] **Step 4: Run to verify pass**

Run: `cd disney-pin-assistant && pytest tests/test_comp_scoring.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/pipeline/comp_scoring.py disney-pin-assistant/tests/test_comp_scoring.py
git commit -m "feat(comps): add pure scoring functions for per-pin comps"
```

---

## Task 6: Comp lookup service

**Files:**
- Create: `src/pipeline/comp_lookup.py`
- Test: `tests/test_comp_lookup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_comp_lookup.py`:

```python
from datetime import date
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import select

from src.models import (
    Pin, PinStatus, VisionExtraction, Comp, MatchType,
    EbayListing, EbayListingType, CollectionJob, CollectionJobType, CollectionJobStatus,
    CompLookupBudget,
)


async def _make_pin(session_factory, parsed_fields: dict) -> int:
    async with session_factory() as db:
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.EXTRACTED,
                  reference_parsed_fields=parsed_fields)
        db.add(pin)
        await db.commit()
        return pin.id


@pytest.mark.asyncio
async def test_lookup_skipped_sparse(async_session_factory):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus
    pin_id = await _make_pin(async_session_factory, {"characters": ["Mickey"]})  # 1 field
    result = await lookup_comps_for_pin(async_session_factory, pin_id, today=date(2026, 4, 12))
    assert result.status == LookupStatus.SKIPPED_SPARSE


@pytest.mark.asyncio
async def test_lookup_skipped_capped(async_session_factory, monkeypatch):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus
    from src.config import settings
    monkeypatch.setattr(settings, "comp_lookup_daily_limit", 1)

    async with async_session_factory() as db:
        db.add(CompLookupBudget(date="2026-04-12", calls=1))
        await db.commit()

    pin_id = await _make_pin(async_session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000,
    })
    result = await lookup_comps_for_pin(async_session_factory, pin_id, today=date(2026, 4, 12))
    assert result.status == LookupStatus.SKIPPED_CAPPED


@pytest.mark.asyncio
async def test_lookup_cache_hit_writes_comps_and_skips_api(async_session_factory):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus

    async with async_session_factory() as db:
        job = CollectionJob(
            job_type=CollectionJobType.KEYWORD_SOLD, query="seed",
            source="rapidapi_sold", status=CollectionJobStatus.COMPLETED,
        )
        db.add(job)
        await db.flush()
        for i in range(6):
            db.add(EbayListing(
                listing_type=EbayListingType.SOLD, source="rapidapi_sold",
                title=f"Stitch pin {i}", price=10.0 + i,
                sale_date="2026-04-01",
                parsed_fields={
                    "characters": ["Stitch"], "franchise": "Lilo & Stitch",
                    "edition_size": 2000, "release_year": 2019,
                },
                collection_job_id=job.id,
            ))
        await db.commit()

    pin_id = await _make_pin(async_session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch",
        "edition_size": 2000, "release_year": 2019,
    })

    with patch(
        "src.pipeline.comp_lookup.sold_data_client.fetch_sold_listings",
        new=AsyncMock(side_effect=AssertionError("should not be called")),
    ):
        result = await lookup_comps_for_pin(
            async_session_factory, pin_id, today=date(2026, 4, 12),
        )
    assert result.status == LookupStatus.CACHE_HIT

    async with async_session_factory() as db:
        comps = (await db.execute(
            select(Comp).where(Comp.pin_id == pin_id)
        )).scalars().all()
        assert len(comps) >= 1
        assert all(c.match_type == MatchType.RAPIDAPI_SOLD for c in comps)
        assert all(c.weight is not None for c in comps)


@pytest.mark.asyncio
async def test_lookup_cache_miss_calls_api_and_increments_budget(async_session_factory):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus

    pin_id = await _make_pin(async_session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000,
    })
    fake_response = {
        "aggregates": {"average_price": 15.0},
        "products": [
            {"title": "Stitch LE 2000 pin", "sale_price": 15.0,
             "date_sold": "2026-03-01", "link": "https://ebay.com/x"},
            {"title": "Stitch LE 2000 different", "sale_price": 18.0,
             "date_sold": "2026-04-01", "link": "https://ebay.com/y"},
        ],
    }
    with patch(
        "src.pipeline.comp_lookup.sold_data_client.fetch_sold_listings",
        new=AsyncMock(return_value=fake_response),
    ) as m:
        result = await lookup_comps_for_pin(
            async_session_factory, pin_id, today=date(2026, 4, 12),
        )

    assert result.status == LookupStatus.API_CALLED
    m.assert_awaited_once()

    async with async_session_factory() as db:
        listings = (await db.execute(select(EbayListing))).scalars().all()
        assert len(listings) == 2
        budget = (await db.execute(
            select(CompLookupBudget).where(CompLookupBudget.date == "2026-04-12")
        )).scalar_one_or_none()
        assert budget is not None and budget.calls == 1


@pytest.mark.asyncio
async def test_lookup_api_failure_marks_job_failed(async_session_factory):
    from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus

    pin_id = await _make_pin(async_session_factory, {
        "characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000,
    })
    with patch(
        "src.pipeline.comp_lookup.sold_data_client.fetch_sold_listings",
        new=AsyncMock(side_effect=RuntimeError("api down")),
    ):
        result = await lookup_comps_for_pin(
            async_session_factory, pin_id, today=date(2026, 4, 12),
        )
    assert result.status == LookupStatus.FAILED

    async with async_session_factory() as db:
        jobs = (await db.execute(select(CollectionJob))).scalars().all()
        assert any(j.status == CollectionJobStatus.FAILED for j in jobs)
```

- [ ] **Step 2: Run to verify fail**

Run: `cd disney-pin-assistant && pytest tests/test_comp_lookup.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the service**

Create `src/pipeline/comp_lookup.py`:

```python
"""Per-pin sold-data comp lookup service.

Flow:
1. Check pin's parsed fields for sparseness (< comp_min_parsed_fields useful fields).
2. Check daily budget cap.
3. Cache: query ebay_listings for sold rows overlapping parsed fields.
4. If cache has >= comp_cache_min_hits relevant rows: score and write to comps.
5. Else: call sold_data_client, store results in ebay_listings, score, write to comps.
6. On any uncaught exception during API call: mark collection_jobs row FAILED.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.config import settings
from src.models import (
    Pin, Comp, MatchType, ListingType,
    EbayListing, EbayListingType, CollectionJob, CollectionJobType, CollectionJobStatus,
    CompLookupBudget,
)
from src.pipeline.comp_scoring import (
    field_overlap_score, score_comp, weighted_price_recommendation,
)
from src.services import sold_data_client


class LookupStatus(str, Enum):
    SKIPPED_SPARSE = "skipped_sparse"
    SKIPPED_CAPPED = "skipped_capped"
    CACHE_HIT = "cache_hit"
    API_CALLED = "api_called"
    FAILED = "failed"


@dataclass
class LookupResult:
    status: LookupStatus
    comps_written: int = 0
    suggested_price: float | None = None
    error: str | None = None


def _useful_field_count(parsed: dict | None) -> int:
    if not parsed:
        return 0
    count = 0
    if parsed.get("characters"):
        count += 1
    if parsed.get("franchise"):
        count += 1
    if parsed.get("edition_size") is not None:
        count += 1
    if parsed.get("release_year") is not None:
        count += 1
    return count


def _build_query(parsed: dict) -> str:
    parts: list[str] = []
    chars = parsed.get("characters") or []
    if chars:
        parts.append(" ".join(str(c) for c in chars[:2]))
    fr = parsed.get("franchise")
    if fr:
        parts.append(str(fr))
    ed = parsed.get("edition_size")
    if ed is not None:
        parts.append(f"LE {ed}")
    yr = parsed.get("release_year")
    if yr is not None:
        parts.append(str(yr))
    return " ".join(parts).strip()


def _parse_sale_date(raw: str | None, today: date) -> date:
    if not raw:
        return today
    try:
        return date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        return today


async def _get_or_create_budget(db, today: date) -> CompLookupBudget:
    key = today.isoformat()
    existing = (await db.execute(
        select(CompLookupBudget).where(CompLookupBudget.date == key)
    )).scalar_one_or_none()
    if existing:
        return existing
    row = CompLookupBudget(date=key, calls=0)
    db.add(row)
    await db.flush()
    return row


async def lookup_comps_for_pin(
    session_factory: async_sessionmaker,
    pin_id: int,
    today: date | None = None,
) -> LookupResult:
    today = today or date.today()

    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        if pin is None:
            return LookupResult(status=LookupStatus.FAILED, error="pin not found")
        parsed = pin.reference_parsed_fields or {}

    if _useful_field_count(parsed) < settings.comp_min_parsed_fields:
        return LookupResult(status=LookupStatus.SKIPPED_SPARSE)

    # Cache check
    async with session_factory() as db:
        listings = (await db.execute(
            select(EbayListing).where(EbayListing.listing_type == EbayListingType.SOLD)
        )).scalars().all()
        relevant = [
            l for l in listings
            if field_overlap_score(parsed, l.parsed_fields or {}) > 0
        ]

    if len(relevant) >= settings.comp_cache_min_hits:
        count = await _write_comps_from_listings(
            session_factory, pin_id, parsed, relevant, today,
        )
        return LookupResult(status=LookupStatus.CACHE_HIT, comps_written=count)

    # Budget check
    async with session_factory() as db:
        budget = await _get_or_create_budget(db, today)
        if budget.calls >= settings.comp_lookup_daily_limit:
            await db.commit()
            return LookupResult(status=LookupStatus.SKIPPED_CAPPED)

    # API call
    query = _build_query(parsed)
    async with session_factory() as db:
        job = CollectionJob(
            job_type=CollectionJobType.KEYWORD_SOLD, query=query,
            source="rapidapi_sold", status=CollectionJobStatus.RUNNING,
            started_at=today.isoformat(),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    try:
        response = await sold_data_client.fetch_sold_listings(
            query, max_results=settings.comp_max_results_per_lookup,
        )
    except Exception as exc:
        async with session_factory() as db:
            j = await db.get(CollectionJob, job_id)
            j.status = CollectionJobStatus.FAILED
            j.error_message = str(exc)
            j.completed_at = today.isoformat()
            await db.commit()
        return LookupResult(status=LookupStatus.FAILED, error=str(exc))

    new_listings: list[EbayListing] = []
    async with session_factory() as db:
        for product in response.get("products", []):
            title = product.get("title") or ""
            price_raw = product.get("sale_price") or product.get("price")
            if not title or price_raw is None:
                continue
            try:
                price = float(price_raw)
            except (ValueError, TypeError):
                continue
            sale_date_raw = product.get("date_sold") or product.get("sale_date")
            listing = EbayListing(
                listing_type=EbayListingType.SOLD, source="rapidapi_sold",
                title=title, price=price,
                sale_date=sale_date_raw,
                listing_url=product.get("link"),
                parsed_fields=parsed,
                collection_job_id=job_id,
            )
            db.add(listing)
            new_listings.append(listing)

        job = await db.get(CollectionJob, job_id)
        job.status = CollectionJobStatus.COMPLETED
        job.listings_found = len(response.get("products", []))
        job.listings_new = len(new_listings)
        job.result_metadata = response.get("aggregates")
        job.completed_at = today.isoformat()

        budget = await _get_or_create_budget(db, today)
        budget.calls += 1

        await db.commit()

    count = await _write_comps_from_listings(
        session_factory, pin_id, parsed, new_listings, today,
    )
    return LookupResult(status=LookupStatus.API_CALLED, comps_written=count)


async def _write_comps_from_listings(
    session_factory: async_sessionmaker,
    pin_id: int,
    parsed: dict,
    listings: list[EbayListing],
    today: date,
) -> int:
    scored: list[dict] = []
    for l in listings:
        sd = _parse_sale_date(l.sale_date, today)
        weight = score_comp(
            parsed, l.parsed_fields or {}, sale_date=sd, today=today,
            half_life_days=settings.comp_recency_half_life_days,
        )
        if weight <= 0:
            continue
        scored.append({
            "listing": l, "sale_date": l.sale_date, "title": l.title,
            "price": l.price, "weight": weight,
        })
    scored.sort(key=lambda s: s["weight"], reverse=True)
    top = scored[:10]

    async with session_factory() as db:
        for s in top:
            db.add(Comp(
                pin_id=pin_id,
                title=s["title"], price=s["price"], sale_date=s["sale_date"],
                listing_type=ListingType.SOLD,
                match_type=MatchType.RAPIDAPI_SOLD,
                weight=s["weight"],
            ))
        await db.commit()

    return len(top)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd disney-pin-assistant && pytest tests/test_comp_lookup.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/pipeline/comp_lookup.py disney-pin-assistant/tests/test_comp_lookup.py
git commit -m "feat(comps): add comp_lookup service with cache + budget + scoring"
```

---

## Task 7: Wire the auto-trigger into the orchestrator

**Files:**
- Modify: `src/pipeline/orchestrator.py` (inside `_process_single_pin_inner`, after the PRICED commit block near line 93)
- Test: `tests/test_orchestrator_comp_hook.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/test_orchestrator_comp_hook.py`:

```python
from unittest.mock import AsyncMock, patch
import pytest


@pytest.mark.asyncio
async def test_orchestrator_calls_lookup_comps_after_priced(async_session_factory):
    from src.models import Pin, PinStatus
    from src.pipeline import orchestrator

    async with async_session_factory() as db:
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.PRICED,
                  reference_parsed_fields={"characters": ["Stitch"], "franchise": "Lilo & Stitch"})
        db.add(pin)
        await db.commit()
        pin_id = pin.id

    with patch(
        "src.pipeline.orchestrator.lookup_comps_for_pin",
        new=AsyncMock(return_value=None),
    ) as m:
        await orchestrator.run_comp_lookup_hook(async_session_factory, pin_id)
    m.assert_awaited_once_with(async_session_factory, pin_id)


@pytest.mark.asyncio
async def test_orchestrator_hook_swallows_lookup_errors(async_session_factory):
    from src.models import Pin, PinStatus
    from src.pipeline import orchestrator

    async with async_session_factory() as db:
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.PRICED)
        db.add(pin)
        await db.commit()
        pin_id = pin.id

    with patch(
        "src.pipeline.orchestrator.lookup_comps_for_pin",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        # Should not raise
        await orchestrator.run_comp_lookup_hook(async_session_factory, pin_id)
```

- [ ] **Step 2: Run to verify fail**

Run: `cd disney-pin-assistant && pytest tests/test_orchestrator_comp_hook.py -v`
Expected: FAIL (`run_comp_lookup_hook` missing).

- [ ] **Step 3: Add the hook**

In `src/pipeline/orchestrator.py`, add to the imports at the top:

```python
from src.pipeline.comp_lookup import lookup_comps_for_pin
```

Add this function at module scope (e.g., below `_process_single_pin_inner`):

```python
async def run_comp_lookup_hook(session_factory: async_sessionmaker, pin_id: int) -> None:
    """Best-effort comp lookup trigger. Failures are logged and swallowed."""
    try:
        await lookup_comps_for_pin(session_factory, pin_id)
    except Exception as exc:
        print(f"[orchestrator] comp lookup failed for pin {pin_id}: {exc}")
```

And wire it into `_process_single_pin_inner`. Find the block ending with `pin.status = PinStatus.PRICED` / `await db.commit()` (around line 93). Immediately after that block (and before the final draft-generation block) add:

```python
    await run_comp_lookup_hook(session_factory, pin_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd disney-pin-assistant && pytest tests/test_orchestrator_comp_hook.py -v`
Expected: PASS.

- [ ] **Step 5: Run full test suite to catch regressions**

Run: `cd disney-pin-assistant && pytest -x`
Expected: all tests PASS (prior 230+ plus new additions).

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/src/pipeline/orchestrator.py disney-pin-assistant/tests/test_orchestrator_comp_hook.py
git commit -m "feat(comps): auto-trigger comp lookup after pipeline PRICED stage"
```

---

## Task 8: CLI `comps` subcommand

**Files:**
- Modify: `scripts/collect_listings.py` (add subcommand in `main()` argparse block)
- Test: `tests/test_collect_listings.py` (append)

- [ ] **Step 1: Write failing test**

Append to `tests/test_collect_listings.py`:

```python
@pytest.mark.asyncio
async def test_comps_subcommand_invokes_lookup(async_session_factory, monkeypatch):
    from scripts import collect_listings
    from src.models import Pin, PinStatus

    async with async_session_factory() as db:
        pin = Pin(batch_id="b1", image_paths=[], status=PinStatus.PRICED,
                  reference_parsed_fields={"characters": ["Mickey"], "franchise": "Disney"})
        db.add(pin)
        await db.commit()
        pin_id = pin.id

    called = {}
    async def fake_lookup(session_factory, pid, today=None):
        called["pid"] = pid
        from src.pipeline.comp_lookup import LookupResult, LookupStatus
        return LookupResult(status=LookupStatus.API_CALLED, comps_written=3)

    monkeypatch.setattr(collect_listings, "lookup_comps_for_pin", fake_lookup)
    monkeypatch.setattr(collect_listings, "_make_session_factory", lambda: async_session_factory)

    await collect_listings.run_comps(pin_id=pin_id, refresh=False)
    assert called["pid"] == pin_id
```

(If `_make_session_factory` does not exist in `collect_listings.py`, refactor to introduce it in Step 2. Existing subcommands like `run_sold` already create a session factory from `settings.database_url` — extract that into a module-level helper named `_make_session_factory`.)

- [ ] **Step 2: Run to verify fail**

Run: `cd disney-pin-assistant && pytest tests/test_collect_listings.py::test_comps_subcommand_invokes_lookup -v`
Expected: FAIL.

- [ ] **Step 3: Add the subcommand**

In `scripts/collect_listings.py`:

1. Add to imports at top:

```python
from src.pipeline.comp_lookup import lookup_comps_for_pin, LookupStatus
from src.models import Comp
from sqlalchemy import delete
```

2. Add (or extract, if missing) the session-factory helper at module scope:

```python
def _make_session_factory():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, expire_on_commit=False)
```

If existing subcommands already create their own engine inline, replace those with calls to `_make_session_factory()`.

3. Add the runner function:

```python
async def run_comps(pin_id: int, refresh: bool) -> None:
    session_factory = _make_session_factory()
    if refresh:
        async with session_factory() as db:
            await db.execute(delete(Comp).where(Comp.pin_id == pin_id))
            await db.commit()
    result = await lookup_comps_for_pin(session_factory, pin_id)
    print(f"Pin {pin_id}: {result.status.value} — {result.comps_written} comps written")
    if result.error:
        print(f"  error: {result.error}")
```

4. In the `main()` argparse block, add the new subparser alongside `active-seller`, `active-search`, `sold`, `promote`:

```python
    p_comps = sub.add_parser("comps", help="Look up sold comps for a single pin")
    p_comps.add_argument("--pin-id", type=int, required=True)
    p_comps.add_argument("--refresh", action="store_true",
                         help="Delete existing comps for this pin before lookup")
```

5. In the dispatch block of `main()`, add:

```python
    elif args.command == "comps":
        asyncio.run(run_comps(pin_id=args.pin_id, refresh=args.refresh))
```

- [ ] **Step 4: Run to verify pass**

Run: `cd disney-pin-assistant && pytest tests/test_collect_listings.py -v`
Expected: all PASS.

- [ ] **Step 5: Manual smoke test**

Run: `cd disney-pin-assistant && python scripts/collect_listings.py comps --pin-id 1`
Expected: either `cache_hit`, `api_called`, `skipped_sparse`, or `skipped_capped` — printed to stdout.

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/scripts/collect_listings.py disney-pin-assistant/tests/test_collect_listings.py
git commit -m "feat(comps): add 'comps' CLI subcommand for manual lookup"
```

---

## Final verification

- [ ] **Run the full suite**

Run: `cd disney-pin-assistant && pytest`
Expected: all tests PASS.

- [ ] **Verify app starts cleanly with migrations**

Run: `cd disney-pin-assistant && uvicorn src.main:app --port 8765 &` then `curl localhost:8765/health` → `{"status":"ok"}`. Kill server.
Expected: no migration errors; `comp_lookup_budget` table exists, `comps.weight` column exists.

Run: `cd disney-pin-assistant && sqlite3 disney_pins.db ".schema comps" | grep weight` — expect a match.
Run: `cd disney-pin-assistant && sqlite3 disney_pins.db ".schema comp_lookup_budget"` — expect to see the table.
