"""NLP enrichment script for catalog entries.

Extracts characters, franchise, and series/collection from pin title and
description text, then enriches catalog JSON entries in place.
"""

import argparse
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from scraper.pinpics_parser import CHARACTER_ALIASES, FRANCHISE_MAP

# Pre-sort aliases longest-first so "Tinker Bell" matches before "Bell",
# and "Buzz Lightyear" matches before "Buzz".
_SORTED_ALIASES = sorted(CHARACTER_ALIASES.keys(), key=len, reverse=True)


def extract_characters(title: str, description: str | None) -> list[str]:
    """Extract canonical character names from title and description text.

    Args:
        title: Pin title string.
        description: Optional pin description string.

    Returns:
        Deduplicated list of canonical character names found in the text.
    """
    text = title or ""
    if description:
        text = text + " " + description

    text_lower = text.lower()

    # Track matched character spans to prevent overlapping matches.
    matched_spans: list[tuple[int, int]] = []
    # Track canonical names already added (for deduplication).
    seen_canonical: set[str] = set()
    characters: list[str] = []

    for alias in _SORTED_ALIASES:
        pattern = r"\b" + re.escape(alias) + r"\b"
        for m in re.finditer(pattern, text_lower, re.IGNORECASE):
            start, end = m.start(), m.end()
            # Skip if this span overlaps with an already-matched span.
            overlaps = any(
                not (end <= s or start >= e) for s, e in matched_spans
            )
            if overlaps:
                continue

            canonical = CHARACTER_ALIASES[alias]
            matched_spans.append((start, end))
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                characters.append(canonical)

    return characters


def infer_franchise(characters: list[str]) -> str | None:
    """Infer the most likely franchise from a list of character names.

    Args:
        characters: List of canonical character names.

    Returns:
        The franchise name with the most character hits, or None.
    """
    if not characters:
        return None

    franchise_counts: dict[str, int] = {}
    for char in characters:
        franchise = FRANCHISE_MAP.get(char)
        if franchise:
            franchise_counts[franchise] = franchise_counts.get(franchise, 0) + 1

    if not franchise_counts:
        return None

    return max(franchise_counts, key=lambda f: franchise_counts[f])


def extract_series(title: str) -> str | None:
    """Extract a series or collection name from a pin title.

    Args:
        title: Pin title string.

    Returns:
        The series/collection name, or None if not found.
    """
    patterns = [
        r"(.+?(?:Mystery\s+(?:Pin\s+)?)?Collection)\b",
        r"(.+?\bSeries)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, title, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def enrich_entry(entry: dict) -> dict:
    """Enrich a catalog entry with NLP-derived fields.

    Never overwrites existing parser-derived fields. Adds characters,
    franchise, series_or_collection, and enrichment_source where absent.

    Args:
        entry: A CatalogEntry-compatible dict.

    Returns:
        The (mutated) entry dict.
    """
    title = entry.get("canonical_name") or ""
    description = entry.get("description") or None

    characters = extract_characters(title, description)
    franchise = infer_franchise(characters) if characters else None
    series = extract_series(title) if title else None

    # Determine enrichment_source based on where matches came from.
    title_chars = extract_characters(title, None) if title else []
    desc_chars = extract_characters("", description) if description else []

    title_hit = bool(title_chars)
    desc_hit = bool(desc_chars)

    enrichment_source = None
    if characters or franchise or series:
        if title_hit and desc_hit:
            enrichment_source = "nlp_title+description"
        elif desc_hit:
            enrichment_source = "nlp_description"
        elif title_hit or series:
            enrichment_source = "nlp_title"

    # Only set fields that are currently absent / falsy.
    if characters and not entry.get("characters"):
        entry["characters"] = characters
    if franchise and not entry.get("franchise"):
        entry["franchise"] = franchise
    if series and not entry.get("series_or_collection"):
        entry["series_or_collection"] = series
    if enrichment_source:
        entry["enrichment_source"] = enrichment_source

    return entry


def main():
    default_input = os.path.join(
        os.path.dirname(__file__),
        "scraper",
        "output",
        "pintradingdb_catalog.json",
    )

    parser = argparse.ArgumentParser(
        description="Enrich catalog entries with NLP-derived characters, franchise, and series."
    )
    parser.add_argument(
        "--input",
        default=default_input,
        metavar="FILE",
        help="Input catalog JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output file (default: same as input, in-place)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats without writing output",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        metavar="N",
        help="Print N random enriched entries",
    )
    args = parser.parse_args()

    output_path = args.output or args.input

    with open(args.input, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    total = len(catalog)
    enriched_entries = [enrich_entry(dict(entry)) for entry in catalog]

    char_count = sum(1 for e in enriched_entries if e.get("characters"))
    franchise_count = sum(1 for e in enriched_entries if e.get("franchise"))
    series_count = sum(1 for e in enriched_entries if e.get("series_or_collection"))

    print(f"Total entries:   {total}")
    print(f"Character rate:  {char_count}/{total} ({100 * char_count // total if total else 0}%)")
    print(f"Franchise rate:  {franchise_count}/{total} ({100 * franchise_count // total if total else 0}%)")
    print(f"Series rate:     {series_count}/{total} ({100 * series_count // total if total else 0}%)")

    if args.sample > 0:
        sample = random.sample(enriched_entries, min(args.sample, len(enriched_entries)))
        for entry in sample:
            print(json.dumps(entry, indent=2))

    if not args.dry_run:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(enriched_entries, f, indent=2, ensure_ascii=False)
        print(f"Wrote {total} entries to {output_path}")


if __name__ == "__main__":
    main()
