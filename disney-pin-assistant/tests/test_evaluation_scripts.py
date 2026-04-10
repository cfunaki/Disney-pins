"""
Unit tests for evaluation functions in scripts/generate_scorecard.py.

Uses unittest.mock.MagicMock to simulate SQLAlchemy ORM objects so that
the tests run without a live database.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Allow importing from the scripts/ directory.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_scorecard import (
    evaluate_identification,
    evaluate_listing_quality,
    evaluate_pricing,
    render_markdown,
)


class TestEvaluateIdentification(unittest.TestCase):
    """Tests for evaluate_identification()."""

    def test_evaluate_identification_all_correct(self):
        """All fields match → correct=True."""
        extraction = MagicMock()
        extraction.characters = ["Mickey Mouse"]
        extraction.franchise = "Mickey & Friends"
        extraction.pin_type = "cloisonne"
        extraction.edition_size = 500

        gt = {
            "expected_characters": ["Mickey Mouse"],
            "expected_franchise": "Mickey",
            "expected_pin_type": "cloisonne",
            "expected_edition_size": 500,
        }

        result = evaluate_identification(extraction, gt)

        self.assertTrue(result["correct"])
        self.assertEqual(result["fields_checked"], result["fields_matched"])
        self.assertGreater(result["fields_checked"], 0)

    def test_evaluate_identification_wrong_character(self):
        """Wrong character → correct=False."""
        extraction = MagicMock()
        extraction.characters = ["Donald Duck"]
        extraction.franchise = "Mickey & Friends"
        extraction.pin_type = "cloisonne"
        extraction.edition_size = 500

        gt = {
            "expected_characters": ["Mickey Mouse"],
            "expected_franchise": "Mickey",
            "expected_pin_type": "cloisonne",
            "expected_edition_size": 500,
        }

        result = evaluate_identification(extraction, gt)

        self.assertFalse(result["correct"])
        self.assertFalse(result["details"]["characters"]["matched"])

    def test_evaluate_identification_no_extraction(self):
        """None extraction → correct=False with explanation."""
        gt = {
            "expected_characters": ["Mickey Mouse"],
            "expected_franchise": "Mickey",
        }

        result = evaluate_identification(None, gt)

        self.assertFalse(result["correct"])
        self.assertEqual(result["fields_checked"], 0)
        self.assertEqual(result["fields_matched"], 0)
        self.assertIn("extraction", result["details"])
        self.assertFalse(result["details"]["extraction"]["matched"])


class TestEvaluateListingQuality(unittest.TestCase):
    """Tests for evaluate_listing_quality()."""

    def test_evaluate_listing_quality_good_match(self):
        """High word overlap → edit_level is 'none' or 'minor'."""
        draft = MagicMock()
        draft.title = "Mickey Mouse Cloisonne Pin Limited Edition"

        gt = {"reference_title": "Mickey Mouse Cloisonne Pin Limited Edition"}

        result = evaluate_listing_quality(draft, gt)

        self.assertIn(result["edit_level"], ("none", "minor"))
        self.assertIsNotNone(result["overlap_ratio"])
        self.assertGreaterEqual(result["overlap_ratio"], 0.3)

    def test_evaluate_listing_quality_poor_match(self):
        """No word overlap → edit_level is 'major'."""
        draft = MagicMock()
        draft.title = "Completely Unrelated Listing Words Here"

        gt = {"reference_title": "Mickey Mouse Cloisonne Limited Edition"}

        result = evaluate_listing_quality(draft, gt)

        self.assertEqual(result["edit_level"], "major")

    def test_evaluate_listing_quality_no_draft(self):
        """None draft → edit_level is 'no_draft'."""
        gt = {"reference_title": "Mickey Mouse Cloisonne Pin"}

        result = evaluate_listing_quality(None, gt)

        self.assertEqual(result["edit_level"], "no_draft")
        self.assertIsNone(result["overlap_ratio"])
        self.assertIsNone(result["ai_title"])


class TestEvaluatePricing(unittest.TestCase):
    """Tests for evaluate_pricing()."""

    def test_evaluate_pricing_within_threshold(self):
        """Suggested price within 25% of reference → within_threshold=True."""
        draft = MagicMock()
        draft.suggested_price = 22.00

        gt = {"reference_price": 20.00}

        result = evaluate_pricing(draft, gt)

        self.assertTrue(result["within_threshold"])
        self.assertIsNotNone(result["delta_pct"])
        self.assertLessEqual(result["delta_pct"], 25.0)

    def test_evaluate_pricing_outside_threshold(self):
        """Suggested price more than 25% away from reference → within_threshold=False."""
        draft = MagicMock()
        draft.suggested_price = 50.00

        gt = {"reference_price": 20.00}

        result = evaluate_pricing(draft, gt)

        self.assertFalse(result["within_threshold"])
        self.assertGreater(result["delta_pct"], 25.0)

    def test_evaluate_pricing_no_draft(self):
        """None draft → within_threshold=None, no suggested price."""
        gt = {"reference_price": 20.00}

        result = evaluate_pricing(None, gt)

        self.assertIsNone(result["within_threshold"])
        self.assertIsNone(result["suggested_price"])
        self.assertEqual(result["reference_price"], 20.00)


class TestRenderMarkdown(unittest.TestCase):
    """Tests for render_markdown()."""

    def _make_passing_result(self, image_file: str) -> dict:
        """Build a result dict that passes both id and listing checks."""
        return {
            "image_file": image_file,
            "pin_id": 1,
            "identification": {
                "correct": True,
                "fields_checked": 2,
                "fields_matched": 2,
                "details": {},
            },
            "listing_quality": {
                "edit_level": "none",
                "overlap_ratio": 0.95,
                "ai_title": "Mickey Mouse Pin",
                "reference_title": "Mickey Mouse Pin",
            },
            "pricing": {
                "within_threshold": True,
                "delta_pct": 5.0,
                "suggested_price": 21.00,
                "reference_price": 20.00,
                "reason": "5.0% delta (within 25% threshold)",
            },
        }

    def test_generate_markdown_produces_gate_decision(self):
        """Two passing results → markdown contains 'Gate Decision' and 'PASS'."""
        results = [
            self._make_passing_result("pin_001.jpg"),
            self._make_passing_result("pin_002.jpg"),
        ]

        scorecard = {
            "batch_id": "test-batch",
            "total_pins": 2,
            "summary": {
                "identification_accuracy": 1.0,
                "identification_correct": 2,
                "identification_target": 0.80,
                "identification_pass": True,
                "edit_rate": 1.0,
                "edit_pass_count": 2,
                "edit_target": 0.70,
                "edit_pass": True,
                "pricing_rate": 1.0,
                "pricing_evaluated": 2,
            },
            "gate": "PASS",
            "results": results,
        }

        md = render_markdown(scorecard)

        self.assertIn("Gate Decision", md)
        self.assertIn("PASS", md)


if __name__ == "__main__":
    unittest.main()
