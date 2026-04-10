# Phase 1C: Comp Search + Pricing Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate that eBay comp search returns relevant results and pricing suggestions are within 25% of reference prices for 70%+ of pins.

**Architecture:** Configure eBay API credentials, run the same test pins through the full pipeline (now with comps enabled), extend the scorecard generator to include pricing evaluation, and produce a final Phase 1 gate decision.

**Tech Stack:** Existing Python/FastAPI stack, eBay Browse API (already implemented in `src/services/ebay_client.py` and `src/pipeline/comps.py`).

---

### Task 1: eBay Developer Account Setup Guide

**Files:**
- Modify: `disney-pin-assistant/evaluation/README.md`

- [ ] **Step 1: Append Phase 1C setup instructions to the evaluation README**

Add the following section to the end of `disney-pin-assistant/evaluation/README.md`:

```markdown

---

# Phase 1C Evaluation Workflow

## Prerequisites

1. Phase 1A and 1B completed
2. eBay developer account registered

## eBay Developer Account Setup

1. Go to https://developer.ebay.com and create an account
2. Create an application (select "Production" environment)
3. Note your **App ID (Client ID)** and **Cert ID (Client Secret)**
4. The Browse API uses the **Client Credentials** grant — no user auth needed
5. Update your `.env`:

```bash
EBAY_CLIENT_ID=your-app-id-here
EBAY_CLIENT_SECRET=your-cert-id-here
```

6. Verify credentials work:

```bash
# Quick test — should return a token
python -c "
import asyncio
from src.services.ebay_client import get_ebay_token
token = asyncio.run(get_ebay_token())
print(f'Token: {token[:20]}...' if token else 'FAILED')
"
```

**Rate limits:** eBay Browse API allows 5,000 calls/day on production keys. Each pin uses ~2 calls (sold + active search), so you can process ~2,500 pins/day.
```

- [ ] **Step 2: Commit**

```bash
git add disney-pin-assistant/evaluation/README.md
git commit -m "docs: add eBay developer setup guide for Phase 1C"
```

---

### Task 2: Extend Scorecard with Pricing Evaluation

**Files:**
- Modify: `disney-pin-assistant/scripts/generate_scorecard.py`
- Modify: `disney-pin-assistant/tests/test_evaluation_scripts.py`

Add pricing comparison to the scorecard when comps and reference prices are available.

- [ ] **Step 1: Write the failing test**

Add to `disney-pin-assistant/tests/test_evaluation_scripts.py`:

```python
def test_evaluate_pricing_within_threshold():
    from generate_scorecard import evaluate_pricing

    draft = MagicMock()
    draft.suggested_price = 25.00
    draft.quick_sale_price = 18.00
    draft.price_confidence = "medium"
    gt = {"reference_price": 28.00}
    result = evaluate_pricing(draft, gt)
    assert result["within_threshold"] is True
    assert result["delta_pct"] == pytest.approx(-10.7, abs=1)


def test_evaluate_pricing_outside_threshold():
    from generate_scorecard import evaluate_pricing

    draft = MagicMock()
    draft.suggested_price = 10.00
    draft.quick_sale_price = 7.00
    draft.price_confidence = "low"
    gt = {"reference_price": 28.00}
    result = evaluate_pricing(draft, gt)
    assert result["within_threshold"] is False


def test_evaluate_pricing_no_reference():
    from generate_scorecard import evaluate_pricing

    draft = MagicMock()
    draft.suggested_price = 25.00
    draft.quick_sale_price = 18.00
    draft.price_confidence = "medium"
    gt = {"reference_price": None}
    result = evaluate_pricing(draft, gt)
    assert result["within_threshold"] is None
    assert result["delta_pct"] is None


def test_evaluate_pricing_no_draft():
    from generate_scorecard import evaluate_pricing

    gt = {"reference_price": 28.00}
    result = evaluate_pricing(None, gt)
    assert result["within_threshold"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd disney-pin-assistant && python -m pytest tests/test_evaluation_scripts.py::test_evaluate_pricing_within_threshold -v
```

Expected: FAIL (function not found)

- [ ] **Step 3: Add the evaluate_pricing function to generate_scorecard.py**

Add this function to `disney-pin-assistant/scripts/generate_scorecard.py` after the `evaluate_listing_quality` function:

```python
def evaluate_pricing(draft, gt: dict) -> dict:
    """Compare suggested price against reference price."""
    ref_price = gt.get("reference_price")
    if not draft or not draft.suggested_price or not ref_price:
        return {
            "ai_price": draft.suggested_price if draft else None,
            "reference_price": ref_price,
            "delta_pct": None,
            "within_threshold": None,
            "price_confidence": draft.price_confidence if draft else None,
        }

    delta = draft.suggested_price - ref_price
    delta_pct = (delta / ref_price) * 100

    return {
        "ai_price": draft.suggested_price,
        "reference_price": ref_price,
        "delta_pct": round(delta_pct, 1),
        "within_threshold": abs(delta_pct) <= 25,
        "price_confidence": draft.price_confidence,
    }
```

- [ ] **Step 4: Update the main() function to include pricing in results**

In the `main()` function of `generate_scorecard.py`, update the results-building loop. After the `listing_eval` line, add:

```python
        pricing_eval = evaluate_pricing(pin.listing_draft, gt)
```

And update the `results.append` dict to include:

```python
        results.append({
            "pin_id": pin.id,
            "image_file": gt["image_file"],
            "identification": ident_eval,
            "listing": listing_eval,
            "pricing": pricing_eval,
        })
```

- [ ] **Step 5: Update generate_markdown to include pricing columns**

In the `generate_markdown` function, add pricing summary stats after the existing summary:

```python
    # Pricing stats (only if any pins have pricing data)
    priced = [r for r in results if r.get("pricing", {}).get("within_threshold") is not None]
    if priced:
        within = sum(1 for r in priced if r["pricing"]["within_threshold"])
        total_priced = len(priced)
        lines.append(f"| Pricing within 25% | {within}/{total_priced} ({within/total_priced*100:.0f}%) | 70%+ |")
```

And update the detail table header and rows to include pricing:

```python
    lines.append("| # | Image | ID Correct? | Edits Needed | AI Price | Ref Price | Delta | Within 25%? |")
    lines.append("|---|-------|-------------|-------------|----------|-----------|-------|-------------|")
```

For each result row, add pricing columns:

```python
        pricing = r.get("pricing", {})
        ai_price = f"${pricing['ai_price']:.2f}" if pricing.get("ai_price") else "—"
        ref_price = f"${pricing['reference_price']:.2f}" if pricing.get("reference_price") else "—"
        delta = f"{pricing['delta_pct']:+.0f}%" if pricing.get("delta_pct") is not None else "—"
        price_ok = "Y" if pricing.get("within_threshold") else ("N" if pricing.get("within_threshold") is False else "—")
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd disney-pin-assistant && python -m pytest tests/test_evaluation_scripts.py -v
```

Expected: All tests PASS (including the 4 new pricing tests)

- [ ] **Step 7: Commit**

```bash
git add disney-pin-assistant/scripts/generate_scorecard.py disney-pin-assistant/tests/test_evaluation_scripts.py
git commit -m "feat: extend scorecard with pricing evaluation for Phase 1C"
```

---

### Task 3: Comp Relevance Review Script

**Files:**
- Create: `disney-pin-assistant/scripts/review_comps.py`

A script that displays comps for each pin and lets the user flag irrelevant ones. This helps evaluate whether the comp search and filtering logic work correctly.

- [ ] **Step 1: Create the comp review script**

Create `disney-pin-assistant/scripts/review_comps.py`:

```python
"""
Review comp search results for relevance.

Usage:
    python scripts/review_comps.py <batch_id>

For each processed pin, shows the returned comps and asks the user
to mark whether each comp is relevant. Produces a relevance report.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.database import engine, async_session
from src.models import Pin

REPORT_PATH = Path("evaluation/comp_relevance.md")


async def main(batch_id: str):
    async with async_session() as db:
        result = await db.execute(
            select(Pin)
            .options(
                selectinload(Pin.extraction),
                selectinload(Pin.comps),
                selectinload(Pin.listing_draft),
            )
            .where(Pin.batch_id == batch_id)
        )
        pins = result.scalars().all()

    if not pins:
        print(f"No pins found for batch {batch_id}")
        sys.exit(1)

    total_comps = 0
    relevant_comps = 0
    excluded_correct = 0
    excluded_wrong = 0
    pins_with_comps = 0
    pin_reports = []

    for pin in pins:
        if not pin.comps:
            continue

        pins_with_comps += 1
        title = pin.listing_draft.title if pin.listing_draft else f"Pin #{pin.id}"
        chars = ", ".join(pin.extraction.characters) if pin.extraction else "unknown"

        print(f"\n{'='*60}")
        print(f"Pin #{pin.id}: {title}")
        print(f"Characters: {chars}")
        print(f"{'='*60}")

        pin_relevant = 0
        pin_total = 0

        for comp in pin.comps:
            pin_total += 1
            total_comps += 1

            status = "[EXCLUDED]" if comp.excluded else "[INCLUDED]"
            print(f"\n  {status} ${comp.price:.2f} — {comp.title}")
            if comp.excluded:
                print(f"    Reason: {comp.exclusion_reason}")

            try:
                answer = input("  Relevant to this pin? (y/n/s=skip): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nStopping review...")
                break

            if answer == "y":
                relevant_comps += 1
                pin_relevant += 1
                if comp.excluded:
                    excluded_wrong += 1
                    print("    ^ Filter incorrectly excluded this comp")
            elif answer == "n":
                if comp.excluded:
                    excluded_correct += 1
            # s = skip, don't count

        pin_reports.append({
            "pin_id": pin.id,
            "title": title,
            "total_comps": pin_total,
            "relevant_comps": pin_relevant,
        })

    # Generate report
    lines = ["# Comp Relevance Report\n"]
    lines.append(f"**Batch:** {batch_id}")
    lines.append(f"**Pins with comps:** {pins_with_comps}")
    lines.append(f"**Total comps reviewed:** {total_comps}")
    lines.append(f"**Relevant comps:** {relevant_comps} ({relevant_comps/total_comps*100:.0f}%)" if total_comps > 0 else "")
    lines.append("")

    if excluded_correct + excluded_wrong > 0:
        lines.append("## Filter Effectiveness\n")
        total_excluded = excluded_correct + excluded_wrong
        lines.append(f"- Correctly excluded: {excluded_correct}")
        lines.append(f"- Incorrectly excluded (false positives): {excluded_wrong}")
        lines.append(f"- Filter precision: {excluded_correct/total_excluded*100:.0f}%" if total_excluded > 0 else "")
        lines.append("")

    lines.append("## Per-Pin Results\n")
    lines.append("| Pin | Title | Total Comps | Relevant | Relevance Rate |")
    lines.append("|-----|-------|-------------|----------|---------------|")
    for r in pin_reports:
        rate = f"{r['relevant_comps']/r['total_comps']*100:.0f}%" if r["total_comps"] > 0 else "—"
        lines.append(f"| #{r['pin_id']} | {r['title'][:40]} | {r['total_comps']} | {r['relevant_comps']} | {rate} |")

    report = "\n".join(lines)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)
    print(f"\n\nReport saved to {REPORT_PATH}")
    print(report)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/review_comps.py <batch_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 2: Verify the script shows usage without errors**

```bash
cd disney-pin-assistant && python scripts/review_comps.py 2>&1 | head -1
```

Expected: "Usage: python scripts/review_comps.py <batch_id>"

- [ ] **Step 3: Commit**

```bash
git add disney-pin-assistant/scripts/review_comps.py
git commit -m "feat: add comp relevance review script for Phase 1C evaluation"
```

---

### Task 4: Phase 1C Evaluation Workflow and Final Gate

**Files:**
- Modify: `disney-pin-assistant/evaluation/README.md`

- [ ] **Step 1: Append Phase 1C evaluation steps to the README**

Add the following to the end of `disney-pin-assistant/evaluation/README.md`:

```markdown

## Step 1: Configure eBay Credentials

Follow the eBay Developer Account Setup section above. Verify with the test command.

## Step 2: Re-Process Test Pins

Upload the same pin photos as a new batch and process them. This time the pipeline will:
- Run vision extraction (same as before)
- Match against catalog (same as Phase 1B)
- Search eBay for comps (NEW in Phase 1C)
- Generate pricing based on comp data

```bash
# Start the app
uvicorn src.main:app --reload
# Upload, process via web UI, note the batch ID
```

## Step 3: Review Comp Relevance

```bash
python scripts/review_comps.py <batch_id>
```

Walk through each comp and mark whether it's actually for the same pin. This produces `evaluation/comp_relevance.md`.

## Step 4: Generate Full Scorecard

```bash
python scripts/generate_scorecard.py <batch_id>
```

The scorecard now includes pricing columns (AI price vs reference price, delta %, within 25% threshold).

## Step 5: Final Phase 1 Gate Decision

Review all three evaluation artifacts:
- `evaluation/scorecard.md` — identification + listing + pricing
- `evaluation/phase_comparison.md` — 1A vs 1B improvement
- `evaluation/comp_relevance.md` — comp search quality

**Phase 1 passes if ALL of these hold:**
1. Vision extraction correctly identifies 80%+ of pins (Phase 1A)
2. Generated listings need only minor edits for 70%+ of pins (Phase 1A)
3. Catalog matching improves results (Phase 1B)
4. Comp search returns relevant results for 70%+ of pins (Phase 1C)
5. Pricing is within 25% of reference for 70%+ of priced pins (Phase 1C)

**If Phase 1 passes:** Proceed to Phase 2 (Workflow Efficiency) — process a real batch of 50-100 pins.

**If any gate fails:** Document which component needs work, tune it, and re-evaluate before proceeding.
```

- [ ] **Step 2: Commit**

```bash
git add disney-pin-assistant/evaluation/README.md
git commit -m "docs: add Phase 1C evaluation workflow and final gate criteria"
```

---

## Self-Review

**Spec coverage check:**
- Register for eBay developer account → Task 1 (setup guide)
- Run comp searches for test pins → handled by existing pipeline (Task 2 in Phase 1A made comps conditional on keys)
- Review comp relevance → Task 3 (interactive review script)
- Evaluate filter effectiveness → Task 3 (false positive tracking)
- Compare pricing vs reference → Task 2 (scorecard extension)
- Success criteria (70% relevant comps, 25% pricing threshold) → Task 2 (scorecard), Task 4 (gate criteria)

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code is complete.

**Type consistency:** `evaluate_pricing` takes the same SQLAlchemy `draft` model and `dict` ground truth as the other evaluate functions. Return shape is consistent. The generate_markdown updates use the same `r["pricing"]` dict shape returned by `evaluate_pricing`. All consistent.
