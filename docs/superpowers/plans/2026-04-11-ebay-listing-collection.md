# eBay Listing Collection System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a formalized system for collecting active and sold eBay listings into a dedicated `ebay_listings` table, with job tracking, raw response archival, RapidAPI sold-data integration, and a promote-to-pins bridge.

**Architecture:** Two new SQLAlchemy models (`EbayListing`, `CollectionJob`) in the existing SQLite database. A single CLI script (`scripts/collect_listings.py`) with subcommands for active-seller, active-search, sold, and promote. Raw API responses archived to `data/raw/` on disk. RapidAPI client for sold listings in `src/services/rapidapi_client.py`.

**Tech Stack:** Python 3.12, SQLAlchemy (async), httpx, argparse (subparsers), pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-04-11-ebay-listing-collection-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/models.py` | Modify | Add `EbayListing`, `CollectionJob` models + new enums |
| `src/config.py` | Modify | Add `rapidapi_key`, `rapidapi_sold_delay_sec`, `collection_data_dir`, `collection_parse_labels` |
| `src/database.py` | Modify | Add `ensure_listing_collection_tables()` migration |
| `src/services/rapidapi_client.py` | Create | RapidAPI sold-listing client |
| `src/services/ebay_client.py` | No change | Already has `browse_api_seller_search`, `browse_api_search`, `browse_api_item_detail` |
| `src/pipeline/reference_label.py` | No change | Already has `parse_listing_label` |
| `scripts/collect_listings.py` | Create | CLI entry point with subcommands |
| `tests/test_collection_models.py` | Create | Model + enum tests |
| `tests/test_rapidapi_client.py` | Create | RapidAPI client tests |
| `tests/test_collect_listings.py` | Create | CLI integration tests |
| `.gitignore` | Modify | Add `data/` |

---

### Task 1: Models and Enums

**Files:**
- Modify: `disney-pin-assistant/src/models.py`
- Create: `disney-pin-assistant/tests/test_collection_models.py`

- [ ] **Step 1: Write the failing test for new enums and models**

Create `tests/test_collection_models.py`:

```python
import pytest
from sqlalchemy import select
from src.models import (
    EbayListing,
    CollectionJob,
    EbayListingType,
    CollectionJobType,
    CollectionJobStatus,
)


def test_ebay_listing_type_enum_values():
    assert EbayListingType.ACTIVE.value == "active"
    assert EbayListingType.SOLD.value == "sold"


def test_collection_job_type_enum_values():
    assert CollectionJobType.SELLER_ACTIVE.value == "seller_active"
    assert CollectionJobType.KEYWORD_ACTIVE.value == "keyword_active"
    assert CollectionJobType.KEYWORD_SOLD.value == "keyword_sold"


def test_collection_job_status_enum_values():
    assert CollectionJobStatus.PENDING.value == "pending"
    assert CollectionJobStatus.RUNNING.value == "running"
    assert CollectionJobStatus.COMPLETED.value == "completed"
    assert CollectionJobStatus.FAILED.value == "failed"


@pytest.mark.asyncio
async def test_collection_job_round_trip(db_session):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE,
        query="pins-n-things",
        source="browse_api",
        status=CollectionJobStatus.PENDING,
    )
    db_session.add(job)
    await db_session.commit()

    result = await db_session.execute(select(CollectionJob))
    row = result.scalars().first()
    assert row is not None
    assert row.query == "pins-n-things"
    assert row.job_type == CollectionJobType.SELLER_ACTIVE
    assert row.status == CollectionJobStatus.PENDING
    assert row.listings_found == 0
    assert row.listings_new == 0


@pytest.mark.asyncio
async def test_ebay_listing_round_trip(db_session):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE,
        query="test",
        source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing = EbayListing(
        listing_type=EbayListingType.ACTIVE,
        source="browse_api",
        ebay_item_id="v1|123|0",
        title="Disney Stitch Pin LE 500",
        price=24.99,
        seller="pins-n-things",
        collection_job_id=job.id,
    )
    db_session.add(listing)
    await db_session.commit()

    result = await db_session.execute(select(EbayListing))
    row = result.scalars().first()
    assert row is not None
    assert row.title == "Disney Stitch Pin LE 500"
    assert row.price == 24.99
    assert row.listing_type == EbayListingType.ACTIVE
    assert row.ebay_item_id == "v1|123|0"
    assert row.collection_job_id == job.id
    assert row.currency == "USD"


@pytest.mark.asyncio
async def test_ebay_listing_relationship_to_job(db_session):
    job = CollectionJob(
        job_type=CollectionJobType.KEYWORD_SOLD,
        query="disney pin",
        source="rapidapi_sold",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing = EbayListing(
        listing_type=EbayListingType.SOLD,
        source="rapidapi_sold",
        title="Maleficent Pin",
        price=15.00,
        sale_date="2026-03-15",
        collection_job_id=job.id,
    )
    db_session.add(listing)
    await db_session.commit()

    await db_session.refresh(job, attribute_names=["listings"])
    assert len(job.listings) == 1
    assert job.listings[0].title == "Maleficent Pin"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collection_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'EbayListing'`

- [ ] **Step 3: Add enums and models to `src/models.py`**

Add these enums after the existing `ExportStatus` enum (around line 52):

```python
class EbayListingType(str, enum.Enum):
    ACTIVE = "active"
    SOLD = "sold"


class CollectionJobType(str, enum.Enum):
    SELLER_ACTIVE = "seller_active"
    KEYWORD_ACTIVE = "keyword_active"
    KEYWORD_SOLD = "keyword_sold"


class CollectionJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
```

Add these models after the `ListingDraft` class (at end of file):

```python
class CollectionJob(Base):
    __tablename__ = "collection_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(Enum(CollectionJobType), nullable=False)
    query = Column(String(500), nullable=False)
    category_id = Column(String(50), nullable=True)
    source = Column(String(50), nullable=False)
    status = Column(Enum(CollectionJobStatus), nullable=False, default=CollectionJobStatus.PENDING)
    listings_found = Column(Integer, default=0)
    listings_new = Column(Integer, default=0)
    result_metadata = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(String, nullable=True)
    completed_at = Column(String, nullable=True)
    created_at = Column(String, default=lambda: _utcnow().isoformat())

    # Relationships
    listings = relationship("EbayListing", back_populates="collection_job")


class EbayListing(Base):
    __tablename__ = "ebay_listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_type = Column(Enum(EbayListingType), nullable=False)
    source = Column(String(50), nullable=False)
    ebay_item_id = Column(String(100), nullable=True, unique=True)
    title = Column(String(500), nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    sale_date = Column(String(20), nullable=True)
    seller = Column(String(200), nullable=True)
    category = Column(String(200), nullable=True)
    condition = Column(String(50), nullable=True)
    image_url = Column(String(500), nullable=True)
    local_image_path = Column(String(500), nullable=True)
    listing_url = Column(String(500), nullable=True)
    parsed_fields = Column(JSON, nullable=True)
    collection_job_id = Column(Integer, ForeignKey("collection_jobs.id"), nullable=False)
    created_at = Column(String, default=lambda: _utcnow().isoformat())
    updated_at = Column(String, default=lambda: _utcnow().isoformat(), onupdate=lambda: _utcnow().isoformat())

    # Relationships
    collection_job = relationship("CollectionJob", back_populates="listings")
```

Note: The existing `ListingType` enum (line 41) is used by the `Comp` model. Our new `EbayListingType` is separate — same values but different enum to avoid coupling.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collection_models.py -v`
Expected: PASS — all 7 tests green

- [ ] **Step 5: Run full test suite for regressions**

Run: `cd disney-pin-assistant && python -m pytest --tb=short -q`
Expected: All existing tests still pass (207+)

- [ ] **Step 6: Commit**

```bash
git add src/models.py tests/test_collection_models.py
git commit -m "feat: add EbayListing and CollectionJob models with enums"
```

---

### Task 2: Configuration Settings

**Files:**
- Modify: `disney-pin-assistant/src/config.py`
- Create: `disney-pin-assistant/tests/test_collection_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_collection_config.py`:

```python
from src.config import Settings


def test_rapidapi_key_defaults_to_empty():
    s = Settings(anthropic_api_key="x", _env_file=None)
    assert s.rapidapi_key == ""


def test_rapidapi_sold_delay_defaults():
    s = Settings(anthropic_api_key="x", _env_file=None)
    assert s.rapidapi_sold_delay_sec == 2.0


def test_collection_data_dir_defaults():
    s = Settings(anthropic_api_key="x", _env_file=None)
    assert str(s.collection_data_dir) == "data"


def test_collection_parse_labels_defaults_true():
    s = Settings(anthropic_api_key="x", _env_file=None)
    assert s.collection_parse_labels is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collection_config.py -v`
Expected: FAIL — `ValidationError` (unknown fields)

- [ ] **Step 3: Add settings to `src/config.py`**

Add four new fields to the `Settings` class, after `max_concurrent_processing`:

```python
    rapidapi_key: str = ""
    rapidapi_sold_delay_sec: float = 2.0
    collection_data_dir: Path = Path("data")
    collection_parse_labels: bool = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collection_config.py -v`
Expected: PASS — all 4 tests green

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_collection_config.py
git commit -m "feat: add RapidAPI and collection config settings"
```

---

### Task 3: Database Migration

**Files:**
- Modify: `disney-pin-assistant/src/database.py`
- Modify: `disney-pin-assistant/.gitignore`

- [ ] **Step 1: Add idempotent migration function to `src/database.py`**

Add after the existing `ensure_reference_label_columns` function:

```python
async def ensure_listing_collection_tables(engine):
    """Idempotent migration for ebay_listings and collection_jobs tables."""
    from src.models import Base
    async with engine.begin() as conn:
        # Check if tables exist; create only if missing
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='collection_jobs'")
        )
        if result.fetchone() is None:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.tables["collection_jobs"].create(sync_conn, checkfirst=True)
            )
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='ebay_listings'")
        )
        if result.fetchone() is None:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.tables["ebay_listings"].create(sync_conn, checkfirst=True)
            )
```

- [ ] **Step 2: Add `data/` to `.gitignore`**

Append to `disney-pin-assistant/.gitignore`:

```
# Listing collection data (raw responses + images)
data/
```

- [ ] **Step 3: Verify migration is idempotent**

Run from `disney-pin-assistant/`:

```bash
python -c "
import asyncio
from src.database import engine, ensure_listing_collection_tables
async def main():
    await ensure_listing_collection_tables(engine)
    await ensure_listing_collection_tables(engine)  # second call must not fail
    print('OK: migration is idempotent')
asyncio.run(main())
"
```

Expected: `OK: migration is idempotent`

- [ ] **Step 4: Commit**

```bash
git add src/database.py .gitignore
git commit -m "feat: add idempotent migration for listing collection tables"
```

---

### Task 4: RapidAPI Client

**Files:**
- Create: `disney-pin-assistant/src/services/rapidapi_client.py`
- Create: `disney-pin-assistant/tests/test_rapidapi_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rapidapi_client.py`:

```python
import json
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from src.services.rapidapi_client import fetch_sold_listings


def _mock_response(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_fetch_sold_returns_products_and_aggregates():
    api_response = {
        "average_price": 25.50,
        "median_price": 24.00,
        "min_price": 10.00,
        "max_price": 45.00,
        "results": 3,
        "products": [
            {"title": "Stitch LE 500", "sale_price": "25.00", "date_sold": "Mar 10, 2026", "link": "https://ebay.com/1"},
            {"title": "Stitch LE 500", "sale_price": "24.00", "date_sold": "Mar 08, 2026", "link": "https://ebay.com/2"},
            {"title": "Stitch Pin", "sale_price": "27.50", "date_sold": "Mar 05, 2026", "link": "https://ebay.com/3"},
        ],
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(api_response))

    with patch("src.services.rapidapi_client.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.rapidapi_client.settings") as mock_settings:
            mock_settings.rapidapi_key = "test-key"
            result = await fetch_sold_listings("Stitch LE 500", max_results=240)

    assert result["aggregates"]["average_price"] == 25.50
    assert result["aggregates"]["median_price"] == 24.00
    assert len(result["products"]) == 3
    assert result["products"][0]["title"] == "Stitch LE 500"
    assert result["products"][0]["sale_price"] == "25.00"
    assert result["products"][0]["date_sold"] == "Mar 10, 2026"
    assert result["products"][0]["link"] == "https://ebay.com/1"


@pytest.mark.asyncio
async def test_fetch_sold_passes_category_id():
    api_response = {"average_price": 0, "median_price": 0, "min_price": 0, "max_price": 0, "results": 0, "products": []}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(api_response))

    with patch("src.services.rapidapi_client.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.rapidapi_client.settings") as mock_settings:
            mock_settings.rapidapi_key = "test-key"
            await fetch_sold_listings("pin", max_results=60, category_id="171")

    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert body["category_id"] == "171"


@pytest.mark.asyncio
async def test_fetch_sold_raises_on_missing_key():
    with patch("src.services.rapidapi_client.settings") as mock_settings:
        mock_settings.rapidapi_key = ""
        with pytest.raises(ValueError, match="rapidapi_key"):
            await fetch_sold_listings("test")


@pytest.mark.asyncio
async def test_fetch_sold_handles_empty_products():
    api_response = {"average_price": 0, "median_price": 0, "min_price": 0, "max_price": 0, "results": 0, "products": []}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(api_response))

    with patch("src.services.rapidapi_client.httpx.AsyncClient", return_value=mock_client):
        with patch("src.services.rapidapi_client.settings") as mock_settings:
            mock_settings.rapidapi_key = "test-key"
            result = await fetch_sold_listings("obscure pin")

    assert result["products"] == []
    assert result["aggregates"]["results"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_rapidapi_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.rapidapi_client'`

- [ ] **Step 3: Implement the RapidAPI client**

Create `src/services/rapidapi_client.py`:

```python
"""RapidAPI client for eBay sold/completed listing data.

Uses the "eBay Average Selling Price" endpoint on RapidAPI.
Docs: https://rapidapi.com/rpi4gx/api/ebay-average-selling-price
"""

import httpx
from src.config import settings

_RAPIDAPI_URL = "https://ebay-average-selling-price.p.rapidapi.com/findCompletedItems"
_RAPIDAPI_HOST = "ebay-average-selling-price.p.rapidapi.com"


async def fetch_sold_listings(
    keywords: str,
    max_results: int = 240,
    category_id: str | None = None,
) -> dict:
    """Fetch sold eBay listings from RapidAPI.

    Returns:
        {
            "aggregates": {"average_price": ..., "median_price": ..., ...},
            "products": [{"title": ..., "sale_price": ..., "date_sold": ..., "link": ...}, ...],
        }

    Raises:
        ValueError: if rapidapi_key is not configured.
        httpx.HTTPStatusError: on API errors.
    """
    if not settings.rapidapi_key:
        raise ValueError("rapidapi_key is not configured — set RAPIDAPI_KEY in .env")

    body: dict = {
        "keywords": keywords,
        "max_search_results": str(max_results),
    }
    if category_id:
        body["category_id"] = category_id

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            _RAPIDAPI_URL,
            headers={
                "Content-Type": "application/json",
                "X-RapidAPI-Key": settings.rapidapi_key,
                "X-RapidAPI-Host": _RAPIDAPI_HOST,
            },
            json=body,
        )
        response.raise_for_status()
        data = response.json()

    return {
        "aggregates": {
            "average_price": data.get("average_price"),
            "median_price": data.get("median_price"),
            "min_price": data.get("min_price"),
            "max_price": data.get("max_price"),
            "results": data.get("results", 0),
        },
        "products": data.get("products", []),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_rapidapi_client.py -v`
Expected: PASS — all 4 tests green

- [ ] **Step 5: Commit**

```bash
git add src/services/rapidapi_client.py tests/test_rapidapi_client.py
git commit -m "feat: add RapidAPI sold-listing client"
```

---

### Task 5: Active Seller Collection Logic

**Files:**
- Create: `disney-pin-assistant/scripts/collect_listings.py` (partial — active-seller subcommand)
- Create: `disney-pin-assistant/tests/test_collect_listings.py` (partial — active-seller tests)

This task builds the core collection logic for active seller listings and the CLI skeleton. Later tasks add active-search, sold, and promote subcommands.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collect_listings.py`:

```python
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from sqlalchemy import select

from src.models import EbayListing, CollectionJob, CollectionJobStatus, EbayListingType

# Import the script by path (scripts/ isn't a package).
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "collect_listings",
    Path(__file__).resolve().parents[1] / "scripts" / "collect_listings.py",
)
collect_listings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collect_listings)


def _session_wrapper(session):
    @asynccontextmanager
    async def _cm():
        yield session
    return _cm()


@pytest.mark.asyncio
async def test_active_seller_creates_listings_and_job(db_session, tmp_path):
    summaries = [
        {"itemId": "v1|1|0", "title": "Stitch Pin", "itemWebUrl": "https://ebay.com/1"},
        {"itemId": "v1|2|0", "title": "Goofy Pin LE 500", "itemWebUrl": "https://ebay.com/2"},
    ]

    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return summaries if offset == 0 else []

    async def fake_item_detail(item_id):
        return {
            "itemId": item_id,
            "title": next(s["title"] for s in summaries if s["itemId"] == item_id),
            "description": "test desc",
            "image": {"imageUrl": f"https://cdn/{item_id}.jpg"},
            "price": {"value": "19.99", "currency": "USD"},
            "seller": {"username": "pins-n-things"},
            "condition": "New",
        }

    async def fake_download(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"\xff\xd8\xff\xe0")
        return dest

    async def fake_parse(title, description):
        return {"characters": ["Stitch"] if "Stitch" in title else ["Goofy"]}

    with patch.object(collect_listings, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(collect_listings, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(collect_listings, "_download_image", new=AsyncMock(side_effect=fake_download)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(side_effect=fake_parse)):
        result = await collect_listings.run_active_seller(
            seller="pins-n-things",
            query="disney",
            data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=True,
        )

    assert result["listings_new"] == 2
    assert result["listings_found"] == 2

    # Check job was created
    jobs = (await db_session.execute(select(CollectionJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status == CollectionJobStatus.COMPLETED
    assert jobs[0].listings_new == 2

    # Check listings were created
    listings = (await db_session.execute(select(EbayListing))).scalars().all()
    assert len(listings) == 2
    for listing in listings:
        assert listing.listing_type == EbayListingType.ACTIVE
        assert listing.source == "browse_api"
        assert listing.seller == "pins-n-things"
        assert listing.parsed_fields is not None


@pytest.mark.asyncio
async def test_active_seller_upserts_existing_listing(db_session, tmp_path):
    # Pre-create a job and listing
    job = CollectionJob(
        job_type="seller_active", query="test", source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    existing = EbayListing(
        listing_type=EbayListingType.ACTIVE,
        source="browse_api",
        ebay_item_id="v1|1|0",
        title="Old Title",
        price=10.00,
        seller="pins-n-things",
        collection_job_id=job.id,
    )
    db_session.add(existing)
    await db_session.commit()

    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return [{"itemId": "v1|1|0", "title": "New Title", "itemWebUrl": "https://ebay.com/1"}] if offset == 0 else []

    async def fake_item_detail(item_id):
        return {
            "title": "New Title", "description": None,
            "image": {"imageUrl": "https://cdn/1.jpg"},
            "price": {"value": "29.99", "currency": "USD"},
            "seller": {"username": "pins-n-things"},
        }

    with patch.object(collect_listings, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(collect_listings, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(collect_listings, "_download_image", new=AsyncMock()), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value={})):
        result = await collect_listings.run_active_seller(
            seller="pins-n-things",
            query="disney",
            data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=False,
        )

    assert result["listings_new"] == 0
    assert result["listings_updated"] == 1

    await db_session.refresh(existing)
    assert existing.title == "New Title"
    assert existing.price == 29.99


@pytest.mark.asyncio
async def test_active_seller_archives_raw_response(db_session, tmp_path):
    async def fake_seller_search(seller, query="disney", limit=50, offset=0):
        return [{"itemId": "v1|1|0", "title": "Pin", "itemWebUrl": "https://ebay.com/1"}] if offset == 0 else []

    async def fake_item_detail(item_id):
        return {"title": "Pin", "image": {"imageUrl": "https://cdn/1.jpg"}, "price": {"value": "5.00"}, "seller": {"username": "test"}}

    async def fake_download(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"\xff\xd8")
        return dest

    with patch.object(collect_listings, "browse_api_seller_search", new=AsyncMock(side_effect=fake_seller_search)), \
         patch.object(collect_listings, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(collect_listings, "_download_image", new=AsyncMock(side_effect=fake_download)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value=None)):
        await collect_listings.run_active_seller(
            seller="test", query="disney", data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=False,
        )

    raw_dir = tmp_path / "raw" / "browse_api"
    json_files = list(raw_dir.rglob("*.json"))
    assert len(json_files) == 1
    data = json.loads(json_files[0].read_text())
    assert isinstance(data, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collect_listings.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `scripts/collect_listings.py` with active-seller**

Create `scripts/collect_listings.py`:

```python
"""Collect eBay listings into the ebay_listings table.

Usage:
    python scripts/collect_listings.py active-seller --seller pins-n-things
    python scripts/collect_listings.py active-search --query "disney pin"
    python scripts/collect_listings.py sold --query "disney pin LE"
    python scripts/collect_listings.py promote --job-id 1 --batch-name my-batch
"""

import argparse
import asyncio
import json
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import settings
from src.database import async_session
from src.models import (
    CollectionJob,
    CollectionJobStatus,
    CollectionJobType,
    EbayListing,
    EbayListingType,
)
from src.pipeline.reference_label import parse_listing_label
from src.services.ebay_client import (
    browse_api_item_detail,
    browse_api_search,
    browse_api_seller_search,
)

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


def _extract_price(detail: dict) -> float | None:
    price = detail.get("price") or {}
    if isinstance(price, dict) and price.get("value"):
        try:
            return float(price["value"])
        except (ValueError, TypeError):
            return None
    return None


@asynccontextmanager
async def _default_session_factory():
    async with async_session() as session:
        yield session


async def run_active_seller(
    seller: str,
    query: str = "disney",
    data_dir: Path = Path("data"),
    session_factory: Callable = _default_session_factory,
    parse_labels: bool = True,
) -> dict:
    """Collect active listings from a specific seller."""
    result = {"listings_found": 0, "listings_new": 0, "listings_updated": 0, "errors": 0}

    # 1. Paginate through seller listings
    all_summaries: list[dict] = []
    offset = 0
    while True:
        page = await browse_api_seller_search(
            seller=seller, query=query, limit=PAGE_SIZE, offset=offset,
        )
        if not page:
            break
        all_summaries.extend(page)
        offset += PAGE_SIZE
        if len(page) < PAGE_SIZE:
            break

    result["listings_found"] = len(all_summaries)

    async with session_factory() as db:
        # 2. Create job
        job = CollectionJob(
            job_type=CollectionJobType.SELLER_ACTIVE,
            query=seller,
            source="browse_api",
            status=CollectionJobStatus.RUNNING,
            started_at=_utcnow_iso(),
        )
        db.add(job)
        await db.commit()

        # 3. Load existing listings for dedup
        existing_result = await db.execute(
            select(EbayListing).where(EbayListing.ebay_item_id.isnot(None))
        )
        existing_by_id = {l.ebay_item_id: l for l in existing_result.scalars().all()}

        # 4. Process each listing
        raw_details: list[dict] = []
        for item_summary in all_summaries:
            item_id = item_summary.get("itemId")
            if not item_id:
                continue

            try:
                detail = await browse_api_item_detail(item_id)
            except Exception as exc:
                print(f"[warn] get_item failed for {item_id}: {exc}", file=sys.stderr)
                result["errors"] += 1
                continue

            raw_details.append(detail)

            raw_title = detail.get("title") or item_summary.get("title") or ""
            raw_description = detail.get("description")
            listing_url = detail.get("itemWebUrl") or item_summary.get("itemWebUrl")
            price = _extract_price(detail)
            seller_name = (detail.get("seller") or {}).get("username", seller)
            condition = detail.get("condition")
            image_url = _extract_primary_image_url(detail)

            parsed = None
            if parse_labels:
                try:
                    parsed = await parse_listing_label(raw_title, raw_description)
                except Exception as exc:
                    print(f"[warn] label parser failed for {item_id}: {exc}", file=sys.stderr)

            # Upsert
            existing = existing_by_id.get(item_id)
            if existing is not None:
                existing.title = raw_title
                existing.price = price or existing.price
                existing.listing_url = listing_url
                existing.seller = seller_name
                existing.condition = condition
                existing.image_url = image_url
                if parsed is not None:
                    existing.parsed_fields = parsed
                existing.updated_at = _utcnow_iso()
                result["listings_updated"] += 1
            else:
                # Download image for new listings
                local_image = None
                if image_url:
                    dest = data_dir / "images" / "active" / _safe_filename(item_id)
                    try:
                        await _download_image(image_url, dest)
                        local_image = str(dest)
                    except Exception as exc:
                        print(f"[warn] image download failed for {item_id}: {exc}", file=sys.stderr)
                        result["errors"] += 1

                listing = EbayListing(
                    listing_type=EbayListingType.ACTIVE,
                    source="browse_api",
                    ebay_item_id=item_id,
                    title=raw_title,
                    price=price or 0.0,
                    seller=seller_name,
                    condition=condition,
                    image_url=image_url,
                    local_image_path=local_image,
                    listing_url=listing_url,
                    parsed_fields=parsed,
                    collection_job_id=job.id,
                )
                db.add(listing)
                existing_by_id[item_id] = listing
                result["listings_new"] += 1

        # 5. Archive raw response
        raw_dir = data_dir / "raw" / "browse_api" / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"job_{job.id}.json"
        raw_path.write_text(json.dumps(raw_details, indent=2))

        # 6. Finalize job
        job.listings_found = result["listings_found"]
        job.listings_new = result["listings_new"]
        job.status = CollectionJobStatus.COMPLETED
        job.completed_at = _utcnow_iso()
        await db.commit()

    return result


# ── CLI ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_listings",
        description="Collect eBay listings into the ebay_listings table.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # active-seller
    p_seller = sub.add_parser("active-seller", help="Collect active listings from a seller")
    p_seller.add_argument("--seller", required=True)
    p_seller.add_argument("--query", default="disney")
    p_seller.add_argument("--no-parse", action="store_true", help="Skip label parsing")

    # active-search (Task 6)
    p_search = sub.add_parser("active-search", help="Collect active listings by keyword")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--category", default=None)
    p_search.add_argument("--no-parse", action="store_true")

    # sold (Task 7)
    p_sold = sub.add_parser("sold", help="Collect sold listings via RapidAPI")
    p_sold.add_argument("--query", required=True)
    p_sold.add_argument("--max-results", type=int, default=240, choices=[60, 120, 240])
    p_sold.add_argument("--category", default=None)
    p_sold.add_argument("--no-parse", action="store_true")

    # promote (Task 8)
    p_promote = sub.add_parser("promote", help="Promote listings to pins")
    p_promote.add_argument("--job-id", type=int, default=None)
    p_promote.add_argument("--seller", default=None)
    p_promote.add_argument("--batch-name", required=True, dest="batch_name")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    data_dir = Path(settings.collection_data_dir)

    if args.command == "active-seller":
        result = asyncio.run(run_active_seller(
            seller=args.seller,
            query=args.query,
            data_dir=data_dir,
            parse_labels=not args.no_parse,
        ))
        print(f"Active seller collection complete: {result}")

    elif args.command == "active-search":
        result = asyncio.run(run_active_search(
            query=args.query,
            category=args.category,
            data_dir=data_dir,
            parse_labels=not args.no_parse,
        ))
        print(f"Active search collection complete: {result}")

    elif args.command == "sold":
        result = asyncio.run(run_sold(
            query=args.query,
            max_results=args.max_results,
            category=args.category,
            data_dir=data_dir,
            parse_labels=not args.no_parse,
        ))
        print(f"Sold collection complete: {result}")

    elif args.command == "promote":
        result = asyncio.run(run_promote(
            job_id=args.job_id,
            seller=args.seller,
            batch_name=args.batch_name,
        ))
        print(f"Promote complete: {result}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collect_listings.py -v`
Expected: PASS — all 3 tests green

- [ ] **Step 5: Commit**

```bash
git add scripts/collect_listings.py tests/test_collect_listings.py
git commit -m "feat: add collect_listings CLI with active-seller subcommand"
```

---

### Task 6: Active Search Collection

**Files:**
- Modify: `disney-pin-assistant/scripts/collect_listings.py`
- Modify: `disney-pin-assistant/tests/test_collect_listings.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_collect_listings.py`:

```python
@pytest.mark.asyncio
async def test_active_search_creates_listings(db_session, tmp_path):
    summaries = [
        {"itemId": "v1|10|0", "title": "WDI Pin LE 300", "itemWebUrl": "https://ebay.com/10"},
    ]

    async def fake_search(query, filters=None, limit=50):
        return summaries

    async def fake_item_detail(item_id):
        return {
            "title": "WDI Pin LE 300", "description": None,
            "image": {"imageUrl": "https://cdn/10.jpg"},
            "price": {"value": "45.00", "currency": "USD"},
            "seller": {"username": "some-seller"},
        }

    async def fake_download(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"\xff\xd8")
        return dest

    with patch.object(collect_listings, "browse_api_search", new=AsyncMock(side_effect=fake_search)), \
         patch.object(collect_listings, "browse_api_item_detail", new=AsyncMock(side_effect=fake_item_detail)), \
         patch.object(collect_listings, "_download_image", new=AsyncMock(side_effect=fake_download)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value={"characters": ["WDI"]})):
        result = await collect_listings.run_active_search(
            query="WDI pin",
            data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=True,
        )

    assert result["listings_new"] == 1

    jobs = (await db_session.execute(select(CollectionJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].job_type == CollectionJobType.KEYWORD_ACTIVE

    listings = (await db_session.execute(select(EbayListing))).scalars().all()
    assert len(listings) == 1
    assert listings[0].title == "WDI Pin LE 300"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collect_listings.py::test_active_search_creates_listings -v`
Expected: FAIL — `AttributeError: module 'collect_listings' has no attribute 'run_active_search'`

- [ ] **Step 3: Implement `run_active_search`**

Add to `scripts/collect_listings.py`, after `run_active_seller`:

```python
async def run_active_search(
    query: str,
    category: str | None = None,
    data_dir: Path = Path("data"),
    session_factory: Callable = _default_session_factory,
    parse_labels: bool = True,
) -> dict:
    """Collect active listings from a keyword search."""
    result = {"listings_found": 0, "listings_new": 0, "listings_updated": 0, "errors": 0}

    filters = f"categoryId:{{{category}}}" if category else None
    all_summaries = await browse_api_search(query=query, filters=filters, limit=200)
    result["listings_found"] = len(all_summaries)

    async with session_factory() as db:
        job = CollectionJob(
            job_type=CollectionJobType.KEYWORD_ACTIVE,
            query=query,
            category_id=category,
            source="browse_api",
            status=CollectionJobStatus.RUNNING,
            started_at=_utcnow_iso(),
        )
        db.add(job)
        await db.commit()

        existing_result = await db.execute(
            select(EbayListing).where(EbayListing.ebay_item_id.isnot(None))
        )
        existing_by_id = {l.ebay_item_id: l for l in existing_result.scalars().all()}

        raw_details: list[dict] = []
        for item_summary in all_summaries:
            item_id = item_summary.get("itemId")
            if not item_id:
                continue

            try:
                detail = await browse_api_item_detail(item_id)
            except Exception as exc:
                print(f"[warn] get_item failed for {item_id}: {exc}", file=sys.stderr)
                result["errors"] += 1
                continue

            raw_details.append(detail)

            raw_title = detail.get("title") or item_summary.get("title") or ""
            raw_description = detail.get("description")
            listing_url = detail.get("itemWebUrl") or item_summary.get("itemWebUrl")
            price = _extract_price(detail)
            seller_name = (detail.get("seller") or {}).get("username")
            condition = detail.get("condition")
            image_url = _extract_primary_image_url(detail)

            parsed = None
            if parse_labels:
                try:
                    parsed = await parse_listing_label(raw_title, raw_description)
                except Exception as exc:
                    print(f"[warn] label parser failed for {item_id}: {exc}", file=sys.stderr)

            existing = existing_by_id.get(item_id)
            if existing is not None:
                existing.title = raw_title
                existing.price = price or existing.price
                existing.listing_url = listing_url
                existing.seller = seller_name
                existing.condition = condition
                existing.image_url = image_url
                if parsed is not None:
                    existing.parsed_fields = parsed
                existing.updated_at = _utcnow_iso()
                result["listings_updated"] += 1
            else:
                local_image = None
                if image_url:
                    dest = data_dir / "images" / "active" / _safe_filename(item_id)
                    try:
                        await _download_image(image_url, dest)
                        local_image = str(dest)
                    except Exception as exc:
                        print(f"[warn] image download failed for {item_id}: {exc}", file=sys.stderr)
                        result["errors"] += 1

                listing = EbayListing(
                    listing_type=EbayListingType.ACTIVE,
                    source="browse_api",
                    ebay_item_id=item_id,
                    title=raw_title,
                    price=price or 0.0,
                    seller=seller_name,
                    condition=condition,
                    image_url=image_url,
                    local_image_path=local_image,
                    listing_url=listing_url,
                    parsed_fields=parsed,
                    collection_job_id=job.id,
                )
                db.add(listing)
                existing_by_id[item_id] = listing
                result["listings_new"] += 1

        raw_dir = data_dir / "raw" / "browse_api" / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"job_{job.id}.json").write_text(json.dumps(raw_details, indent=2))

        job.listings_found = result["listings_found"]
        job.listings_new = result["listings_new"]
        job.status = CollectionJobStatus.COMPLETED
        job.completed_at = _utcnow_iso()
        await db.commit()

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collect_listings.py -v`
Expected: PASS — all 4 tests green

- [ ] **Step 5: Commit**

```bash
git add scripts/collect_listings.py tests/test_collect_listings.py
git commit -m "feat: add active-search subcommand to collect_listings"
```

---

### Task 7: Sold Listing Collection (RapidAPI)

**Files:**
- Modify: `disney-pin-assistant/scripts/collect_listings.py`
- Modify: `disney-pin-assistant/tests/test_collect_listings.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_collect_listings.py`:

```python
@pytest.mark.asyncio
async def test_sold_creates_listings_from_rapidapi(db_session, tmp_path):
    api_result = {
        "aggregates": {
            "average_price": 22.50, "median_price": 20.00,
            "min_price": 10.00, "max_price": 35.00, "results": 2,
        },
        "products": [
            {"title": "Stitch LE 500 Pin", "sale_price": "25.00", "date_sold": "Mar 10, 2026", "link": "https://ebay.com/sold/1"},
            {"title": "Stitch Pin Lot", "sale_price": "20.00", "date_sold": "Mar 08, 2026", "link": "https://ebay.com/sold/2"},
        ],
    }

    with patch.object(collect_listings, "fetch_sold_listings", new=AsyncMock(return_value=api_result)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value={"characters": ["Stitch"]})):
        result = await collect_listings.run_sold(
            query="Stitch LE 500",
            data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=True,
        )

    assert result["listings_new"] == 2
    assert result["listings_skipped"] == 0

    jobs = (await db_session.execute(select(CollectionJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].job_type == CollectionJobType.KEYWORD_SOLD
    assert jobs[0].result_metadata["average_price"] == 22.50

    listings = (await db_session.execute(select(EbayListing))).scalars().all()
    assert len(listings) == 2
    for listing in listings:
        assert listing.listing_type == EbayListingType.SOLD
        assert listing.source == "rapidapi_sold"
        assert listing.local_image_path is None  # no image download for sold


@pytest.mark.asyncio
async def test_sold_deduplicates_on_title_price_date(db_session, tmp_path):
    # Pre-create a sold listing
    job = CollectionJob(
        job_type="keyword_sold", query="test", source="rapidapi_sold",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    existing = EbayListing(
        listing_type=EbayListingType.SOLD,
        source="rapidapi_sold",
        title="Stitch LE 500 Pin",
        price=25.00,
        sale_date="Mar 10, 2026",
        collection_job_id=job.id,
    )
    db_session.add(existing)
    await db_session.commit()

    api_result = {
        "aggregates": {"average_price": 25.00, "median_price": 25.00, "min_price": 25.00, "max_price": 25.00, "results": 2},
        "products": [
            {"title": "Stitch LE 500 Pin", "sale_price": "25.00", "date_sold": "Mar 10, 2026", "link": "https://ebay.com/1"},
            {"title": "New Pin", "sale_price": "30.00", "date_sold": "Mar 11, 2026", "link": "https://ebay.com/2"},
        ],
    }

    with patch.object(collect_listings, "fetch_sold_listings", new=AsyncMock(return_value=api_result)), \
         patch.object(collect_listings, "parse_listing_label", new=AsyncMock(return_value={})):
        result = await collect_listings.run_sold(
            query="Stitch", data_dir=tmp_path,
            session_factory=lambda: _session_wrapper(db_session),
            parse_labels=False,
        )

    assert result["listings_new"] == 1
    assert result["listings_skipped"] == 1

    listings = (await db_session.execute(select(EbayListing))).scalars().all()
    assert len(listings) == 2  # 1 existing + 1 new
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collect_listings.py::test_sold_creates_listings_from_rapidapi -v`
Expected: FAIL — `AttributeError: module 'collect_listings' has no attribute 'run_sold'`

- [ ] **Step 3: Implement `run_sold`**

Add the import at the top of `scripts/collect_listings.py`:

```python
from src.services.rapidapi_client import fetch_sold_listings
```

Add the function after `run_active_search`:

```python
async def run_sold(
    query: str,
    max_results: int = 240,
    category: str | None = None,
    data_dir: Path = Path("data"),
    session_factory: Callable = _default_session_factory,
    parse_labels: bool = True,
) -> dict:
    """Collect sold listings via RapidAPI."""
    result = {"listings_found": 0, "listings_new": 0, "listings_skipped": 0, "errors": 0}

    api_result = await fetch_sold_listings(
        keywords=query, max_results=max_results, category_id=category,
    )

    products = api_result["products"]
    result["listings_found"] = len(products)

    async with session_factory() as db:
        job = CollectionJob(
            job_type=CollectionJobType.KEYWORD_SOLD,
            query=query,
            category_id=category,
            source="rapidapi_sold",
            status=CollectionJobStatus.RUNNING,
            started_at=_utcnow_iso(),
            result_metadata=api_result["aggregates"],
        )
        db.add(job)
        await db.commit()

        # Load existing sold listings for soft dedup
        existing_sold = await db.execute(
            select(EbayListing).where(EbayListing.listing_type == EbayListingType.SOLD)
        )
        dedup_set: set[tuple[str, float, str]] = set()
        for row in existing_sold.scalars().all():
            dedup_set.add((row.title, row.price, row.sale_date or ""))

        for product in products:
            title = product.get("title", "")
            sale_price_str = product.get("sale_price", "0")
            try:
                sale_price = float(sale_price_str)
            except (ValueError, TypeError):
                sale_price = 0.0
            date_sold = product.get("date_sold", "")
            link = product.get("link")

            dedup_key = (title, sale_price, date_sold)
            if dedup_key in dedup_set:
                result["listings_skipped"] += 1
                continue

            parsed = None
            if parse_labels:
                try:
                    parsed = await parse_listing_label(title, None)
                except Exception as exc:
                    print(f"[warn] label parser failed: {exc}", file=sys.stderr)
                    result["errors"] += 1

            listing = EbayListing(
                listing_type=EbayListingType.SOLD,
                source="rapidapi_sold",
                title=title,
                price=sale_price,
                sale_date=date_sold,
                listing_url=link,
                parsed_fields=parsed,
                collection_job_id=job.id,
            )
            db.add(listing)
            dedup_set.add(dedup_key)
            result["listings_new"] += 1

        # Archive raw response
        raw_dir = data_dir / "raw" / "rapidapi_sold" / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"job_{job.id}.json").write_text(json.dumps(api_result, indent=2))

        job.listings_found = result["listings_found"]
        job.listings_new = result["listings_new"]
        job.status = CollectionJobStatus.COMPLETED
        job.completed_at = _utcnow_iso()
        await db.commit()

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collect_listings.py -v`
Expected: PASS — all 6 tests green

- [ ] **Step 5: Commit**

```bash
git add scripts/collect_listings.py tests/test_collect_listings.py
git commit -m "feat: add sold subcommand with RapidAPI integration and soft dedup"
```

---

### Task 8: Promote to Pins

**Files:**
- Modify: `disney-pin-assistant/scripts/collect_listings.py`
- Modify: `disney-pin-assistant/tests/test_collect_listings.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_collect_listings.py`:

```python
from src.models import Pin, PinStatus


@pytest.mark.asyncio
async def test_promote_creates_pins_from_listings(db_session, tmp_path):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE, query="test", source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing1 = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|1|0", title="Stitch Pin",
        price=19.99, seller="pins-n-things",
        local_image_path=str(tmp_path / "img1.jpg"),
        listing_url="https://ebay.com/1",
        parsed_fields={"characters": ["Stitch"]},
        collection_job_id=job.id,
    )
    listing2 = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|2|0", title="Goofy Pin",
        price=14.99, seller="pins-n-things",
        local_image_path=str(tmp_path / "img2.jpg"),
        listing_url="https://ebay.com/2",
        parsed_fields={"characters": ["Goofy"]},
        collection_job_id=job.id,
    )
    db_session.add_all([listing1, listing2])
    await db_session.commit()

    result = await collect_listings.run_promote(
        job_id=job.id,
        batch_name="test-batch",
        session_factory=lambda: _session_wrapper(db_session),
    )

    assert result["promoted"] == 2
    assert result["skipped"] == 0

    pins = (await db_session.execute(select(Pin).where(Pin.batch_id == "test-batch"))).scalars().all()
    assert len(pins) == 2
    for pin in pins:
        assert pin.status == PinStatus.UNPROCESSED
        assert pin.reference_source == "browse_api"
        assert pin.reference_external_id in {"v1|1|0", "v1|2|0"}


@pytest.mark.asyncio
async def test_promote_skips_already_promoted(db_session, tmp_path):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE, query="test", source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|1|0", title="Stitch Pin",
        price=19.99, collection_job_id=job.id,
    )
    db_session.add(listing)
    await db_session.commit()

    # Pre-create a pin with the same external ID
    pin = Pin(
        batch_id="old-batch", status=PinStatus.PRICED, image_paths=[],
        reference_source="ebay_browse", reference_external_id="v1|1|0",
    )
    db_session.add(pin)
    await db_session.commit()

    result = await collect_listings.run_promote(
        job_id=job.id,
        batch_name="new-batch",
        session_factory=lambda: _session_wrapper(db_session),
    )

    assert result["promoted"] == 0
    assert result["skipped"] == 1


@pytest.mark.asyncio
async def test_promote_by_seller(db_session, tmp_path):
    job = CollectionJob(
        job_type=CollectionJobType.SELLER_ACTIVE, query="test", source="browse_api",
        status=CollectionJobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.commit()

    listing1 = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|1|0", title="Pin A", price=10.00,
        seller="target-seller", collection_job_id=job.id,
    )
    listing2 = EbayListing(
        listing_type=EbayListingType.ACTIVE, source="browse_api",
        ebay_item_id="v1|2|0", title="Pin B", price=20.00,
        seller="other-seller", collection_job_id=job.id,
    )
    db_session.add_all([listing1, listing2])
    await db_session.commit()

    result = await collect_listings.run_promote(
        seller="target-seller",
        batch_name="promote-test",
        session_factory=lambda: _session_wrapper(db_session),
    )

    assert result["promoted"] == 1
    assert result["skipped"] == 0

    pins = (await db_session.execute(select(Pin).where(Pin.batch_id == "promote-test"))).scalars().all()
    assert len(pins) == 1
    assert pins[0].reference_raw_title == "Pin A"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collect_listings.py::test_promote_creates_pins_from_listings -v`
Expected: FAIL — `AttributeError: module 'collect_listings' has no attribute 'run_promote'`

- [ ] **Step 3: Implement `run_promote`**

Add the import at the top of `scripts/collect_listings.py` (alongside existing imports):

```python
from src.models import Pin, PinStatus
```

Note: `Pin` and `PinStatus` are already available from `src.models` — just add them to the existing import line that imports `CollectionJob`, `CollectionJobStatus`, etc.

Add the function after `run_sold`:

```python
async def run_promote(
    batch_name: str,
    job_id: int | None = None,
    seller: str | None = None,
    session_factory: Callable = _default_session_factory,
) -> dict:
    """Promote collected listings to Pin rows for pipeline processing."""
    result = {"promoted": 0, "skipped": 0}

    async with session_factory() as db:
        # Build query based on filter
        query = select(EbayListing)
        if job_id is not None:
            query = query.where(EbayListing.collection_job_id == job_id)
        elif seller is not None:
            query = query.where(EbayListing.seller == seller)
        else:
            raise ValueError("Must provide either --job-id or --seller")

        listings = (await db.execute(query)).scalars().all()

        # Load existing pins for dedup
        existing_pins = await db.execute(
            select(Pin.reference_external_id).where(
                Pin.reference_external_id.isnot(None)
            )
        )
        existing_ext_ids: set[str] = {row[0] for row in existing_pins.fetchall()}

        for listing in listings:
            # Skip if already promoted (by ebay_item_id)
            if listing.ebay_item_id and listing.ebay_item_id in existing_ext_ids:
                result["skipped"] += 1
                continue

            image_paths = [listing.local_image_path] if listing.local_image_path else []
            pin = Pin(
                batch_id=batch_name,
                status=PinStatus.UNPROCESSED,
                image_paths=image_paths,
                reference_source=listing.source,
                reference_external_id=listing.ebay_item_id,
                reference_url=listing.listing_url,
                reference_raw_title=listing.title,
                reference_parsed_fields=listing.parsed_fields,
                reference_ingested_at=_utcnow_iso(),
            )
            db.add(pin)
            if listing.ebay_item_id:
                existing_ext_ids.add(listing.ebay_item_id)
            result["promoted"] += 1

        await db.commit()

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_collect_listings.py -v`
Expected: PASS — all 9 tests green

- [ ] **Step 5: Run full test suite**

Run: `cd disney-pin-assistant && python -m pytest --tb=short -q`
Expected: All tests pass (207+ existing + new tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/collect_listings.py tests/test_collect_listings.py
git commit -m "feat: add promote subcommand to bridge listings to pin pipeline"
```

---

### Task 9: Integration Smoke Test

**Files:**
- No new files — this is a manual verification task

- [ ] **Step 1: Run the migration on the real database**

```bash
cd disney-pin-assistant && python -c "
import asyncio
from src.database import engine, ensure_listing_collection_tables
asyncio.run(ensure_listing_collection_tables(engine))
print('Migration complete')
"
```

Expected: `Migration complete` — two new tables created in `pins.db`

- [ ] **Step 2: Verify tables exist**

```bash
cd disney-pin-assistant && python -c "
import asyncio, sqlite3
conn = sqlite3.connect('pins.db')
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('Tables:', tables)
assert 'collection_jobs' in tables
assert 'ebay_listings' in tables
print('OK')
conn.close()
"
```

Expected: Tables list includes `collection_jobs` and `ebay_listings`

- [ ] **Step 3: Test active-seller collection against real eBay API**

```bash
cd disney-pin-assistant && python scripts/collect_listings.py active-seller --seller pins-n-things --query disney --no-parse
```

Expected: Output showing listings collected, job created, raw response archived under `data/raw/browse_api/`

- [ ] **Step 4: Verify data was stored**

```bash
cd disney-pin-assistant && python -c "
import asyncio
from src.database import async_session
from sqlalchemy import select, func
from src.models import EbayListing, CollectionJob
async def check():
    async with async_session() as db:
        jobs = (await db.execute(select(func.count()).select_from(CollectionJob))).scalar()
        listings = (await db.execute(select(func.count()).select_from(EbayListing))).scalar()
        print(f'Jobs: {jobs}, Listings: {listings}')
asyncio.run(check())
"
```

Expected: At least 1 job and 1+ listings

- [ ] **Step 5: Verify raw response was archived**

```bash
ls -la disney-pin-assistant/data/raw/browse_api/
```

Expected: A date-stamped directory with a `job_*.json` file

- [ ] **Step 6: Run full test suite one final time**

Run: `cd disney-pin-assistant && python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 7: Commit any final adjustments**

Only if fixes were needed during smoke testing.

---

## Self-Review

**Spec coverage check:**
- `ebay_listings` table — Task 1 ✅
- `collection_jobs` table — Task 1 ✅
- `result_metadata` on jobs — Task 7 (stored in `run_sold`) ✅
- Config settings — Task 2 ✅
- Database migration — Task 3 ✅
- RapidAPI client — Task 4 ✅
- CLI active-seller — Task 5 ✅
- CLI active-search — Task 6 ✅
- CLI sold — Task 7 ✅
- CLI promote — Task 8 ✅
- Raw response archival — Tasks 5, 6, 7 ✅
- Label parsing on collected listings — Tasks 5, 6, 7 (controlled by `parse_labels` param) ✅
- Soft dedup for sold listings — Task 7 ✅
- Upsert for active listings — Tasks 5, 6 ✅
- Image download for active only — Tasks 5, 6 ✅
- `.gitignore` update — Task 3 ✅
- Retiring `import_ebay_seller.py` — noted but not deleted (spec says "kept temporarily") ✅
- Price comp integration — spec says "out of scope / follow-up" ✅ (correctly omitted)

**Placeholder scan:** No TBDs, TODOs, or vague instructions found.

**Type consistency check:**
- `EbayListingType` used consistently across all tasks (not confused with existing `ListingType`)
- `CollectionJobType` enum values (`SELLER_ACTIVE`, `KEYWORD_ACTIVE`, `KEYWORD_SOLD`) match between Task 1 definition and Tasks 5-7 usage
- `CollectionJobStatus` enum values match between Task 1 and all `run_*` functions
- `run_active_seller`, `run_active_search`, `run_sold`, `run_promote` — function signatures consistent between test mocks and implementations
- `fetch_sold_listings` return shape (`aggregates` + `products`) matches between Task 4 (client) and Task 7 (consumer)
- `_session_wrapper` helper used identically in all test files
