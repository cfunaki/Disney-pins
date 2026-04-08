# Phase 1A Evaluation Workflow

## Prerequisites

1. **Anthropic API key:** Sign up at https://console.anthropic.com, create an API key
2. **Pin photos:** Collect 10-20 pin photos from your friend's eBay listings
3. **Reference data:** Note down the listing title, description, price, and pin details for each photo

## Setup

1. Copy `.env.example` to `.env` and add your Anthropic API key:

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

2. Install dependencies:

```bash
pip install -e ".[dev]"
```

3. Place pin photos in `sample_data/`:

```bash
mkdir -p sample_data
# Copy pin photos here (jpg, png, or webp)
```

## Step 1: Collect Ground Truth

Run the interactive collection script to record your friend's listing data:

```bash
python scripts/collect_ground_truth.py
```

For each photo, enter:
- Friend's listing title (required)
- Friend's description
- Friend's price
- Expected characters, franchise, pin type, edition size
- Any notes

This creates `evaluation/ground_truth.json`.

## Step 2: Upload and Process Pins

Start the app:

```bash
uvicorn src.main:app --reload
```

Then either:

**Option A: Use the web UI**
1. Open http://localhost:8000
2. Upload all pin photos from `sample_data/`
3. Click "Process Batch"
4. Wait for processing to complete
5. Note the batch ID from the URL (e.g., `http://localhost:8000/queue/abc12345` → batch_id is `abc12345`)

**Option B: Use the API directly**
```bash
# Upload photos
curl -X POST http://localhost:8000/api/upload \
  -F "files=@sample_data/pin1.jpg" \
  -F "files=@sample_data/pin2.jpg"
# Note the batch_id from the response

# Process the batch
curl -X POST http://localhost:8000/api/batch/{batch_id}/process
```

## Step 3: Generate Scorecard

```bash
python scripts/generate_scorecard.py {batch_id}
```

This compares AI output against ground truth and produces:
- `evaluation/scorecard.md` — human-readable results with pass/fail gate
- `evaluation/scorecard.json` — raw comparison data for further analysis

## Step 4: Review Results

Open `evaluation/scorecard.md` to see:
- Overall identification accuracy (target: 80%+)
- Listing quality / edit rate (target: 70%+ need no/minor edits)
- Per-pin breakdown of what the AI got right and wrong
- Automatic gate decision (PASS → proceed to Phase 1B, NEEDS WORK → tune vision prompt)

## If Results Need Improvement

1. Check `evaluation/scorecard.md` for patterns in failures
2. Tune the vision prompt in `src/pipeline/vision.py`
3. Re-run: delete `pins.db`, re-upload photos, re-process, re-generate scorecard
4. Iterate until targets are met

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
