# Scraper Parser Enhancement + NLP Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture all available PinTradingDB detail fields and enrich catalog entries with characters, franchise, and series/collection extracted from title and description text.

**Architecture:** Two independent improvements — (1) parser update adds 4 new fields from the HTML details table, followed by a clean re-scrape; (2) standalone enrichment script extracts characters/franchise/series from text using existing alias maps imported from `pinpics_parser.py`. Enrichment is idempotent and decoupled from scraping.

**Tech Stack:** Python 3, BeautifulSoup (existing), pytest, regex. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-11-scraper-parser-enrichment-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `tests/fixtures/pintradingdb_detail.html` | Modify | Add Description, SKU, Retire Date, Original Price rows |
| `tests/test_pintradingdb_parser.py` | Modify | Add tests for new fields |
| `scripts/scraper/pintradingdb_parser.py` | Modify | Extract 4 new fields from details_table |
| `tests/test_enrich_catalog.py` | Create | Unit tests for enrichment logic |
| `scripts/enrich_catalog.py` | Create | Standalone NLP enrichment script |

---

### Task 1: Update test fixture with new HTML fields

**Files:**
- Modify: `tests/fixtures/pintradingdb_detail.html:22-29`

- [ ] **Step 1: Add Description, SKU, Retire Date, and Original Price rows to the fixture**

The current fixture has these rows: Edition Size, Release Date, Original Price, Origin, SKU, Added By, Description. Wait — looking at the fixture, it already has Original Price, SKU, and Description rows but the *parser doesn't extract them*. It's missing Retire Date.

Update the fixture to include a Retire Date row (the one field not present). Add it between Release Date and Original Price:

In `tests/fixtures/pintradingdb_detail.html`, replace:

```html
  <tr><td class="pinLabel">Release Date</td><td>01/23/2014</td></tr>
  <tr><td class="pinLabel">Original Price</td><td>$19.95 Box of 2</td></tr>
```

with:

```html
  <tr><td class="pinLabel">Release Date</td><td>01/23/2014</td></tr>
  <tr><td class="pinLabel">Retire Date</td><td>06/15/2015</td></tr>
  <tr><td class="pinLabel">Original Price</td><td>$19.95 Box of 2</td></tr>
```

- [ ] **Step 2: Commit fixture update**

```bash
git add tests/fixtures/pintradingdb_detail.html
git commit -m "test: add Retire Date row to pintradingdb fixture"
```

---

### Task 2: Write failing parser tests for new fields

**Files:**
- Modify: `tests/test_pintradingdb_parser.py`

- [ ] **Step 1: Add tests for description, sku, retire_date, and original_price**

Append to `tests/test_pintradingdb_parser.py`:

```python
def test_extracts_description(parsed):
    """Description text is extracted from the details table."""
    assert parsed["description"] == (
        "The Characters & Cameras Mystery Collection features "
        "Dopey chaser pin."
    )


def test_extracts_sku(parsed):
    """SKU is extracted from the details table."""
    assert parsed["sku"] == "400008192705"


def test_extracts_retire_date(parsed):
    """Retire date string is extracted from the details table."""
    assert parsed["retire_date"] == "06/15/2015"


def test_extracts_original_price(parsed):
    """Original price string is extracted from the details table."""
    assert parsed["original_price"] == "$19.95 Box of 2"


def test_missing_fields_are_none():
    """Fields missing from the HTML return None."""
    minimal_html = """
    <html><body>
    <div id="sidebar">
      <h2 class="title">999 - Minimal Pin</h2>
      <h3>Released: 01/01/2020 - </h3>
    </div>
    <table class="pinTable details_table"></table>
    </body></html>
    """
    result = parse_pin_detail(minimal_html, "999")
    assert result["description"] is None
    assert result["sku"] is None
    assert result["retire_date"] is None
    assert result["original_price"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant && python -m pytest tests/test_pintradingdb_parser.py -v -k "description or sku or retire or price or missing_fields"`

Expected: FAIL — `KeyError: 'description'` (fields not yet in parser output)

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_pintradingdb_parser.py
git commit -m "test: add failing tests for description, sku, retire_date, original_price"
```

---

### Task 3: Implement parser changes

**Files:**
- Modify: `scripts/scraper/pintradingdb_parser.py:120-163`

- [ ] **Step 1: Add field extraction in parse_pin_detail**

In `scripts/scraper/pintradingdb_parser.py`, add three new variables after `exclusive_source` initialization (after line 122):

```python
    edition_size: int | None = None
    exclusive_source: str | None = None
    description: str | None = None
    sku: str | None = None
    retire_date: str | None = None
    original_price: str | None = None
```

Then extend the `details_table` loop (the `for row in details_table.find_all("tr")` block) to handle the new fields. Add these `elif` branches after the `elif label == "Origin"` block (after line 144):

```python
                elif label == "Description":
                    description = value_text or None
                elif label == "SKU":
                    sku = value_text or None
                elif label == "Retire Date":
                    retire_date = value_text or None
                elif label == "Original Price":
                    original_price = value_text or None
```

Then add the new fields to the return dict (before the closing `}`):

```python
        "description": description,
        "sku": sku,
        "retire_date": retire_date,
        "original_price": original_price,
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant && python -m pytest tests/test_pintradingdb_parser.py -v`

Expected: ALL PASS (including the 5 new tests + all existing tests)

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant && python -m pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/scraper/pintradingdb_parser.py
git commit -m "feat: extract description, sku, retire_date, original_price from pintradingdb"
```

---

### Task 4: Write failing enrichment tests

**Files:**
- Create: `tests/test_enrich_catalog.py`

- [ ] **Step 1: Create test file with character, franchise, and series extraction tests**

Create `tests/test_enrich_catalog.py`:

```python
"""Tests for the catalog NLP enrichment script."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest
from enrich_catalog import extract_characters, infer_franchise, extract_series


class TestExtractCharacters:
    def test_single_character_in_title(self):
        assert "Mickey Mouse" in extract_characters("Mickey Mouse Club Pin", None)

    def test_multiple_characters(self):
        chars = extract_characters("Mickey and Minnie Valentine Pin", None)
        assert "Mickey Mouse" in chars
        assert "Minnie Mouse" in chars

    def test_character_in_description(self):
        chars = extract_characters("Mystery Pin", "Features Stitch surfing")
        assert "Stitch" in chars

    def test_no_characters(self):
        assert extract_characters("Epcot Festival Pin 2026", None) == []

    def test_deduplicates(self):
        chars = extract_characters("Mickey Pin", "Mickey Mouse design")
        assert chars.count("Mickey Mouse") == 1

    def test_case_insensitive(self):
        assert "Elsa" in extract_characters("ELSA Frozen Pin", None)

    def test_alias_buzz(self):
        assert "Buzz Lightyear" in extract_characters("Buzz Lightyear Star Command", None)

    def test_alias_tink(self):
        assert "Tinker Bell" in extract_characters("Tink Fairy Pin", None)

    def test_word_boundary_no_false_positive(self):
        """'Belle' should not match inside 'Tinker Belle' when 'Tinker Bell' already matched."""
        chars = extract_characters("Tinker Bell Fairy Wings", None)
        assert "Tinker Bell" in chars
        assert "Belle" not in chars


class TestInferFranchise:
    def test_single_franchise(self):
        assert infer_franchise(["Simba"]) == "The Lion King"

    def test_multiple_same_franchise(self):
        assert infer_franchise(["Woody", "Buzz Lightyear"]) == "Toy Story"

    def test_multiple_different_franchises(self):
        result = infer_franchise(["Mickey Mouse", "Simba"])
        assert result in ("Mickey & Friends", "The Lion King")

    def test_no_characters(self):
        assert infer_franchise([]) is None

    def test_unknown_character(self):
        assert infer_franchise(["Figment"]) is None


class TestExtractSeries:
    def test_mystery_collection(self):
        assert extract_series("Characters & Cameras Mystery Collection - Dopey") == "Characters & Cameras Mystery Collection"

    def test_series_keyword(self):
        assert extract_series("Star Wars Helmet Series Pin 3") == "Star Wars Helmet Series"

    def test_pin_collection(self):
        assert extract_series("Hidden Mickey Pin Collection 2024") == "Hidden Mickey Pin Collection"

    def test_no_series(self):
        assert extract_series("Mickey Mouse Limited Edition 500") is None

    def test_mystery_pin_collection(self):
        assert extract_series("Disney Parks Mystery Pin Collection - Villains") == "Disney Parks Mystery Pin Collection"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant && python -m pytest tests/test_enrich_catalog.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'enrich_catalog'`

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_enrich_catalog.py
git commit -m "test: add failing tests for catalog enrichment"
```

---

### Task 5: Implement enrichment script

**Files:**
- Create: `scripts/enrich_catalog.py`

- [ ] **Step 1: Create the enrichment script**

Create `scripts/enrich_catalog.py`:

```python
"""NLP enrichment for PinTradingDB catalog entries.

Extracts characters, franchise, and series/collection from title and
description text using alias maps from pinpics_parser.
"""

import argparse
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))

from scraper.pinpics_parser import CHARACTER_ALIASES, FRANCHISE_MAP

DEFAULT_CATALOG = os.path.join(
    os.path.dirname(__file__), "scraper", "output", "pintradingdb_catalog.json",
)

_SERIES_PATTERNS = [
    re.compile(r"(.+?(?:Mystery\s+(?:Pin\s+)?)?Collection)\b", re.IGNORECASE),
    re.compile(r"(.+?\bSeries)\b", re.IGNORECASE),
]

_CHAR_PATTERNS: dict[str, re.Pattern] = {}


def _get_char_pattern(alias: str) -> re.Pattern:
    if alias not in _CHAR_PATTERNS:
        _CHAR_PATTERNS[alias] = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
    return _CHAR_PATTERNS[alias]


def extract_characters(title: str | None, description: str | None) -> list[str]:
    """Extract character names from title and description using CHARACTER_ALIASES."""
    text = ""
    if title:
        text += title
    if description:
        text += " " + description
    if not text.strip():
        return []

    found: dict[str, str] = {}  # canonical_name -> source_alias (for dedup)
    matched_spans: list[tuple[int, int]] = []

    sorted_aliases = sorted(CHARACTER_ALIASES.keys(), key=len, reverse=True)

    for alias in sorted_aliases:
        canonical = CHARACTER_ALIASES[alias]
        if canonical in found:
            continue
        pattern = _get_char_pattern(alias)
        match = pattern.search(text)
        if match:
            overlap = False
            for start, end in matched_spans:
                if match.start() < end and match.end() > start:
                    overlap = True
                    break
            if not overlap:
                found[canonical] = alias
                matched_spans.append((match.start(), match.end()))

    return list(found.keys())


def infer_franchise(characters: list[str]) -> str | None:
    """Infer franchise from characters using FRANCHISE_MAP. Most-common wins."""
    if not characters:
        return None
    counts: dict[str, int] = {}
    for char in characters:
        franchise = FRANCHISE_MAP.get(char)
        if franchise:
            counts[franchise] = counts.get(franchise, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def extract_series(title: str | None) -> str | None:
    """Extract series or collection name from pin title."""
    if not title:
        return None
    for pattern in _SERIES_PATTERNS:
        match = pattern.search(title)
        if match:
            return match.group(1).strip()
    return None


def _enrichment_source(title_chars: list, desc_chars: list) -> str:
    has_title = len(title_chars) > 0
    has_desc = len(desc_chars) > 0
    if has_title and has_desc:
        return "nlp_title+description"
    if has_desc:
        return "nlp_description"
    return "nlp_title"


def enrich_entry(entry: dict) -> dict:
    """Enrich a single catalog entry. Returns modified copy."""
    result = dict(entry)
    title = entry.get("canonical_name")
    description = entry.get("description")

    title_chars = extract_characters(title, None)
    desc_chars = extract_characters(None, description)
    all_chars = extract_characters(title, description)

    series = extract_series(title)
    franchise = infer_franchise(all_chars)

    enriched = False
    if all_chars:
        result["characters"] = all_chars
        enriched = True
    if franchise:
        result["franchise"] = franchise
        enriched = True
    if series:
        result["series_or_collection"] = series
        enriched = True

    if enriched:
        result["enrichment_source"] = _enrichment_source(title_chars, desc_chars)

    return result


def enrich_catalog(entries: list[dict]) -> list[dict]:
    """Enrich all entries in a catalog list."""
    return [enrich_entry(e) for e in entries]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich PinTradingDB catalog with NLP-extracted characters, franchise, and series.",
    )
    parser.add_argument(
        "--input", default=DEFAULT_CATALOG,
        help=f"Input catalog JSON (default: {DEFAULT_CATALOG})",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output catalog JSON (default: same as input, in-place)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print stats without modifying the file",
    )
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Print N random enriched entries for validation",
    )
    args = parser.parse_args()

    output = args.output or args.input

    with open(args.input, "r", encoding="utf-8") as f:
        entries = json.load(f)

    print(f"[enrich] Loaded {len(entries)} entries from {args.input}")

    enriched = enrich_catalog(entries)

    with_chars = sum(1 for e in enriched if e.get("characters"))
    with_franchise = sum(1 for e in enriched if e.get("franchise"))
    with_series = sum(1 for e in enriched if e.get("series_or_collection"))

    print(f"[stats] Characters found: {with_chars}/{len(enriched)} ({with_chars * 100 // len(enriched)}%)")
    print(f"[stats] Franchise inferred: {with_franchise}/{len(enriched)} ({with_franchise * 100 // len(enriched)}%)")
    print(f"[stats] Series/collection: {with_series}/{len(enriched)} ({with_series * 100 // len(enriched)}%)")

    if args.sample > 0:
        samples = random.sample(
            [e for e in enriched if e.get("characters") or e.get("series_or_collection")],
            min(args.sample, with_chars + with_series),
        )
        print(f"\n[sample] {len(samples)} enriched entries:")
        for e in samples:
            print(json.dumps({
                "canonical_name": e.get("canonical_name"),
                "characters": e.get("characters"),
                "franchise": e.get("franchise"),
                "series_or_collection": e.get("series_or_collection"),
                "enrichment_source": e.get("enrichment_source"),
            }, indent=2))
            print()

    if args.dry_run:
        print("[dry-run] No changes written.")
        return

    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)
    print(f"[enrich] Wrote {len(enriched)} entries to {output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant && python -m pytest tests/test_enrich_catalog.py -v`

Expected: ALL PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant && python -m pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/enrich_catalog.py
git commit -m "feat: add NLP enrichment script for catalog entries"
```

---

### Task 6: Validate enrichment against existing data

**Files:**
- None modified — this is a validation step

- [ ] **Step 1: Run enrichment in dry-run mode with samples**

Run: `cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant && python scripts/enrich_catalog.py --dry-run --sample 20`

Expected: Stats output showing character/franchise/series match rates, plus 20 sample entries. Review for false positives and missed extractions.

- [ ] **Step 2: If quality is acceptable, run enrichment for real**

Run: `cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant && python scripts/enrich_catalog.py`

Expected: In-place enrichment of the existing catalog JSON.

- [ ] **Step 3: Commit enriched catalog (optional — catalog is gitignored if large)**

If the catalog JSON is tracked in git:

```bash
git add scripts/scraper/output/pintradingdb_catalog.json
git commit -m "data: enrich existing catalog entries with characters and franchise"
```

---

### Task 7: Clean re-scrape with updated parser

**Files:**
- None modified — this is an operational step

- [ ] **Step 1: Stop the running scraper**

```bash
pkill -f "scrape_pintradingdb.py scrape" && echo "Stopped" || echo "Not running"
```

- [ ] **Step 2: Delete the catalog JSON (keep ID cache and images)**

```bash
rm scripts/scraper/output/pintradingdb_catalog.json
ls scripts/scraper/output/pin_ids_cache.json  # should still exist
ls ../catalog_images/ | head -5               # images should still exist
```

- [ ] **Step 3: Restart scraper with updated parser**

```bash
cd /Users/chris.funaki/Documents/GitHub/Disney-pins/disney-pin-assistant
python3 -u scripts/scrape_pintradingdb.py scrape --rate 0.165 2>&1 | tee scrape.log &
```

- [ ] **Step 4: Verify scraper is running and using new fields**

Wait ~5 minutes, then check:

```bash
python3 -c "
import json
data = json.load(open('scripts/scraper/output/pintradingdb_catalog.json'))
entry = data[0]
print('Fields:', list(entry.keys()))
for field in ['description', 'sku', 'retire_date', 'original_price']:
    print(f'  {field}: {entry.get(field, \"MISSING\")!r}')
"
```

Expected: New fields present in output (may be `None` for specific pins but keys must exist).

- [ ] **Step 5: Commit any remaining changes**

```bash
git add -A && git status
git commit -m "chore: clean re-scrape with updated parser"
```
