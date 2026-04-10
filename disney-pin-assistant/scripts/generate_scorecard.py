"""
Scorecard generator for Phase 1A evaluation.

Usage:
    python scripts/generate_scorecard.py <batch_id>

Loads ground truth from evaluation/ground_truth.json, queries the database for
pins in the given batch, matches them by image filename, then evaluates
identification accuracy, listing quality, and pricing. Writes results to
evaluation/scorecard.md and evaluation/scorecard.json.

The evaluate_identification, evaluate_listing_quality, and evaluate_pricing
functions are importable for use in unit tests (Task 6).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running from the repo root or from the scripts/ directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database import async_session
from src.models import Pin


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------

_FILLER_WORDS = {"disney", "pin", "the", "a", "an", "-", "&", "and", "of"}


def evaluate_identification(extraction, ground_truth: dict) -> dict:
    """
    Compare a VisionExtraction object against a ground truth dict.

    Parameters
    ----------
    extraction:
        A VisionExtraction ORM instance (attribute access), or None if the pin
        has not been processed yet.
    ground_truth:
        A dict with optional keys: expected_characters, expected_franchise,
        expected_pin_type, expected_edition_size.

    Returns
    -------
    dict with keys:
        correct (bool), fields_checked (int), fields_matched (int),
        details (dict mapping field name → {"matched": bool, "reason": str})
    """
    details: dict[str, dict] = {}
    fields_checked = 0
    fields_matched = 0

    if extraction is None:
        return {
            "correct": False,
            "fields_checked": 0,
            "fields_matched": 0,
            "details": {"extraction": {"matched": False, "reason": "No extraction found"}},
        }

    # Characters — case-insensitive set overlap (any overlap = match)
    expected_chars = ground_truth.get("expected_characters") or []
    if expected_chars:
        fields_checked += 1
        actual_chars = [c.lower() for c in (extraction.characters or [])]
        expected_lower = [c.lower() for c in expected_chars]
        matched = bool(set(actual_chars) & set(expected_lower))
        details["characters"] = {
            "matched": matched,
            "expected": expected_chars,
            "actual": extraction.characters or [],
            "reason": "overlap found" if matched else "no overlap",
        }
        if matched:
            fields_matched += 1

    # Franchise — case-insensitive substring match
    expected_franchise = ground_truth.get("expected_franchise") or ""
    if expected_franchise:
        fields_checked += 1
        actual_franchise = (extraction.franchise or "").lower()
        matched = expected_franchise.lower() in actual_franchise or actual_franchise in expected_franchise.lower()
        details["franchise"] = {
            "matched": matched,
            "expected": expected_franchise,
            "actual": extraction.franchise,
            "reason": "substring match" if matched else "no match",
        }
        if matched:
            fields_matched += 1

    # Pin type — case-insensitive substring match
    expected_pin_type = ground_truth.get("expected_pin_type") or ""
    if expected_pin_type:
        fields_checked += 1
        actual_pin_type = (extraction.pin_type or "").lower()
        matched = expected_pin_type.lower() in actual_pin_type or actual_pin_type in expected_pin_type.lower()
        details["pin_type"] = {
            "matched": matched,
            "expected": expected_pin_type,
            "actual": extraction.pin_type,
            "reason": "substring match" if matched else "no match",
        }
        if matched:
            fields_matched += 1

    # Edition size — exact match
    expected_edition = ground_truth.get("expected_edition_size")
    if expected_edition is not None:
        fields_checked += 1
        matched = extraction.edition_size == expected_edition
        details["edition_size"] = {
            "matched": matched,
            "expected": expected_edition,
            "actual": extraction.edition_size,
            "reason": "exact match" if matched else "mismatch",
        }
        if matched:
            fields_matched += 1

    correct = fields_checked > 0 and fields_matched == fields_checked
    return {
        "correct": correct,
        "fields_checked": fields_checked,
        "fields_matched": fields_matched,
        "details": details,
    }


def evaluate_listing_quality(draft, ground_truth: dict) -> dict:
    """
    Compare a ListingDraft object against a ground truth dict.

    Parameters
    ----------
    draft:
        A ListingDraft ORM instance (attribute access), or None.
    ground_truth:
        A dict with optional key: reference_title.

    Returns
    -------
    dict with keys:
        edit_level ("none" | "minor" | "major" | "no_draft" | "no_reference"),
        overlap_ratio (float | None),
        ai_title (str | None),
        reference_title (str | None)
    """
    reference_title = ground_truth.get("reference_title") or ""
    if not reference_title:
        return {
            "edit_level": "no_reference",
            "overlap_ratio": None,
            "ai_title": draft.title if draft else None,
            "reference_title": None,
        }

    if draft is None:
        return {
            "edit_level": "no_draft",
            "overlap_ratio": None,
            "ai_title": None,
            "reference_title": reference_title,
        }

    ai_title = draft.title or ""

    def meaningful_words(text: str) -> set[str]:
        words = text.lower().replace("-", " ").replace("&", " ").split()
        return {w.strip(".,!?") for w in words if w.strip(".,!?") not in _FILLER_WORDS and w.strip(".,!?")}

    ai_words = meaningful_words(ai_title)
    ref_words = meaningful_words(reference_title)

    if not ref_words:
        overlap_ratio = 1.0 if not ai_words else 0.0
    else:
        overlap_ratio = len(ai_words & ref_words) / len(ref_words)

    if overlap_ratio >= 0.6:
        edit_level = "none"
    elif overlap_ratio >= 0.3:
        edit_level = "minor"
    else:
        edit_level = "major"

    return {
        "edit_level": edit_level,
        "overlap_ratio": round(overlap_ratio, 4),
        "ai_title": ai_title,
        "reference_title": reference_title,
    }


def evaluate_pricing(draft, ground_truth: dict) -> dict:
    """
    Compare a ListingDraft's suggested_price against the reference_price.

    Parameters
    ----------
    draft:
        A ListingDraft ORM instance (attribute access), or None.
    ground_truth:
        A dict with optional key: reference_price.

    Returns
    -------
    dict with keys:
        within_threshold (bool | None), delta_pct (float | None),
        suggested_price (float | None), reference_price (float | None),
        reason (str)
    """
    reference_price = ground_truth.get("reference_price")
    suggested_price = draft.suggested_price if draft else None

    if reference_price is None:
        return {
            "within_threshold": None,
            "delta_pct": None,
            "suggested_price": suggested_price,
            "reference_price": None,
            "reason": "no reference price",
        }

    if suggested_price is None:
        return {
            "within_threshold": None,
            "delta_pct": None,
            "suggested_price": None,
            "reference_price": reference_price,
            "reason": "no suggested price (no draft or price not set)",
        }

    if reference_price == 0:
        return {
            "within_threshold": None,
            "delta_pct": None,
            "suggested_price": suggested_price,
            "reference_price": reference_price,
            "reason": "reference price is zero",
        }
    delta_pct = abs(suggested_price - reference_price) / reference_price * 100
    within_threshold = delta_pct <= 25.0

    return {
        "within_threshold": within_threshold,
        "delta_pct": round(delta_pct, 2),
        "suggested_price": suggested_price,
        "reference_price": reference_price,
        "reason": f"{delta_pct:.1f}% delta ({'within' if within_threshold else 'outside'} 25% threshold)",
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def load_pins_for_batch(batch_id: str) -> list:
    """Return all Pin records for the given batch_id with relationships loaded."""
    async with async_session() as session:
        result = await session.execute(
            select(Pin)
            .where(Pin.batch_id == batch_id)
            .options(
                selectinload(Pin.extraction),
                selectinload(Pin.listing_draft),
                selectinload(Pin.catalog_matches),
                selectinload(Pin.comps),
            )
        )
        return result.scalars().all()


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def extract_filename(path_str: str) -> str:
    """Return just the filename portion of a path string."""
    return Path(path_str).name


def match_pins_to_ground_truth(pins: list, ground_truth_pins: list) -> list[dict]:
    """
    Match each ground truth entry to a Pin by image filename.

    Returns a list of dicts:
        {
            "ground_truth": <gt dict>,
            "pin": <Pin ORM object or None>,
        }
    """
    # Build index: filename → Pin (use first image_path for matching)
    filename_to_pin: dict[str, Pin] = {}
    for pin in pins:
        for path in (pin.image_paths or []):
            fname = extract_filename(str(path))
            filename_to_pin[fname] = pin

    matched = []
    for gt in ground_truth_pins:
        image_file = gt.get("image_file", "")
        pin = filename_to_pin.get(image_file)
        matched.append({"ground_truth": gt, "pin": pin})

    return matched


# ---------------------------------------------------------------------------
# Scorecard generation
# ---------------------------------------------------------------------------

def generate_scorecard(batch_id: str, matches: list[dict]) -> dict:
    """
    Evaluate all matched pairs and return a scorecard dict.
    """
    results = []

    for item in matches:
        gt = item["ground_truth"]
        pin = item["pin"]
        extraction = pin.extraction if pin else None
        draft = pin.listing_draft if pin else None

        id_result = evaluate_identification(extraction, gt)
        listing_result = evaluate_listing_quality(draft, gt)
        pricing_result = evaluate_pricing(draft, gt)

        results.append(
            {
                "image_file": gt.get("image_file"),
                "pin_id": pin.id if pin else None,
                "identification": id_result,
                "listing_quality": listing_result,
                "pricing": pricing_result,
            }
        )

    # ── Summary statistics ─────────────────────────────────────────────────

    total = len(results)
    id_correct = sum(1 for r in results if r["identification"]["correct"])
    id_accuracy = id_correct / total if total else 0.0

    listing_edits = [r["listing_quality"]["edit_level"] for r in results]
    no_major_edits = sum(1 for e in listing_edits if e in ("none", "minor", "no_reference", "no_draft"))
    # "no edits needed" rate = pins where edit_level is "none" or "minor"
    minor_or_none = sum(1 for e in listing_edits if e in ("none", "minor"))
    edit_rate = minor_or_none / total if total else 0.0

    pricing_evaluated = [r["pricing"] for r in results if r["pricing"]["within_threshold"] is not None]
    if pricing_evaluated:
        pricing_pass = sum(1 for p in pricing_evaluated if p["within_threshold"])
        pricing_rate = pricing_pass / len(pricing_evaluated)
    else:
        pricing_rate = None

    # ── Gate decision ──────────────────────────────────────────────────────

    id_target = 0.80
    edit_target = 0.70

    id_pass = id_accuracy >= id_target
    edit_pass = edit_rate >= edit_target
    gate = "PASS" if (id_pass and edit_pass) else "NEEDS WORK"

    return {
        "batch_id": batch_id,
        "total_pins": total,
        "summary": {
            "identification_accuracy": round(id_accuracy, 4),
            "identification_correct": id_correct,
            "identification_target": id_target,
            "identification_pass": id_pass,
            "edit_rate": round(edit_rate, 4),
            "edit_pass_count": minor_or_none,
            "edit_target": edit_target,
            "edit_pass": edit_pass,
            "pricing_rate": round(pricing_rate, 4) if pricing_rate is not None else None,
            "pricing_evaluated": len(pricing_evaluated),
        },
        "gate": gate,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(scorecard: dict) -> str:
    s = scorecard["summary"]
    gate = scorecard["gate"]
    batch_id = scorecard["batch_id"]
    total = scorecard["total_pins"]
    results = scorecard["results"]

    lines = []
    lines.append(f"# Phase 1A Scorecard — Batch `{batch_id}`\n")

    # Gate banner
    gate_emoji = "PASS" if gate == "PASS" else "NEEDS WORK"
    lines.append(f"**Gate Decision: {gate_emoji}**\n")

    # Summary table
    lines.append("## Summary\n")
    lines.append("| Metric | Value | Target | Pass? |")
    lines.append("|--------|-------|--------|-------|")

    id_pct = f"{s['identification_accuracy'] * 100:.1f}%"
    id_target_pct = f"{s['identification_target'] * 100:.0f}%"
    lines.append(
        f"| Identification accuracy | {id_pct} ({s['identification_correct']}/{total}) "
        f"| {id_target_pct} | {'YES' if s['identification_pass'] else 'NO'} |"
    )

    edit_pct = f"{s['edit_rate'] * 100:.1f}%"
    edit_target_pct = f"{s['edit_target'] * 100:.0f}%"
    lines.append(
        f"| Listings needing <=minor edits | {edit_pct} ({s['edit_pass_count']}/{total}) "
        f"| {edit_target_pct} | {'YES' if s['edit_pass'] else 'NO'} |"
    )

    if s["pricing_rate"] is not None:
        pricing_pct = f"{s['pricing_rate'] * 100:.1f}%"
        lines.append(
            f"| Pricing within 25% | {pricing_pct} (of {s['pricing_evaluated']} evaluated) | — | — |"
        )
    else:
        lines.append("| Pricing within 25% | N/A | — | — |")

    lines.append("")

    # Per-pin detail table
    lines.append("## Per-Pin Results\n")
    lines.append("| Image | Pin ID | ID Correct | Edit Level | Price Delta | Pricing OK |")
    lines.append("|-------|--------|------------|------------|-------------|------------|")

    for r in results:
        img = r["image_file"] or "?"
        pin_id = str(r["pin_id"]) if r["pin_id"] else "—"
        id_ok = "YES" if r["identification"]["correct"] else "NO"
        edit_level = r["listing_quality"]["edit_level"]
        delta = (
            f"{r['pricing']['delta_pct']:.1f}%"
            if r["pricing"]["delta_pct"] is not None
            else "—"
        )
        price_ok = (
            "YES"
            if r["pricing"]["within_threshold"] is True
            else ("NO" if r["pricing"]["within_threshold"] is False else "—")
        )
        lines.append(f"| {img} | {pin_id} | {id_ok} | {edit_level} | {delta} | {price_ok} |")

    lines.append("")

    # Failure analysis
    failures = [r for r in results if not r["identification"]["correct"]]
    if failures:
        lines.append("## Identification Failure Analysis\n")
        for r in failures:
            lines.append(f"### {r['image_file']} (Pin ID: {r['pin_id']})\n")
            details = r["identification"]["details"]
            for field, info in details.items():
                if not info.get("matched", True):
                    expected = info.get("expected", "?")
                    actual = info.get("actual", "?")
                    reason = info.get("reason", "")
                    lines.append(f"- **{field}**: expected `{expected}`, got `{actual}` — {reason}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main(batch_id: str) -> None:
    base_dir = Path(__file__).parent.parent
    eval_dir = base_dir / "evaluation"
    eval_dir.mkdir(exist_ok=True)

    gt_path = eval_dir / "ground_truth.json"
    if not gt_path.exists():
        print(f"ERROR: Ground truth file not found at {gt_path}", file=sys.stderr)
        sys.exit(1)

    with open(gt_path) as f:
        ground_truth_data = json.load(f)

    ground_truth_pins = ground_truth_data.get("pins", [])
    if not ground_truth_pins:
        print("WARNING: ground_truth.json contains no pins.", file=sys.stderr)

    print(f"Loaded {len(ground_truth_pins)} ground truth entries.")

    pins = await load_pins_for_batch(batch_id)
    print(f"Loaded {len(pins)} pins from database for batch '{batch_id}'.")

    matches = match_pins_to_ground_truth(pins, ground_truth_pins)
    unmatched = sum(1 for m in matches if m["pin"] is None)
    if unmatched:
        print(f"WARNING: {unmatched} ground truth entries had no matching pin in the database.")

    scorecard = generate_scorecard(batch_id, matches)

    # Save JSON
    json_path = eval_dir / "scorecard.json"
    with open(json_path, "w") as f:
        json.dump(scorecard, f, indent=2)
    print(f"Scorecard JSON saved to {json_path}")

    # Save Markdown
    md_path = eval_dir / "scorecard.md"
    md_content = render_markdown(scorecard)
    with open(md_path, "w") as f:
        f.write(md_content)
    print(f"Scorecard markdown saved to {md_path}")

    # Print summary
    s = scorecard["summary"]
    gate = scorecard["gate"]
    print("\n--- SCORECARD SUMMARY ---")
    print(f"Batch: {batch_id}  |  Pins evaluated: {scorecard['total_pins']}")
    print(f"Identification accuracy: {s['identification_accuracy'] * 100:.1f}% (target: 80%)")
    print(f"Listings needing <=minor edits: {s['edit_rate'] * 100:.1f}% (target: 70%)")
    if s["pricing_rate"] is not None:
        print(f"Pricing within 25%: {s['pricing_rate'] * 100:.1f}% ({s['pricing_evaluated']} evaluated)")
    print(f"\nGate decision: {gate}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/generate_scorecard.py <batch_id>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
