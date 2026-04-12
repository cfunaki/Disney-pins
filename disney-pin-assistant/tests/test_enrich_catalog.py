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
