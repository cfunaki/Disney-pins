# eBay Seller Listing Import Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that pulls a friend's sold and active Disney pin listings from eBay, downloads images, and produces both catalog entries and evaluation ground truth in one automated step.

**Architecture:** A Finding API client handles sold listings (XML response format). The existing Browse API client (`src/services/ebay_client.py`) handles active listings and item detail lookups. A listing parser extracts structured fields from eBay item specifics with title-based fallbacks, reusing the normalizer from the PinPics scraper. A main CLI script orchestrates the flow: search → detail → parse → download images → write catalog JSON + ground truth JSON.

**Tech Stack:** Python, httpx (existing dependency), xml.etree.ElementTree (stdlib), existing `ebay_client.py` OAuth + Browse API, existing `normalizer.py` for character/franchise normalization.

---

### Task 1: Create the Listing Parser Module

**Files:**
- Create: `disney-pin-assistant/scripts/ebay_import/__init__.py`
- Create: `disney-pin-assistant/scripts/ebay_import/listing_parser.py`
- Create: `disney-pin-assistant/tests/test_ebay_listing_parser.py`

- [ ] **Step 1: Write failing tests for field extraction from item specifics**

Create `disney-pin-assistant/tests/test_ebay_listing_parser.py`:

```python
"""Tests for eBay listing parser field extraction."""

from scripts.ebay_import.listing_parser import parse_listing


def test_parse_listing_with_full_item_specifics():
    """Extract all fields from a listing with complete item specifics."""
    listing = {
        "itemId": "v1|123456789|0",
        "title": "Disney Mickey Mouse LE 3000 Pin",
        "price": {"value": "25.99", "currency": "USD"},
        "condition": "New",
        "image": {"imageUrl": "https://i.ebayimg.com/images/g/abc/s-l1600.jpg"},
        "localizedAspects": [
            {"name": "Character", "value": "Mickey Mouse"},
            {"name": "Theme", "value": "Mickey & Friends"},
            {"name": "Type", "value": "Limited Edition"},
            {"name": "Edition Size", "value": "3000"},
            {"name": "Year", "value": "2024"},
        ],
    }
    result = parse_listing(listing, status="sold")

    assert result["source_reference_id"] == "v1|123456789|0"
    assert result["canonical_name"] == "Disney Mickey Mouse LE 3000 Pin"
    assert result["characters"] == ["Mickey Mouse"]
    assert result["franchise"] == "Mickey & Friends"
    assert result["pin_type"] == "limited edition"
    assert result["edition_size"] == 3000
    assert result["release_year"] == 2024
    assert result["price"] == 25.99
    assert result["image_url"] == "https://i.ebayimg.com/images/g/abc/s-l1600.jpg"
    assert result["status"] == "sold"


def test_parse_listing_multiple_characters():
    """Split comma-separated characters from item specifics."""
    listing = {
        "itemId": "v1|999|0",
        "title": "Mickey and Minnie Pin",
        "price": {"value": "10.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
        "localizedAspects": [
            {"name": "Character", "value": "Mickey Mouse, Minnie Mouse"},
        ],
    }
    result = parse_listing(listing, status="active")
    assert result["characters"] == ["Mickey Mouse", "Minnie Mouse"]


def test_parse_listing_fallback_to_title_for_edition_size():
    """Extract edition size from title when item specifics lack it."""
    listing = {
        "itemId": "v1|888|0",
        "title": "Stitch LE/2500 Disney Pin",
        "price": {"value": "15.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
        "localizedAspects": [],
    }
    result = parse_listing(listing, status="sold")
    assert result["edition_size"] == 2500


def test_parse_listing_no_item_specifics():
    """Handle listing with no localizedAspects at all."""
    listing = {
        "itemId": "v1|777|0",
        "title": "Disney Trading Pin Lot",
        "price": {"value": "5.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
    }
    result = parse_listing(listing, status="active")
    assert result["characters"] == []
    assert result["franchise"] is None
    assert result["edition_size"] is None
    assert result["pin_type"] is None


def test_parse_listing_infers_franchise_from_character():
    """Infer franchise from character when Theme is missing."""
    listing = {
        "itemId": "v1|666|0",
        "title": "Ariel Pin",
        "price": {"value": "12.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
        "localizedAspects": [
            {"name": "Character", "value": "Ariel"},
        ],
    }
    result = parse_listing(listing, status="sold")
    assert result["franchise"] == "The Little Mermaid"


def test_parse_listing_html_description_stripped():
    """Strip HTML tags from description field."""
    listing = {
        "itemId": "v1|555|0",
        "title": "Test Pin",
        "price": {"value": "8.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
        "localizedAspects": [],
        "description": "<p>Beautiful <b>Disney</b> pin in <i>mint</i> condition.</p>",
    }
    result = parse_listing(listing, status="active")
    assert result["description"] == "Beautiful Disney pin in mint condition."
    assert "<" not in result["description"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant && python -m pytest tests/test_ebay_listing_parser.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.ebay_import'`

- [ ] **Step 3: Create the package and implement the parser**

Create `disney-pin-assistant/scripts/ebay_import/__init__.py` (empty file).

Create `disney-pin-assistant/scripts/ebay_import/listing_parser.py`:

```python
"""Extract structured fields from eBay listing data."""

import re
from html.parser import HTMLParser

from scripts.scraper.normalizer import (
    _CHARACTER_FRANCHISE_MAP,
    _CHARACTER_MAP,
    extract_edition_from_name,
)


class _HTMLStripper(HTMLParser):
    """Simple HTML tag stripper."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html(html: str) -> str:
    """Remove HTML tags from a string, returning plain text."""
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text().strip()


def _get_aspect(aspects: list[dict], name: str) -> str | None:
    """Get a single item specific value by name."""
    for aspect in aspects:
        if aspect.get("name", "").lower() == name.lower():
            return aspect.get("value")
    return None


def _parse_characters(raw: str | None) -> list[str]:
    """Split comma-separated character string and normalize names."""
    if not raw:
        return []
    chars = []
    for part in raw.split(","):
        part = part.strip()
        key = part.lower()
        chars.append(_CHARACTER_MAP.get(key, part))
    return chars


def _infer_franchise(characters: list[str], aspects: list[dict]) -> str | None:
    """Get franchise from item specifics or infer from characters."""
    franchise = _get_aspect(aspects, "Theme") or _get_aspect(aspects, "Franchise")
    if franchise:
        return franchise
    for char in characters:
        if char in _CHARACTER_FRANCHISE_MAP:
            return _CHARACTER_FRANCHISE_MAP[char]
    return None


def _parse_pin_type(aspects: list[dict]) -> str | None:
    """Get pin type from item specifics, lowercased."""
    raw = _get_aspect(aspects, "Type")
    return raw.lower() if raw else None


def _parse_edition_size(aspects: list[dict], title: str) -> int | None:
    """Get edition size from item specifics or parse from title."""
    raw = _get_aspect(aspects, "Edition Size")
    if raw:
        cleaned = raw.replace(",", "")
        try:
            return int(cleaned)
        except ValueError:
            pass
    return extract_edition_from_name(title)


def _parse_release_year(aspects: list[dict]) -> int | None:
    """Get release year from item specifics."""
    raw = _get_aspect(aspects, "Year")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


def parse_listing(listing: dict, status: str) -> dict:
    """Parse an eBay listing dict into a structured record.

    Args:
        listing: eBay Browse API item or item summary dict.
        status: "sold" or "active".

    Returns:
        Dict with normalized fields for catalog and ground truth output.
    """
    aspects = listing.get("localizedAspects", [])
    title = listing.get("title", "")
    characters = _parse_characters(_get_aspect(aspects, "Character"))

    price_data = listing.get("price", {})
    price = None
    if price_data.get("value"):
        try:
            price = float(price_data["value"])
        except (ValueError, TypeError):
            pass

    image_url = None
    image_data = listing.get("image")
    if image_data:
        image_url = image_data.get("imageUrl")

    description = ""
    raw_desc = listing.get("description", "")
    if raw_desc:
        description = strip_html(raw_desc)

    return {
        "source_reference_id": listing.get("itemId", ""),
        "canonical_name": title,
        "characters": characters,
        "franchise": _infer_franchise(characters, aspects),
        "pin_type": _parse_pin_type(aspects),
        "edition_size": _parse_edition_size(aspects, title),
        "release_year": _parse_release_year(aspects),
        "price": price,
        "image_url": image_url,
        "description": description,
        "status": status,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd disney-pin-assistant && python -m pytest tests/test_ebay_listing_parser.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/ebay_import/__init__.py scripts/ebay_import/listing_parser.py tests/test_ebay_listing_parser.py
git commit -m "feat: add eBay listing parser with field extraction and tests"
```

---

### Task 2: Create the Finding API Client

**Files:**
- Create: `disney-pin-assistant/scripts/ebay_import/finding_api.py`
- Create: `disney-pin-assistant/tests/test_finding_api.py`

- [ ] **Step 1: Write failing tests for Finding API XML parsing**

Create `disney-pin-assistant/tests/test_finding_api.py`:

```python
"""Tests for Finding API client XML parsing."""

from scripts.ebay_import.finding_api import parse_finding_response


SAMPLE_RESPONSE_XML = """<?xml version='1.0' encoding='UTF-8'?>
<findCompletedItemsResponse xmlns="https://www.ebay.com/marketplace/search/v1/services">
  <ack>Success</ack>
  <paginationOutput>
    <totalPages>2</totalPages>
    <totalEntries>150</totalEntries>
  </paginationOutput>
  <searchResult count="2">
    <item>
      <itemId>123456789</itemId>
      <title>Disney Mickey Mouse LE 3000 Pin</title>
      <sellingStatus>
        <currentPrice currencyId="USD">25.99</currentPrice>
        <sellingState>EndedWithSales</sellingState>
      </sellingStatus>
      <listingInfo>
        <endTime>2024-12-15T10:30:00.000Z</endTime>
      </listingInfo>
      <galleryURL>https://i.ebayimg.com/thumbs/123.jpg</galleryURL>
      <condition>
        <conditionDisplayName>New</conditionDisplayName>
      </condition>
    </item>
    <item>
      <itemId>987654321</itemId>
      <title>Stitch LE 500 Trading Pin</title>
      <sellingStatus>
        <currentPrice currencyId="USD">42.00</currentPrice>
        <sellingState>EndedWithSales</sellingState>
      </sellingStatus>
      <listingInfo>
        <endTime>2024-11-20T15:00:00.000Z</endTime>
      </listingInfo>
      <galleryURL>https://i.ebayimg.com/thumbs/987.jpg</galleryURL>
    </item>
  </searchResult>
</findCompletedItemsResponse>"""


def test_parse_finding_response_extracts_items():
    """Parse XML response and extract item list."""
    items, total_pages = parse_finding_response(SAMPLE_RESPONSE_XML)
    assert len(items) == 2
    assert total_pages == 2


def test_parse_finding_response_item_fields():
    """Verify extracted fields from first item."""
    items, _ = parse_finding_response(SAMPLE_RESPONSE_XML)
    item = items[0]
    assert item["itemId"] == "123456789"
    assert item["title"] == "Disney Mickey Mouse LE 3000 Pin"
    assert item["price"] == {"value": "25.99", "currency": "USD"}
    assert item["image"] == {"imageUrl": "https://i.ebayimg.com/thumbs/123.jpg"}
    assert item["end_time"] == "2024-12-15T10:30:00.000Z"


def test_parse_finding_response_empty():
    """Handle response with no items."""
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <findCompletedItemsResponse xmlns="https://www.ebay.com/marketplace/search/v1/services">
      <ack>Success</ack>
      <paginationOutput><totalPages>0</totalPages><totalEntries>0</totalEntries></paginationOutput>
      <searchResult count="0"/>
    </findCompletedItemsResponse>"""
    items, total_pages = parse_finding_response(xml)
    assert items == []
    assert total_pages == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant && python -m pytest tests/test_finding_api.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the Finding API client**

Create `disney-pin-assistant/scripts/ebay_import/finding_api.py`:

```python
"""eBay Finding API client for retrieving sold listings."""

import asyncio
import xml.etree.ElementTree as ET

import httpx

FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"


def parse_finding_response(xml_text: str) -> tuple[list[dict], int]:
    """Parse Finding API XML response into a list of item dicts.

    Returns:
        Tuple of (items, total_pages).
        Each item dict has keys matching Browse API shape for consistency:
        itemId, title, price, image, end_time.
    """
    ns = {"ns": "https://www.ebay.com/marketplace/search/v1/services"}
    root = ET.fromstring(xml_text)

    total_pages_el = root.find(".//ns:paginationOutput/ns:totalPages", ns)
    total_pages = int(total_pages_el.text) if total_pages_el is not None else 0

    items = []
    for item_el in root.findall(".//ns:searchResult/ns:item", ns):
        item_id_el = item_el.find("ns:itemId", ns)
        title_el = item_el.find("ns:title", ns)
        price_el = item_el.find("ns:sellingStatus/ns:currentPrice", ns)
        gallery_el = item_el.find("ns:galleryURL", ns)
        end_time_el = item_el.find("ns:listingInfo/ns:endTime", ns)

        price_dict = {}
        if price_el is not None:
            price_dict = {
                "value": price_el.text,
                "currency": price_el.get("currencyId", "USD"),
            }

        image_dict = {}
        if gallery_el is not None and gallery_el.text:
            image_dict = {"imageUrl": gallery_el.text}

        items.append({
            "itemId": item_id_el.text if item_id_el is not None else "",
            "title": title_el.text if title_el is not None else "",
            "price": price_dict,
            "image": image_dict,
            "end_time": end_time_el.text if end_time_el is not None else None,
        })

    return items, total_pages


async def fetch_sold_listings(
    seller: str,
    app_id: str,
    max_items: int = 200,
    rate_limiter=None,
) -> list[dict]:
    """Fetch completed/sold listings for a seller from the Finding API.

    Args:
        seller: eBay seller username.
        app_id: eBay Application ID (client_id).
        max_items: Maximum listings to fetch.
        rate_limiter: Optional RateLimiter instance.

    Returns:
        List of item dicts (same shape as parse_finding_response output).
    """
    all_items: list[dict] = []
    page = 1

    while len(all_items) < max_items:
        if rate_limiter:
            await rate_limiter.acquire()

        entries_per_page = min(100, max_items - len(all_items))

        params = {
            "OPERATION-NAME": "findCompletedItems",
            "SERVICE-VERSION": "1.13.0",
            "SECURITY-APPNAME": app_id,
            "RESPONSE-DATA-FORMAT": "XML",
            "REST-PAYLOAD": "",
            "categoryId": "13918",  # Disneyana > Pins
            "itemFilter(0).name": "Seller",
            "itemFilter(0).value": seller,
            "itemFilter(1).name": "SoldItemsOnly",
            "itemFilter(1).value": "true",
            "paginationInput.entriesPerPage": str(entries_per_page),
            "paginationInput.pageNumber": str(page),
            "sortOrder": "EndTimeSoonest",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(FINDING_API_URL, params=params)

        if response.status_code == 429:
            for attempt in range(3):
                backoff = 2 ** (attempt + 1)
                print(f"[finding] 429 rate limited on page {page}, backing off {backoff}s")
                await asyncio.sleep(backoff)
                async with httpx.AsyncClient(timeout=30.0) as retry_client:
                    response = await retry_client.get(FINDING_API_URL, params=params)
                if response.status_code != 429:
                    break
            if response.status_code == 429:
                print(f"[finding] Giving up on page {page} after 429 retries")
                break

        if response.status_code != 200:
            print(f"[finding] Unexpected status {response.status_code} on page {page}")
            break

        items, total_pages = parse_finding_response(response.text)
        if not items:
            break

        all_items.extend(items)
        print(f"[finding] Page {page}/{total_pages}: fetched {len(items)} items (total: {len(all_items)})")

        if page >= total_pages:
            break
        page += 1

    return all_items[:max_items]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd disney-pin-assistant && python -m pytest tests/test_finding_api.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/ebay_import/finding_api.py tests/test_finding_api.py
git commit -m "feat: add Finding API client for sold eBay listings"
```

---

### Task 3: Extend Browse API Client for Seller Search and Item Detail

**Files:**
- Modify: `disney-pin-assistant/src/services/ebay_client.py`
- Create: `disney-pin-assistant/tests/test_ebay_browse_extensions.py`

- [ ] **Step 1: Write failing tests for new Browse API functions**

Create `disney-pin-assistant/tests/test_ebay_browse_extensions.py`:

```python
"""Tests for Browse API seller search and item detail functions."""

from unittest.mock import AsyncMock, patch

import pytest

from src.services.ebay_client import browse_api_seller_search, browse_api_item_detail


@pytest.mark.asyncio
async def test_browse_api_seller_search_calls_correct_filter():
    """Verify seller search passes the correct filter parameter."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "itemSummaries": [
            {"itemId": "v1|111|0", "title": "Test Pin"}
        ],
        "total": 1,
    }
    mock_response.raise_for_status = AsyncMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("src.services.ebay_client.get_ebay_token", return_value="fake-token"), \
         patch("src.services.ebay_client.httpx.AsyncClient", return_value=mock_client):
        items = await browse_api_seller_search("test_seller", limit=50)

    assert len(items) == 1
    assert items[0]["itemId"] == "v1|111|0"
    # Verify filter includes seller
    call_kwargs = mock_client.get.call_args
    assert "sellers" in call_kwargs.kwargs.get("params", {}).get("filter", "")


@pytest.mark.asyncio
async def test_browse_api_item_detail_returns_full_item():
    """Verify item detail returns full item data including localizedAspects."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "itemId": "v1|222|0",
        "title": "Detailed Pin",
        "localizedAspects": [
            {"name": "Character", "value": "Stitch"}
        ],
    }
    mock_response.raise_for_status = AsyncMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("src.services.ebay_client.get_ebay_token", return_value="fake-token"), \
         patch("src.services.ebay_client.httpx.AsyncClient", return_value=mock_client):
        item = await browse_api_item_detail("v1|222|0")

    assert item["itemId"] == "v1|222|0"
    assert item["localizedAspects"][0]["name"] == "Character"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant && python -m pytest tests/test_ebay_browse_extensions.py -v
```

Expected: FAIL — `ImportError: cannot import name 'browse_api_seller_search'`

- [ ] **Step 3: Add the two new functions to ebay_client.py**

Add to the end of `disney-pin-assistant/src/services/ebay_client.py`:

```python
async def browse_api_seller_search(seller: str, limit: int = 50) -> list[dict]:
    """Search active listings by seller username."""
    token = await get_ebay_token()
    params = {
        "q": "disney pin",
        "filter": f"sellers:{{{seller}}}",
        "limit": str(limit),
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


async def browse_api_item_detail(item_id: str) -> dict:
    """Get full item details including localizedAspects."""
    token = await get_ebay_token()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.ebay.com/buy/browse/v1/item/{item_id}",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
        )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd disney-pin-assistant && python -m pytest tests/test_ebay_browse_extensions.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/services/ebay_client.py tests/test_ebay_browse_extensions.py
git commit -m "feat: add Browse API seller search and item detail endpoints"
```

---

### Task 4: Build the Main CLI Script

**Files:**
- Create: `disney-pin-assistant/scripts/import_ebay_listings.py`

- [ ] **Step 1: Implement the CLI script**

Create `disney-pin-assistant/scripts/import_ebay_listings.py`:

```python
"""Import eBay seller listings as catalog entries and ground truth.

Usage:
    python scripts/import_ebay_listings.py --seller <username> [--max 200] [--sold-only] [--rate 2.0]
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ebay_import.finding_api import fetch_sold_listings
from scripts.ebay_import.listing_parser import parse_listing
from scripts.scraper.pinpics_fetcher import RateLimiter
from src.services.ebay_client import browse_api_seller_search, browse_api_item_detail

OUTPUT_DIR = Path(__file__).resolve().parent / "ebay_import" / "output"
SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"
GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "evaluation" / "ground_truth.json"


def load_existing_ids(ground_truth_path: Path) -> set[str]:
    """Load existing eBay item IDs from ground truth file for deduplication."""
    if not ground_truth_path.exists():
        return set()
    data = json.loads(ground_truth_path.read_text())
    ids = set()
    for pin in data.get("pins", []):
        image_file = pin.get("image_file", "")
        if image_file.startswith("v1-"):
            # Extract item ID from filename: v1-123456789-0.jpg -> v1|123456789|0
            parts = image_file.replace(".jpg", "").split("-")
            if len(parts) >= 3:
                ids.add(f"{parts[0]}|{parts[1]}|{parts[2]}")
        elif pin.get("source_reference_id"):
            ids.add(pin["source_reference_id"])
    return ids


def item_id_to_filename(item_id: str) -> str:
    """Convert eBay item ID to safe filename: v1|123|0 -> v1-123-0.jpg"""
    return item_id.replace("|", "-") + ".jpg"


async def download_image(url: str, dest: Path, limiter: RateLimiter) -> bool:
    """Download an image, return True on success."""
    if dest.exists():
        return True
    await limiter.acquire()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                dest.write_bytes(response.content)
                return True
            print(f"[download] Status {response.status_code} for {url}")
            return False
    except Exception as exc:
        print(f"[download] Error downloading {url}: {exc}")
        return False


def build_catalog_entry(parsed: dict) -> dict:
    """Convert parsed listing to catalog import format."""
    return {
        "canonical_name": parsed["canonical_name"],
        "characters": parsed["characters"],
        "franchise": parsed["franchise"],
        "pin_type": parsed["pin_type"],
        "edition_size": parsed["edition_size"],
        "release_year": parsed["release_year"],
        "source": "ebay",
        "source_reference_id": parsed["source_reference_id"],
        "reference_image_url": parsed["image_url"],
        "evidence_strength": "high",
    }


def build_ground_truth_entry(parsed: dict, image_filename: str) -> dict:
    """Convert parsed listing to ground truth format."""
    return {
        "image_file": image_filename,
        "reference_title": parsed["canonical_name"],
        "reference_description": parsed["description"],
        "reference_price": parsed["price"],
        "expected_characters": parsed["characters"],
        "expected_franchise": parsed["franchise"],
        "expected_pin_type": parsed["pin_type"],
        "expected_edition_size": parsed["edition_size"],
        "expected_event": None,
        "notes": parsed["status"],
        "source_reference_id": parsed["source_reference_id"],
    }


async def fetch_active_with_details(
    seller: str, limiter: RateLimiter, max_items: int
) -> list[dict]:
    """Fetch active listings and enrich each with item detail."""
    print(f"[active] Searching active listings for seller: {seller}")
    summaries = await browse_api_seller_search(seller, limit=min(max_items, 200))
    print(f"[active] Found {len(summaries)} active listings")

    detailed = []
    for summary in summaries[:max_items]:
        item_id = summary.get("itemId", "")
        if not item_id:
            continue
        await limiter.acquire()
        try:
            detail = await browse_api_item_detail(item_id)
            detailed.append(detail)
        except Exception as exc:
            print(f"[active] Error fetching detail for {item_id}: {exc}")
            continue

    return detailed


async def run(seller: str, max_items: int, sold_only: bool, rate: float) -> None:
    """Main import workflow."""
    app_id = os.environ.get("EBAY_CLIENT_ID", "")
    if not app_id:
        print("Error: EBAY_CLIENT_ID environment variable is required")
        sys.exit(1)

    limiter = RateLimiter(requests_per_second=rate)

    # Load existing IDs for deduplication
    existing_ids = load_existing_ids(GROUND_TRUTH_PATH)
    print(f"[dedup] Found {len(existing_ids)} existing entries")

    all_parsed: list[dict] = []

    # Fetch sold listings via Finding API
    print(f"\n--- Fetching sold listings for seller: {seller} ---")
    sold_items = await fetch_sold_listings(seller, app_id, max_items=max_items, rate_limiter=limiter)
    print(f"[sold] Retrieved {len(sold_items)} sold listings")

    for item in sold_items:
        item_id = item.get("itemId", "")
        if item_id in existing_ids:
            continue
        parsed = parse_listing(item, status="sold")
        all_parsed.append(parsed)

    # Fetch active listings via Browse API (unless --sold-only)
    if not sold_only:
        remaining = max_items - len(all_parsed)
        if remaining > 0:
            print(f"\n--- Fetching active listings for seller: {seller} ---")
            active_items = await fetch_active_with_details(seller, limiter, remaining)
            for item in active_items:
                item_id = item.get("itemId", "")
                if item_id in existing_ids:
                    continue
                parsed = parse_listing(item, status="active")
                all_parsed.append(parsed)

    print(f"\n[total] {len(all_parsed)} new listings to process")

    if not all_parsed:
        print("No new listings found. Exiting.")
        return

    # Ensure output directories exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Download images and build output
    catalog_entries = []
    ground_truth_entries = []
    downloaded = 0
    skipped_images = 0

    for parsed in all_parsed:
        image_filename = item_id_to_filename(parsed["source_reference_id"])
        image_dest = SAMPLE_DATA_DIR / image_filename

        if parsed["image_url"]:
            success = await download_image(parsed["image_url"], image_dest, limiter)
            if success:
                downloaded += 1
            else:
                skipped_images += 1
        else:
            skipped_images += 1

        catalog_entries.append(build_catalog_entry(parsed))
        ground_truth_entries.append(build_ground_truth_entry(parsed, image_filename))

    # Write catalog JSON
    catalog_path = OUTPUT_DIR / "ebay_catalog.json"
    catalog_path.write_text(json.dumps(catalog_entries, indent=2))
    print(f"\n[output] Catalog: {catalog_path} ({len(catalog_entries)} entries)")

    # Merge with existing ground truth
    existing_gt = {"pins": []}
    if GROUND_TRUTH_PATH.exists():
        existing_gt = json.loads(GROUND_TRUTH_PATH.read_text())

    existing_gt["pins"].extend(ground_truth_entries)
    GROUND_TRUTH_PATH.write_text(json.dumps(existing_gt, indent=2))
    print(f"[output] Ground truth: {GROUND_TRUTH_PATH} ({len(existing_gt['pins'])} total entries)")
    print(f"[output] Images: {downloaded} downloaded, {skipped_images} skipped")


def main():
    parser = argparse.ArgumentParser(description="Import eBay seller listings")
    parser.add_argument("--seller", required=True, help="eBay seller username")
    parser.add_argument("--max", type=int, default=200, help="Maximum listings to pull (default: 200)")
    parser.add_argument("--sold-only", action="store_true", help="Skip active listings, only pull sold")
    parser.add_argument("--rate", type=float, default=2.0, help="Requests per second (default: 2.0)")
    args = parser.parse_args()

    asyncio.run(run(args.seller, args.max, args.sold_only, args.rate))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script parses arguments correctly**

```bash
cd disney-pin-assistant && python scripts/import_ebay_listings.py --help
```

Expected: Help text showing `--seller`, `--max`, `--sold-only`, `--rate` options.

- [ ] **Step 3: Commit**

```bash
git add scripts/import_ebay_listings.py
git commit -m "feat: add main CLI script for eBay listing import"
```

---

### Task 5: Add Integration-Level Tests for the CLI

**Files:**
- Create: `disney-pin-assistant/tests/test_ebay_import_integration.py`

- [ ] **Step 1: Write tests for the output-building functions and deduplication**

Create `disney-pin-assistant/tests/test_ebay_import_integration.py`:

```python
"""Integration tests for eBay import CLI helper functions."""

import json
from pathlib import Path

from scripts.import_ebay_listings import (
    build_catalog_entry,
    build_ground_truth_entry,
    item_id_to_filename,
    load_existing_ids,
)


def test_item_id_to_filename():
    assert item_id_to_filename("v1|123456789|0") == "v1-123456789-0.jpg"


def test_item_id_to_filename_simple():
    assert item_id_to_filename("999") == "999.jpg"


def test_build_catalog_entry():
    parsed = {
        "source_reference_id": "v1|123|0",
        "canonical_name": "Test Pin",
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "pin_type": "limited edition",
        "edition_size": 3000,
        "release_year": 2024,
        "image_url": "https://example.com/img.jpg",
        "price": 25.99,
        "description": "A test pin",
        "status": "sold",
    }
    entry = build_catalog_entry(parsed)
    assert entry["source"] == "ebay"
    assert entry["source_reference_id"] == "v1|123|0"
    assert entry["evidence_strength"] == "high"
    assert entry["canonical_name"] == "Test Pin"
    assert "price" not in entry  # Price is not in catalog


def test_build_ground_truth_entry():
    parsed = {
        "source_reference_id": "v1|123|0",
        "canonical_name": "Test Pin",
        "characters": ["Stitch"],
        "franchise": "Lilo & Stitch",
        "pin_type": "limited edition",
        "edition_size": 500,
        "release_year": None,
        "image_url": "https://example.com/img.jpg",
        "price": 42.00,
        "description": "A stitch pin",
        "status": "sold",
    }
    entry = build_ground_truth_entry(parsed, "v1-123-0.jpg")
    assert entry["image_file"] == "v1-123-0.jpg"
    assert entry["reference_title"] == "Test Pin"
    assert entry["reference_price"] == 42.00
    assert entry["expected_characters"] == ["Stitch"]
    assert entry["expected_franchise"] == "Lilo & Stitch"
    assert entry["notes"] == "sold"


def test_load_existing_ids_empty(tmp_path):
    """Returns empty set when file doesn't exist."""
    ids = load_existing_ids(tmp_path / "nonexistent.json")
    assert ids == set()


def test_load_existing_ids_from_ground_truth(tmp_path):
    """Extracts item IDs from image filenames."""
    gt_path = tmp_path / "ground_truth.json"
    gt_path.write_text(json.dumps({
        "pins": [
            {"image_file": "v1-111-0.jpg", "reference_title": "Pin A"},
            {"image_file": "v1-222-0.jpg", "reference_title": "Pin B"},
            {"image_file": "manual_photo.jpg", "reference_title": "Pin C"},
        ]
    }))
    ids = load_existing_ids(gt_path)
    assert "v1|111|0" in ids
    assert "v1|222|0" in ids
    assert len(ids) == 2  # manual_photo doesn't match pattern
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd disney-pin-assistant && python -m pytest tests/test_ebay_import_integration.py -v
```

Expected: 6 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_ebay_import_integration.py
git commit -m "test: add integration tests for eBay import CLI helpers"
```

---

### Task 6: Update .gitignore and .env.example

**Files:**
- Modify: `disney-pin-assistant/.gitignore`
- Modify: `disney-pin-assistant/.env.example`

- [ ] **Step 1: Add eBay import output directory to .gitignore**

Add the following line to `disney-pin-assistant/.gitignore` (in the evaluation artifacts section):

```
scripts/ebay_import/output/
```

- [ ] **Step 2: Update .env.example with eBay credential comments**

Ensure the eBay section of `disney-pin-assistant/.env.example` includes:

```
# eBay API credentials (required for comp search AND eBay listing import)
EBAY_CLIENT_ID=your_ebay_client_id
EBAY_CLIENT_SECRET=your_ebay_client_secret
```

- [ ] **Step 3: Verify .gitignore works**

```bash
cd disney-pin-assistant && mkdir -p scripts/ebay_import/output && touch scripts/ebay_import/output/test.json && git status scripts/ebay_import/output/
```

Expected: No untracked files shown for the output directory.

- [ ] **Step 4: Commit**

```bash
git add .gitignore .env.example
git commit -m "chore: add eBay import output to gitignore and update env example"
```

---

### Task 7: Run All Tests and Final Verification

**Files:**
- No new files

- [ ] **Step 1: Run the full test suite**

```bash
cd disney-pin-assistant && python -m pytest tests/ -v --tb=short
```

Expected: All tests pass, including:
- `test_ebay_listing_parser.py` — 6 tests
- `test_finding_api.py` — 3 tests
- `test_ebay_browse_extensions.py` — 2 tests
- `test_ebay_import_integration.py` — 6 tests
- All existing tests still pass

- [ ] **Step 2: Verify CLI help output**

```bash
cd disney-pin-assistant && python scripts/import_ebay_listings.py --help
```

Expected: Clean help output with all 4 arguments documented.

- [ ] **Step 3: Verify file structure**

```bash
ls -la scripts/ebay_import/
ls -la tests/test_ebay_*.py tests/test_finding_api.py
```

Expected:
- `scripts/ebay_import/__init__.py`
- `scripts/ebay_import/finding_api.py`
- `scripts/ebay_import/listing_parser.py`
- `scripts/ebay_import/output/` (directory)
- `tests/test_ebay_listing_parser.py`
- `tests/test_finding_api.py`
- `tests/test_ebay_browse_extensions.py`
- `tests/test_ebay_import_integration.py`
