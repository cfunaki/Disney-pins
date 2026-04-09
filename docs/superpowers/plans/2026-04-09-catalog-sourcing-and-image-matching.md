# Catalog Sourcing & Image-Based Pin Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken PinPics scraper with a PinTradingDB scraper that downloads images, generate CLIP embeddings for visual similarity, and build a hybrid text+image matching pipeline that reliably identifies specific pins.

**Architecture:** Text-based attribute matching narrows catalog to ~30 candidates, then CLIP embeddings re-rank by visual similarity to find the exact pin. Optional Claude Vision confirmation for low-confidence matches. PinTradingDB replaces PinPics as the catalog data source.

**Tech Stack:** httpx (async HTTP), BeautifulSoup4 (HTML parsing), transformers + torch (CLIP model), numpy (embedding math), SQLAlchemy 2.0 (ORM), Anthropic SDK (Claude Vision confirmation)

---

## File Structure

| File | Responsibility |
|------|----------------|
| **Create:** `scripts/scrape_pintradingdb.py` | CLI entry point for PinTradingDB scraper |
| **Create:** `scripts/scraper/pintradingdb_fetcher.py` | HTTP fetcher for PinTradingDB pages (pagination + detail) |
| **Create:** `scripts/scraper/pintradingdb_parser.py` | HTML parser for PinTradingDB pin detail pages |
| **Create:** `src/pipeline/image_matching.py` | CLIP embedding generation and cosine similarity scoring |
| **Create:** `tests/test_pintradingdb_parser.py` | Parser tests with HTML fixtures |
| **Create:** `tests/test_pintradingdb_fetcher.py` | Fetcher tests (rate limiting, pagination) |
| **Create:** `tests/test_image_matching.py` | CLIP embedding and similarity tests |
| **Create:** `tests/test_hybrid_matching.py` | End-to-end hybrid pipeline tests |
| **Create:** `tests/fixtures/pintradingdb_detail.html` | Sample PinTradingDB detail page HTML |
| **Create:** `tests/fixtures/pintradingdb_list.html` | Sample PinTradingDB list page HTML |
| **Modify:** `src/models.py` | Add `image_path` and `clip_embedding` columns to CatalogEntry |
| **Modify:** `src/pipeline/matching.py` | Add CLIP re-ranking after text scoring; add Claude Vision confirmation |
| **Modify:** `src/routes/catalog.py` | Add endpoint to trigger embedding generation for existing entries |
| **Modify:** `pyproject.toml` | Add `transformers`, `torch`, `numpy`, `Pillow` dependencies |
| **Modify:** `.gitignore` | Add `catalog_images/` |

---

### Task 1: Add Dependencies and Model Columns

**Files:**
- Modify: `disney-pin-assistant/pyproject.toml`
- Modify: `disney-pin-assistant/src/models.py:109-131`
- Modify: `disney-pin-assistant/.gitignore`
- Test: `disney-pin-assistant/tests/test_models.py`

- [ ] **Step 1: Write failing test for new CatalogEntry columns**

```python
# tests/test_catalog_image_columns.py
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
        source="pintradingdb",
        source_reference_id="12345",
        image_path="catalog_images/12345.jpg",
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    assert entry.image_path == "catalog_images/12345.jpg"


@pytest.mark.asyncio
async def test_catalog_entry_has_clip_embedding(db_session):
    import json
    embedding = [0.1] * 512  # CLIP ViT-B/32 produces 512-dim vectors
    entry = CatalogEntry(
        canonical_name="Test Pin",
        source="pintradingdb",
        source_reference_id="12345",
        clip_embedding=json.dumps(embedding),
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    loaded = json.loads(entry.clip_embedding)
    assert len(loaded) == 512
    assert loaded[0] == pytest.approx(0.1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd disney-pin-assistant && python -m pytest tests/test_catalog_image_columns.py -v`
Expected: FAIL — `TypeError: CatalogEntry() got an unexpected keyword argument 'image_path'`

- [ ] **Step 3: Add columns to CatalogEntry model**

In `src/models.py`, add two columns to the `CatalogEntry` class after `reference_image_url`:

```python
    reference_image_url = Column(String(500), nullable=True)
    image_path = Column(String(500), nullable=True)        # Local path to downloaded image
    clip_embedding = Column(Text, nullable=True)           # JSON-serialized float list (512 dims)
    evidence_strength = Column(String(20), default="low")
```

- [ ] **Step 4: Add dependencies to pyproject.toml**

```toml
[project]
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy>=2.0.0",
    "anthropic>=0.40.0",
    "httpx>=0.27.0",
    "python-multipart>=0.0.9",
    "python-dotenv>=1.0.0",
    "pydantic-settings>=2.0.0",
    "jinja2>=3.1.0",
    "aiosqlite>=0.20.0",
    "greenlet>=3.0.0",
    "beautifulsoup4>=4.12",
    "transformers>=4.40.0",
    "torch>=2.2.0",
    "numpy>=1.26.0",
    "Pillow>=10.0.0",
]
```

- [ ] **Step 5: Add catalog_images/ to .gitignore**

Append to `.gitignore`:

```
# Catalog images (downloaded by scraper)
catalog_images/
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd disney-pin-assistant && pip install -e ".[dev]" && python -m pytest tests/test_catalog_image_columns.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
cd disney-pin-assistant
git add src/models.py pyproject.toml .gitignore tests/test_catalog_image_columns.py
git commit -m "feat: add image_path and clip_embedding columns to CatalogEntry model"
```

---

### Task 2: PinTradingDB HTML Parser

**Files:**
- Create: `disney-pin-assistant/scripts/scraper/pintradingdb_parser.py`
- Create: `disney-pin-assistant/tests/test_pintradingdb_parser.py`
- Create: `disney-pin-assistant/tests/fixtures/pintradingdb_detail.html`
- Create: `disney-pin-assistant/tests/fixtures/pintradingdb_list.html`

**Context:** PinTradingDB pin detail pages have structured data in elements with CSS class `.pinLabel`. The list/pagination endpoint at `ajaxPinList.php?pinPage={n}` returns HTML fragments with pin links. The parser needs to handle both.

- [ ] **Step 1: Create HTML fixture for pin detail page**

First, fetch a real PinTradingDB page to create the fixture. Run:

```bash
cd disney-pin-assistant
curl -s "https://pintradingdb.com/pin/1" -o /tmp/pintradingdb_sample.html
head -200 /tmp/pintradingdb_sample.html
```

Examine the HTML structure and create a representative fixture. Save to `tests/fixtures/pintradingdb_detail.html`. The fixture should contain the key `.pinLabel` elements and image tag. Example structure (adapt to actual HTML after fetching):

```html
<html>
<body>
<div class="pinDetail">
  <div class="pinImage">
    <img src="/images/pins/12345.jpg" alt="Mickey Mouse 50th Anniversary LE 3000" />
  </div>
  <div class="pinInfo">
    <div class="pinLabel">Name:</div>
    <div class="pinValue">Mickey Mouse 50th Anniversary LE 3000</div>
    <div class="pinLabel">Characters:</div>
    <div class="pinValue">Mickey Mouse</div>
    <div class="pinLabel">Origin:</div>
    <div class="pinValue">Walt Disney World</div>
    <div class="pinLabel">Edition Size:</div>
    <div class="pinValue">3000</div>
    <div class="pinLabel">Release Year:</div>
    <div class="pinValue">2023</div>
    <div class="pinLabel">Pin Type:</div>
    <div class="pinValue">Limited Edition</div>
    <div class="pinLabel">Event:</div>
    <div class="pinValue">50th Anniversary Celebration</div>
    <div class="pinLabel">Franchise:</div>
    <div class="pinValue">Mickey & Friends</div>
  </div>
</div>
</body>
</html>
```

**IMPORTANT:** After fetching the actual page, adapt the fixture and the parser below to match the real HTML structure. The field names, CSS classes, and DOM layout must match what PinTradingDB actually serves. The code below assumes a label/value pair pattern — adjust if the site uses a different structure.

- [ ] **Step 2: Create HTML fixture for list/pagination page**

```bash
curl -s "https://pintradingdb.com/ajaxPinList.php?pinPage=1" -o /tmp/pintradingdb_list.html
head -100 /tmp/pintradingdb_list.html
```

Save a representative fixture to `tests/fixtures/pintradingdb_list.html`. Expected: HTML fragment with links to pin detail pages containing pin IDs.

- [ ] **Step 3: Write failing parser tests**

```python
# tests/test_pintradingdb_parser.py
import os
import pytest
from scripts.scraper.pintradingdb_parser import parse_pin_detail, extract_pin_ids_from_list

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(filename: str) -> str:
    with open(os.path.join(FIXTURES_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


class TestParseDetail:
    def test_extracts_canonical_name(self):
        html = _read_fixture("pintradingdb_detail.html")
        result = parse_pin_detail(html, "12345")
        assert result["canonical_name"] is not None
        assert len(result["canonical_name"]) > 0

    def test_extracts_characters(self):
        html = _read_fixture("pintradingdb_detail.html")
        result = parse_pin_detail(html, "12345")
        assert isinstance(result["characters"], list)
        assert len(result["characters"]) >= 1

    def test_extracts_edition_size(self):
        html = _read_fixture("pintradingdb_detail.html")
        result = parse_pin_detail(html, "12345")
        assert result["edition_size"] is not None
        assert isinstance(result["edition_size"], int)

    def test_extracts_image_url(self):
        html = _read_fixture("pintradingdb_detail.html")
        result = parse_pin_detail(html, "12345")
        assert result["reference_image_url"] is not None
        assert result["reference_image_url"].startswith("http")

    def test_sets_source_fields(self):
        html = _read_fixture("pintradingdb_detail.html")
        result = parse_pin_detail(html, "12345")
        assert result["source"] == "pintradingdb"
        assert result["source_reference_id"] == "12345"

    def test_extracts_all_available_fields(self):
        html = _read_fixture("pintradingdb_detail.html")
        result = parse_pin_detail(html, "12345")
        # Verify dict has all expected keys
        expected_keys = [
            "canonical_name", "characters", "franchise", "edition_size",
            "release_year", "pin_type", "event", "reference_image_url",
            "source", "source_reference_id",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"


class TestExtractPinIds:
    def test_extracts_pin_ids_from_list_page(self):
        html = _read_fixture("pintradingdb_list.html")
        pin_ids = extract_pin_ids_from_list(html)
        assert isinstance(pin_ids, list)
        assert len(pin_ids) > 0
        assert all(isinstance(pid, str) for pid in pin_ids)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_pintradingdb_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.scraper.pintradingdb_parser'`

- [ ] **Step 5: Implement the parser**

```python
# scripts/scraper/pintradingdb_parser.py
"""HTML parser for PinTradingDB pin detail and list pages."""

import re
from bs4 import BeautifulSoup

PINTRADINGDB_BASE = "https://pintradingdb.com"


def parse_pin_detail(html: str, pin_id: str) -> dict:
    """Parse a PinTradingDB pin detail page into a catalog entry dict.

    Returns a dict with keys matching CatalogEntry fields.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract label/value pairs from pinLabel elements
    fields = _extract_label_value_pairs(soup)

    # Extract image URL
    image_url = _extract_image_url(soup)

    # Parse characters (may be comma-separated)
    characters_raw = fields.get("characters", "")
    characters = [c.strip() for c in characters_raw.split(",") if c.strip()] if characters_raw else []

    # Parse edition size
    edition_raw = fields.get("edition size", "") or fields.get("edition", "")
    edition_size = _parse_edition_size(edition_raw)

    # Parse release year
    year_raw = fields.get("release year", "") or fields.get("year", "")
    release_year = _parse_year(year_raw)

    return {
        "canonical_name": fields.get("name", "").strip() or None,
        "characters": characters,
        "franchise": fields.get("franchise", "").strip() or None,
        "series_or_collection": fields.get("series", "").strip() or fields.get("collection", "").strip() or None,
        "event": fields.get("event", "").strip() or None,
        "edition_size": edition_size,
        "release_year": release_year,
        "pin_type": (fields.get("pin type", "") or fields.get("type", "")).strip().lower() or None,
        "exclusive_source": fields.get("origin", "").strip() or fields.get("exclusive", "").strip() or None,
        "reference_image_url": image_url,
        "source": "pintradingdb",
        "source_reference_id": str(pin_id),
        "evidence_strength": "high",
    }


def extract_pin_ids_from_list(html: str) -> list[str]:
    """Extract pin IDs from a PinTradingDB list/pagination page.

    Looks for links matching /pin/{id} pattern.
    """
    soup = BeautifulSoup(html, "html.parser")
    pin_ids = []
    for link in soup.find_all("a", href=True):
        match = re.search(r"/pin/(\d+)", link["href"])
        if match:
            pid = match.group(1)
            if pid not in pin_ids:
                pin_ids.append(pid)
    return pin_ids


def _extract_label_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Extract label → value pairs from pinLabel elements.

    Handles two common patterns:
    1. <div class="pinLabel">Name:</div><div class="pinValue">...</div>
    2. <span class="pinLabel">Name:</span> value text
    """
    fields: dict[str, str] = {}

    labels = soup.find_all(class_="pinLabel")
    for label_el in labels:
        label_text = label_el.get_text(strip=True).rstrip(":").lower()
        # Try sibling with pinValue class first
        value_el = label_el.find_next_sibling(class_="pinValue")
        if value_el:
            fields[label_text] = value_el.get_text(strip=True)
        else:
            # Try next sibling text
            next_sib = label_el.next_sibling
            if next_sib and isinstance(next_sib, str):
                fields[label_text] = next_sib.strip()

    return fields


def _extract_image_url(soup: BeautifulSoup) -> str | None:
    """Extract the pin image URL from the detail page."""
    # Look for image in pinImage container or main content area
    for container_class in ["pinImage", "pinDetail", "pin-image"]:
        container = soup.find(class_=container_class)
        if container:
            img = container.find("img")
            if img and img.get("src"):
                src = img["src"]
                if src.startswith("/"):
                    return f"{PINTRADINGDB_BASE}{src}"
                if src.startswith("http"):
                    return src

    # Fallback: first img with "pin" in src
    for img in soup.find_all("img", src=True):
        if "pin" in img["src"].lower():
            src = img["src"]
            if src.startswith("/"):
                return f"{PINTRADINGDB_BASE}{src}"
            if src.startswith("http"):
                return src

    return None


def _parse_edition_size(raw: str) -> int | None:
    """Parse edition size from text like '3000', 'LE 3000', 'LE/2,500'."""
    if not raw:
        return None
    match = re.search(r"(\d[\d,]*)", raw)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _parse_year(raw: str) -> int | None:
    """Parse a 4-digit year from text."""
    if not raw:
        return None
    match = re.search(r"((?:19|20)\d{2})", raw)
    if match:
        return int(match.group(1))
    return None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_pintradingdb_parser.py -v`
Expected: PASS (8 tests)

**Note:** If tests fail because the fixture HTML doesn't match the parser's expectations, update either the fixture or the parser to match PinTradingDB's actual HTML structure.

- [ ] **Step 7: Commit**

```bash
cd disney-pin-assistant
git add scripts/scraper/pintradingdb_parser.py tests/test_pintradingdb_parser.py tests/fixtures/pintradingdb_detail.html tests/fixtures/pintradingdb_list.html
git commit -m "feat: add PinTradingDB HTML parser with detail and list page support"
```

---

### Task 3: PinTradingDB Fetcher (HTTP Client + Image Download)

**Files:**
- Create: `disney-pin-assistant/scripts/scraper/pintradingdb_fetcher.py`
- Create: `disney-pin-assistant/tests/test_pintradingdb_fetcher.py`

**Context:** The fetcher handles three operations: (1) fetch paginated list pages to discover pin IDs, (2) fetch pin detail pages, (3) download pin images to local disk. It reuses the existing `RateLimiter` from `scripts/scraper/pinpics_fetcher.py`.

- [ ] **Step 1: Write failing fetcher tests**

```python
# tests/test_pintradingdb_fetcher.py
import os
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

# Add scripts to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from scraper.pintradingdb_fetcher import (
    fetch_pin_list_page,
    fetch_pin_detail,
    download_pin_image,
    PINTRADINGDB_BASE,
)
from scraper.pinpics_fetcher import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter(requests_per_second=100.0)  # Fast for tests


class TestFetchPinListPage:
    @pytest.mark.asyncio
    async def test_returns_html_on_200(self, limiter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><a href='/pin/100'>Pin</a></html>"

        with patch("scraper.pintradingdb_fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await fetch_pin_list_page(1, limiter)
            assert result == "<html><a href='/pin/100'>Pin</a></html>"

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self, limiter):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = ""

        with patch("scraper.pintradingdb_fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await fetch_pin_list_page(1, limiter)
            assert result is None


class TestDownloadPinImage:
    @pytest.mark.asyncio
    async def test_saves_image_to_disk(self, limiter, tmp_path):
        fake_image_bytes = b"\xff\xd8\xff\xe0fake-jpeg-data"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_image_bytes

        with patch("scraper.pintradingdb_fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            output_dir = str(tmp_path)
            result = await download_pin_image(
                "https://pintradingdb.com/images/pins/12345.jpg",
                "12345",
                output_dir,
                limiter,
            )
            assert result is not None
            assert os.path.exists(result)
            with open(result, "rb") as f:
                assert f.read() == fake_image_bytes

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self, limiter, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.content = b""

        with patch("scraper.pintradingdb_fetcher.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await download_pin_image(
                "https://pintradingdb.com/images/pins/99999.jpg",
                "99999",
                str(tmp_path),
                limiter,
            )
            assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_pintradingdb_fetcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.pintradingdb_fetcher'`

- [ ] **Step 3: Implement the fetcher**

```python
# scripts/scraper/pintradingdb_fetcher.py
"""HTTP fetcher for PinTradingDB with rate limiting, retry logic, and image download."""

import os

import httpx

from scraper.pinpics_fetcher import RateLimiter

PINTRADINGDB_BASE = "https://pintradingdb.com"
LIST_URL = f"{PINTRADINGDB_BASE}/ajaxPinList.php"
DETAIL_URL = f"{PINTRADINGDB_BASE}/pin"
USER_AGENT = "DisneyPinAssistant/1.0 (personal pin catalog project)"


async def fetch_pin_list_page(
    page_number: int,
    limiter: RateLimiter,
    max_retries: int = 3,
) -> str | None:
    """Fetch a paginated list page from PinTradingDB.

    Returns HTML string on success, None on failure.
    """
    url = f"{LIST_URL}?pinPage={page_number}"
    return await _fetch_url(url, limiter, max_retries)


async def fetch_pin_detail(
    pin_id: str,
    limiter: RateLimiter,
    max_retries: int = 3,
) -> str | None:
    """Fetch a pin detail page from PinTradingDB.

    Returns HTML string on success, None on failure.
    """
    url = f"{DETAIL_URL}/{pin_id}"
    return await _fetch_url(url, limiter, max_retries)


async def download_pin_image(
    image_url: str,
    pin_id: str,
    output_dir: str,
    limiter: RateLimiter,
    max_retries: int = 3,
) -> str | None:
    """Download a pin image and save to output_dir.

    Returns the local file path on success, None on failure.
    """
    # Determine file extension from URL
    ext = os.path.splitext(image_url)[1] or ".jpg"
    if "?" in ext:
        ext = ext.split("?")[0]
    output_path = os.path.join(output_dir, f"{pin_id}{ext}")

    # Skip if already downloaded
    if os.path.exists(output_path):
        return output_path

    headers = {"User-Agent": USER_AGENT}

    for attempt in range(max_retries):
        await limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(image_url, headers=headers)

            if response.status_code == 200:
                os.makedirs(output_dir, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(response.content)
                return output_path

            if response.status_code == 404:
                return None

            print(f"[fetcher] Status {response.status_code} downloading image for pin {pin_id} (attempt {attempt + 1}/{max_retries})")

        except httpx.TimeoutException:
            print(f"[fetcher] Timeout downloading image for pin {pin_id} (attempt {attempt + 1}/{max_retries})")
        except Exception as exc:
            print(f"[fetcher] Error downloading image for pin {pin_id}: {exc} (attempt {attempt + 1}/{max_retries})")

    return None


async def _fetch_url(url: str, limiter: RateLimiter, max_retries: int) -> str | None:
    """Shared fetch logic with rate limiting and retries."""
    headers = {"User-Agent": USER_AGENT}

    for attempt in range(max_retries):
        await limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 200:
                return response.text

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                import asyncio
                backoff = 2 ** attempt
                print(f"[fetcher] 429 rate limited for {url}, backing off {backoff}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(backoff)
                continue

            print(f"[fetcher] Unexpected status {response.status_code} for {url} (attempt {attempt + 1}/{max_retries})")

        except httpx.TimeoutException:
            print(f"[fetcher] Timeout fetching {url} (attempt {attempt + 1}/{max_retries})")
        except Exception as exc:
            print(f"[fetcher] Error fetching {url}: {exc} (attempt {attempt + 1}/{max_retries})")

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_pintradingdb_fetcher.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd disney-pin-assistant
git add scripts/scraper/pintradingdb_fetcher.py tests/test_pintradingdb_fetcher.py
git commit -m "feat: add PinTradingDB HTTP fetcher with image download support"
```

---

### Task 4: PinTradingDB Scraper CLI

**Files:**
- Create: `disney-pin-assistant/scripts/scrape_pintradingdb.py`

**Context:** This is the CLI entry point that orchestrates the full scrape: paginate → discover pin IDs → fetch details → parse → normalize → download images → save to JSON. Follows the same patterns as `scripts/scrape_pinpics.py` (resume support, checkpoints, rate limiting). Does NOT generate CLIP embeddings — that happens at import time (Task 6).

- [ ] **Step 1: Implement the scraper CLI**

```python
# scripts/scrape_pintradingdb.py
"""CLI for scraping PinTradingDB pin data and images into a catalog."""

import argparse
import asyncio
import json
import os
import sys

# Ensure the scripts directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

from scraper.pinpics_fetcher import RateLimiter
from scraper.pintradingdb_fetcher import fetch_pin_list_page, fetch_pin_detail, download_pin_image
from scraper.pintradingdb_parser import parse_pin_detail, extract_pin_ids_from_list
from scraper.normalizer import normalize_entry

DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(__file__), "scraper", "output", "pintradingdb_catalog.json"
)
DEFAULT_IMAGE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "catalog_images"
)


def load_existing(output_path: str) -> dict[str, dict]:
    """Load existing output file and return a dict keyed by source_reference_id."""
    if not os.path.exists(output_path):
        return {}
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        return {e["source_reference_id"]: e for e in entries if "source_reference_id" in e}
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"[warning] Could not load existing output ({exc}), starting fresh.")
        return {}


def save_entries(output_path: str, entries: list[dict]) -> None:
    """Write entries list to the output JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


async def discover_pin_ids(
    start_page: int, end_page: int, limiter: RateLimiter
) -> list[str]:
    """Paginate through list pages and collect all pin IDs."""
    all_ids: list[str] = []
    for page in range(start_page, end_page + 1):
        html = await fetch_pin_list_page(page, limiter)
        if html is None:
            print(f"[discover] Page {page} returned no data, stopping pagination.")
            break
        ids = extract_pin_ids_from_list(html)
        if not ids:
            print(f"[discover] Page {page} had no pin IDs, stopping pagination.")
            break
        all_ids.extend(ids)
        print(f"[discover] Page {page}: found {len(ids)} pins (total: {len(all_ids)})")
    return all_ids


async def scrape(args: argparse.Namespace) -> None:
    output_path = args.output
    image_dir = args.image_dir

    # Resume: load existing entries and build skip set
    existing: dict[str, dict] = {}
    if args.resume:
        existing = load_existing(output_path)
        if existing:
            print(f"[resume] Loaded {len(existing)} existing entries, skipping those IDs.")

    entries: list[dict] = list(existing.values())
    limiter = RateLimiter(requests_per_second=args.rate)

    # Discover pin IDs
    if args.pin_ids:
        pin_ids = args.pin_ids.split(",")
        print(f"[scraper] Scraping {len(pin_ids)} specific pin IDs")
    else:
        print(f"[scraper] Discovering pins from pages {args.start_page}–{args.end_page}")
        pin_ids = await discover_pin_ids(args.start_page, args.end_page, limiter)
        print(f"[scraper] Discovered {len(pin_ids)} pin IDs")

    fetched = 0
    skipped = 0

    for pin_id in pin_ids:
        if args.resume and pin_id in existing:
            skipped += 1
            continue

        # Fetch detail page
        html = await fetch_pin_detail(pin_id, limiter)
        if html is None:
            fetched += 1
            continue

        # Parse and normalize
        raw = parse_pin_detail(html, pin_id)
        normalized = normalize_entry(raw)

        # Download image
        if normalized.get("reference_image_url"):
            image_path = await download_pin_image(
                normalized["reference_image_url"], pin_id, image_dir, limiter
            )
            if image_path:
                normalized["image_path"] = image_path

        entries.append(normalized)
        fetched += 1

        processed = fetched + skipped
        if processed % 50 == 0:
            print(
                f"[progress] Processed {processed}/{len(pin_ids)} "
                f"| Entries collected: {len(entries)}"
            )

        if fetched % 200 == 0 and fetched > 0:
            save_entries(output_path, entries)
            print(f"[checkpoint] Saved {len(entries)} entries to {output_path}")

    # Final save
    save_entries(output_path, entries)
    print(f"\n[done] Total entries collected: {len(entries)}")
    print(f"[done] Output saved to: {output_path}")
    print(f"[done] Images saved to: {image_dir}")
    print(
        f"\nTo import into the catalog, run:\n"
        f"  python scripts/import_catalog.py --input {output_path}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrape_pintradingdb",
        description="Scrape PinTradingDB pin data and images into a catalog.",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Start pagination page (default: 1).",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=100,
        help="End pagination page inclusive (default: 100).",
    )
    parser.add_argument(
        "--pin-ids",
        type=str,
        default=None,
        help="Comma-separated list of specific pin IDs to scrape (skips discovery).",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=1.0,
        metavar="RPS",
        help="Requests per second (default: 1.0).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip pin IDs already present in the output file.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        metavar="FILE",
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--image-dir",
        type=str,
        default=DEFAULT_IMAGE_DIR,
        metavar="DIR",
        help=f"Directory for downloaded images (default: {DEFAULT_IMAGE_DIR}).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(scrape(args))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test with a single pin**

Run: `cd disney-pin-assistant && python scripts/scrape_pintradingdb.py --pin-ids 1 --rate 1.0`
Expected: Should fetch one pin, print its data, save to output JSON.

- [ ] **Step 3: Commit**

```bash
cd disney-pin-assistant
git add scripts/scrape_pintradingdb.py
git commit -m "feat: add PinTradingDB scraper CLI with image download and resume support"
```

---

### Task 5: CLIP Embedding Module

**Files:**
- Create: `disney-pin-assistant/src/pipeline/image_matching.py`
- Create: `disney-pin-assistant/tests/test_image_matching.py`

**Context:** This module handles two things: (1) generating CLIP embeddings from images, and (2) computing cosine similarity between embeddings. The CLIP model (`openai/clip-vit-base-patch32`) is loaded lazily on first use. Embeddings are 512-dimensional float vectors.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_image_matching.py
import json
import math
import os
import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from src.pipeline.image_matching import (
    compute_clip_embedding,
    cosine_similarity,
    rank_by_visual_similarity,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_similar_vectors(self):
        a = [1.0, 1.0, 0.0]
        b = [1.0, 0.0, 0.0]
        sim = cosine_similarity(a, b)
        assert 0.5 < sim < 1.0


class TestRankByVisualSimilarity:
    def test_ranks_candidates_by_similarity(self):
        query_embedding = [1.0, 0.0, 0.0]
        candidates = [
            {"catalog_entry_id": 1, "clip_embedding": json.dumps([0.0, 1.0, 0.0])},  # orthogonal
            {"catalog_entry_id": 2, "clip_embedding": json.dumps([0.9, 0.1, 0.0])},  # similar
            {"catalog_entry_id": 3, "clip_embedding": json.dumps([0.5, 0.5, 0.0])},  # somewhat similar
        ]
        ranked = rank_by_visual_similarity(query_embedding, candidates)
        assert ranked[0]["catalog_entry_id"] == 2
        assert ranked[1]["catalog_entry_id"] == 3
        assert ranked[2]["catalog_entry_id"] == 1

    def test_adds_visual_similarity_score(self):
        query_embedding = [1.0, 0.0, 0.0]
        candidates = [
            {"catalog_entry_id": 1, "clip_embedding": json.dumps([1.0, 0.0, 0.0])},
        ]
        ranked = rank_by_visual_similarity(query_embedding, candidates)
        assert "visual_similarity" in ranked[0]
        assert ranked[0]["visual_similarity"] == pytest.approx(1.0)

    def test_skips_candidates_without_embedding(self):
        query_embedding = [1.0, 0.0, 0.0]
        candidates = [
            {"catalog_entry_id": 1, "clip_embedding": None},
            {"catalog_entry_id": 2, "clip_embedding": json.dumps([1.0, 0.0, 0.0])},
        ]
        ranked = rank_by_visual_similarity(query_embedding, candidates)
        assert len(ranked) == 1
        assert ranked[0]["catalog_entry_id"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_image_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline.image_matching'`

- [ ] **Step 3: Implement the image matching module**

```python
# src/pipeline/image_matching.py
"""CLIP-based image embedding and visual similarity scoring."""

import json
import math
from typing import Sequence

import numpy as np

# Lazy-loaded CLIP model and processor
_model = None
_processor = None


def _load_clip():
    """Lazily load the CLIP model and processor on first use."""
    global _model, _processor
    if _model is not None:
        return _model, _processor

    from transformers import CLIPModel, CLIPProcessor

    model_name = "openai/clip-vit-base-patch32"
    _processor = CLIPProcessor.from_pretrained(model_name)
    _model = CLIPModel.from_pretrained(model_name)
    _model.eval()
    return _model, _processor


def compute_clip_embedding(image_path: str) -> list[float]:
    """Generate a CLIP embedding vector for an image file.

    Returns a 512-dimensional float list.
    """
    import torch
    from PIL import Image

    model, processor = _load_clip()
    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")

    with torch.no_grad():
        image_features = model.get_image_features(**inputs)

    # Normalize the embedding
    embedding = image_features[0].numpy()
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding.tolist()


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)

    dot = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot / (norm_a * norm_b))


def rank_by_visual_similarity(
    query_embedding: list[float],
    candidates: list[dict],
    top_k: int | None = None,
) -> list[dict]:
    """Re-rank candidates by visual similarity to the query image.

    Each candidate dict must have a 'clip_embedding' field (JSON string or None).
    Returns candidates sorted by descending visual similarity, with
    'visual_similarity' score added to each.
    """
    scored = []
    for candidate in candidates:
        raw = candidate.get("clip_embedding")
        if raw is None:
            continue
        if isinstance(raw, str):
            embedding = json.loads(raw)
        else:
            embedding = raw

        sim = cosine_similarity(query_embedding, embedding)
        entry = dict(candidate)
        entry["visual_similarity"] = sim
        scored.append(entry)

    scored.sort(key=lambda x: x["visual_similarity"], reverse=True)

    if top_k is not None:
        return scored[:top_k]
    return scored
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_image_matching.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
cd disney-pin-assistant
git add src/pipeline/image_matching.py tests/test_image_matching.py
git commit -m "feat: add CLIP embedding generation and visual similarity scoring"
```

---

### Task 6: Hybrid Matching Pipeline

**Files:**
- Modify: `disney-pin-assistant/src/pipeline/matching.py`
- Create: `disney-pin-assistant/tests/test_hybrid_matching.py`

**Context:** The existing `find_catalog_matches` does text-only scoring. This task adds a new `find_catalog_matches_hybrid` function that: (1) runs existing text scoring to get top 30, (2) re-ranks by CLIP similarity to get top 5, (3) optionally calls Claude Vision for confirmation on low-confidence matches. The original `find_catalog_matches` stays unchanged for backward compatibility.

- [ ] **Step 1: Write failing tests for hybrid matching**

```python
# tests/test_hybrid_matching.py
import json
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
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
    """Seed DB with entries that have CLIP embeddings."""
    # Embedding that's "similar" to our query — high first dimension
    similar_embedding = [0.9, 0.1, 0.0] + [0.0] * 509
    # Embedding that's "different" — high second dimension
    different_embedding = [0.1, 0.9, 0.0] + [0.0] * 509

    entries = [
        CatalogEntry(
            canonical_name="Mickey Mouse 50th Anniversary LE 3000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            edition_size=3000,
            release_year=2023,
            pin_type="limited edition",
            source="pintradingdb",
            source_reference_id="100",
            evidence_strength="high",
            clip_embedding=json.dumps(similar_embedding),
            image_path="catalog_images/100.jpg",
        ),
        CatalogEntry(
            canonical_name="Mickey Mouse Holiday LE 3000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            edition_size=3000,
            release_year=2023,
            pin_type="limited edition",
            source="pintradingdb",
            source_reference_id="101",
            evidence_strength="high",
            clip_embedding=json.dumps(different_embedding),
            image_path="catalog_images/101.jpg",
        ),
        CatalogEntry(
            canonical_name="Stitch Surfing Pin",
            characters=["Stitch"],
            franchise="Lilo & Stitch",
            pin_type="enamel",
            source="pintradingdb",
            source_reference_id="102",
            evidence_strength="medium",
            clip_embedding=json.dumps(different_embedding),
        ),
    ]
    db_session.add_all(entries)
    await db_session.commit()
    return db_session


@pytest.mark.asyncio
async def test_hybrid_reranks_by_visual_similarity(seeded_db_with_embeddings):
    """Two Mickey LE 3000 pins with same text score — visual similarity breaks the tie."""
    extraction = {
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
    # Query embedding similar to entry 100
    query_embedding = [0.95, 0.05, 0.0] + [0.0] * 509

    matches = await find_catalog_matches_hybrid(
        seeded_db_with_embeddings,
        extraction,
        query_embedding=query_embedding,
        max_results=3,
    )
    assert len(matches) >= 2
    # The visually similar pin should rank first
    assert matches[0]["source_reference_id"] == "100"
    assert "visual_similarity" in matches[0]


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_text_only_without_embedding(seeded_db_with_embeddings):
    """When no query embedding is provided, falls back to text-only matching."""
    extraction = {
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
    matches = await find_catalog_matches_hybrid(
        seeded_db_with_embeddings,
        extraction,
        query_embedding=None,
        max_results=3,
    )
    assert len(matches) >= 1
    # Should still return results, just without visual_similarity
    assert "visual_similarity" not in matches[0]


@pytest.mark.asyncio
async def test_hybrid_excludes_stitch_for_mickey_query(seeded_db_with_embeddings):
    """Text filtering should exclude Stitch pin from Mickey query results."""
    extraction = {
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
    query_embedding = [0.95, 0.05, 0.0] + [0.0] * 509

    matches = await find_catalog_matches_hybrid(
        seeded_db_with_embeddings,
        extraction,
        query_embedding=query_embedding,
        max_results=3,
    )
    names = [m["canonical_name"] for m in matches]
    assert not any("Stitch" in n for n in names)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_hybrid_matching.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_catalog_matches_hybrid'`

- [ ] **Step 3: Add find_catalog_matches_hybrid to matching.py**

Add the following function to the end of `src/pipeline/matching.py`:

```python
from src.pipeline.image_matching import rank_by_visual_similarity


async def find_catalog_matches_hybrid(
    db: "AsyncSession",
    extraction: dict,
    query_embedding: list[float] | None = None,
    max_text_candidates: int = 30,
    max_results: int = 5,
) -> list[dict]:
    """Hybrid matching: text scoring → CLIP visual re-ranking.

    1. Text-based scoring narrows to top max_text_candidates
    2. If query_embedding is provided, re-ranks by CLIP visual similarity
    3. Returns top max_results matches
    """
    # Step 1: Text-based scoring (existing logic)
    result = await db.execute(select(CatalogEntry))
    all_entries = result.scalars().all()

    scored = []
    for entry in all_entries:
        score = _compute_match_score(entry, extraction)
        if score > 0:
            scored.append({
                "catalog_entry_id": entry.id,
                "canonical_name": entry.canonical_name,
                "characters": entry.characters,
                "franchise": entry.franchise,
                "event": entry.event,
                "edition_size": entry.edition_size,
                "release_year": entry.release_year,
                "pin_type": entry.pin_type,
                "evidence_strength": entry.evidence_strength,
                "source_reference_id": entry.source_reference_id,
                "image_path": entry.image_path,
                "clip_embedding": entry.clip_embedding,
                "confidence": score,
                "reasoning": _build_reasoning(entry, extraction),
            })

    scored.sort(key=lambda x: x["confidence"], reverse=True)
    text_candidates = scored[:max_text_candidates]

    # Step 2: Visual re-ranking (if embedding available)
    if query_embedding is not None and text_candidates:
        candidates_with_embeddings = [
            c for c in text_candidates if c.get("clip_embedding") is not None
        ]
        if candidates_with_embeddings:
            reranked = rank_by_visual_similarity(
                query_embedding, candidates_with_embeddings, top_k=max_results
            )
            # Add back candidates without embeddings at the end
            without_embeddings = [
                c for c in text_candidates if c.get("clip_embedding") is None
            ]
            result_list = reranked + without_embeddings
            return result_list[:max_results]

    # Fallback: text-only
    return text_candidates[:max_results]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_hybrid_matching.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run existing matching tests to verify no regression**

Run: `cd disney-pin-assistant && python -m pytest tests/test_matching.py -v`
Expected: PASS (3 tests — existing tests unchanged)

- [ ] **Step 6: Commit**

```bash
cd disney-pin-assistant
git add src/pipeline/matching.py tests/test_hybrid_matching.py
git commit -m "feat: add hybrid text+visual matching pipeline with CLIP re-ranking"
```

---

### Task 7: Claude Vision Confirmation

**Files:**
- Modify: `disney-pin-assistant/src/pipeline/matching.py`
- Modify: `disney-pin-assistant/src/services/anthropic_client.py`
- Create: `disney-pin-assistant/tests/test_vision_confirmation.py`

**Context:** When the top CLIP match has similarity between 0.75 and 0.92, we send the user's photo alongside the top 3 catalog images to Claude Vision and ask it to pick the best match. This is the final confirmation step in the hybrid pipeline.

- [ ] **Step 1: Write failing tests for vision confirmation**

```python
# tests/test_vision_confirmation.py
import json
import pytest
from unittest.mock import patch, AsyncMock

from src.pipeline.matching import confirm_match_with_vision


@pytest.mark.asyncio
async def test_vision_confirms_best_match():
    candidates = [
        {
            "catalog_entry_id": 1,
            "canonical_name": "Mickey 50th Anniversary",
            "image_path": "catalog_images/100.jpg",
            "visual_similarity": 0.85,
        },
        {
            "catalog_entry_id": 2,
            "canonical_name": "Mickey Holiday",
            "image_path": "catalog_images/101.jpg",
            "visual_similarity": 0.80,
        },
    ]

    # Mock Claude returning catalog_entry_id 1 as the best match
    mock_response = json.dumps({"best_match_catalog_entry_id": 1, "confidence": "high", "reasoning": "Same pose and background design"})
    with patch("src.pipeline.matching.send_vision_request", new_callable=AsyncMock, return_value=mock_response):
        result = await confirm_match_with_vision("uploads/user_photo.jpg", candidates)

    assert result["catalog_entry_id"] == 1
    assert result["vision_confirmed"] is True


@pytest.mark.asyncio
async def test_vision_returns_none_match():
    candidates = [
        {
            "catalog_entry_id": 1,
            "canonical_name": "Mickey 50th Anniversary",
            "image_path": "catalog_images/100.jpg",
            "visual_similarity": 0.78,
        },
    ]

    mock_response = json.dumps({"best_match_catalog_entry_id": None, "confidence": "low", "reasoning": "None of these match the uploaded pin"})
    with patch("src.pipeline.matching.send_vision_request", new_callable=AsyncMock, return_value=mock_response):
        result = await confirm_match_with_vision("uploads/user_photo.jpg", candidates)

    assert result is None


@pytest.mark.asyncio
async def test_vision_handles_api_error_gracefully():
    candidates = [
        {
            "catalog_entry_id": 1,
            "canonical_name": "Mickey 50th Anniversary",
            "image_path": "catalog_images/100.jpg",
            "visual_similarity": 0.85,
        },
    ]

    with patch("src.pipeline.matching.send_vision_request", new_callable=AsyncMock, side_effect=Exception("API error")):
        result = await confirm_match_with_vision("uploads/user_photo.jpg", candidates)

    # Should return None on error, not crash
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd disney-pin-assistant && python -m pytest tests/test_vision_confirmation.py -v`
Expected: FAIL — `ImportError: cannot import name 'confirm_match_with_vision'`

- [ ] **Step 3: Implement confirm_match_with_vision**

Add to the end of `src/pipeline/matching.py`:

```python
from src.services.anthropic_client import send_vision_request

VISION_CONFIRM_PROMPT = """You are comparing a user's Disney pin photo against catalog reference images to find an exact match.

The FIRST image is the user's photo of a pin they want to identify.
The remaining images are catalog reference images of candidate pins.

For each candidate, I'll tell you its catalog_entry_id and name.

Candidates:
{candidates_text}

Compare the user's pin photo against each candidate image. Look at:
- The exact character pose and expression
- Background design, colors, and patterns
- Pin shape and border style
- Any text, numbers, or logos on the pin
- Edition markings or backstamp details

Return ONLY valid JSON:
{{
  "best_match_catalog_entry_id": <id or null if none match>,
  "confidence": "high" | "medium" | "low",
  "reasoning": "brief explanation"
}}

If NONE of the candidates match the user's pin, return null for best_match_catalog_entry_id."""


async def confirm_match_with_vision(
    user_image_path: str,
    candidates: list[dict],
) -> dict | None:
    """Use Claude Vision to confirm which catalog pin matches the user's photo.

    Returns the confirmed candidate dict with vision_confirmed=True,
    or None if no match confirmed or on error.
    """
    # Build candidate text for the prompt
    candidates_text = "\n".join(
        f"- catalog_entry_id={c['catalog_entry_id']}: {c['canonical_name']}"
        for c in candidates
    )
    prompt = VISION_CONFIRM_PROMPT.format(candidates_text=candidates_text)

    # Build image list: user photo first, then candidate images
    image_paths = [user_image_path]
    for c in candidates:
        if c.get("image_path"):
            image_paths.append(c["image_path"])

    try:
        raw_response = await send_vision_request(image_paths, prompt)
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        result = json.loads(text.strip())

        best_id = result.get("best_match_catalog_entry_id")
        if best_id is None:
            return None

        # Find the matching candidate
        for candidate in candidates:
            if candidate["catalog_entry_id"] == best_id:
                confirmed = dict(candidate)
                confirmed["vision_confirmed"] = True
                confirmed["vision_reasoning"] = result.get("reasoning", "")
                return confirmed

        return None

    except Exception as exc:
        print(f"[matching] Vision confirmation failed: {exc}")
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd disney-pin-assistant && python -m pytest tests/test_vision_confirmation.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd disney-pin-assistant
git add src/pipeline/matching.py tests/test_vision_confirmation.py
git commit -m "feat: add Claude Vision confirmation for low-confidence CLIP matches"
```

---

### Task 8: Wire Hybrid Matching into Orchestrator

**Files:**
- Modify: `disney-pin-assistant/src/pipeline/orchestrator.py:40-53`

**Context:** The orchestrator currently calls `find_catalog_matches`. This task updates it to: (1) generate a CLIP embedding from the user's uploaded photo, (2) call `find_catalog_matches_hybrid` instead, (3) trigger Claude Vision confirmation when the top match is in the 0.75–0.92 similarity range.

- [ ] **Step 1: Write failing test for orchestrator using hybrid matching**

```python
# tests/test_orchestrator_hybrid.py
import json
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.models import Base, Pin, PinStatus, CatalogEntry
from src.pipeline.orchestrator import process_single_pin


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_factory(session_factory):
    async with session_factory() as db:
        entry = CatalogEntry(
            canonical_name="Mickey Mouse Test Pin",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            pin_type="limited edition",
            source="pintradingdb",
            source_reference_id="100",
            evidence_strength="high",
            clip_embedding=json.dumps([1.0] + [0.0] * 511),
            image_path="catalog_images/100.jpg",
        )
        db.add(entry)
        pin = Pin(
            batch_id="test-batch",
            status=PinStatus.UNPROCESSED,
            image_paths=["uploads/test_pin.jpg"],
        )
        db.add(pin)
        await db.commit()
        pin_id = pin.id
    return session_factory, pin_id


@pytest.mark.asyncio
async def test_orchestrator_uses_hybrid_matching(seeded_factory):
    session_factory, pin_id = seeded_factory

    mock_extraction = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "pin_type": "limited edition",
        "edition_size": None,
        "event_clues": None,
        "visible_dates": None,
        "text_on_pin": None,
        "collection_or_series": None,
        "condition_observations": "",
        "suggested_search_terms": ["mickey mouse pin"],
        "confidence_score": 0.9,
    }
    mock_embedding = [1.0] + [0.0] * 511

    with patch("src.pipeline.orchestrator.extract_pin_metadata", new_callable=AsyncMock, return_value=mock_extraction), \
         patch("src.pipeline.orchestrator.compute_clip_embedding", return_value=mock_embedding), \
         patch("src.pipeline.orchestrator.search_comps", new_callable=AsyncMock, return_value=[]), \
         patch("src.pipeline.orchestrator.filter_comps", return_value=[]):

        await process_single_pin(session_factory, pin_id)

    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        # Should have progressed past MATCHED
        assert pin.status != PinStatus.UNPROCESSED
        assert pin.status != PinStatus.EXTRACTED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd disney-pin-assistant && python -m pytest tests/test_orchestrator_hybrid.py -v`
Expected: FAIL — `ImportError` or `AttributeError` for `compute_clip_embedding`

- [ ] **Step 3: Update orchestrator to use hybrid matching**

Replace the matching section of `src/pipeline/orchestrator.py` (the second `async with session_factory()` block, around lines 41-53):

Change the imports at the top of the file:

```python
from src.pipeline.matching import find_catalog_matches_hybrid
from src.pipeline.image_matching import compute_clip_embedding
```

Replace the matching block (lines 41-53) with:

```python
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)

        # Generate CLIP embedding from user's photo
        query_embedding = None
        try:
            if pin.image_paths:
                query_embedding = compute_clip_embedding(pin.image_paths[0])
        except Exception as exc:
            print(f"[orchestrator] CLIP embedding failed for pin {pin_id}: {exc}")

        matches = await find_catalog_matches_hybrid(
            db, extraction_data,
            query_embedding=query_embedding,
            max_results=3,
        )
        for rank, match in enumerate(matches, 1):
            catalog_match = CatalogMatch(
                pin_id=pin.id, catalog_entry_id=match["catalog_entry_id"],
                match_confidence=match.get("visual_similarity", match["confidence"]),
                match_reasoning=match["reasoning"],
                rank=rank, status=MatchStatus.SUGGESTED,
            )
            db.add(catalog_match)
        if matches:
            pin.status = PinStatus.MATCHED
        await db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd disney-pin-assistant && python -m pytest tests/test_orchestrator_hybrid.py -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests to verify no regressions**

Run: `cd disney-pin-assistant && python -m pytest tests/ -v --timeout=60`
Expected: All existing tests pass. Some may need minor adjustments if they mock `find_catalog_matches` (which is no longer called by orchestrator).

- [ ] **Step 6: Commit**

```bash
cd disney-pin-assistant
git add src/pipeline/orchestrator.py tests/test_orchestrator_hybrid.py
git commit -m "feat: wire hybrid CLIP+text matching into pin processing orchestrator"
```

---

### Task 9: Catalog Import with Embedding Generation

**Files:**
- Modify: `disney-pin-assistant/src/routes/catalog.py`
- Create: `disney-pin-assistant/tests/test_catalog_embedding_import.py`

**Context:** When importing catalog entries that have `image_path` set, automatically generate CLIP embeddings. This happens at import time so embeddings are ready for matching. Also add an endpoint to regenerate embeddings for existing entries.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_catalog_embedding_import.py
import json
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.models import Base, CatalogEntry
from src.main import app
from src.database import get_db


@pytest_asyncio.fixture
async def test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def override_get_db():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db
    yield factory
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_json_import_generates_embeddings_for_entries_with_images(test_db):
    entries = [
        {
            "canonical_name": "Test Pin With Image",
            "characters": ["Mickey Mouse"],
            "source": "pintradingdb",
            "source_reference_id": "12345",
            "image_path": "catalog_images/12345.jpg",
        }
    ]

    mock_embedding = [0.1] * 512
    with patch("src.routes.catalog.generate_embedding_for_entry", return_value=mock_embedding):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            import io
            file_content = json.dumps(entries).encode()
            response = await client.post(
                "/api/catalog/import/json",
                files={"file": ("catalog.json", io.BytesIO(file_content), "application/json")},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 1

    # Verify embedding was stored
    async with test_db() as db:
        from sqlalchemy import select
        result = await db.execute(select(CatalogEntry))
        entry = result.scalar_one()
        assert entry.clip_embedding is not None
        loaded = json.loads(entry.clip_embedding)
        assert len(loaded) == 512
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd disney-pin-assistant && python -m pytest tests/test_catalog_embedding_import.py -v`
Expected: FAIL — `ImportError: cannot import name 'generate_embedding_for_entry'`

- [ ] **Step 3: Add embedding generation to catalog import**

Add to `src/routes/catalog.py`:

```python
import json as json_module
from src.pipeline.image_matching import compute_clip_embedding


def generate_embedding_for_entry(image_path: str) -> list[float] | None:
    """Generate a CLIP embedding for a catalog entry's image.

    Returns the embedding list, or None if the image can't be processed.
    """
    import os
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        return compute_clip_embedding(image_path)
    except Exception as exc:
        print(f"[catalog] Failed to generate embedding for {image_path}: {exc}")
        return None
```

Then modify the JSON import endpoint's loop to generate embeddings when `image_path` is present. After creating each `CatalogEntry`, add:

```python
        # Generate CLIP embedding if image is available
        image_path = entry_data.get("image_path")
        if image_path:
            db_entry.image_path = image_path
            embedding = generate_embedding_for_entry(image_path)
            if embedding:
                db_entry.clip_embedding = json_module.dumps(embedding)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd disney-pin-assistant && python -m pytest tests/test_catalog_embedding_import.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd disney-pin-assistant
git add src/routes/catalog.py tests/test_catalog_embedding_import.py
git commit -m "feat: auto-generate CLIP embeddings during catalog JSON import"
```

---

### Task 10: End-to-End Integration Test

**Files:**
- Create: `disney-pin-assistant/tests/test_hybrid_integration.py`

**Context:** Verify the full pipeline works end-to-end: catalog entries with embeddings exist in DB → user uploads pin photo → orchestrator extracts metadata, generates CLIP embedding, runs hybrid matching → correct pin is identified.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_hybrid_integration.py
"""End-to-end test for hybrid text + image matching pipeline."""
import json
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from src.models import Base, Pin, PinStatus, CatalogEntry, CatalogMatch


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_factory(session_factory):
    """Seed with two Mickey pins that have identical text attributes but different embeddings."""
    async with session_factory() as db:
        # Pin A: "50th anniversary" design — embedding points in direction A
        entry_a = CatalogEntry(
            canonical_name="Mickey Mouse 50th Anniversary LE 2000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            edition_size=2000,
            release_year=2023,
            pin_type="limited edition",
            source="pintradingdb",
            source_reference_id="A",
            evidence_strength="high",
            clip_embedding=json.dumps([0.9, 0.1] + [0.0] * 510),
            image_path="catalog_images/A.jpg",
        )
        # Pin B: "Holiday" design — embedding points in direction B
        entry_b = CatalogEntry(
            canonical_name="Mickey Mouse Holiday Cheer LE 2000",
            characters=["Mickey Mouse"],
            franchise="Mickey & Friends",
            edition_size=2000,
            release_year=2023,
            pin_type="limited edition",
            source="pintradingdb",
            source_reference_id="B",
            evidence_strength="high",
            clip_embedding=json.dumps([0.1, 0.9] + [0.0] * 510),
            image_path="catalog_images/B.jpg",
        )
        pin = Pin(
            batch_id="integration-test",
            status=PinStatus.UNPROCESSED,
            image_paths=["uploads/user_pin.jpg"],
        )
        db.add_all([entry_a, entry_b, pin])
        await db.commit()
        pin_id = pin.id
    return session_factory, pin_id


@pytest.mark.asyncio
async def test_hybrid_pipeline_identifies_correct_pin(seeded_factory):
    """The user's pin looks like pin A (50th anniversary).
    Both pins have identical text attributes, so text matching alone can't distinguish them.
    CLIP embedding should identify the correct one."""
    session_factory, pin_id = seeded_factory

    mock_extraction = {
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "edition_size": 2000,
        "pin_type": "limited edition",
        "visible_dates": "2023",
        "event_clues": None,
        "text_on_pin": None,
        "collection_or_series": None,
        "condition_observations": "",
        "suggested_search_terms": ["mickey mouse anniversary pin"],
        "confidence_score": 0.9,
    }
    # User's photo embedding is close to pin A
    mock_embedding = [0.95, 0.05] + [0.0] * 510

    with patch("src.pipeline.orchestrator.extract_pin_metadata", new_callable=AsyncMock, return_value=mock_extraction), \
         patch("src.pipeline.orchestrator.compute_clip_embedding", return_value=mock_embedding), \
         patch("src.pipeline.orchestrator.search_comps", new_callable=AsyncMock, return_value=[]), \
         patch("src.pipeline.orchestrator.filter_comps", return_value=[]):

        from src.pipeline.orchestrator import process_single_pin
        await process_single_pin(session_factory, pin_id)

    # Verify: pin A should be the top match
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        assert pin.status in (PinStatus.MATCHED, PinStatus.PRICED)

        result = await db.execute(
            select(CatalogMatch)
            .where(CatalogMatch.pin_id == pin_id)
            .order_by(CatalogMatch.rank)
        )
        matches = result.scalars().all()
        assert len(matches) >= 1

        top_match = matches[0]
        top_entry = await db.get(CatalogEntry, top_match.catalog_entry_id)
        assert top_entry.source_reference_id == "A"
```

- [ ] **Step 2: Run the integration test**

Run: `cd disney-pin-assistant && python -m pytest tests/test_hybrid_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `cd disney-pin-assistant && python -m pytest tests/ -v --timeout=60`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
cd disney-pin-assistant
git add tests/test_hybrid_integration.py
git commit -m "test: add end-to-end integration test for hybrid matching pipeline"
```

---

## Summary

| Task | What it builds | Key files |
|------|---------------|-----------|
| 1 | Model columns + dependencies | `models.py`, `pyproject.toml`, `.gitignore` |
| 2 | PinTradingDB HTML parser | `pintradingdb_parser.py` |
| 3 | PinTradingDB HTTP fetcher + image download | `pintradingdb_fetcher.py` |
| 4 | Scraper CLI | `scrape_pintradingdb.py` |
| 5 | CLIP embedding module | `image_matching.py` |
| 6 | Hybrid matching function | `matching.py` (new function) |
| 7 | Claude Vision confirmation | `matching.py` (new function) |
| 8 | Orchestrator integration | `orchestrator.py` |
| 9 | Catalog import with embeddings | `catalog.py` |
| 10 | End-to-end integration test | `test_hybrid_integration.py` |
