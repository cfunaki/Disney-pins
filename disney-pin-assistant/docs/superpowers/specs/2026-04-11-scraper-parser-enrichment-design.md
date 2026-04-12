# Scraper Parser Enhancement + NLP Enrichment

## Problem

The PinTradingDB scraper parser (`pintradingdb_parser.py`) leaves several available fields unextracted (Description, SKU, Retire Date, Original Price) and hardcodes `characters`, `franchise`, `series_or_collection`, and `event` to empty values. While PinTradingDB doesn't expose these four as structured fields, the data is present in pin titles and descriptions as free text and can be extracted via NLP.

## Goals

1. Capture all structured fields available on PinTradingDB detail pages
2. Extract `characters`, `franchise`, and `series_or_collection` from title/description via NLP
3. Make enrichment a separate, idempotent pass that can iterate independently of the scraper
4. Validate enrichment rules against existing scraped data before full catalog completes

## Non-Goals

- Extracting `event` from title/description (fuzzy, overlaps with pin types and origins — defer)
- Changing the scraper's rate limiting or concurrency model
- Building a vector/embedding pipeline (separate effort, uses CLIP)
- Modifying the ID cache or discovery logic

## Part 1: Parser Update

### New Fields

Add four fields to `parse_pin_detail()` output, extracted from `details_table` rows:

| Field | Source Row | Type | Example |
|-------|-----------|------|---------|
| `description` | "Description" | `str \| None` | "The Characters & Cameras Mystery Collection features..." |
| `sku` | "SKU" | `str \| None` | "400008192705" |
| `retire_date` | "Retire Date" | `str \| None` | "03/15/2016" or "Unknown!" |
| `original_price` | "Original Price" | `str \| None` | "$19.95 Box of 2" |

All extracted from existing HTML — no additional HTTP requests.

### Files Changed

- `scripts/scraper/pintradingdb_parser.py` — add field extraction in `parse_pin_detail()`
- `scripts/scraper/normalizer.py` — pass through new fields if needed
- `tests/fixtures/pintradingdb_detail.html` — update fixture with Description/SKU/Retire Date/Original Price rows
- `tests/test_pintradingdb_parser.py` — add assertions for new fields

## Part 2: Clean Re-scrape

After parser update ships:

1. Stop running scraper process
2. Delete `scripts/scraper/output/pintradingdb_catalog.json`
3. Keep `pin_ids_cache.json` (57,303 IDs — saves ~30 min discovery phase)
4. Keep `catalog_images/` directory (existing images skipped by `download_pin_image`)
5. Restart scraper: `python3 -u scripts/scrape_pintradingdb.py scrape --rate 0.165 2>&1 | tee scrape.log`

Expected behavior: re-scrapes previously-collected pins quickly (image downloads skipped), then continues through remaining ~51,500 pins. Total time ~6 days at 0.165 RPS.

## Part 3: NLP Enrichment Script

### Location

`scripts/enrich_catalog.py`

### Interface

```
python3 scripts/enrich_catalog.py [--input FILE] [--output FILE] [--dry-run] [--sample N]
```

- `--input` / `--output` default to `scripts/scraper/output/pintradingdb_catalog.json`
- When input == output, enriches in-place
- `--dry-run` prints stats without modifying the file
- `--sample N` prints N random enriched entries for eyeball validation

### Extraction Rules

**Characters** — scan `canonical_name` + `description` against `CHARACTER_ALIASES` from `scripts/scraper/pinpics_parser.py` (import, don't duplicate). Match is case-insensitive word-boundary search. Normalize via the alias map.

**Franchise** — infer from matched characters via `FRANCHISE_MAP` from `scripts/scraper/pinpics_parser.py`. If multiple franchises match, pick the one with the most character hits.

**Series/Collection** — regex patterns on `canonical_name`:
- `(.+?)\s+(?:Collection|Series)\b` — e.g., "Characters & Cameras Mystery Collection"
- `Mystery\s+(?:Pin\s+)?Collection` — special case
- Additional patterns TBD during validation

### Output Fields

For each entry where enrichment populates at least one field:

```json
{
  "characters": ["Dopey"],
  "franchise": "Snow White",
  "series_or_collection": "Characters & Cameras Mystery Collection",
  "enrichment_source": "nlp_title"
}
```

`enrichment_source` values: `"nlp_title"`, `"nlp_description"`, `"nlp_title+description"`.

### Invariants

- Never overwrites parser-derived fields (`canonical_name`, `edition_size`, `release_year`, `pin_type`, `exclusive_source`, `source_reference_id`, `reference_image_url`, `source`, `evidence_strength`)
- Never modifies `evidence_strength`
- Idempotent: safe to re-run; NLP-derived fields are overwritten on each run
- Does not require network access

## Part 4: Validation Run

Run enrichment against existing ~5,800 entries immediately after building the script.

### Metrics to Check

- Character match rate: % of entries with >= 1 character extracted
- Franchise coverage: % of character-matched entries with a franchise
- Series/collection detection rate
- False positive spot-check: sample 20 random enriched entries, eyeball quality

### Iteration

Adjust `CHARACTER_ALIASES`, `FRANCHISE_MAP`, and series regex patterns based on validation results. Re-run enrichment (idempotent) until quality is acceptable. Final re-run after full scrape completes.

## Testing

### Parser Tests

- Update `tests/fixtures/pintradingdb_detail.html` with Description, SKU, Retire Date, Original Price rows
- Add assertions in `tests/test_pintradingdb_parser.py` for new fields
- Test edge cases: missing rows, empty values, "Unknown!" retire date

### Enrichment Tests

- Unit tests for character extraction from sample titles
- Unit tests for franchise inference with single and multi-franchise titles
- Unit tests for series/collection regex patterns
- Edge cases: no matches, ambiguous characters (e.g., "Jack" could be Jack Skellington or Jack Sparrow)

## Dependencies

- `pinpics_parser.py` — reuse `CHARACTER_ALIASES` and `FRANCHISE_MAP` (import path: `scripts.scraper.pinpics_parser` or refactor maps to shared module if import is awkward)
- `beautifulsoup4` — already installed
- No new dependencies
