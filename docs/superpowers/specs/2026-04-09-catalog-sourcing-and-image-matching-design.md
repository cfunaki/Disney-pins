# Catalog Sourcing & Image-Based Pin Matching

## Problem

The current pin identification system relies on text-based attribute matching (characters, franchise, year, edition size, etc.). This is insufficient — popular characters like Mickey Mouse have dozens of limited edition pins per year with identical text attributes but completely different visual designs. Reliable identification requires visual comparison.

## Goals

1. Replace PinPics (Cloudflare-blocked) with PinTradingDB as the primary catalog source
2. Scrape catalog data **including images** for ~10K recent pins
3. Build a hybrid matching pipeline: text filtering narrows candidates, then CLIP visual similarity identifies the exact pin
4. Optional Claude Vision confirmation for low-confidence matches

## Non-Goals

- Full 57K pin scrape (start with recent ~10K, expand later)
- Hosted automation for scraping (start manual, automate later)
- Building a dedicated vector database (NumPy + SQLite is sufficient at this scale)

## Data Source: PinTradingDB

- **URL:** pintradingdb.com
- **Size:** ~57K pins, targeting recent ~10K to start
- **Access:** No Cloudflare, plain HTTP, works with httpx
- **Pagination:** AJAX at `ajaxPinList.php?pinPage={n}`
- **Pin detail:** `pin/{id}` with `.pinLabel` CSS class for structured fields
- **Fields available:** Pin name, characters, franchise, year, edition size, pin type, event, image URL

## Catalog Matching Pipeline

```
User uploads pin photo
        |
[1] Vision API extracts text attributes
    (characters, franchise, year, edition, pin type, event, search terms)
        |
[2] Text matching scores all catalog entries -> top 30 candidates
    (current weighted scoring in matching.py, loosened thresholds)
        |
[3] CLIP embedding of user's photo vs. pre-computed catalog embeddings
    -> re-rank candidates by visual similarity -> top 3-5
        |
[4] Claude Vision confirmation (if top CLIP match is not high-confidence)
    -> sends user photo + top 3 catalog images -> picks best match
        |
[5] Return matched catalog entry (or "no confident match" if scores too low)
```

### Confidence Thresholds

- CLIP similarity > 0.92: Auto-match, skip step 4
- CLIP similarity 0.75-0.92: Claude Vision confirms
- CLIP similarity < 0.75: No confident match, flag for manual review

Thresholds will be tuned against ground truth data from Phase 1A evaluation.

## Scraper Architecture

### Flow

1. Paginate through `ajaxPinList.php?pinPage={n}` to collect pin IDs
2. Fetch detail page per pin, parse structured fields from `.pinLabel` elements
3. Download pin image, save to `catalog_images/{pin_id}.jpg`
4. Generate CLIP embedding, store as BLOB in catalog DB
5. Checkpoint every 500 pins (same pattern as existing scraper)

### Rate Limiting

1 request/second default, using the existing `RateLimiter` class from `scripts/scraper/pinpics_fetcher.py`.

### Resume Support

Skip pin IDs already present in catalog DB (same pattern as `scrape_pinpics.py --resume`).

### Output

- Catalog entries in SQLite database (existing `pins.db` catalog table)
- Images in `catalog_images/` directory (gitignored)
- CLIP embeddings stored as BLOB column in catalog table

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| CLIP model | `openai/clip-vit-base-patch32` via `transformers` | Runs locally, no API cost, proven for visual similarity |
| Vector storage | NumPy arrays in SQLite BLOB column | No dedicated vector DB needed at 10K scale |
| Image storage | Local `catalog_images/` directory | ~2 GB for 10K pins, negligible hosted cost |
| HTTP client | httpx (async) | Already used by existing scraper |
| HTML parsing | BeautifulSoup | Already a project dependency |

## Storage Estimates

| Asset | Size (10K pins) | Size (57K pins) |
|-------|-----------------|-----------------|
| Catalog images | ~2 GB | ~12 GB |
| CLIP embeddings | ~30 MB | ~170 MB |
| Metadata/DB | < 10 MB | < 50 MB |
| Hosted cost (S3) | ~$0.05/mo | ~$0.30/mo |

## Update Cadence

- **Phase 1:** Manual runs via CLI (`python scripts/scrape_pintradingdb.py --recent`)
- **Phase 2:** Scheduled weekly scrape of newest pages only, incremental by last-seen ID

## Integration with Existing System

### What Changes

- `src/pipeline/matching.py`: After text scoring narrows to top 30, add CLIP re-ranking step
- `src/models/catalog.py`: Add `image_path` and `clip_embedding` columns to catalog model
- New `src/pipeline/image_matching.py`: CLIP embedding generation and similarity scoring
- New `scripts/scrape_pintradingdb.py`: CLI scraper (replaces PinPics scraper)

### What Stays the Same

- `src/pipeline/vision.py`: Still extracts text attributes from user photos
- Text-based scoring weights in `matching.py`: Still used as first-pass filter
- API endpoints for upload/process: No changes
- Evaluation workflow: Same ground truth comparison

## Risk Mitigation

- **PinTradingDB goes down/blocks us:** We store all data locally. Catalog continues to work from local copy. Can add PinPics (via Playwright) as fallback later.
- **CLIP accuracy insufficient:** Claude Vision confirmation step catches mismatches. If CLIP consistently underperforms, we can lower the auto-match threshold and lean more on Claude Vision.
- **CLIP model too large for deployment:** `clip-vit-base-patch32` is ~600 MB. Acceptable for a server deployment. For edge cases, could use ONNX-quantized version (~150 MB).
