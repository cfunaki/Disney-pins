# Apify Sold-Data Comps — Design Spec

## Goal

Replace the RapidAPI sold-listings integration with a **targeted, per-pin** comp lookup backed by Apify. Automatically attach recency-weighted price comps to every new pin, while keeping monthly API spend in the $5–10 range for a solo operator.

## Motivation

The existing `rapidapi_client.py` integration was built for broad keyword scraping (up to 240 results per query). In practice we only care about sold data that comps a specific pin we actually own. Broad scraping is expensive and produces mostly irrelevant data. A per-pin, cache-first model is cheaper, produces better comps, and turns the `ebay_listings` table into a durable asset that reduces spend over time.

RapidAPI's endpoint also has structural problems: no eBay item IDs (fragile dedup), 10+ second latency from CAPTCHA-based scraping, unclear pricing. Apify's actor ecosystem offers stable pricing, item IDs, and multiple actors specialized for sold-listing data.

## Architecture

**Trigger:** Every new pin automatically fires a comp lookup after reference-label parsing completes. The pipeline does not wait on it — lookups run async and populate the `comps` table when they finish.

**Cache-first:** Before hitting Apify, query the local `ebay_listings` table for sold listings whose `parsed_fields` overlap the pin's parsed fields. If ≥5 relevant comps exist locally, skip the API call entirely.

**Guardrails:**
- Skip lookup when the pin has fewer than 2 useful parsed fields (query would be too broad)
- Per-day spend cap enforced in code via a count of comp-lookup jobs per day

**Weighting:** Comps scored by relevance × recency decay. No hard TTL — old data is downweighted, not discarded.

## Components

### 1. Apify client (`src/services/apify_client.py`, replaces `rapidapi_client.py`)

- Async function `fetch_sold_listings(query: str, max_results: int = 50) -> dict`
- Submits a run to a chosen Apify actor, polls for completion, returns dataset items
- Reads `apify_token` and `apify_actor_id` from config
- Returns shape identical enough to the old RapidAPI response that `collect_listings.py sold` keeps working with minor adapter tweaks

**Default actor:** `ebay-sold-comps` (midwest_united) — provides aggregates + listing samples with confidence grading. Configurable if we want to swap.

### 2. Comp lookup service (`src/pipeline/comp_lookup.py`, new)

- `async def lookup_comps_for_pin(pin_id: int) -> CompResult`
- Builds query string from pin's parsed fields (character + franchise + edition_size + year, in priority order)
- Checks sparseness guardrail → returns early with status `SKIPPED_SPARSE` if fails
- Checks daily spend cap → returns `SKIPPED_CAPPED` if hit
- Cache check: queries `ebay_listings` for sold rows with overlapping parsed fields
  - If ≥5 relevant hits → use cache, skip API
- If cache miss: calls `apify_client.fetch_sold_listings`, stores results in `ebay_listings`
- Scores comps with relevance × recency weight
- Writes top-N weighted comps to `comps` table with `match_type = "apify_sold"`

### 3. Scoring (`src/pipeline/comp_scoring.py`, new)

Pure function, no I/O, easy to unit test:

```python
def score_comp(pin_fields: dict, comp_fields: dict, sale_date: date, today: date) -> float:
    relevance = _field_overlap_score(pin_fields, comp_fields)  # 0.0 to 1.0
    days_old = (today - sale_date).days
    recency = math.exp(-days_old / HALF_LIFE_DAYS)
    return relevance * recency
```

- `HALF_LIFE_DAYS = 90` (config override: `comp_recency_half_life_days`)
- `_field_overlap_score`: +0.4 character match, +0.3 franchise match, +0.2 edition_size exact, +0.1 year within ±1
- Weighted price = sum(price × weight) / sum(weight); confidence band = interquartile range of weighted sample

### 4. Pipeline hook (`src/pipeline/processing.py`, modified)

After `parse_reference_label` succeeds, enqueue a comp lookup task. Runs in the existing async task machinery — no new worker infrastructure. On failure, log and move on; pin processing is not blocked.

### 5. CLI changes (`scripts/collect_listings.py`)

- `sold` subcommand kept, rerouted to Apify client (unchanged UX)
- New `comps` subcommand: `collect_listings.py comps --pin-id 42` for manual trigger / debugging
- `--refresh` flag on `comps` to force a re-query even if cache hits

### 6. Config (`src/config.py`, modified)

| Setting | Default | Notes |
|---------|---------|-------|
| `apify_token` | `""` | Apify API token |
| `apify_sold_actor_id` | `"midwest_united/ebay-sold-comps"` | |
| `apify_poll_interval_sec` | `3.0` | Run status polling cadence |
| `apify_run_timeout_sec` | `180.0` | Max wait per run |
| `comp_lookup_daily_limit` | `50` | Max Apify calls per UTC day |
| `comp_recency_half_life_days` | `90` | Exponential decay half-life |
| `comp_min_parsed_fields` | `2` | Sparseness floor |
| `comp_cache_min_hits` | `5` | Skip API if local cache has this many relevant comps |

`rapidapi_*` settings removed.

## Data Model Changes

**No new tables.** Existing `ebay_listings` and `comps` tables accommodate this.

`comps` table gets a new `match_type` value: `"apify_sold"`. A new nullable column `weight` (FLOAT) records the computed weight used for the recommendation — useful for debugging and UI display.

A new lightweight table `comp_lookup_budget`:

| Column | Type | Notes |
|--------|------|-------|
| `date` | DATE PK | UTC day |
| `calls` | INTEGER | count of Apify calls made |

Used only for daily cap enforcement.

## Failure Modes

- **Apify timeout/error:** lookup returns status `FAILED`, error stored in `collection_jobs`, pin continues without comps. Retry is a separate manual action.
- **Sparse parsed fields:** lookup returns `SKIPPED_SPARSE`, flagged on the pin in the review UI.
- **Daily cap hit:** lookup returns `SKIPPED_CAPPED`, pin flagged for next-day retry (simple cron or manual batch).
- **Zero useful comps after scoring:** pin shows "no comps available" state in UI; no price recommendation.

## Testing

- Unit: `score_comp` with synthetic pin/comp fields and sale dates
- Unit: `_field_overlap_score` edge cases (empty fields, case mismatch, list vs scalar characters)
- Unit: Apify client with mocked HTTP
- Unit: daily cap enforcement (monkeypatch date)
- Integration: `lookup_comps_for_pin` end-to-end with mocked Apify returning fixture data
- Integration: cache-hit path (prepopulate `ebay_listings`, assert no Apify call)

## Migration

- Remove `src/services/rapidapi_client.py` and its tests
- Remove `rapidapi_*` settings from config
- `scripts/collect_listings.py sold` keeps the same UX; the underlying call swaps to Apify
- Existing 99 pins: not backfilled automatically. A separate one-off backfill script can run later if desired (out of scope for this design).

## Parallel Track: eBay Marketplace Insights API

Apply for eBay Business account access in parallel. If approved, a future design replaces the Apify client with an official SDK call — same scoring, same cache, same pipeline hook. Tracked as a README note in `docs/`, no code work until approval lands.

## Scope Boundaries

**In scope:**
- Apify client + per-pin comp lookup + scoring
- Pipeline hook, config, CLI changes
- Cache-first logic, daily cap, sparseness guardrail
- Replacing RapidAPI integration

**Out of scope:**
- Manual bulk backfill of existing pins
- UI changes beyond "comps available / skipped / failed" status surfaces
- Alternative Apify actor evaluation (we start with `ebay-sold-comps` and change only if it disappoints)
- Marketplace Insights API integration (separate future design)
