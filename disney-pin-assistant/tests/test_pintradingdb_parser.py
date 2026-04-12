"""Tests for the PinTradingDB HTML page parser."""

import os
import sys

# Allow importing from scripts/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest
from scraper.pintradingdb_parser import parse_pin_detail, extract_pin_ids_from_list

DETAIL_FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "pintradingdb_detail.html")
LIST_FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "pintradingdb_list.html")


@pytest.fixture
def detail_html() -> str:
    with open(DETAIL_FIXTURE_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def list_html() -> str:
    with open(LIST_FIXTURE_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def parsed(detail_html) -> dict:
    return parse_pin_detail(detail_html, "1000")


def test_extracts_canonical_name(parsed):
    """Pin name is extracted without the numeric ID prefix."""
    assert parsed["canonical_name"] == "Characters & Cameras Mystery Collection - Dopey Chaser ONLY"


def test_extracts_edition_size(parsed):
    """Edition size is parsed as an integer."""
    assert parsed["edition_size"] == 250


def test_extracts_release_year(parsed):
    """Release year is extracted from the release date."""
    assert parsed["release_year"] == 2014


def test_extracts_image_url(parsed):
    """Full image URL is returned (thumbnail suffix removed)."""
    assert parsed["reference_image_url"] == "http://www.ptdb.co/storedImages/1627.jpg"
    assert "_thumb" not in parsed["reference_image_url"]


def test_sets_source_fields(parsed):
    """Source metadata is set correctly."""
    assert parsed["source"] == "pintradingdb"
    assert parsed["source_reference_id"] == "1000"
    assert parsed["evidence_strength"] == "high"


def test_extracts_origin(parsed):
    """exclusive_source is extracted from the Origin table field (text only, no HTML)."""
    assert parsed["exclusive_source"] == "DLR/DCA, WDW"


def test_extracts_pin_type(parsed):
    """Pin type is inferred from the edition size text."""
    assert parsed["pin_type"] == "limited edition"


def test_extracts_pin_ids_from_list(list_html):
    """Pin IDs are extracted from list page href attributes."""
    ids = extract_pin_ids_from_list(list_html)
    assert "59707" in ids
    assert "59706" in ids
    assert "59705" in ids
    assert "59704" in ids
    assert len(ids) == 4


def test_characters_is_empty_list(parsed):
    """Characters are left as an empty list (inferred later by normalizer)."""
    assert parsed["characters"] == []


def test_franchise_is_none(parsed):
    """Franchise is None (inferred later by normalizer)."""
    assert parsed["franchise"] is None


def test_event_is_none(parsed):
    """Event is None for pins with no event data in HTML."""
    assert parsed["event"] is None


def test_open_edition_pin_type():
    """OE in edition text maps to 'open edition'."""
    from scraper.pintradingdb_parser import _parse_pin_type_from_h3
    assert _parse_pin_type_from_h3("Released: 05/01/2020 - ") == "open edition"


def test_hidden_mickey_pin_type():
    """Hidden Mickey in edition text maps to 'hidden mickey'."""
    from scraper.pintradingdb_parser import _parse_pin_type_from_h3
    assert _parse_pin_type_from_h3("Released: 05/01/2020 - Hidden Mickey") == "hidden mickey"


def test_hm_abbreviation_pin_type():
    """HM abbreviation maps to 'hidden mickey'."""
    from scraper.pintradingdb_parser import _parse_pin_type_from_h3
    assert _parse_pin_type_from_h3("Released: 05/01/2020 - HM 5 of 9") == "hidden mickey"
