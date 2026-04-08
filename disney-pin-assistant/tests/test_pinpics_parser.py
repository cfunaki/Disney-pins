"""Tests for the PinPics HTML page parser."""

import os
import sys

# Allow importing from scripts/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest
from scraper.pinpics_parser import parse_pin_page

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "pinpics_sample.html")


@pytest.fixture
def sample_html() -> str:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def parsed(sample_html) -> dict:
    return parse_pin_page(sample_html, "134567")


def test_parse_pin_page_extracts_name(parsed):
    assert parsed["canonical_name"] == "Mickey Mouse Epcot Food & Wine 2019"


def test_parse_pin_page_extracts_edition_size(parsed):
    assert parsed["edition_size"] == 3000


def test_parse_pin_page_extracts_release_year(parsed):
    assert parsed["release_year"] == 2019


def test_parse_pin_page_extracts_characters(parsed):
    assert "Mickey Mouse" in parsed["characters"]


def test_parse_pin_page_extracts_pin_type(parsed):
    assert parsed["pin_type"] == "limited edition"


def test_parse_pin_page_extracts_event(parsed):
    assert "Food & Wine" in parsed["event"]


def test_parse_pin_page_sets_source_fields(parsed):
    assert parsed["source"] == "pinpics"
    assert parsed["source_reference_id"] == "134567"
    assert parsed["evidence_strength"] == "medium"
