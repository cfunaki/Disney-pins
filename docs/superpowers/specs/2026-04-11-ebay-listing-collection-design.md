# eBay Listing Collection System — Design Spec

## Goal

Build a formalized system for collecting and storing eBay listings (both active and sold) across all collectible pins — not just Disney. This serves two purposes: (1) a price comp database for the pin assistant pipeline, and (2) a broad catalog of pin listings for discovery and reference.

## Motivation

Today, eBay data enters the system ad hoc through `import_ebay_seller.py`, which creates `pins` rows directly. This conflates "listings we've observed" with "pins we want to process." We need a dedicated listing store that:

- Tracks what we've collected and when, preventing redundant API calls
- Stores sold listing data for price comps (not available from eBay's public APIs)
- Scales to hundreds of thousands of listings across many sellers and keywords
- Keeps raw API responses for audit and replay
- Stays on SQLite now, migrates cleanly to PostgreSQL later

## Architecture

**Two-tier storage:**
- **SQLite** — structured metadata, indexes, query-able fields
- **Local filesystem** — raw API responses (JSON) and downloaded images

**Two data sources:**
- **eBay Browse API** — active listings (existing integration)
- **RapidAPI eBay Average Selling Price** — sold/completed listings

**Separation from pin pipeline:** The `ebay_listings` table is the data lake. The `pins` table is the processing pipeline. Listings can be promoted to pins via an explicit command, but most listings stay as reference data only.

## Data Model

### `ebay_listings`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | auto-increment |
| `listing_type` | ENUM(ACTIVE, SOLD) | |
| `source` | STRING | `"browse_api"` or `"rapidapi_sold"` |
| `ebay_item_id` | STRING, nullable, unique | Browse API provides this; RapidAPI does not |
| `title` | STRING | listing title |
| `price` | FLOAT | sale price (sold) or current price (active) |
| `currency` | STRING, default `"USD"` | |
| `sale_date` | DATE, nullable | sold listings only |
| `seller` | STRING, nullable | known for active listings, not for sold |
| `category` | STRING, nullable | eBay category name or ID |
| `condition` | STRING, nullable | |
| `image_url` | STRING, nullable | remote URL |
| `local_image_path` | STRING, nullable | downloaded path; active listings only |
| `listing_url` | STRING, nullable | eBay link (Browse API or RapidAPI `link`) |
| `parsed_fields` | JSON, nullable | output from `parse_listing_label` (Haiku) |
| `collection_job_id` | INTEGER FK | references `collection_jobs.id` |
| `created_at` | DATETIME | row creation time |
| `updated_at` | DATETIME | last refresh time |

**Dedup strategy:**
- Active listings: unique on `ebay_item_id`. Re-collection upserts (updates price, title, `updated_at`).
- Sold listings: soft dedup in code on `(title, price, sale_date)`. No hard DB constraint — edge cases (two different pins, same title, same price, same day) would crash a unique constraint. Code checks before insert, skips if match exists, logs a warning.

### `collection_jobs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | auto-increment |
| `job_type` | ENUM(SELLER_ACTIVE, KEYWORD_ACTIVE, KEYWORD_SOLD) | |
| `query` | STRING | keyword or seller name used |
| `category_id` | STRING, nullable | eBay category filter if used |
| `source` | STRING | `"browse_api"` or `"rapidapi_sold"` |
| `status` | ENUM(PENDING, RUNNING, COMPLETED, FAILED) | |
| `listings_found` | INTEGER, default 0 | total from API response |
| `listings_new` | INTEGER, default 0 | after dedup |
| `result_metadata` | JSON, nullable | RapidAPI aggregates (avg/median/min/max price), Browse API total counts |
| `error_message` | STRING, nullable | on failure |
| `started_at` | DATETIME, nullable | |
| `completed_at` | DATETIME, nullable | |
| `created_at` | DATETIME | |

## Collection Pipeline

### CLI Interface

A single entry point: `scripts/collect_listings.py`

```
# Active listings from a specific seller
python scripts/collect_listings.py active-seller --seller pins-n-things --query "disney"

# Active listings from keyword search
python scripts/collect_listings.py active-search --query "disney trading pin LE" --category 171

# Sold listings via RapidAPI
python scripts/collect_listings.py sold --query "disney trading pin LE 500" --max-results 240

# Promote collected listings to pins for pipeline processing
python scripts/collect_listings.py promote --job-id 42 --batch-name "pnt-april"
python scripts/collect_listings.py promote --seller pins-n-things --batch-name "pnt-april"
```

### Active Listing Collection (Browse API)

1. Create `collection_jobs` row with status PENDING
2. Call `browse_api_seller_search` or `browse_api_search`, paginating through all results
3. For each listing:
   - Check if `ebay_item_id` exists in `ebay_listings`
   - If exists: upsert (update price, title, `updated_at`)
   - If new: download primary image to `data/images/active/{ebay_item_id}.jpg`
   - Run `parse_listing_label` on title + description (if `collection_parse_labels` is enabled)
   - Insert/update `ebay_listings` row
4. Archive raw API response to `data/raw/browse_api/{date}/{job_id}.json`
5. Update `collection_jobs` with final counts and status COMPLETED

### Sold Listing Collection (RapidAPI)

1. Create `collection_jobs` row with status PENDING
2. POST to `https://ebay-average-selling-price.p.rapidapi.com/findCompletedItems`
   - Headers: `X-RapidAPI-Key`, `X-RapidAPI-Host`
   - Body: `keywords`, `max_search_results` (60/120/240), optional `category_id`
3. Store aggregate stats (`average_price`, `median_price`, etc.) in `collection_jobs.result_metadata`
4. For each product in response:
   - Soft dedup: check `(title, price, sale_date)` in `ebay_listings`
   - If match exists: skip, log warning
   - If new: insert with `listing_type=SOLD`, `source="rapidapi_sold"`
   - Run `parse_listing_label` on title (no description available from RapidAPI)
   - No image download (store `link` as `listing_url` only)
5. Archive raw response to `data/raw/rapidapi_sold/{date}/{job_id}.json`
6. Update `collection_jobs` with counts and status COMPLETED
7. Rate limit: configurable delay between calls (default 2 seconds)

### Promote to Pins

The `promote` command creates `pins` rows from `ebay_listings` rows, bridging the collection system to the existing pipeline:

1. Select listings matching the filter (by `collection_job_id`, `ebay_listings.seller`, or title keyword)
2. Skip any listing whose `ebay_item_id` already exists in `pins.reference_external_id`
3. For each new listing: create a `Pin` row with:
   - `reference_source = "ebay_browse"` (or `"rapidapi_sold"`)
   - `reference_external_id = ebay_item_id` (if available)
   - `reference_url = listing_url`
   - `reference_raw_title = title`
   - `reference_parsed_fields = parsed_fields`
   - `image_paths = [local_image_path]` (if downloaded)
   - `status = UNPROCESSED`
4. Report: N promoted, M skipped (already existed)

### Retiring `import_ebay_seller.py`

The existing `import_ebay_seller.py` script is superseded by `collect_listings.py active-seller` + `collect_listings.py promote`. It should be kept temporarily for reference but not used for new imports.

## File Organization

```
data/                          # gitignored
├── images/
│   └── active/
│       └── {ebay_item_id}.jpg
└── raw/
    ├── browse_api/
    │   └── 2026-04-11/
    │       └── job_42.json
    └── rapidapi_sold/
        └── 2026-04-11/
            └── job_43.json
```

- `data/` at the `disney-pin-assistant/` project root, added to `.gitignore`
- Raw responses are append-only, never overwritten
- Images downloaded only for active listings; sold listings store remote URL only

## Configuration

New settings in `src/config.py` (loaded from `.env`):

| Setting | Default | Notes |
|---------|---------|-------|
| `rapidapi_key` | `""` | RapidAPI subscription key |
| `rapidapi_sold_delay_sec` | `2.0` | Delay between RapidAPI calls (seconds) |
| `collection_data_dir` | `"./data"` | Root for raw responses + images |
| `collection_parse_labels` | `True` | Run Haiku label parsing on collected listings |

## Price Comp Integration

The `ebay_listings` table augments (does not replace) the existing live-search comp logic:

1. **Local-first:** Query `ebay_listings WHERE listing_type = 'SOLD'`, match on `parsed_fields` overlap (characters, franchise, edition_size, series)
2. **Rank by relevance:** More matching parsed fields = higher confidence comp
3. **Live fallback:** If local results are insufficient, fall back to the existing live eBay search
4. **Bridge:** Matched comps are written to the existing `comps` table with `match_type` indicating source

This integration is a follow-up concern — the collection system works standalone first, price comp wiring comes later.

## Migration Path to PostgreSQL

When scale demands it, the migration to Approach C is mechanical:

- SQLAlchemy models work with both SQLite and PostgreSQL dialects — change the connection string
- `JSON` columns become `JSONB` (better indexing, no code changes)
- Add proper unique constraints that SQLite handles loosely
- Raw JSON files on disk stay as-is
- Add a task queue (e.g., `arq` + Redis) for automated scheduling — the CLI commands become queue tasks

No schema redesign required. The data model is dialect-agnostic by design.

## Scope Boundaries

**In scope:**
- `ebay_listings` and `collection_jobs` tables
- CLI for active-seller, active-search, sold collection
- Promote-to-pins command
- RapidAPI client integration
- Raw response archival
- Label parsing on collected listings
- Configuration settings

**Out of scope (future work):**
- Automated scheduling (cron/task queue)
- Price comp query logic (wiring `ebay_listings` into the comp-finding pipeline)
- Bulk/batch YAML configuration
- Sold listing image download
- Full-text search on listings
- Analytics/dashboards on collected data
