# Per-Pin Sold-Data Comps — Design Spec

## Goal

Add automatic, recency-weighted price comps to every new pin, using the existing RapidAPI sold-data integration. Keep monthly API spend in the $5–10 range by doing targeted per-pin queries with a local cache, not broad scraping.

## Motivation

The existing RapidAPI integration was built as a broad keyword-scraping tool. In practice we only care about sold data that comps a specific pin we actually own. Broad queries are wasteful; targeted per-pin queries are cheap and produce better comps. The `ebay_listings` table accumulates as a durable cache — pins sharing characters/franchise/edition reuse prior query results and cost $0.

This design adds the scoring, caching, and pipeline-wiring on top of the RapidAPI client we already have. No source swap.

## Why Stay on RapidAPI (vs Apify or Marketplace Insights)

- It already works and is smoke-tested
- Synchronous REST is simpler than Apify's submit/poll/fetch job model (~50 fewer lines, fewer failure modes)
- The 240-result cap is irrelevant for per-pin queries (~50 results each)
- Both RapidAPI and Apify are scraping under the hood; neither is official
- Pricing for our volume lands in the same ballpark
- The sold-data client is abstracted behind a small interface, so a future swap to Apify or eBay Marketplace Insights is localized

Known RapidAPI tradeoffs we accept:
- No eBay item IDs → dedup stays soft (existing `(title, price, sale_date)` tuple)
- Scraping fragility → we monitor `collection_jobs.status=FAILED` and address if it spikes

## Architecture

**Trigger:** Every new pin automatically fires a comp lookup after reference-label parsing completes. Lookup runs async; pin processing is not blocked.

**Cache-first:** Before hitting the API, query `ebay_listings` for sold listings whose `parsed_fields` overlap the pin's parsed fields. If ≥5 relevant comps exist locally, skip the API call.

**Guardrails:**
- Skip if the pin has fewer than 2 useful parsed fields (query too broad)
- Per-day spend cap on API calls (not total listings)

**Weighting:** Comps scored by relevance × recency decay. No hard TTL — old data is downweighted, not discarded.

## Components

### 1. Sold-data client interface (`src/services/sold_data_client.py`, new thin wrapper)

A module-level async function that is the only entry point the rest of the code uses:

```python
async def fetch_sold_listings(query: str, max_results: int = 50) -> SoldDataResult:
    ...
```

Today this delegates to `rapidapi_client.fetch_sold_listings`. Future source swaps change only this file.

`SoldDataResult` is a typed dict: `{"aggregates": {...}, "products": [...]}` — the shape the existing RapidAPI client already returns.

### 2. Comp lookup service (`src/pipeline/comp_lookup.py`, new)

- `async def lookup_comps_for_pin(pin_id: int) -> CompResult`
- Builds query string from parsed fields in priority order (character + franchise + edition_size + year)
- Sparseness guardrail → returns `SKIPPED_SPARSE` if < 2 useful fields
- Daily cap check → returns `SKIPPED_CAPPED` if hit
- Cache check: queries `ebay_listings` for sold rows with overlapping parsed fields
  - If ≥ `comp_cache_min_hits` relevant hits → use cache, no API call
- On cache miss: calls `sold_data_client.fetch_sold_listings`, stores results in `ebay_listings`, increments daily budget
- Scores comps with relevance × recency
- Writes top-N weighted comps to `comps` table with `match_type = "rapidapi_sold"` and the computed `weight`

### 3. Scoring (`src/pipeline/comp_scoring.py`, new)

Pure functions, no I/O:

```python
def score_comp(pin_fields: dict, comp_fields: dict, sale_date: date, today: date) -> float:
    relevance = _field_overlap_score(pin_fields, comp_fields)  # 0.0 to 1.0
    days_old = max(0, (today - sale_date).days)
    recency = math.exp(-days_old / HALF_LIFE_DAYS)
    return relevance * recency
```

- `HALF_LIFE_DAYS` sourced from `comp_recency_half_life_days` (default 90)
- `_field_overlap_score`: +0.4 character match, +0.3 franchise match, +0.2 edition_size exact, +0.1 year within ±1
- Weighted price recommendation = `sum(price × weight) / sum(weight)`
- Confidence band = IQR of the weighted sample

### 4. Pipeline hook (`src/pipeline/processing.py`, modified)

After `parse_reference_label` succeeds, enqueue a comp lookup via the existing async task mechanism. Failures are logged and do not block pin processing.

### 5. CLI changes (`scripts/collect_listings.py`)

- `sold` subcommand: unchanged (still useful for ad-hoc market research)
- New `comps` subcommand: `collect_listings.py comps --pin-id 42` for manual trigger / debugging
- `--refresh` flag on `comps` to force re-query even if cache hits

### 6. Config (`src/config.py`, modified)

New settings added; existing `rapidapi_*` settings kept.

| Setting | Default | Notes |
|---------|---------|-------|
| `comp_lookup_daily_limit` | `50` | Max sold-data API calls per UTC day |
| `comp_recency_half_life_days` | `90` | Exponential decay half-life |
| `comp_min_parsed_fields` | `2` | Sparseness floor |
| `comp_cache_min_hits` | `5` | Skip API if local cache has this many relevant comps |
| `comp_max_results_per_lookup` | `50` | Passed to `sold_data_client.fetch_sold_listings` |

## Data Model Changes

**No new large tables.** Existing `ebay_listings` and `comps` accommodate this.

`comps` table:
- New `match_type` value: `"rapidapi_sold"`
- New nullable `weight` (FLOAT) column — computed weight for the comp, used for debugging and UI display

New lightweight table `comp_lookup_budget`:

| Column | Type | Notes |
|--------|------|-------|
| `date` | DATE PK | UTC day |
| `calls` | INTEGER | count of sold-data API calls made |

Used only for daily cap enforcement.

## Failure Modes

- **API timeout/error:** lookup returns `FAILED`, error stored in `collection_jobs`, pin continues without comps. Retry is a manual action.
- **Sparse parsed fields:** lookup returns `SKIPPED_SPARSE`, flagged on the pin in the review UI.
- **Daily cap hit:** lookup returns `SKIPPED_CAPPED`, pin flagged for next-day retry.
- **Zero useful comps after scoring:** pin shows "no comps available" in the UI; no price recommendation.

## Testing

- Unit: `score_comp` with synthetic pin/comp fields and sale dates
- Unit: `_field_overlap_score` edge cases (empty fields, case mismatch, list vs scalar characters)
- Unit: daily cap enforcement (monkeypatch date)
- Unit: sparseness guardrail (various parsed-field shapes)
- Integration: `lookup_comps_for_pin` end-to-end with mocked sold-data client
- Integration: cache-hit path (prepopulate `ebay_listings`, assert no API call)
- Integration: cache-miss path (API called, results stored, comps written)

## Migration

- No source swap. Existing `rapidapi_client.py` stays as-is.
- New thin `sold_data_client.py` wrapper added; callers updated to import from the wrapper.
- Alembic-style idempotent migration adds `comps.weight` column and creates `comp_lookup_budget`.
- Existing 99 pins: not backfilled automatically. Separate one-off backfill out of scope here.

## Parallel Track: Marketplace Insights API

Apply for eBay Business account access in parallel. If approved, a future design replaces the sold-data client internals with the official SDK — same scoring, same cache, same pipeline hook. Tracked as a README note in `docs/`, no code work until approval lands.

## Scope Boundaries

**In scope:**
- `sold_data_client.py` wrapper around existing RapidAPI client
- `comp_lookup.py` service (cache-first, guardrails, scoring, DB writes)
- `comp_scoring.py` pure scoring functions
- Pipeline auto-trigger hook
- New `comps` CLI subcommand
- Config settings for cap / half-life / sparseness
- `comps.weight` column and `comp_lookup_budget` table

**Out of scope:**
- Switching sold-data source (Apify or Marketplace Insights)
- Bulk backfill of existing pins
- UI beyond surfacing "comps available / skipped / failed" states
- Alternative scoring models (ML, per-franchise weights) — default linear weights only
