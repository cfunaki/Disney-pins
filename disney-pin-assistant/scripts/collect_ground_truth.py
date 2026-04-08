#!/usr/bin/env python3
"""
Interactive CLI script to collect ground truth data from friend's eBay listings.
Records listing metadata per image for use in AI output evaluation.
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
SAMPLE_DATA_DIR = BASE_DIR / "sample_data"
EVALUATION_DIR = BASE_DIR / "evaluation"
GROUND_TRUTH_FILE = EVALUATION_DIR / "ground_truth.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def load_ground_truth() -> dict:
    """Load existing ground truth data, or return empty structure."""
    if GROUND_TRUTH_FILE.exists():
        with open(GROUND_TRUTH_FILE, "r") as f:
            return json.load(f)
    return {"pins": []}


def save_ground_truth(data: dict) -> None:
    """Save ground truth data to JSON file."""
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    with open(GROUND_TRUTH_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nSaved to {GROUND_TRUTH_FILE}")


def prompt_required(label: str) -> str:
    """Prompt for a required field, looping until a non-empty value is given."""
    while True:
        value = input(f"  {label}: ").strip()
        if value:
            return value
        print(f"  (Required) Please enter a value for '{label}'.")


def prompt_optional(label: str, default: str = "") -> str:
    """Prompt for an optional field."""
    value = input(f"  {label} (optional): ").strip()
    return value if value else default


def parse_price(raw: str) -> float | None:
    """Strip $ and , from price string and convert to float."""
    cleaned = raw.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def prompt_price() -> float | None:
    """Prompt for price with validation."""
    while True:
        raw = input("  Friend's price (e.g. 24.99): ").strip()
        if not raw:
            return None
        price = parse_price(raw)
        if price is not None:
            return price
        print("  Invalid price. Enter a number like 24.99 or $24.99.")


def parse_characters(raw: str) -> list[str]:
    """Split comma-separated characters, strip whitespace, filter empty strings."""
    return [c.strip() for c in raw.split(",") if c.strip()]


def prompt_characters() -> list[str]:
    """Prompt for expected characters (required, comma-separated)."""
    while True:
        raw = input("  Expected characters (comma-separated): ").strip()
        characters = parse_characters(raw)
        if characters:
            return characters
        print("  (Required) Please enter at least one character.")


def parse_edition_size(raw: str) -> int | None:
    """Convert edition size string to int, or None if blank."""
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        print(f"  Warning: '{cleaned}' is not a valid integer — storing as None.")
        return None


def collect_for_image(image_name: str) -> dict:
    """Interactively collect ground truth fields for a single image."""
    print(f"\n--- Image: {image_name} ---")

    title = prompt_required("Friend's listing title")
    description = prompt_optional("Friend's description (brief)")
    price = prompt_price()
    characters = prompt_characters()
    franchise = prompt_optional("Expected franchise (e.g. Mickey & Friends)")
    pin_type = prompt_optional("Expected pin type (e.g. limited edition, rack, hidden mickey)")

    edition_size_raw = prompt_optional("Expected edition size (or blank)")
    edition_size = parse_edition_size(edition_size_raw)

    event = prompt_optional("Expected event (e.g. Food & Wine Festival)")
    notes = prompt_optional("Any notes")

    return {
        "image_file": image_name,
        "reference_title": title,
        "reference_description": description,
        "reference_price": price,
        "expected_characters": characters,
        "expected_franchise": franchise,
        "expected_pin_type": pin_type,
        "expected_edition_size": edition_size,
        "expected_event": event,
        "notes": notes,
    }


def get_image_files() -> list[Path]:
    """Return sorted list of image files in sample_data/."""
    return sorted(
        p for p in SAMPLE_DATA_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def main() -> None:
    if not SAMPLE_DATA_DIR.exists():
        print("Create a sample_data/ directory with pin photos first.")
        sys.exit(1)

    image_files = get_image_files()
    if not image_files:
        print("No image files found in sample_data/. Add .jpg, .jpeg, .png, or .webp files.")
        sys.exit(1)

    ground_truth = load_ground_truth()
    already_recorded = {p["image_file"] for p in ground_truth["pins"]}
    new_images = [img for img in image_files if img.name not in already_recorded]

    if not new_images:
        print(f"All {len(image_files)} image(s) already have ground truth recorded.")
        print(f"Ground truth file: {GROUND_TRUTH_FILE}")
        sys.exit(0)

    print(f"Found {len(new_images)} new image(s) to record (skipping {len(already_recorded)} already done).")
    print("Press Ctrl+C at any time to save progress and exit.\n")

    try:
        for image_path in new_images:
            entry = collect_for_image(image_path.name)
            ground_truth["pins"].append(entry)

    except KeyboardInterrupt:
        print("\n\nInterrupted — saving progress...")

    save_ground_truth(ground_truth)
    recorded_count = len(ground_truth["pins"])
    print(f"Total records saved: {recorded_count}")


if __name__ == "__main__":
    main()
