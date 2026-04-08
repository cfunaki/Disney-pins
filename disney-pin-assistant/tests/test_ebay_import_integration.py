"""Integration tests for eBay import CLI helper functions."""

import json
from pathlib import Path

from scripts.import_ebay_listings import (
    build_catalog_entry,
    build_ground_truth_entry,
    item_id_to_filename,
    load_existing_ids,
)


def test_item_id_to_filename():
    assert item_id_to_filename("v1|123456789|0") == "v1-123456789-0.jpg"


def test_item_id_to_filename_simple():
    assert item_id_to_filename("999") == "999.jpg"


def test_build_catalog_entry():
    parsed = {
        "source_reference_id": "v1|123|0",
        "canonical_name": "Test Pin",
        "characters": ["Mickey Mouse"],
        "franchise": "Mickey & Friends",
        "pin_type": "limited edition",
        "edition_size": 3000,
        "release_year": 2024,
        "image_url": "https://example.com/img.jpg",
        "price": 25.99,
        "description": "A test pin",
        "status": "sold",
    }
    entry = build_catalog_entry(parsed)
    assert entry["source"] == "ebay"
    assert entry["source_reference_id"] == "v1|123|0"
    assert entry["evidence_strength"] == "high"
    assert entry["canonical_name"] == "Test Pin"
    assert "price" not in entry  # Price is not in catalog


def test_build_ground_truth_entry():
    parsed = {
        "source_reference_id": "v1|123|0",
        "canonical_name": "Test Pin",
        "characters": ["Stitch"],
        "franchise": "Lilo & Stitch",
        "pin_type": "limited edition",
        "edition_size": 500,
        "release_year": None,
        "image_url": "https://example.com/img.jpg",
        "price": 42.00,
        "description": "A stitch pin",
        "status": "sold",
    }
    entry = build_ground_truth_entry(parsed, "v1-123-0.jpg")
    assert entry["image_file"] == "v1-123-0.jpg"
    assert entry["reference_title"] == "Test Pin"
    assert entry["reference_price"] == 42.00
    assert entry["expected_characters"] == ["Stitch"]
    assert entry["expected_franchise"] == "Lilo & Stitch"
    assert entry["notes"] == "sold"


def test_load_existing_ids_empty(tmp_path):
    """Returns empty set when file doesn't exist."""
    ids = load_existing_ids(tmp_path / "nonexistent.json")
    assert ids == set()


def test_load_existing_ids_from_ground_truth(tmp_path):
    """Extracts item IDs from image filenames."""
    gt_path = tmp_path / "ground_truth.json"
    gt_path.write_text(json.dumps({
        "pins": [
            {"image_file": "v1-111-0.jpg", "reference_title": "Pin A"},
            {"image_file": "v1-222-0.jpg", "reference_title": "Pin B"},
            {"image_file": "manual_photo.jpg", "reference_title": "Pin C"},
        ]
    }))
    ids = load_existing_ids(gt_path)
    assert "v1|111|0" in ids
    assert "v1|222|0" in ids
    assert len(ids) == 2  # manual_photo doesn't match pattern
