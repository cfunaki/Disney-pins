# eBay Seller Listing Import Tool

## Purpose

Pull a friend's sold and active Disney pin listings from eBay, download images, and produce both catalog entries and evaluation ground truth in one automated step. This replaces the manual ground truth collection process and seeds a high-quality initial catalog from verified human listings.

## Data Sources

### Finding API — Sold Listings
- Endpoint: `findCompletedItems` (SOAP/REST, legacy but functional)
- Filter by seller username
- Returns: title, sold price, images, category, condition, listing dates
- Auth: Client credentials (Application OAuth token) — no user login needed
- Pagination: up to 100 items per page, multiple pages

### Browse API — Active Listings
- Endpoint: `/item_summary/search` with `filter=sellers:{username}`
- Returns: title, price, images, condition, category, itemId
- Auth: Client credentials

### Browse API — Item Detail
- Endpoint: `/item/{itemId}`
- Returns: full item specifics (Character, Theme, Edition Size, Type, Brand), high-res images, HTML description
- Called per-listing to get structured fields not available in search results

## CLI Interface

```
python scripts/import_ebay_listings.py --seller <username> [--max 200] [--sold-only] [--rate 2.0]
```

**Arguments:**
- `--seller` (required): eBay seller username
- `--max` (default 200): Maximum listings to pull
- `--sold-only` (flag): Skip active listings, only pull sold
- `--rate` (default 2.0): Requests per second rate limit

## Output

### 1. Downloaded Images
- Saved to `sample_data/` directory
- Filename: `{ebay_item_id}.jpg` (e.g., `v1-123456789-0.jpg`)
- Primary listing image only (first image)

### 2. Catalog Entries
- Saved to `scripts/ebay_import/output/ebay_catalog.json`
- Format: JSON array matching the existing `/api/catalog/import/json` endpoint schema
- Importable via: `curl -X POST http://localhost:8000/api/catalog/import/json -F 'file=@scripts/ebay_import/output/ebay_catalog.json'`

Field mapping from eBay listing to catalog entry:

| Catalog Field | eBay Source |
|---------------|-------------|
| `canonical_name` | Listing title |
| `characters` | Item specific "Character" (split on comma) |
| `franchise` | Item specific "Theme" or "Franchise" |
| `pin_type` | Item specific "Type" or inferred from title keywords |
| `edition_size` | Item specific "Edition Size" or parsed from title (LE pattern) |
| `release_year` | Item specific "Year" or parsed from title |
| `source` | `"ebay"` |
| `source_reference_id` | eBay item ID |
| `reference_image_url` | eBay image URL |
| `evidence_strength` | `"high"` |

### 3. Ground Truth
- Saved to `evaluation/ground_truth.json`
- Format: `{"pins": [...]}` matching the existing scorecard generator's expected schema

Field mapping from eBay listing to ground truth:

| Ground Truth Field | eBay Source |
|-------------------|-------------|
| `image_file` | Downloaded filename (e.g., `v1-123456789-0.jpg`) |
| `reference_title` | Listing title |
| `reference_description` | Listing description (stripped HTML) |
| `reference_price` | Sold price (or asking price for active) |
| `expected_characters` | Item specific "Character" (split on comma) |
| `expected_franchise` | Item specific "Theme" or "Franchise" |
| `expected_pin_type` | Item specific "Type" or inferred |
| `expected_edition_size` | Item specific "Edition Size" or parsed |
| `expected_event` | Item specific "Event" or parsed from title |
| `notes` | `"sold"` or `"active"` + sale date if available |

## Implementation Structure

### Files
- `scripts/ebay_import/__init__.py` — empty package
- `scripts/ebay_import/finding_api.py` — Finding API client for sold listings
- `scripts/ebay_import/listing_parser.py` — Extract structured fields from eBay item data
- `scripts/import_ebay_listings.py` — Main CLI script
- `tests/test_ebay_listing_parser.py` — Tests for field extraction logic

### Reuse
- `src/services/ebay_client.py` — Existing OAuth token management and Browse API client
- Rate limiting approach from PinPics scraper (`RateLimiter` class)

### Finding API Client
The existing `ebay_client.py` only supports the Browse API. A new `finding_api.py` module handles the Finding API's different auth and response format:
- Uses the same client credentials (App ID) but different endpoint
- Response is XML (Finding API) — parse with standard library `xml.etree.ElementTree`
- Handles pagination (100 items/page)

### Listing Parser
Extracts structured fields from eBay's item specifics and title:
- Item specifics are key-value pairs (e.g., `{"Character": "Mickey Mouse", "Edition Size": "3000"}`)
- Falls back to title parsing when item specifics are missing (e.g., extract "LE 3000" from title)
- Strips HTML from descriptions
- Normalizes character names using the same logic as the PinPics normalizer

## Deduplication
- On re-run, loads existing ground truth file and skips items already present (by eBay item ID in filename)
- Catalog import endpoint already handles deduplication by `(source, source_reference_id)`

## Rate Limits
- eBay Browse API: 5,000 calls/day
- Finding API: 5,000 calls/day
- For ~200 listings: ~200 search results + ~200 detail calls + ~200 image downloads = ~600 requests
- Well within daily limits at 2 req/sec

## Error Handling
- Skip individual listings that fail to download (log warning, continue)
- Retry on 429 with exponential backoff (same pattern as PinPics fetcher)
- Save progress incrementally (don't lose everything if script is interrupted)

## Testing
- Unit tests for listing parser with mocked eBay response data
- No live API calls in tests
- Test field extraction from item specifics
- Test title-based fallback parsing
- Test HTML stripping from descriptions

## What This Replaces
- `scripts/collect_ground_truth.py` — manual interactive ground truth collection (still available as fallback but not the primary path)
- Partially replaces PinPics as initial catalog seed — friend's listings provide a small, high-quality catalog. PinPics scraper remains for broader coverage later.

## Revised Evaluation Workflow
1. Set up `.env` with Anthropic + eBay credentials
2. Run `python scripts/import_ebay_listings.py --seller <friend_username>`
3. Import catalog: `curl -X POST .../api/catalog/import/json -F 'file=@scripts/ebay_import/output/ebay_catalog.json'`
4. Upload downloaded images through the web UI, process batch
5. Run `python scripts/generate_scorecard.py <batch_id>`
6. Review scorecard — gate decision on whether pipeline works
