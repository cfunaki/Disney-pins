"""
Phase 1A vs Phase 1B comparison script.

Compares vision-only (1A) results against vision + catalog matching (1B) results
to determine whether catalog seeding improved identification and listing quality.

Usage:
    python scripts/compare_phases.py <phase_1a_batch_id> <phase_1b_batch_id>
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database import async_session
from src.models import Pin

# ── Constants ──────────────────────────────────────────────────────────────────

EVALUATION_DIR = Path(__file__).parent.parent / "evaluation"
SCORECARD_PATH = EVALUATION_DIR / "scorecard.json"
GROUND_TRUTH_PATH = EVALUATION_DIR / "ground_truth.json"
OUTPUT_PATH = EVALUATION_DIR / "phase_comparison.md"

FILLER_WORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
    "with", "by", "from", "is", "pin", "disney",
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, remove filler words."""
    tokens = set()
    for word in text.lower().split():
        word = word.strip(".,!?\"'-()[]")
        if word and word not in FILLER_WORDS:
            tokens.add(word)
    return tokens


def _edit_level(draft_title: str, reference_title: str) -> str:
    """Return 'none', 'minor', or 'major' edits needed."""
    if not draft_title or not reference_title:
        return "major"
    draft_tokens = _tokenize(draft_title)
    ref_tokens = _tokenize(reference_title)
    if not ref_tokens:
        return "none"
    overlap = len(draft_tokens & ref_tokens) / len(ref_tokens)
    if overlap >= 0.85:
        return "none"
    if overlap >= 0.5:
        return "minor"
    return "major"


def _image_filename(image_paths: list) -> str | None:
    """Extract filename from the first image path entry."""
    if not image_paths:
        return None
    first = image_paths[0]
    return Path(str(first)).name


# ── Database ───────────────────────────────────────────────────────────────────


async def load_phase1b_pins(batch_id: str) -> dict[str, Pin]:
    """Return a dict of {image_filename: Pin} for a given batch_id."""
    async with async_session() as session:
        result = await session.execute(
            select(Pin)
            .where(Pin.batch_id == batch_id)
            .options(
                selectinload(Pin.extraction),
                selectinload(Pin.listing_draft),
                selectinload(Pin.catalog_matches),
            )
        )
        pins = result.scalars().all()

    pins_by_filename: dict[str, Pin] = {}
    for pin in pins:
        filename = _image_filename(pin.image_paths or [])
        if filename:
            pins_by_filename[filename] = pin
    return pins_by_filename


# ── Data loading ───────────────────────────────────────────────────────────────


def load_scorecard(batch_id_1a: str) -> dict[str, dict]:
    """Load Phase 1A scorecard and index by image filename."""
    if not SCORECARD_PATH.exists():
        raise FileNotFoundError(f"Scorecard not found: {SCORECARD_PATH}")
    data = json.loads(SCORECARD_PATH.read_text())

    # Support both list and dict-of-entries formats
    entries: list[dict] = data if isinstance(data, list) else data.get("entries", [])

    by_filename: dict[str, dict] = {}
    for entry in entries:
        # Accept entries that belong to this batch or have no batch recorded
        entry_batch = entry.get("batch_id", batch_id_1a)
        if entry_batch != batch_id_1a:
            continue
        filename = entry.get("image_filename") or entry.get("filename")
        if filename:
            by_filename[filename] = entry
    return by_filename


def load_ground_truth() -> dict[str, dict]:
    """Load ground truth and index by image filename."""
    if not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(f"Ground truth not found: {GROUND_TRUTH_PATH}")
    data = json.loads(GROUND_TRUTH_PATH.read_text())
    entries: list[dict] = data if isinstance(data, list) else data.get("pins", [])
    return {entry["image_filename"]: entry for entry in entries if "image_filename" in entry}


# ── Comparison logic ───────────────────────────────────────────────────────────


def evaluate_1a_row(scorecard_entry: dict, ground_truth: dict) -> dict:
    """Extract 1A metrics from the scorecard entry."""
    id_correct = scorecard_entry.get("id_correct", False)
    edits = scorecard_entry.get("edits_needed", "major")
    return {"id_correct": bool(id_correct), "edits": edits}


def evaluate_1b_row(pin: Pin, ground_truth: dict) -> dict:
    """Derive 1B metrics from the database Pin object."""
    # Identification: check whether the listing title matches reference_title
    reference_title = ground_truth.get("reference_title", "")
    draft_title = pin.listing_draft.title if pin.listing_draft else ""

    edits = _edit_level(draft_title, reference_title)
    id_correct = edits in ("none", "minor")

    # Catalog match info
    top_match = next(
        (m for m in sorted(pin.catalog_matches, key=lambda m: m.rank)),
        None,
    )
    catalog_matched = top_match is not None
    match_confidence = round(top_match.match_confidence, 3) if top_match else None

    return {
        "id_correct": id_correct,
        "edits": edits,
        "catalog_matched": catalog_matched,
        "match_confidence": match_confidence,
    }


# ── Report generation ──────────────────────────────────────────────────────────


def build_report(
    scorecard_1a: dict[str, dict],
    ground_truth: dict[str, dict],
    pins_1b: dict[str, Pin],
    batch_id_1a: str,
    batch_id_1b: str,
) -> str:
    """Build the full Markdown report and return it as a string."""

    # Gather all filenames present in both phases
    all_filenames = sorted(set(scorecard_1a) | set(pins_1b))

    rows: list[dict] = []
    for filename in all_filenames:
        gt = ground_truth.get(filename, {})
        sc = scorecard_1a.get(filename)
        pin = pins_1b.get(filename)

        m1a = evaluate_1a_row(sc, gt) if sc else {"id_correct": None, "edits": "n/a"}
        m1b = evaluate_1b_row(pin, gt) if pin else {
            "id_correct": None, "edits": "n/a",
            "catalog_matched": False, "match_confidence": None,
        }

        rows.append({
            "filename": filename,
            "1a_id_correct": m1a["id_correct"],
            "1b_id_correct": m1b["id_correct"],
            "1a_edits": m1a["edits"],
            "1b_edits": m1b["edits"],
            "catalog_matched": m1b.get("catalog_matched", False),
            "match_confidence": m1b.get("match_confidence"),
        })

    # ── Summary counts ──────────────────────────────────────────────────────
    improved = regressed = unchanged = 0
    for row in rows:
        a_ok = row["1a_id_correct"]
        b_ok = row["1b_id_correct"]
        if a_ok is None or b_ok is None:
            continue
        if b_ok and not a_ok:
            improved += 1
        elif a_ok and not b_ok:
            regressed += 1
        else:
            unchanged += 1

    total = improved + regressed + unchanged
    if total == 0:
        verdict = "No clear impact (no comparable pins found)"
    elif improved > regressed:
        verdict = "Catalog matching improves results"
    elif regressed > improved:
        verdict = "Catalog matching hurts results"
    else:
        verdict = "No clear impact"

    # ── Build Markdown ──────────────────────────────────────────────────────
    lines: list[str] = []
    lines.append("# Phase 1A vs Phase 1B Comparison\n")
    lines.append(f"- **Phase 1A batch:** `{batch_id_1a}`")
    lines.append(f"- **Phase 1B batch:** `{batch_id_1b}`\n")

    # Table header
    lines.append(
        "| Pin | 1A ID Correct | 1B ID Correct | 1A Edits | 1B Edits "
        "| Catalog Match? | Match Confidence |"
    )
    lines.append(
        "|-----|:-------------:|:-------------:|:--------:|:--------:"
        "|:--------------:|:----------------:|"
    )

    for row in rows:
        def fmt_bool(v):
            if v is None:
                return "—"
            return "Yes" if v else "No"

        def fmt_conf(v):
            return f"{v:.3f}" if v is not None else "—"

        lines.append(
            f"| {row['filename']} "
            f"| {fmt_bool(row['1a_id_correct'])} "
            f"| {fmt_bool(row['1b_id_correct'])} "
            f"| {row['1a_edits']} "
            f"| {row['1b_edits']} "
            f"| {fmt_bool(row['catalog_matched'])} "
            f"| {fmt_conf(row['match_confidence'])} |"
        )

    lines.append("")
    lines.append("## Summary\n")
    lines.append(f"| Outcome | Count |")
    lines.append(f"|---------|------:|")
    lines.append(f"| Improved (1B correct, 1A wrong) | {improved} |")
    lines.append(f"| Regressed (1A correct, 1B wrong) | {regressed} |")
    lines.append(f"| Unchanged | {unchanged} |")
    lines.append(f"| Total comparable | {total} |")
    lines.append("")
    lines.append(f"## Verdict\n")
    lines.append(f"**{verdict}**\n")

    return "\n".join(lines)


# ── Entry point ────────────────────────────────────────────────────────────────


async def main(batch_id_1a: str, batch_id_1b: str) -> None:
    print(f"Loading Phase 1A scorecard for batch: {batch_id_1a}")
    scorecard_1a = load_scorecard(batch_id_1a)
    print(f"  Found {len(scorecard_1a)} scorecard entries")

    print("Loading ground truth...")
    ground_truth = load_ground_truth()
    print(f"  Found {len(ground_truth)} ground truth entries")

    print(f"Loading Phase 1B pins for batch: {batch_id_1b}")
    pins_1b = await load_phase1b_pins(batch_id_1b)
    print(f"  Found {len(pins_1b)} Phase 1B pins")

    report = build_report(scorecard_1a, ground_truth, pins_1b, batch_id_1a, batch_id_1b)

    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report)
    print(f"\nReport written to: {OUTPUT_PATH}")

    # Print summary section to stdout for quick review
    for line in report.splitlines():
        if line.startswith("## Summary") or line.startswith("## Verdict") or line.startswith("**"):
            print(line)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/compare_phases.py <phase_1a_batch_id> <phase_1b_batch_id>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1], sys.argv[2]))
