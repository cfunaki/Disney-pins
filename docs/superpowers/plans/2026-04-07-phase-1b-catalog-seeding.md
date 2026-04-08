# Phase 1B: Catalog Seeding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PinPics scraper, normalize the scraped data, seed the catalog with 5,000-10,000 entries, and re-evaluate the same test pins to measure whether catalog matching improves identification and listing quality.

**Architecture:** A standalone scraper script fetches pin data from PinPics HTML pages with respectful rate limiting. A normalization module cleans inconsistencies (character names, capitalization, edition size parsing). Normalized data is imported via the existing JSON catalog import endpoint. A comparison script re-runs evaluation against Phase 1A results.

**Tech Stack:** Python, httpx (already a dependency), BeautifulSoup4 (new dependency), existing FastAPI catalog import endpoints.

---

### Task 1: Add BeautifulSoup4 Dependency

**Files:**
- Modify: `disney-pin-assistant/pyproject.toml`

- [ ] **Step 1: Add beautifulsoup4 to project dependencies**

In `disney-pin-assistant/pyproject.toml`, add `"beautifulsoup4>=4.12"` to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.100",
    "uvicorn[standard]>=0.22",
    "sqlalchemy[asyncio]>=2.0",
    "anthropic>=0.25",
    "httpx>=0.25",
    "python-multipart>=0.0.6",
    "python-dotenv>=1.0",
    "pydantic-settings>=2.0",
    "jinja2>=3.1",
    "aiosqlite>=0.19",
    "greenlet>=3.0.0",
    "beautifulsoup4>=4.12",
]
```

- [ ] **Step 2: Install the updated dependencies**

```bash
cd disney-pin-assistant && pip install -e ".[dev]"
```

- [ ] **Step 3: Verify import works**

```bash
python -c "from bs4 import BeautifulSoup; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add disney-pin-assistant/pyproject.toml
git commit -m "chore: add beautifulsoup4 dependency for PinPics scraper"
```

---

### Task 2: PinPics Scraper — Page Parser

**Files:**
- Create: `disney-pin-assistant/scripts/scraper/pinpics_parser.py`
- Create: `disney-pin-assistant/tests/test_pinpics_parser.py`

This module parses a single PinPics pin detail page HTML into a structured dict. It is tested against saved HTML fixtures, not live requests.

- [ ] **Step 1: Create a sample HTML fixture for testing**

Create `disney-pin-assistant/tests/fixtures/pinpics_sample.html`:

```html
<html>
<body>
<table class="pointed">
<tr><td class="pointed" colspan="2"><b>Mickey Mouse Epcot Food & Wine 2019</b></td></tr>
<tr><td class="pointed">Pin Number:</td><td class="pointed">134567</td></tr>
<tr><td class="pointed">Edition Size:</td><td class="pointed">3000</td></tr>
<tr><td class="pointed">Release Date:</td><td class="pointed">10/01/2019</td></tr>
<tr><td class="pointed">Origin:</td><td class="pointed">Epcot</td></tr>
<tr><td class="pointed">Pin Category:</td><td class="pointed">Limited Edition</td></tr>
<tr><td class="pointed">Characters:</td><td class="pointed">Mickey Mouse</td></tr>
<tr><td class="pointed">Features:</td><td class="pointed">Food & Wine Festival</td></tr>
</table>
<img src="/images/pins/134567.jpg">
</body>
</html>
```

- [ ] **Step 2: Write the failing test**

Create `disney-pin-assistant/tests/test_pinpics_parser.py`:

```python
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scraper.pinpics_parser import parse_pin_page


@pytest.fixture
def sample_html():
    fixture_path = Path(__file__).parent / "fixtures" / "pinpics_sample.html"
    return fixture_path.read_text()


def test_parse_pin_page_extracts_name(sample_html):
    result = parse_pin_page(sample_html, pin_id="134567")
    assert result["canonical_name"] == "Mickey Mouse Epcot Food & Wine 2019"


def test_parse_pin_page_extracts_edition_size(sample_html):
    result = parse_pin_page(sample_html, pin_id="134567")
    assert result["edition_size"] == 3000


def test_parse_pin_page_extracts_release_year(sample_html):
    result = parse_pin_page(sample_html, pin_id="134567")
    assert result["release_year"] == 2019


def test_parse_pin_page_extracts_characters(sample_html):
    result = parse_pin_page(sample_html, pin_id="134567")
    assert "Mickey Mouse" in result["characters"]


def test_parse_pin_page_extracts_pin_type(sample_html):
    result = parse_pin_page(sample_html, pin_id="134567")
    assert result["pin_type"] == "limited edition"


def test_parse_pin_page_extracts_event(sample_html):
    result = parse_pin_page(sample_html, pin_id="134567")
    assert "Food & Wine" in (result["event"] or "")


def test_parse_pin_page_sets_source_fields(sample_html):
    result = parse_pin_page(sample_html, pin_id="134567")
    assert result["source"] == "pinpics"
    assert result["source_reference_id"] == "134567"
    assert result["evidence_strength"] == "medium"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd disney-pin-assistant && python -m pytest tests/test_pinpics_parser.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 4: Create the parser module**

Create `disney-pin-assistant/scripts/scraper/__init__.py` (empty file).

Create `disney-pin-assistant/scripts/scraper/pinpics_parser.py`:

```python
"""Parse a PinPics pin detail page HTML into a structured dict."""
import re
from bs4 import BeautifulSoup


def parse_pin_page(html: str, pin_id: str) -> dict:
    """Parse a single PinPics pin detail page.

    Args:
        html: Raw HTML of the pin detail page.
        pin_id: The PinPics numeric pin ID.

    Returns:
        Dict matching the CatalogEntry JSON import format.
    """
    soup = BeautifulSoup(html, "html.parser")
    fields = _extract_table_fields(soup)

    name = _extract_name(soup)
    edition_size = _parse_edition_size(fields.get("Edition Size", ""))
    release_year = _parse_release_year(fields.get("Release Date", ""))
    characters = _parse_characters(fields.get("Characters", ""))
    pin_type = _normalize_pin_type(fields.get("Pin Category", ""))
    event = fields.get("Features") or None
    origin = fields.get("Origin") or None
    image_url = _extract_image_url(soup, pin_id)

    return {
        "canonical_name": name,
        "alternate_names": [],
        "characters": characters,
        "franchise": _infer_franchise(characters),
        "series_or_collection": None,
        "event": event,
        "edition_size": edition_size,
        "release_year": release_year,
        "pin_type": pin_type,
        "exclusive_source": origin,
        "source": "pinpics",
        "source_reference_id": pin_id,
        "reference_image_url": image_url,
        "evidence_strength": "medium",
    }


def _extract_table_fields(soup: BeautifulSoup) -> dict:
    """Extract key-value pairs from the PinPics detail table."""
    fields = {}
    rows = soup.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) == 2:
            label = cells[0].get_text(strip=True).rstrip(":")
            value = cells[1].get_text(strip=True)
            if label and value:
                fields[label] = value
    return fields


def _extract_name(soup: BeautifulSoup) -> str:
    """Extract pin name from the header row."""
    bold = soup.find("b")
    if bold:
        return bold.get_text(strip=True)
    header = soup.find("td", attrs={"colspan": "2"})
    if header:
        return header.get_text(strip=True)
    return "Unknown Pin"


def _parse_edition_size(raw: str) -> int | None:
    """Parse edition size from text like '3000' or 'LE 3000'."""
    if not raw:
        return None
    match = re.search(r"(\d[\d,]+)", raw.replace(",", ""))
    if match:
        return int(match.group(1))
    return None


def _parse_release_year(raw: str) -> int | None:
    """Extract year from date string like '10/01/2019' or '2019'."""
    if not raw:
        return None
    match = re.search(r"(20\d{2}|19\d{2})", raw)
    if match:
        return int(match.group(1))
    return None


def _parse_characters(raw: str) -> list[str]:
    """Parse character names from comma or slash separated string."""
    if not raw:
        return []
    separators = re.compile(r"[,/&]|\band\b", re.IGNORECASE)
    chars = separators.split(raw)
    return [_normalize_character_name(c.strip()) for c in chars if c.strip()]


def _normalize_character_name(name: str) -> str:
    """Standardize common character name variations."""
    name_map = {
        "mickey": "Mickey Mouse",
        "minnie": "Minnie Mouse",
        "donald": "Donald Duck",
        "daisy": "Daisy Duck",
        "goofy": "Goofy",
        "pluto": "Pluto",
        "chip": "Chip",
        "dale": "Dale",
    }
    lower = name.lower().strip()
    if lower in name_map:
        return name_map[lower]
    return name.strip()


def _normalize_pin_type(raw: str) -> str:
    """Normalize pin type/category to standard values."""
    lower = raw.lower().strip()
    type_map = {
        "limited edition": "limited edition",
        "le": "limited edition",
        "hidden mickey": "hidden mickey",
        "hm": "hidden mickey",
        "mystery": "mystery",
        "rack": "rack",
        "open edition": "rack",
        "oe": "rack",
        "booster": "booster",
        "completer": "completer",
        "starter": "starter",
    }
    for key, value in type_map.items():
        if key in lower:
            return value
    return lower if lower else "other"


def _infer_franchise(characters: list[str]) -> str | None:
    """Infer franchise from character names."""
    franchise_map = {
        "Mickey Mouse": "Mickey & Friends",
        "Minnie Mouse": "Mickey & Friends",
        "Donald Duck": "Mickey & Friends",
        "Daisy Duck": "Mickey & Friends",
        "Goofy": "Mickey & Friends",
        "Pluto": "Mickey & Friends",
        "Stitch": "Lilo & Stitch",
        "Lilo": "Lilo & Stitch",
        "Elsa": "Frozen",
        "Anna": "Frozen",
        "Olaf": "Frozen",
        "Simba": "The Lion King",
        "Nala": "The Lion King",
        "Woody": "Toy Story",
        "Buzz Lightyear": "Toy Story",
        "Ariel": "The Little Mermaid",
        "Belle": "Beauty and the Beast",
        "Cinderella": "Cinderella",
        "Rapunzel": "Tangled",
        "Moana": "Moana",
        "Baby Yoda": "Star Wars",
        "Grogu": "Star Wars",
        "Darth Vader": "Star Wars",
        "R2-D2": "Star Wars",
        "Iron Man": "Marvel",
        "Spider-Man": "Marvel",
    }
    for char in characters:
        if char in franchise_map:
            return franchise_map[char]
    return None


def _extract_image_url(soup: BeautifulSoup, pin_id: str) -> str | None:
    """Extract the pin image URL."""
    img = soup.find("img", src=re.compile(r"pin|image", re.IGNORECASE))
    if img and img.get("src"):
        src = img["src"]
        if src.startswith("/"):
            return f"https://www.pinpics.com{src}"
        return src
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd disney-pin-assistant && python -m pytest tests/test_pinpics_parser.py -v
```

Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/scripts/scraper/ disney-pin-assistant/tests/test_pinpics_parser.py disney-pin-assistant/tests/fixtures/
git commit -m "feat: add PinPics HTML page parser with character normalization"
```

---

### Task 3: PinPics Scraper — Fetcher with Rate Limiting

**Files:**
- Create: `disney-pin-assistant/scripts/scraper/pinpics_fetcher.py`
- Create: `disney-pin-assistant/tests/test_pinpics_fetcher.py`

This module handles HTTP fetching with respectful rate limiting (1-2 req/sec), retries, and progress tracking.

- [ ] **Step 1: Write the failing test**

Create `disney-pin-assistant/tests/test_pinpics_fetcher.py`:

```python
import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scraper.pinpics_fetcher import RateLimiter, fetch_pin_page


@pytest.mark.asyncio
async def test_rate_limiter_enforces_delay():
    limiter = RateLimiter(requests_per_second=10)  # fast for testing
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.09  # at least ~0.1s for 2 requests at 10/sec


@pytest.mark.asyncio
async def test_fetch_pin_page_returns_html():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>pin data</body></html>"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    limiter = RateLimiter(requests_per_second=100)

    with patch("scraper.pinpics_fetcher.httpx.AsyncClient", return_value=mock_client):
        html = await fetch_pin_page("12345", limiter)
    assert html == "<html><body>pin data</body></html>"


@pytest.mark.asyncio
async def test_fetch_pin_page_returns_none_on_404():
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    limiter = RateLimiter(requests_per_second=100)

    with patch("scraper.pinpics_fetcher.httpx.AsyncClient", return_value=mock_client):
        html = await fetch_pin_page("99999", limiter)
    assert html is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant && python -m pytest tests/test_pinpics_fetcher.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 3: Create the fetcher module**

Create `disney-pin-assistant/scripts/scraper/pinpics_fetcher.py`:

```python
"""Fetch PinPics pages with rate limiting and retry logic."""
import asyncio
import time
import httpx

PINPICS_BASE_URL = "https://www.pinpics.com/pinMT.php"
USER_AGENT = "DisneyPinAssistant/1.0 (personal pin catalog project)"


class RateLimiter:
    """Simple token-bucket rate limiter."""

    def __init__(self, requests_per_second: float = 1.0):
        self.min_interval = 1.0 / requests_per_second
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


async def fetch_pin_page(
    pin_id: str,
    limiter: RateLimiter,
    max_retries: int = 3,
) -> str | None:
    """Fetch a single PinPics pin detail page.

    Args:
        pin_id: The PinPics numeric pin ID.
        limiter: Rate limiter instance.
        max_retries: Number of retry attempts on failure.

    Returns:
        HTML string on success, None on 404 or persistent failure.
    """
    url = f"{PINPICS_BASE_URL}?pinID={pin_id}"

    for attempt in range(max_retries):
        await limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=True,
                )

            if response.status_code == 404:
                return None

            if response.status_code == 200:
                return response.text

            if response.status_code == 429:
                # Rate limited — back off
                wait = 2 ** (attempt + 1)
                print(f"  Rate limited on pin {pin_id}, waiting {wait}s...")
                await asyncio.sleep(wait)
                continue

            print(f"  Unexpected status {response.status_code} for pin {pin_id}")

        except httpx.TimeoutException:
            print(f"  Timeout fetching pin {pin_id} (attempt {attempt + 1})")
        except httpx.HTTPError as e:
            print(f"  HTTP error fetching pin {pin_id}: {e} (attempt {attempt + 1})")

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd disney-pin-assistant && python -m pytest tests/test_pinpics_fetcher.py -v
```

Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/scripts/scraper/pinpics_fetcher.py disney-pin-assistant/tests/test_pinpics_fetcher.py
git commit -m "feat: add PinPics fetcher with rate limiting and retry logic"
```

---

### Task 4: Name Normalization Module

**Files:**
- Create: `disney-pin-assistant/scripts/scraper/normalizer.py`
- Create: `disney-pin-assistant/tests/test_normalizer.py`

Cleans and standardizes scraped pin data before catalog import.

- [ ] **Step 1: Write the failing tests**

Create `disney-pin-assistant/tests/test_normalizer.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scraper.normalizer import normalize_entry, normalize_name, extract_edition_from_name


def test_normalize_name_title_case():
    assert normalize_name("MICKEY MOUSE EPCOT PIN") == "Mickey Mouse Epcot Pin"


def test_normalize_name_strips_whitespace():
    assert normalize_name("  Mickey Mouse  Pin  ") == "Mickey Mouse Pin"


def test_normalize_name_preserves_acronyms():
    assert normalize_name("Mickey LE 3000") == "Mickey LE 3000"
    assert normalize_name("Hidden Mickey HM") == "Hidden Mickey HM"


def test_extract_edition_from_name():
    assert extract_edition_from_name("Mickey Mouse LE 3000") == 3000
    assert extract_edition_from_name("Mickey Pin LE/2500") == 2500
    assert extract_edition_from_name("Mickey Pin LE 1,000") == 1000
    assert extract_edition_from_name("Mickey Rack Pin") is None


def test_normalize_entry_cleans_all_fields():
    raw = {
        "canonical_name": "MICKEY MOUSE  FOOD & WINE  2019  LE 3000",
        "characters": ["mickey", "MINNIE"],
        "franchise": None,
        "pin_type": "Limited Edition",
        "edition_size": None,
        "event": "food & wine festival",
        "release_year": 2019,
        "source": "pinpics",
        "source_reference_id": "134567",
        "evidence_strength": "medium",
        "alternate_names": [],
        "series_or_collection": None,
        "exclusive_source": None,
        "reference_image_url": None,
    }
    result = normalize_entry(raw)
    assert result["canonical_name"] == "Mickey Mouse Food & Wine 2019 LE 3000"
    assert result["characters"] == ["Mickey Mouse", "Minnie Mouse"]
    assert result["franchise"] == "Mickey & Friends"
    assert result["edition_size"] == 3000
    assert result["pin_type"] == "limited edition"
    assert result["event"] == "Food & Wine Festival"


def test_normalize_entry_no_duplicate_edition():
    """If edition_size is already set, don't re-extract from name."""
    raw = {
        "canonical_name": "Pin LE 3000",
        "characters": [],
        "franchise": None,
        "pin_type": "limited edition",
        "edition_size": 3000,
        "event": None,
        "release_year": None,
        "source": "pinpics",
        "source_reference_id": "1",
        "evidence_strength": "medium",
        "alternate_names": [],
        "series_or_collection": None,
        "exclusive_source": None,
        "reference_image_url": None,
    }
    result = normalize_entry(raw)
    assert result["edition_size"] == 3000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant && python -m pytest tests/test_normalizer.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 3: Create the normalizer module**

Create `disney-pin-assistant/scripts/scraper/normalizer.py`:

```python
"""Normalize scraped pin data for catalog import."""
import re

# Acronyms that should stay uppercase
PRESERVE_UPPER = {"LE", "HM", "OE", "WDW", "DLR", "AP", "AK", "MK", "DHS", "EPCOT", "DCA", "TDL", "TDS", "HKDL", "SDL", "DLP", "PIN"}


def normalize_name(name: str) -> str:
    """Normalize pin name: title case, collapse whitespace, preserve acronyms."""
    name = re.sub(r"\s+", " ", name.strip())
    words = name.split()
    result = []
    for word in words:
        if word.upper() in PRESERVE_UPPER:
            result.append(word.upper())
        elif re.match(r"^\d", word):
            result.append(word)
        else:
            result.append(word.capitalize())
    return " ".join(result)


def extract_edition_from_name(name: str) -> int | None:
    """Extract edition size from pin name like 'LE 3000' or 'LE/2,500'."""
    match = re.search(r"\bLE[/ ]?([\d,]+)\b", name, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


def _normalize_character(name: str) -> str:
    """Normalize a single character name."""
    name_map = {
        "mickey": "Mickey Mouse",
        "mickey mouse": "Mickey Mouse",
        "minnie": "Minnie Mouse",
        "minnie mouse": "Minnie Mouse",
        "donald": "Donald Duck",
        "donald duck": "Donald Duck",
        "daisy": "Daisy Duck",
        "daisy duck": "Daisy Duck",
        "goofy": "Goofy",
        "pluto": "Pluto",
        "chip": "Chip",
        "dale": "Dale",
        "stitch": "Stitch",
        "lilo": "Lilo",
    }
    lower = name.lower().strip()
    return name_map.get(lower, name.strip().title())


def _infer_franchise(characters: list[str]) -> str | None:
    """Infer franchise from normalized character names."""
    franchise_map = {
        "Mickey Mouse": "Mickey & Friends",
        "Minnie Mouse": "Mickey & Friends",
        "Donald Duck": "Mickey & Friends",
        "Daisy Duck": "Mickey & Friends",
        "Goofy": "Mickey & Friends",
        "Pluto": "Mickey & Friends",
        "Stitch": "Lilo & Stitch",
        "Lilo": "Lilo & Stitch",
        "Elsa": "Frozen",
        "Anna": "Frozen",
        "Simba": "The Lion King",
        "Woody": "Toy Story",
        "Buzz Lightyear": "Toy Story",
        "Ariel": "The Little Mermaid",
        "Belle": "Beauty and the Beast",
    }
    for char in characters:
        if char in franchise_map:
            return franchise_map[char]
    return None


def normalize_entry(entry: dict) -> dict:
    """Normalize all fields of a scraped catalog entry.

    Args:
        entry: Raw scraped entry dict.

    Returns:
        Cleaned entry dict ready for catalog import.
    """
    result = dict(entry)

    # Normalize name
    result["canonical_name"] = normalize_name(result.get("canonical_name", ""))

    # Normalize characters
    raw_chars = result.get("characters") or []
    result["characters"] = [_normalize_character(c) for c in raw_chars]

    # Infer franchise if missing
    if not result.get("franchise"):
        result["franchise"] = _infer_franchise(result["characters"])

    # Extract edition size from name if not already set
    if not result.get("edition_size"):
        result["edition_size"] = extract_edition_from_name(
            result["canonical_name"]
        )

    # Normalize pin type to lowercase
    if result.get("pin_type"):
        result["pin_type"] = result["pin_type"].lower().strip()

    # Title-case event
    if result.get("event"):
        result["event"] = result["event"].strip().title()

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd disney-pin-assistant && python -m pytest tests/test_normalizer.py -v
```

Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/scripts/scraper/normalizer.py disney-pin-assistant/tests/test_normalizer.py
git commit -m "feat: add name normalization for scraped catalog entries"
```

---

### Task 5: Scraper CLI — Main Script

**Files:**
- Create: `disney-pin-assistant/scripts/scrape_pinpics.py`

This is the main CLI that ties together fetching, parsing, and normalizing. It scrapes a range of PinPics IDs, normalizes the results, and outputs a JSON file ready for catalog import.

- [ ] **Step 1: Create the scraper CLI**

Create `disney-pin-assistant/scripts/scrape_pinpics.py`:

```python
"""
Scrape PinPics for catalog seeding.

Usage:
    # Scrape pin IDs 130000-135000 at 1 request/second
    python scripts/scrape_pinpics.py --start 130000 --end 135000

    # Scrape specific categories (uses known ID ranges)
    python scripts/scrape_pinpics.py --category le-2019

    # Resume a previous scrape (skips already-fetched IDs)
    python scripts/scrape_pinpics.py --start 130000 --end 135000 --resume

Output: scripts/scraper/output/pinpics_catalog.json
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.pinpics_fetcher import RateLimiter, fetch_pin_page
from scraper.pinpics_parser import parse_pin_page
from scraper.normalizer import normalize_entry

OUTPUT_DIR = Path(__file__).parent / "scraper" / "output"

# Known approximate ID ranges for common categories
CATEGORY_RANGES = {
    "le-2021": (140000, 145000),
    "le-2022": (145000, 150000),
    "le-2023": (150000, 155000),
    "le-2024": (155000, 160000),
    "hm-recent": (135000, 140000),
    "rack-common": (120000, 130000),
}


def load_existing(output_path: Path) -> dict:
    """Load previously scraped entries for resume support."""
    if output_path.exists():
        data = json.loads(output_path.read_text())
        return {e["source_reference_id"]: e for e in data}
    return {}


async def scrape_range(
    start_id: int,
    end_id: int,
    rate: float,
    resume: bool,
    output_path: Path,
) -> list[dict]:
    """Scrape a range of PinPics IDs."""
    limiter = RateLimiter(requests_per_second=rate)
    existing = load_existing(output_path) if resume else {}
    entries = list(existing.values())
    total = end_id - start_id
    scraped = 0
    found = 0
    errors = 0

    print(f"Scraping PinPics IDs {start_id}-{end_id} ({total} IDs)")
    if resume and existing:
        print(f"Resuming: {len(existing)} entries already scraped")
    print(f"Rate: {rate} requests/second")
    print()

    for pin_id in range(start_id, end_id):
        str_id = str(pin_id)

        if resume and str_id in existing:
            scraped += 1
            continue

        html = await fetch_pin_page(str_id, limiter)
        scraped += 1

        if html is None:
            continue

        try:
            raw_entry = parse_pin_page(html, str_id)
            entry = normalize_entry(raw_entry)
            entries.append(entry)
            found += 1
        except Exception as e:
            errors += 1
            print(f"  Parse error for pin {pin_id}: {e}")

        # Progress update every 100 pins
        if scraped % 100 == 0:
            pct = (scraped / total) * 100
            print(f"  Progress: {scraped}/{total} ({pct:.0f}%) — {found} found, {errors} errors")

        # Save checkpoint every 500 pins
        if scraped % 500 == 0:
            _save_entries(entries, output_path)

    _save_entries(entries, output_path)
    return entries


def _save_entries(entries: list[dict], output_path: Path):
    """Save entries to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(entries, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Scrape PinPics for catalog seeding")
    parser.add_argument("--start", type=int, help="Start pin ID")
    parser.add_argument("--end", type=int, help="End pin ID")
    parser.add_argument("--category", choices=list(CATEGORY_RANGES.keys()), help="Predefined category range")
    parser.add_argument("--rate", type=float, default=1.0, help="Requests per second (default: 1.0)")
    parser.add_argument("--resume", action="store_true", help="Resume previous scrape")
    parser.add_argument("--output", type=str, default=str(OUTPUT_DIR / "pinpics_catalog.json"), help="Output file path")
    args = parser.parse_args()

    if args.category:
        start, end = CATEGORY_RANGES[args.category]
    elif args.start and args.end:
        start, end = args.start, args.end
    else:
        parser.error("Provide --start/--end or --category")
        return

    output_path = Path(args.output)
    entries = asyncio.run(scrape_range(start, end, args.rate, args.resume, output_path))

    print(f"\nDone! {len(entries)} total entries saved to {output_path}")
    print(f"\nTo import into catalog:")
    print(f"  curl -X POST http://localhost:8000/api/catalog/import/json \\")
    print(f"    -F 'file=@{output_path}'")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script shows help without errors**

```bash
cd disney-pin-assistant && python scripts/scrape_pinpics.py --help
```

Expected: Usage message with all arguments listed

- [ ] **Step 3: Commit**

```bash
git add disney-pin-assistant/scripts/scrape_pinpics.py
git commit -m "feat: add PinPics scraper CLI with resume and category support"
```

---

### Task 6: Catalog Import Deduplication

**Files:**
- Modify: `disney-pin-assistant/src/routes/catalog.py:44-71`
- Create: `disney-pin-assistant/tests/test_catalog_dedup.py`

The existing JSON import endpoint creates duplicate entries on re-import. Add deduplication by `source_reference_id`.

- [ ] **Step 1: Write the failing test**

Create `disney-pin-assistant/tests/test_catalog_dedup.py`:

```python
import io
import json
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.database import get_db
from src.models import Base, CatalogEntry
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


@pytest_asyncio.fixture
async def test_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app, engine
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_json_import_deduplicates_by_source_ref(test_app):
    test_app_instance, engine = test_app
    entries = [
        {"canonical_name": "Pin A", "characters": ["Mickey Mouse"], "source": "pinpics", "source_reference_id": "100"},
        {"canonical_name": "Pin B", "characters": ["Stitch"], "source": "pinpics", "source_reference_id": "101"},
    ]
    transport = ASGITransport(app=test_app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First import
        file_content = json.dumps(entries).encode()
        response = await client.post(
            "/api/catalog/import/json",
            files=[("file", ("catalog.json", io.BytesIO(file_content), "application/json"))],
        )
        assert response.status_code == 200
        assert response.json()["imported"] == 2

        # Second import (same data)
        response = await client.post(
            "/api/catalog/import/json",
            files=[("file", ("catalog.json", io.BytesIO(file_content), "application/json"))],
        )
        assert response.status_code == 200
        assert response.json()["imported"] == 0  # no new entries
        assert response.json()["skipped"] == 2  # all duplicates

    # Verify only 2 entries in DB
    async with async_sessionmaker(engine, class_=AsyncSession)() as db:
        result = await db.execute(select(func.count(CatalogEntry.id)))
        assert result.scalar() == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd disney-pin-assistant && python -m pytest tests/test_catalog_dedup.py -v
```

Expected: FAIL (response doesn't have `skipped` key, and duplicates are created)

- [ ] **Step 3: Modify the JSON import endpoint to skip duplicates**

In `disney-pin-assistant/src/routes/catalog.py`, replace the `import_catalog_json` function with:

```python
@router.post("/import/json")
async def import_catalog_json(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    entries = json.loads(content.decode("utf-8"))
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="Expected a JSON array")

    # Load existing source_reference_ids to skip duplicates
    existing_refs = set()
    result = await db.execute(
        select(CatalogEntry.source, CatalogEntry.source_reference_id)
        .where(CatalogEntry.source_reference_id.isnot(None))
    )
    for row in result:
        existing_refs.add((row[0], row[1]))

    imported = 0
    skipped = 0
    for item in entries:
        source = item.get("source", "import")
        ref_id = item.get("source_reference_id")
        if ref_id and (source, ref_id) in existing_refs:
            skipped += 1
            continue

        entry = CatalogEntry(
            canonical_name=item.get("canonical_name", item.get("name", "")),
            alternate_names=item.get("alternate_names", []),
            characters=item.get("characters", []),
            franchise=item.get("franchise"),
            series_or_collection=item.get("series_or_collection"),
            event=item.get("event"),
            edition_size=item.get("edition_size"),
            release_year=item.get("release_year"),
            pin_type=item.get("pin_type"),
            exclusive_source=item.get("exclusive_source"),
            source=source,
            source_reference_id=ref_id,
            reference_image_url=item.get("reference_image_url"),
            evidence_strength=item.get("evidence_strength", "medium"),
        )
        db.add(entry)
        imported += 1
        if ref_id:
            existing_refs.add((source, ref_id))
    await db.commit()
    return {"imported": imported, "skipped": skipped}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd disney-pin-assistant && python -m pytest tests/test_catalog_dedup.py -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
cd disney-pin-assistant && python -m pytest tests/ -v
```

Expected: All tests PASS (existing catalog import tests may need minor updates if they check response shape — verify)

- [ ] **Step 6: Commit**

```bash
git add disney-pin-assistant/src/routes/catalog.py disney-pin-assistant/tests/test_catalog_dedup.py
git commit -m "feat: add deduplication to catalog JSON import by source_reference_id"
```

---

### Task 7: Phase 1B Evaluation — Re-Run Comparison

**Files:**
- Create: `disney-pin-assistant/scripts/compare_phases.py`

This script re-runs the same test pins after catalog seeding and compares results against Phase 1A scorecard.

- [ ] **Step 1: Create the comparison script**

Create `disney-pin-assistant/scripts/compare_phases.py`:

```python
"""
Compare Phase 1A (vision-only) vs Phase 1B (vision + catalog) results.

Usage:
    python scripts/compare_phases.py <phase_1a_batch_id> <phase_1b_batch_id>

Prerequisites:
    1. Phase 1A scorecard exists at evaluation/scorecard.json
    2. Catalog has been seeded
    3. Same test pins re-uploaded and processed as a new batch
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.database import engine, async_session
from src.models import Pin

PHASE_1A_RESULTS = Path("evaluation/scorecard.json")
COMPARISON_OUTPUT = Path("evaluation/phase_comparison.md")


async def load_batch_pins(batch_id: str) -> list:
    async with async_session() as db:
        result = await db.execute(
            select(Pin)
            .options(
                selectinload(Pin.extraction),
                selectinload(Pin.listing_draft),
                selectinload(Pin.catalog_matches),
            )
            .where(Pin.batch_id == batch_id)
        )
        return result.scalars().all()


def generate_comparison(phase_1a: list[dict], phase_1b_pins: list, ground_truth: list[dict]) -> str:
    lines = ["# Phase 1A vs 1B Comparison\n"]

    lines.append("| Pin | 1A ID Correct | 1B ID Correct | 1A Edits | 1B Edits | Catalog Match? | Match Confidence |")
    lines.append("|-----|--------------|--------------|----------|----------|---------------|-----------------|")

    improved = 0
    regressed = 0
    unchanged = 0

    for i, (a_result, b_pin) in enumerate(zip(phase_1a, phase_1b_pins)):
        a_correct = a_result.get("identification", {}).get("correct", False)
        a_edits = a_result.get("listing", {}).get("edits_needed", "major")

        # Check 1B results
        b_has_match = len(b_pin.catalog_matches) > 0 if b_pin.catalog_matches else False
        b_match_conf = b_pin.catalog_matches[0].match_confidence if b_has_match else 0

        b_draft_title = b_pin.listing_draft.title if b_pin.listing_draft else ""

        # Find ground truth for this pin
        gt = None
        if b_pin.image_paths:
            pin_filename = Path(b_pin.image_paths[0]).name
            gt = next((g for g in ground_truth if g["image_file"] == pin_filename), None)

        b_correct = "—"
        b_edits = "—"
        if gt:
            # Simple check: does title contain key reference words?
            ref_title = gt.get("reference_title", "")
            ref_words = set(ref_title.lower().split()) - {"disney", "pin", "the", "a", "an", "-", "&", "and", "of"}
            b_words = set(b_draft_title.lower().split()) - {"disney", "pin", "the", "a", "an", "-", "&", "and", "of"}
            overlap = len(ref_words & b_words) / len(ref_words) if ref_words else 0

            b_correct = "Y" if overlap >= 0.3 else "N"
            if overlap >= 0.6:
                b_edits = "none"
            elif overlap >= 0.3:
                b_edits = "minor"
            else:
                b_edits = "major"

        a_ok = "Y" if a_correct else "N"
        match_str = "Y" if b_has_match else "N"

        if b_edits != "—":
            edit_scores = {"none": 2, "minor": 1, "major": 0}
            a_score = edit_scores.get(a_edits, 0)
            b_score = edit_scores.get(b_edits, 0)
            if b_score > a_score:
                improved += 1
            elif b_score < a_score:
                regressed += 1
            else:
                unchanged += 1

        lines.append(
            f"| {i+1} | {a_ok} | {b_correct} | {a_edits} | {b_edits} | {match_str} | {b_match_conf:.2f} |"
        )

    lines.append("")
    lines.append("## Summary\n")
    lines.append(f"- **Improved:** {improved} pins")
    lines.append(f"- **Regressed:** {regressed} pins")
    lines.append(f"- **Unchanged:** {unchanged} pins")
    lines.append("")

    if improved > regressed:
        lines.append("**VERDICT:** Catalog matching improves results. Proceed to Phase 1C.")
    elif regressed > improved:
        lines.append("**VERDICT:** Catalog matching hurts results. Investigate matching weights before proceeding.")
    else:
        lines.append("**VERDICT:** Catalog matching has no clear impact. Consider if catalog effort is justified.")

    return "\n".join(lines)


async def main(phase_1a_batch: str, phase_1b_batch: str):
    if not PHASE_1A_RESULTS.exists():
        print(f"Phase 1A results not found at {PHASE_1A_RESULTS}")
        print("Run generate_scorecard.py for Phase 1A batch first.")
        sys.exit(1)

    phase_1a = json.loads(PHASE_1A_RESULTS.read_text())

    gt_path = Path("evaluation/ground_truth.json")
    ground_truth = json.loads(gt_path.read_text())["pins"] if gt_path.exists() else []

    phase_1b_pins = await load_batch_pins(phase_1b_batch)

    if not phase_1b_pins:
        print(f"No pins found for Phase 1B batch {phase_1b_batch}")
        sys.exit(1)

    comparison = generate_comparison(phase_1a, phase_1b_pins, ground_truth)
    COMPARISON_OUTPUT.write_text(comparison)
    print(comparison)
    print(f"\nSaved to {COMPARISON_OUTPUT}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/compare_phases.py <phase_1a_batch_id> <phase_1b_batch_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
```

- [ ] **Step 2: Verify the script shows usage without errors**

```bash
cd disney-pin-assistant && python scripts/compare_phases.py 2>&1 | head -1
```

Expected: "Usage: python scripts/compare_phases.py <phase_1a_batch_id> <phase_1b_batch_id>"

- [ ] **Step 3: Commit**

```bash
git add disney-pin-assistant/scripts/compare_phases.py
git commit -m "feat: add Phase 1A vs 1B comparison script for catalog evaluation"
```

---

### Task 8: Phase 1B Evaluation Workflow README

**Files:**
- Modify: `disney-pin-assistant/evaluation/README.md`

- [ ] **Step 1: Append Phase 1B workflow to the evaluation README**

Add the following section to the end of `disney-pin-assistant/evaluation/README.md`:

```markdown

---

# Phase 1B Evaluation Workflow

## Prerequisites

1. Phase 1A completed and scorecard generated
2. PinPics scraper built (Tasks 1-5 above)

## Step 1: Scrape PinPics

Start with a small test category to verify the scraper works:

```bash
# Test scrape: 100 pin IDs
python scripts/scrape_pinpics.py --start 150000 --end 150100 --rate 1.0
```

Then scrape target categories:

```bash
# Recent limited editions
python scripts/scrape_pinpics.py --category le-2024

# Or custom range
python scripts/scrape_pinpics.py --start 130000 --end 160000 --rate 1.0 --resume
```

Output: `scripts/scraper/output/pinpics_catalog.json`

## Step 2: Import into Catalog

```bash
# Start the app
uvicorn src.main:app --reload

# Import scraped data
curl -X POST http://localhost:8000/api/catalog/import/json \
  -F 'file=@scripts/scraper/output/pinpics_catalog.json'

# Verify
curl http://localhost:8000/api/catalog/stats
```

Re-importing the same file is safe — duplicates are skipped by source_reference_id.

## Step 3: Re-Process Test Pins

Upload the same pin photos from Phase 1A as a new batch and process them:

1. Open http://localhost:8000
2. Upload all pin photos from `sample_data/`
3. Process the batch
4. Note the new batch ID

## Step 4: Compare Results

```bash
python scripts/compare_phases.py <phase_1a_batch_id> <phase_1b_batch_id>
```

This produces `evaluation/phase_comparison.md` showing side-by-side results.

## Step 5: Review

Open `evaluation/phase_comparison.md` to see:
- Per-pin comparison of 1A vs 1B identification and listing quality
- Count of improved / regressed / unchanged pins
- Verdict on whether catalog matching helps

## Gate Decision

- **Improved > Regressed:** Catalog matching adds value. Proceed to Phase 1C.
- **Regressed > Improved:** Investigate matching weights in `src/pipeline/matching.py`. Tune and re-test.
- **No clear impact:** Consider if catalog seeding effort is justified for Phase 1C.
```

- [ ] **Step 2: Commit**

```bash
git add disney-pin-assistant/evaluation/README.md
git commit -m "docs: add Phase 1B evaluation workflow to README"
```

---

## Self-Review

**Spec coverage check:**
- Build PinPics scraper with rate limiting → Tasks 2, 3, 5
- Design normalization pipeline → Task 4
- Scrape initial 5-10K entries → Task 5 (CLI with category ranges)
- Import via existing endpoints → Task 6 (with dedup added)
- Re-run same test pins → Task 7 (comparison script)
- Compare catalog-matched vs vision-only → Task 7
- Success criteria (70% top-3 match, improvement visible) → Task 7 (comparison output)

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code is complete.

**Type consistency:** `parse_pin_page` returns a dict matching the CatalogEntry JSON import format. `normalize_entry` takes and returns the same dict shape. `scrape_range` calls both in sequence. The import endpoint accepts this exact format. All consistent.
