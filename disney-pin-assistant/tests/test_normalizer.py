"""
Tests for the name normalization module.
"""

import sys
import os

# Make scripts/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from scraper.normalizer import normalize_name, extract_edition_from_name, normalize_entry


def test_normalize_name_title_case():
    """Words that are not acronyms should be title-cased."""
    result = normalize_name("MICKEY MOUSE EPCOT PIN")
    # EPCOT and PIN are preserved acronyms; MICKEY and MOUSE become title-case
    assert result == "Mickey Mouse Epcot Pin"


def test_normalize_name_strips_whitespace():
    """Leading, trailing, and internal extra whitespace should be collapsed."""
    result = normalize_name("  Mickey Mouse  Pin  ")
    assert result == "Mickey Mouse Pin"


def test_normalize_name_preserves_acronyms():
    """Recognized acronyms must stay uppercase regardless of input case."""
    assert normalize_name("Mickey LE 3000") == "Mickey LE 3000"
    assert normalize_name("Hidden Mickey HM") == "Hidden Mickey HM"


def test_extract_edition_from_name():
    """Edition sizes should be extracted from various LE patterns."""
    assert extract_edition_from_name("Mickey Mouse LE 3000") == 3000
    assert extract_edition_from_name("Mickey Pin LE/2500") == 2500
    assert extract_edition_from_name("Mickey Pin LE 1,000") == 1000
    assert extract_edition_from_name("Mickey Rack Pin") is None


def test_normalize_entry_cleans_all_fields():
    """A full messy entry should have all relevant fields cleaned."""
    raw = {
        "canonical_name": "  MICKEY MOUSE LE 300  ",
        "characters": ["mickey", "minnie"],
        "franchise": None,
        "edition_size": None,
        "pin_type": "OPEN EDITION",
        "event": "magic kingdom festival",
    }

    result = normalize_entry(raw)

    assert result["canonical_name"] == "Mickey Mouse LE 300"
    assert result["characters"] == ["Mickey Mouse", "Minnie Mouse"]
    assert result["franchise"] == "Mickey & Friends"
    assert result["edition_size"] == 300
    assert result["pin_type"] == "open edition"
    assert result["event"] == "Magic Kingdom Festival"


def test_normalize_entry_no_duplicate_edition():
    """If edition_size is already set, it should not be overwritten from the name."""
    raw = {
        "canonical_name": "Mickey Mouse LE 3000",
        "characters": [],
        "franchise": None,
        "edition_size": 500,
        "pin_type": "limited edition",
        "event": None,
    }

    result = normalize_entry(raw)

    # edition_size was already set to 500; should NOT be overwritten with 3000
    assert result["edition_size"] == 500
