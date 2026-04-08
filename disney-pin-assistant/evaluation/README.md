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
