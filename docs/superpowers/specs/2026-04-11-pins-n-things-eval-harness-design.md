# pins-n-things Eval Harness — Design Spec

**Date:** 2026-04-11
**Status:** Draft
**Author:** chris-funaki-sh (with Claude)
**Working directory:** `disney-pin-assistant/` unless a path starts with `docs/`.

## Purpose

Build an evaluation harness that measures how accurately the existing image-to-metadata pipeline (vision extraction + hybrid CLIP/text catalog matching) identifies Disney pins, using live eBay listings from the **pins-n-things** seller as a real-world test corpus.

The harness is **Phase 1** of a larger goal: harden the pre-listing workflow so a photo of a pin produces an accurate, ready-to-paste listing draft. Phase 2 — actually improving the pipeline based on what we learn here — is intentionally out of scope and will become a separate spec once Phase 1 has surfaced real findings.

## Non-goals

Explicit, to keep scope disciplined:

- No price comparison, no sold-listing data, no Marketplace Insights API work.
- No changes to the vision model, matching pipeline, or catalog data sources.
- No accuracy scores, metrics dashboards, or automated grading. Output is a **disagreement surface**, not a pass/fail metric.
- No multi-seller ingestion in one run; CLI takes one seller, re-run for others.
- No incremental ingestion ("listings added since last run"). Full passes only; duplicate detection handles idempotency.
- No uploads to chfun4444 or any other Sell API work.
- No Sandbox integration. Real work requires production keys; Sandbox has no corpus to evaluate against.
- No backfill script for re-parsing existing `reference_parsed_fields`. Added later if needed.
- No aggregate reports or multi-batch rollups. Everything is reviewed in a single batch through the existing review UI.

## Prerequisites

The plan derived from this spec **cannot start execution** until all of these are true:

1. **Production eBay keyset activated.** Requires either deletion-notification exemption granted (preferred) or a deletion webhook endpoint deployed. The existing `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` in `.env` must be production-tier.
2. **Human review UI shipped** per `docs/superpowers/plans/2026-04-10-human-review-ui.md` — specifically `review.html`, `static/review.js`, the `/queue/{batch_id}` route pointing at the new template, `_pin_to_dict` in `src/routes/pins.py`, and the `Pin.no_catalog_match` column.
3. **`ANTHROPIC_API_KEY`** present in `.env` (already the case).

Until prerequisite 1 is met, development can still proceed against recorded Browse API fixtures, and unit tests can run without any real API calls.

## Architecture overview

```
eBay Browse API
     │
     │ filter=sellers:pins-n-things
     ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────┐
│ import_ebay_     │───▶│  label parser    │───▶│  Pin rows    │
│ seller.py (CLI)  │    │  (Claude Haiku,  │    │  w/ reference│
│                  │    │  one call per    │    │  columns     │
│ • enumerate      │    │  listing)        │    │  populated   │
│ • download imgs  │    └──────────────────┘    └──────┬───────┘
│ • create batch   │                                   │
└──────────────────┘                                   ▼
                                                ┌──────────────┐
                                                │  existing    │
                                                │  orchestrator│
                                                │  (vision +   │
                                                │   match +    │
                                                │   draft gen) │
                                                └──────┬───────┘
                                                       │
                                                       ▼
                                                ┌──────────────┐
                                                │ review.html  │
                                                │ + diff       │
                                                │ overlay      │
                                                └──────────────┘
```

The three new things built in this spec:

1. **`scripts/import_ebay_seller.py`** — CLI that ingests a seller's live listings through the Browse API, downloads images, creates `Pin` rows in a named batch, and enqueues them for normal processing.
2. **`src/pipeline/reference_label.py`** — single function `parse_listing_label(title, description)` that extracts structured metadata from a noisy listing title using Claude Haiku.
3. **Diff overlay on the review UI** — an additive section in `review.html` / `review.js` that renders tool output vs. parsed reference label side-by-side, highlighting disagreements. Zero new endpoints.

Everything else — vision extraction, catalog matching, draft generation, batch orchestration, review workspace — is existing or already-planned code that the harness composes with unchanged.

## Fields and grading model

Fields are split into three buckets based on where the information can come from:

### Bucket A — image-inferable (vision model output)

Graded strictly because a clear image should yield these unambiguously:

- **`characters`** — Disney characters appearing on the pin.
- **`franchise`** — classification like "Classic Disney", "Star Wars", "Pixar".

### Bucket B — catalog-derived (matched catalog entry)

Graded loosely because these fields only exist on the tool side if the matching pipeline finds the right entry. When a match *is* found, individual field comparisons can still be strict — the looseness is about coverage (did we match at all?), not about how agreement is scored per field.

- **`canonical_name`** — the standardized pin name (strict string compare against matched catalog entry).
- **`series_or_collection`**
- **`release_year`**
- **`edition_size`**

### Bucket C — carried through but not graded

Not reliably inferable from the image, and often missing in both the catalog and the reference listing. Still rendered in the diff overlay if present on either side, but disagreements here are noise and can be ignored:

- **`event`**
- **`pin_type`**
- **`exclusive_source`**

### Grading model

Ground truth = friend's listing title parsed into structured fields via the label parser. The harness does **not** produce an accuracy number. Instead, the review UI's diff overlay surfaces each pin's disagreements and the user reviews them one at a time through the existing review workspace, accepting or rejecting catalog matches and editing extraction as already planned. Disagreement review is where labeling patterns and pipeline gaps are discovered.

Catalog coverage — the fraction of pins-n-things listings that have *any* plausible catalog match — is surfaced implicitly via the `Pin.no_catalog_match` flag already added by the human review UI plan. A pin marked `no_catalog_match=True` with a non-empty `reference_parsed_fields` is a coverage gap.

## Schema changes

One table modified, no new tables. All additions to `Pin` are nullable; normal user uploads ignore them entirely.

```python
# src/models.py — additions to Pin
reference_source          = Column(String,   nullable=True)   # e.g. "ebay_browse"
reference_external_id     = Column(String,   nullable=True)   # eBay item ID
reference_url             = Column(String,   nullable=True)   # listing URL
reference_raw_title       = Column(Text,     nullable=True)   # original listing title
reference_raw_description = Column(Text,     nullable=True)   # original listing body
reference_parsed_fields   = Column(JSON,     nullable=True)   # output of label parser
reference_ingested_at     = Column(DateTime, nullable=True)   # when we pulled it
```

**Field notes:**

- `reference_source` is a plain string rather than an enum to keep migration trivial and leave room for future sources.
- Uniqueness for `(reference_source, reference_external_id)` is enforced at ingestion time in code, not via DB constraint, so re-runs against the same seller refresh existing rows instead of failing.
- `reference_parsed_fields` stores the parser output verbatim. Loose-by-design so the parser can evolve without schema migrations.
- `reference_raw_description` is stored even though it's often boilerplate, because occasionally the description contains info the title lacks (e.g., edition size buried in the body). Disk is cheap.

### Migration

Follow the same pattern as `Pin.no_catalog_match` from the human-review-ui plan — idempotent `ALTER TABLE` in `src/database.py` on startup, wrapped in a `try/except OperationalError` so re-runs are safe:

```python
async def ensure_reference_label_columns(engine):
    statements = [
        "ALTER TABLE pins ADD COLUMN reference_source TEXT",
        "ALTER TABLE pins ADD COLUMN reference_external_id TEXT",
        "ALTER TABLE pins ADD COLUMN reference_url TEXT",
        "ALTER TABLE pins ADD COLUMN reference_raw_title TEXT",
        "ALTER TABLE pins ADD COLUMN reference_raw_description TEXT",
        "ALTER TABLE pins ADD COLUMN reference_parsed_fields JSON",
        "ALTER TABLE pins ADD COLUMN reference_ingested_at DATETIME",
    ]
    async with engine.begin() as conn:
        for sql in statements:
            try:
                await conn.execute(text(sql))
            except OperationalError:
                pass  # column already exists
```

### `_pin_to_dict` extension

The serializer in `src/routes/pins.py` includes the seven reference columns **only when `reference_source` is non-null**, keeping the payload lean for normal uploads.

## Ingestion component: `scripts/import_ebay_seller.py`

### CLI interface

```
python scripts/import_ebay_seller.py \
    --seller pins-n-things \
    --batch-name "pnt-eval-2026-04-11" \
    [--max 500] \
    [--skip-processing] \
    [--dry-run]
```

| Flag | Required | Effect |
|---|---|---|
| `--seller` | yes | eBay username for Browse API `sellers` filter |
| `--batch-name` | yes | Human-readable batch label. Re-runs with the same name append to the existing batch (idempotent). |
| `--max` | no | Cap on listings to ingest, default unlimited. Useful for smoke tests. |
| `--skip-processing` | no | Ingest pins but do not enqueue for vision/match pipeline. Default: processing runs automatically after ingest. |
| `--dry-run` | no | Hit the API, parse labels, print what would be created, write nothing. |

### Execution flow

1. **Auth.** Acquire an application token via `client_credentials` grant using `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`. Cache in memory for the duration of the run.
2. **Enumerate.** Call `GET /buy/browse/v1/item_summary/search?filter=sellers:{seller}&limit=200&offset=N` in a loop until `total` is exhausted or `--max` is hit.
3. **Skip duplicates.** For each `itemId`, check whether a Pin already exists with `reference_source='ebay_browse'` AND `reference_external_id=itemId`. If yes, refresh parsed fields; do not re-download the image.
4. **Fetch details.** For new listings, call `GET /buy/browse/v1/item/{itemId}` to get the full title, description, and high-res image URLs.
5. **Download image.** Fetch the primary high-res image from the CDN URL and save to `uploads/{batch_id}/{safe_filename}.jpg`, matching the existing upload convention.
6. **Parse reference label.** Call `reference_label.parse_listing_label(title, description)`; store result (or `None` on failure) in `reference_parsed_fields`.
7. **Create Pin row.** Populate all seven reference columns, `image_paths=[downloaded_path]`, `status=UNPROCESSED`, tied to the batch.
8. **Enqueue.** Unless `--skip-processing`, trigger the existing batch processing orchestrator for the batch.

### Re-run semantics

Idempotent: re-running with the same `--batch-name` refreshes existing pins' `reference_parsed_fields` and adds any new listings. Does not delete pins that have disappeared from the seller's live listings. This is deliberate — we want to keep evidence of old pins for comparison, not silently drop them.

### Rate limiting and errors

| Failure | Behavior |
|---|---|
| Browse API 401 / 403 | Print a clear "check EBAY_* env vars and production activation" message and exit 1. |
| Browse API 429 | Print rate-limit message from response and exit. No silent backoff. |
| Browse API 5xx on search | One retry, then fail the run. |
| `getItem` 404 mid-run | Listing ended between calls. Log, skip, continue. |
| Image download failure | Log, skip pin (do not create a Pin row with a missing image), count in summary. |
| Label parser failure | Log, create Pin with `reference_parsed_fields=null`. Raw title is preserved; diff overlay falls back to showing raw title only. |
| Token expiry mid-run | One retry after refreshing; fail loudly if second attempt fails. |

### Reuse vs. new code

Extend `src/services/ebay_client.py` — do not replace it. Add whichever of these methods is missing:

- `get_application_token()` — client-credentials token acquisition with in-memory cache.
- `search_seller(seller, offset, limit)` — Browse API `item_summary/search` with `filter=sellers:{seller}`.
- `get_item(item_id)` — Browse API `item/{item_id}` for full details.

The existing image download helper (wherever the normal upload flow persists images) is reused unchanged.

### Output summary

At the end of a run, print a one-screen summary:

```
pins-n-things ingestion complete
  batch: pnt-eval-2026-04-11 (id=42)
  listings seen: 247
  new pins created: 231
  duplicates refreshed: 14
  errors: 2 (image download fail, see log)
  label parser failures: 0
  processing: enqueued
```

## Reference label parser: `src/pipeline/reference_label.py`

### Signature

```python
async def parse_listing_label(
    title: str,
    description: str | None = None,
) -> dict:
    """
    Extract structured metadata from a noisy eBay listing title/description.
    Returns a dict with whatever fields the LLM could confidently extract.
    Unextracted fields are omitted (not set to null).
    """
```

### Model and config

- **Model:** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`).
- **Temperature:** 0 for deterministic, repeatable output.
- **Output format:** JSON object requested in the prompt.
- **Why LLM over regex:** pin listing titles are chaotic (`"DSSH Maleficent dragon LE250 new"`, `"Hidden Mickey 2022 Series 1 Pluto pin trading"`). Keyword-regex extraction tops out around 40%; a zero-shot Haiku call gets 95%+ for fractions of a cent per listing.

### Output schema (loose)

```json
{
  "characters":          ["..."],
  "franchise":           "...",
  "series_or_collection": "...",
  "release_year":        2019,
  "edition_size":        250,
  "is_limited_edition":  true,
  "pin_type":            "hidden_mickey",
  "event":               null,
  "exclusive_source":    "DSSH",
  "confidence_notes":    "free text"
}
```

Every field except `confidence_notes` is **optional**. If the parser is not confident, it omits the field entirely. Within a successful parser result, an **absent key** means "not extracted" — the diff overlay treats it as "we don't know" and renders it muted.

This is distinct from a **whole-call failure** (network error, unparseable JSON), in which case the ingestion CLI stores `reference_parsed_fields = null` on the Pin row. At the column level, `null` means "parser never produced a result"; at the dict level, a missing key means "parser ran but didn't extract this field." The diff overlay handles both — a null column falls back to showing the raw title only.

### Prompt strategy

Prompt wording is **not frozen in the spec** and is expected to iterate during implementation. Requirements on the prompt:

- System prompt describes the domain ("parse eBay Disney pin listings") and the output schema.
- Instructs the model to omit fields it's not confident about rather than guess.
- Asks for JSON output only, no prose.

### Cost sanity check

~500 input tokens + ~200 output tokens per listing. At Haiku 4.5 pricing (~$0.80/$4 per M tokens), that's <0.05¢ per listing. For 500 listings, under 25¢ total. Non-issue.

### Error handling

- **LLM call fails (network, 5xx):** one retry, then raise. Caller (ingestion CLI) catches and creates the Pin with `reference_parsed_fields=null`.
- **LLM returns unparseable JSON:** log raw response, return `None`. Do not attempt to patch malformed JSON.
- **LLM returns unexpected fields:** accept verbatim. The diff overlay only renders known fields; unknown fields are harmless.

### Where it's called from

Only from `scripts/import_ebay_seller.py` at ingest time, synchronously per pin. **Never called from the review UI**, so re-parsing old listings requires a deliberate backfill script (not included in this spec).

## Review UI diff overlay

Smallest UI change possible: one additive section in the right pane of `review.html`, hidden by CSS when the pin has no `reference_source`.

### Layout

```
┌─ Reference label (pins-n-things) ──────────────── [↗ eBay]  [▾]
│
│   Raw title
│   ──────────
│   "Disney Pin Lilo Stitch cute kawaii 2019 LE Hidden Mickey Series 1"
│
│   Parsed reference             Tool extraction
│   ─────────────────            ───────────────
│   characters     Lilo, Stitch  ✓ Lilo, Stitch
│   franchise      (not parsed)  ⚠ Classic Disney         (tool-only)
│   year           2019          ✓ 2019
│   series         Hidden Mickey ✗ Hidden Mickey 2023     (mismatch)
│                  Series 1        Series 2
│   edition_size   (not parsed)    LE 2000                (tool-only)
│   LE flag        true          ✓ true
│
└────────────────────────────────────────────────────────────────
```

### Diff semantics

| Icon | Meaning |
|---|---|
| `✓` | Both sides present and agree (case-insensitive, set-equal for lists) |
| `✗` | Both sides present and disagree |
| `⚠` | One side present, other not — noteworthy but not a graded failure |
| *(muted)* | Neither side present |

An eBay-link icon at the top-right opens the original listing in a new tab. The section is **collapsed by default when all rows are `✓`**, **expanded by default when any `✗` is present**, so disagreements self-surface as you page through a batch.

### Tool-side data source per field

| Field | Tool-side source |
|---|---|
| `characters` | Vision model output (Bucket A) |
| `franchise` | Vision model output (Bucket A) |
| `canonical_name` | Matched catalog entry (Bucket B) |
| `series_or_collection` | Matched catalog entry |
| `release_year` | Matched catalog entry |
| `edition_size` | Matched catalog entry |
| `event`, `pin_type`, `exclusive_source` | Matched catalog entry (Bucket C — rendered but not graded) |

If `pin.no_catalog_match=True`, Bucket B fields render as `(no match)` on the tool side. This makes coverage gaps obvious in the diff without any new tracking.

### Client-side diff logic

Intentionally conservative — we'd rather miss a disagreement than clutter the diff with false positives. Refinements get added *after* real data surfaces specific cases worth catching.

- **Character lists:** normalize each entry (lowercase, strip), compare as sets. Partial overlap = `✗`.
- **String fields (franchise, series, event):** case-insensitive substring either direction = `✓`. So `"Hidden Mickey"` vs `"Hidden Mickey 2023 Series 1"` agrees.
- **Numeric fields (year, edition_size):** exact equality.
- **Booleans (is_LE):** exact equality.

### Implementation footprint

- `src/templates/review.html` — add one `<section>` block in the right pane, conditionally rendered via `{% if pin.reference_source %}...{% endif %}`. Thin scaffolding only; content is built by JS at runtime.
- `static/review.js` — new pure function `renderReferenceLabel(pin)` that reads from the already-fetched pin object and renders the diff. No new fetch calls.
- `static/style.css` — new classes for diff rows, status icons, muted state. Match existing review UI visual language.
- `src/routes/pins.py` — extend `_pin_to_dict` to include the seven reference columns when `reference_source` is non-null. ~10 lines, the only server-side change.

**No new endpoints.** Reference data rides along on the existing review API payload.

## Testing strategy

### Unit tests (fast, no network, CI-safe)

- `tests/test_reference_label_parser.py` — mocked Anthropic client, ~10 fixture titles spanning the title-chaos spectrum. Asserts returned dict shapes and the "omit uncertain fields" contract.
- `tests/test_import_ebay_seller.py` — mocked Browse API client with recorded fixture responses. Asserts Pin rows get created with all seven reference columns populated, duplicate detection works, `--dry-run` writes nothing.
- `tests/test_pin_to_dict_reference_fields.py` — asserts `_pin_to_dict` serializes reference columns when present and omits them when null.
- `tests/test_diff_overlay_logic.py` — unit tests for diff comparison logic. If the repo has no JS test harness, the diff logic is mirrored in a small Python helper and unit-tested there, with the JS as a thin wrapper.

### Integration smoke tests (manual, not in CI)

- Dry-run `import_ebay_seller.py --seller pins-n-things --dry-run --max 5` against the real Browse API — verifies auth, pagination, and image URL shape in one shot. Requires production keys.
- Full end-to-end: ingest 5 real listings, open the batch in the review UI, verify the diff overlay renders and disagreements look sane.

### What we do not test

- Real LLM calls in CI — too flaky and too expensive. Fixtures only.
- Exact prompt wording — the prompt is expected to evolve; tests assert shape, not content.
- Real Browse API calls in CI — same reasoning.

## Open questions

- **Disagreement-only filter view.** If the small corpus (~a few hundred listings) turns out to have too many agreements and you want a "show only disagreements" filter, we can add a `?disagreements_only=1` query param on the existing queue page. Not in this spec — add if it becomes necessary.
- **Description parsing.** Currently the parser receives both title and description; if descriptions are mostly shipping boilerplate and add no signal, we can drop them from the parser input later. Decide once real data is in hand.
