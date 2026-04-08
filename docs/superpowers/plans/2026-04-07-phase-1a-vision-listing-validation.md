# Phase 1A: Vision + Listing Quality Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable end-to-end pipeline validation with real pin photos and no eBay dependency, then produce a scorecard comparing AI output against human-written reference listings.

**Architecture:** Make the pipeline gracefully skip eBay comp search when credentials aren't configured, add a ground truth collection script to store friend's reference listings, and add a scorecard generator that compares pipeline output against ground truth.

**Tech Stack:** Python, FastAPI (existing), asyncio, JSON for ground truth storage, markdown for scorecard output.

---

### Task 1: Add .env.example and Update .gitignore

**Files:**
- Create: `disney-pin-assistant/.env.example`
- Modify: `disney-pin-assistant/.gitignore`

- [ ] **Step 1: Create .env.example**

```
# Required for Phase 1A
ANTHROPIC_API_KEY=your-anthropic-api-key-here

# Required for Phase 1C (can be left empty for Phase 1A)
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=

# Optional overrides
# UPLOAD_DIR=./uploads
# DATABASE_URL=sqlite+aiosqlite:///./pins.db
# MAX_CONCURRENT_PROCESSING=5
```

- [ ] **Step 2: Update .gitignore to add evaluation and sample_data entries**

Add these lines to the existing `disney-pin-assistant/.gitignore`:

```
# Evaluation artifacts (scorecard is regenerated)
evaluation/scorecard.md

# Sample data for manual testing
sample_data/
```

- [ ] **Step 3: Commit**

```bash
git add disney-pin-assistant/.env.example disney-pin-assistant/.gitignore
git commit -m "chore: add .env.example and update .gitignore for evaluation"
```

---

### Task 2: Make Comp Search Skip Gracefully Without eBay Keys

**Files:**
- Modify: `disney-pin-assistant/src/pipeline/orchestrator.py:54-74`
- Test: `disney-pin-assistant/tests/test_orchestrator_skip_comps.py`

- [ ] **Step 1: Write the failing test**

Create `disney-pin-assistant/tests/test_orchestrator_skip_comps.py`:

```python
import pytest
from src.config import settings


def test_ebay_keys_empty_by_default():
    """Verify that when EBAY_CLIENT_ID is empty, the orchestrator
    should skip comp search rather than crash."""
    assert settings.ebay_client_id == "" or settings.ebay_client_id == "your-ebay-client-id"
```

This is a smoke test to verify the config state. The real behavioral test is manual (run pipeline, confirm no crash).

- [ ] **Step 2: Run test to verify it passes**

Run: `cd disney-pin-assistant && python -m pytest tests/test_orchestrator_skip_comps.py -v`
Expected: PASS (this confirms the default config has empty eBay keys)

- [ ] **Step 3: Modify orchestrator to skip comp search when eBay keys are empty**

In `disney-pin-assistant/src/pipeline/orchestrator.py`, replace the third `async with session_factory() as db:` block (the comp search block, lines 54-74) with:

```python
    async with session_factory() as db:
        pin = await db.get(Pin, pin_id)
        search_terms = extraction_data.get("suggested_search_terms", [])
        if matches:
            search_terms = [matches[0]["canonical_name"]] + search_terms

        all_comps = []
        if settings.ebay_client_id and settings.ebay_client_secret:
            sold_comps = await search_comps(search_terms[:1], listing_type="sold")
            active_comps = await search_comps(search_terms[:1], listing_type="active")
            all_comps = filter_comps(sold_comps + active_comps)
            for comp_data in all_comps:
                comp = Comp(
                    pin_id=pin.id, ebay_listing_id=comp_data.get("ebay_listing_id"),
                    title=comp_data["title"], price=comp_data["price"],
                    sale_date=comp_data.get("sale_date"), listing_type=ListingType(comp_data["listing_type"]),
                    condition=comp_data.get("condition"), match_type=MatchType.EXACT if matches else MatchType.NEAR,
                    excluded=comp_data.get("excluded", False), exclusion_reason=comp_data.get("exclusion_reason"),
                    raw_data=comp_data.get("raw_data"),
                )
                db.add(comp)

        pin.status = PinStatus.PRICED
        await db.commit()
```

Also add `from src.config import settings` to the imports at the top of the file (it's already imported but verify).

- [ ] **Step 4: Run full test suite to verify nothing breaks**

Run: `cd disney-pin-assistant && python -m pytest tests/ -v`
Expected: All 29+ tests PASS

- [ ] **Step 5: Commit**

```bash
git add disney-pin-assistant/src/pipeline/orchestrator.py disney-pin-assistant/tests/test_orchestrator_skip_comps.py
git commit -m "feat: skip eBay comp search when credentials not configured"
```

---

### Task 3: Ground Truth Collection Script

**Files:**
- Create: `disney-pin-assistant/scripts/collect_ground_truth.py`
- Create: `disney-pin-assistant/evaluation/` (directory)

This script lets the user record their friend's reference listings alongside pin photos. It creates a `ground_truth.json` file that the scorecard generator will compare against.

- [ ] **Step 1: Create the evaluation directory**

```bash
mkdir -p disney-pin-assistant/evaluation
```

- [ ] **Step 2: Create the ground truth collection script**

Create `disney-pin-assistant/scripts/collect_ground_truth.py`:

```python
"""
Collect ground truth reference data from a friend's eBay listings.

Usage:
    python scripts/collect_ground_truth.py

Walks through each image in sample_data/ and prompts for the friend's
listing title, description, price, and key identification fields.
Saves to evaluation/ground_truth.json.

If ground_truth.json already exists, only prompts for new images
not already in the file.
"""
import json
import sys
from pathlib import Path

GROUND_TRUTH_PATH = Path("evaluation/ground_truth.json")
SAMPLE_DIR = Path("sample_data")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def load_existing() -> dict:
    if GROUND_TRUTH_PATH.exists():
        return json.loads(GROUND_TRUTH_PATH.read_text())
    return {"pins": []}


def get_image_files() -> list[Path]:
    if not SAMPLE_DIR.exists():
        print(f"Create a {SAMPLE_DIR}/ directory with pin photos first.")
        sys.exit(1)
    files = sorted(
        p for p in SAMPLE_DIR.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not files:
        print(f"No image files found in {SAMPLE_DIR}/")
        sys.exit(1)
    return files


def prompt_field(label: str, required: bool = False, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    marker = " *" if required else ""
    while True:
        value = input(f"  {label}{marker}{suffix}: ").strip()
        if not value and default:
            return default
        if not value and required:
            print(f"    {label} is required.")
            continue
        return value


def prompt_float(label: str) -> float | None:
    value = prompt_field(label)
    if not value:
        return None
    try:
        return float(value.replace("$", "").replace(",", ""))
    except ValueError:
        print(f"    Invalid number, skipping.")
        return None


def collect_pin(image_file: Path) -> dict:
    print(f"\n--- {image_file.name} ---")
    return {
        "image_file": image_file.name,
        "reference_title": prompt_field("Friend's listing title", required=True),
        "reference_description": prompt_field("Friend's description (brief)"),
        "reference_price": prompt_float("Friend's price (e.g., 24.99)"),
        "expected_characters": prompt_field(
            "Characters (comma-separated)", required=True
        ).split(","),
        "expected_franchise": prompt_field("Franchise (e.g., Mickey & Friends)"),
        "expected_pin_type": prompt_field(
            "Pin type (e.g., limited edition, rack, hidden mickey)"
        ),
        "expected_edition_size": prompt_float("Edition size (or blank)"),
        "expected_event": prompt_field("Event (e.g., Food & Wine Festival, or blank)"),
        "notes": prompt_field("Any notes"),
    }


def main():
    data = load_existing()
    existing_files = {p["image_file"] for p in data["pins"]}
    image_files = get_image_files()

    new_files = [f for f in image_files if f.name not in existing_files]
    if not new_files:
        print(f"All {len(image_files)} images already have ground truth entries.")
        print(f"Delete {GROUND_TRUTH_PATH} to start over.")
        return

    print(f"Found {len(new_files)} new images to collect ground truth for.")
    print(f"({len(existing_files)} already recorded)")
    print("Enter reference data from your friend's eBay listings.")
    print("Fields marked with * are required. Press Enter to skip optional fields.\n")

    for img_file in new_files:
        try:
            pin_data = collect_pin(img_file)
            # Clean up character list
            pin_data["expected_characters"] = [
                c.strip() for c in pin_data["expected_characters"] if c.strip()
            ]
            if pin_data["expected_edition_size"]:
                pin_data["expected_edition_size"] = int(
                    pin_data["expected_edition_size"]
                )
            data["pins"].append(pin_data)
        except (KeyboardInterrupt, EOFError):
            print("\n\nStopping collection. Saving what we have so far...")
            break

    GROUND_TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH_PATH.write_text(json.dumps(data, indent=2))
    print(f"\nSaved {len(data['pins'])} entries to {GROUND_TRUTH_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Test the script runs without errors (no images needed)**

```bash
cd disney-pin-assistant && python scripts/collect_ground_truth.py
```

Expected: "Create a sample_data/ directory with pin photos first." (exits cleanly)

- [ ] **Step 4: Commit**

```bash
git add disney-pin-assistant/scripts/collect_ground_truth.py
git commit -m "feat: add ground truth collection script for evaluation"
```

---

### Task 4: Scorecard Generator Script

**Files:**
- Create: `disney-pin-assistant/scripts/generate_scorecard.py`

This script reads ground truth data and pipeline output from the database, compares them, and produces a markdown scorecard.

- [ ] **Step 1: Create the scorecard generator**

Create `disney-pin-assistant/scripts/generate_scorecard.py`:

```python
"""
Generate an evaluation scorecard comparing AI pipeline output against ground truth.

Usage:
    python scripts/generate_scorecard.py <batch_id>

Prerequisites:
    1. Ground truth collected: evaluation/ground_truth.json
    2. Pin photos uploaded and processed through the pipeline

Produces: evaluation/scorecard.md
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.database import engine, async_session
from src.models import Pin, PinStatus

GROUND_TRUTH_PATH = Path("evaluation/ground_truth.json")
SCORECARD_PATH = Path("evaluation/scorecard.md")


def load_ground_truth() -> dict:
    if not GROUND_TRUTH_PATH.exists():
        print("No ground truth found. Run collect_ground_truth.py first.")
        sys.exit(1)
    return json.loads(GROUND_TRUTH_PATH.read_text())


def match_pin_to_ground_truth(pin, ground_truth_pins: list[dict]) -> dict | None:
    """Match a processed pin to its ground truth entry by image filename."""
    if not pin.image_paths:
        return None
    pin_filename = Path(pin.image_paths[0]).name
    for gt in ground_truth_pins:
        if gt["image_file"] == pin_filename:
            return gt
    return None


def evaluate_identification(extraction, gt: dict) -> dict:
    """Compare vision extraction against ground truth identification."""
    if not extraction:
        return {"correct": False, "details": "No extraction data"}

    results = {}

    # Character match
    ai_chars = set(c.lower() for c in (extraction.characters or []))
    gt_chars = set(c.lower().strip() for c in (gt.get("expected_characters") or []))
    if gt_chars:
        char_overlap = ai_chars & gt_chars
        results["characters_match"] = len(char_overlap) > 0
        results["characters_ai"] = list(extraction.characters or [])
        results["characters_expected"] = gt.get("expected_characters", [])
    else:
        results["characters_match"] = None

    # Franchise match
    ai_franchise = (extraction.franchise or "").lower()
    gt_franchise = (gt.get("expected_franchise") or "").lower()
    if gt_franchise:
        results["franchise_match"] = gt_franchise in ai_franchise or ai_franchise in gt_franchise
        results["franchise_ai"] = extraction.franchise
        results["franchise_expected"] = gt.get("expected_franchise")
    else:
        results["franchise_match"] = None

    # Pin type match
    ai_type = (extraction.pin_type or "").lower()
    gt_type = (gt.get("expected_pin_type") or "").lower()
    if gt_type:
        results["pin_type_match"] = gt_type in ai_type or ai_type in gt_type
        results["pin_type_ai"] = extraction.pin_type
        results["pin_type_expected"] = gt.get("expected_pin_type")
    else:
        results["pin_type_match"] = None

    # Edition size match
    ai_edition = extraction.edition_size
    gt_edition = gt.get("expected_edition_size")
    if gt_edition:
        results["edition_match"] = ai_edition == int(gt_edition)
        results["edition_ai"] = ai_edition
        results["edition_expected"] = int(gt_edition)
    else:
        results["edition_match"] = None

    # Overall: correct if characters match and at least one other field matches
    scored_fields = [v for k, v in results.items() if k.endswith("_match") and v is not None]
    results["correct"] = all(scored_fields) if scored_fields else False

    return results


def evaluate_listing_quality(draft, gt: dict) -> dict:
    """Compare listing draft against reference listing."""
    if not draft:
        return {"edits_needed": "major", "details": "No draft generated"}

    ai_title = draft.title or ""
    ref_title = gt.get("reference_title") or ""

    # Simple heuristic: check if key words from reference appear in AI title
    ref_words = set(ref_title.lower().split())
    ai_words = set(ai_title.lower().split())
    # Remove common filler words
    filler = {"disney", "pin", "the", "a", "an", "-", "&", "and", "of"}
    ref_meaningful = ref_words - filler
    ai_meaningful = ai_words - filler

    if ref_meaningful:
        overlap = ref_meaningful & ai_meaningful
        overlap_ratio = len(overlap) / len(ref_meaningful)
    else:
        overlap_ratio = 0

    if overlap_ratio >= 0.6:
        edits_needed = "none"
    elif overlap_ratio >= 0.3:
        edits_needed = "minor"
    else:
        edits_needed = "major"

    return {
        "ai_title": ai_title,
        "reference_title": ref_title,
        "word_overlap_ratio": round(overlap_ratio, 2),
        "edits_needed": edits_needed,
    }


def generate_markdown(results: list[dict]) -> str:
    lines = ["# Phase 1A Evaluation Scorecard\n"]
    lines.append(f"**Pins evaluated:** {len(results)}\n")

    # Summary stats
    id_correct = sum(1 for r in results if r["identification"]["correct"])
    edits_none = sum(1 for r in results if r["listing"]["edits_needed"] == "none")
    edits_minor = sum(1 for r in results if r["listing"]["edits_needed"] == "minor")
    edits_major = sum(1 for r in results if r["listing"]["edits_needed"] == "major")
    total = len(results) or 1

    lines.append("## Summary\n")
    lines.append(f"| Metric | Result | Target |")
    lines.append(f"|--------|--------|--------|")
    lines.append(f"| Identification accuracy | {id_correct}/{total} ({id_correct/total*100:.0f}%) | 80%+ |")
    lines.append(f"| No/minor edits needed | {edits_none + edits_minor}/{total} ({(edits_none + edits_minor)/total*100:.0f}%) | 70%+ |")
    lines.append(f"| No edits needed | {edits_none}/{total} ({edits_none/total*100:.0f}%) | — |")
    lines.append(f"| Major rewrites needed | {edits_major}/{total} ({edits_major/total*100:.0f}%) | — |")
    lines.append("")

    # Gate decision
    id_pass = (id_correct / total) >= 0.8
    listing_pass = ((edits_none + edits_minor) / total) >= 0.7
    if id_pass and listing_pass:
        lines.append("**GATE DECISION: PASS** — Proceed to Phase 1B\n")
    else:
        lines.append("**GATE DECISION: NEEDS WORK** — Review failures below before proceeding\n")

    # Detail table
    lines.append("## Per-Pin Results\n")
    lines.append("| # | Image | ID Correct? | Characters | Franchise | Pin Type | Edits Needed | AI Title | Reference Title |")
    lines.append("|---|-------|-------------|------------|-----------|----------|-------------|----------|-----------------|")

    for i, r in enumerate(results, 1):
        ident = r["identification"]
        listing = r["listing"]
        char_ok = "Y" if ident.get("characters_match") else ("N" if ident.get("characters_match") is False else "—")
        fran_ok = "Y" if ident.get("franchise_match") else ("N" if ident.get("franchise_match") is False else "—")
        type_ok = "Y" if ident.get("pin_type_match") else ("N" if ident.get("pin_type_match") is False else "—")
        id_ok = "Y" if ident["correct"] else "N"

        lines.append(
            f"| {i} | {r['image_file']} | {id_ok} | {char_ok} | {fran_ok} | {type_ok} "
            f"| {listing['edits_needed']} | {listing.get('ai_title', '—')} | {listing.get('reference_title', '—')} |"
        )

    lines.append("")

    # Detailed failures
    failures = [r for r in results if not r["identification"]["correct"]]
    if failures:
        lines.append("## Identification Failures\n")
        for r in failures:
            ident = r["identification"]
            lines.append(f"### {r['image_file']}\n")
            if "characters_ai" in ident:
                lines.append(f"- **Characters:** AI={ident['characters_ai']}, Expected={ident['characters_expected']}, Match={ident.get('characters_match')}")
            if "franchise_ai" in ident:
                lines.append(f"- **Franchise:** AI={ident['franchise_ai']}, Expected={ident['franchise_expected']}, Match={ident.get('franchise_match')}")
            if "pin_type_ai" in ident:
                lines.append(f"- **Pin Type:** AI={ident['pin_type_ai']}, Expected={ident['pin_type_expected']}, Match={ident.get('pin_type_match')}")
            if "edition_ai" in ident:
                lines.append(f"- **Edition:** AI={ident['edition_ai']}, Expected={ident['edition_expected']}, Match={ident.get('edition_match')}")
            lines.append("")

    return "\n".join(lines)


async def main(batch_id: str):
    ground_truth = load_ground_truth()
    gt_pins = ground_truth["pins"]

    async with async_session() as db:
        result = await db.execute(
            select(Pin)
            .options(
                selectinload(Pin.extraction),
                selectinload(Pin.listing_draft),
            )
            .where(Pin.batch_id == batch_id)
        )
        pins = result.scalars().all()

    if not pins:
        print(f"No pins found for batch {batch_id}")
        sys.exit(1)

    print(f"Found {len(pins)} pins in batch {batch_id}")
    print(f"Found {len(gt_pins)} ground truth entries")

    results = []
    for pin in pins:
        gt = match_pin_to_ground_truth(pin, gt_pins)
        if not gt:
            print(f"  Warning: No ground truth for {pin.image_paths}")
            continue

        ident_eval = evaluate_identification(pin.extraction, gt)
        listing_eval = evaluate_listing_quality(pin.listing_draft, gt)

        results.append({
            "pin_id": pin.id,
            "image_file": gt["image_file"],
            "identification": ident_eval,
            "listing": listing_eval,
        })

    if not results:
        print("No pins matched to ground truth entries.")
        sys.exit(1)

    scorecard = generate_markdown(results)
    SCORECARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCORECARD_PATH.write_text(scorecard)
    print(f"\nScorecard saved to {SCORECARD_PATH}")
    print(scorecard)

    # Also save raw results as JSON for further analysis
    raw_path = SCORECARD_PATH.with_suffix(".json")
    raw_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Raw results saved to {raw_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/generate_scorecard.py <batch_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 2: Verify the script loads without import errors**

```bash
cd disney-pin-assistant && python -c "import scripts.generate_scorecard" 2>&1 || python scripts/generate_scorecard.py 2>&1 | head -1
```

Expected: "Usage: python scripts/generate_scorecard.py <batch_id>"

- [ ] **Step 3: Commit**

```bash
git add disney-pin-assistant/scripts/generate_scorecard.py
git commit -m "feat: add scorecard generator for Phase 1A evaluation"
```

---

### Task 5: Evaluation Workflow README

**Files:**
- Create: `disney-pin-assistant/evaluation/README.md`

- [ ] **Step 1: Create the evaluation README with step-by-step workflow**

Create `disney-pin-assistant/evaluation/README.md`:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add disney-pin-assistant/evaluation/README.md
git commit -m "docs: add Phase 1A evaluation workflow guide"
```

---

### Task 6: End-to-End Evaluation Test

**Files:**
- Create: `disney-pin-assistant/tests/test_evaluation_scripts.py`

Test that the scorecard generation logic works correctly with mock data (no API calls needed).

- [ ] **Step 1: Write tests for scorecard evaluation functions**

Create `disney-pin-assistant/tests/test_evaluation_scripts.py`:

```python
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_scorecard import evaluate_identification, evaluate_listing_quality, generate_markdown


def _make_extraction(**kwargs):
    """Create a mock extraction object with attribute access."""
    mock = MagicMock()
    mock.characters = kwargs.get("characters", [])
    mock.franchise = kwargs.get("franchise", None)
    mock.pin_type = kwargs.get("pin_type", None)
    mock.edition_size = kwargs.get("edition_size", None)
    return mock


def test_evaluate_identification_all_correct():
    extraction = _make_extraction(
        characters=["Mickey Mouse"],
        franchise="Mickey & Friends",
        pin_type="limited edition",
        edition_size=3000,
    )
    gt = {
        "expected_characters": ["Mickey Mouse"],
        "expected_franchise": "Mickey & Friends",
        "expected_pin_type": "limited edition",
        "expected_edition_size": 3000,
    }
    result = evaluate_identification(extraction, gt)
    assert result["correct"] is True
    assert result["characters_match"] is True
    assert result["franchise_match"] is True
    assert result["pin_type_match"] is True
    assert result["edition_match"] is True


def test_evaluate_identification_wrong_character():
    extraction = _make_extraction(
        characters=["Donald Duck"],
        franchise="Mickey & Friends",
        pin_type="rack",
    )
    gt = {
        "expected_characters": ["Mickey Mouse"],
        "expected_franchise": "Mickey & Friends",
        "expected_pin_type": "rack",
    }
    result = evaluate_identification(extraction, gt)
    assert result["correct"] is False
    assert result["characters_match"] is False
    assert result["franchise_match"] is True


def test_evaluate_identification_no_extraction():
    result = evaluate_identification(None, {"expected_characters": ["Mickey"]})
    assert result["correct"] is False


def test_evaluate_listing_quality_good_match():
    draft = MagicMock()
    draft.title = "Disney Mickey Mouse Food Wine Festival 2019 Pin LE/3000"
    gt = {"reference_title": "Disney Mickey Mouse Food & Wine 2019 Limited Edition Pin"}
    result = evaluate_listing_quality(draft, gt)
    assert result["edits_needed"] in ("none", "minor")


def test_evaluate_listing_quality_poor_match():
    draft = MagicMock()
    draft.title = "Disney Stitch Surfing Pin"
    gt = {"reference_title": "Mickey Mouse Epcot Food & Wine Festival 2019 LE 3000"}
    result = evaluate_listing_quality(draft, gt)
    assert result["edits_needed"] == "major"


def test_evaluate_listing_quality_no_draft():
    result = evaluate_listing_quality(None, {"reference_title": "Some Pin"})
    assert result["edits_needed"] == "major"


def test_generate_markdown_produces_gate_decision():
    results = [
        {
            "pin_id": 1,
            "image_file": "pin1.jpg",
            "identification": {"correct": True, "characters_match": True},
            "listing": {"edits_needed": "none", "ai_title": "AI Title", "reference_title": "Ref Title"},
        },
        {
            "pin_id": 2,
            "image_file": "pin2.jpg",
            "identification": {"correct": True, "characters_match": True},
            "listing": {"edits_needed": "minor", "ai_title": "AI Title 2", "reference_title": "Ref Title 2"},
        },
    ]
    md = generate_markdown(results)
    assert "GATE DECISION" in md
    assert "PASS" in md
    assert "pin1.jpg" in md
    assert "pin2.jpg" in md
```

- [ ] **Step 2: Run the tests**

Run: `cd disney-pin-assistant && python -m pytest tests/test_evaluation_scripts.py -v`
Expected: All 7 tests PASS

- [ ] **Step 3: Commit**

```bash
git add disney-pin-assistant/tests/test_evaluation_scripts.py
git commit -m "test: add evaluation scorecard unit tests"
```

---

## Self-Review

**Spec coverage check:**
- Setup Anthropic API key → Task 1 (.env.example) + Task 5 (README)
- Collect pin photos → Task 5 (README workflow)
- Record ground truth → Task 3 (collect script)
- Run pipeline without eBay → Task 2 (skip comps)
- Compare output → Task 4 (scorecard generator)
- Scorecard with gate decision → Task 4 (generate_markdown)
- Success criteria (80% identification, 70% minor edits) → Task 4 (built into scorecard)

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code is complete.

**Type consistency:** `evaluate_identification` takes a SQLAlchemy model `extraction` (attribute access) and a `dict` ground truth entry. `evaluate_listing_quality` takes a SQLAlchemy `draft` model. `generate_markdown` takes a list of result dicts. All consistent across Task 4 and Task 6 tests.
