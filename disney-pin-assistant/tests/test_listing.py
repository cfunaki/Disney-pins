import pytest
from src.pipeline.listing import generate_listing_draft, compute_pricing

def test_generate_listing_draft():
    extraction = {"characters": ["Mickey Mouse"], "franchise": "Mickey & Friends", "event_clues": "Epcot Food & Wine Festival", "pin_type": "limited edition", "edition_size": 3000, "condition_observations": "Excellent condition", "visible_dates": "2019", "text_on_pin": "Walt Disney World", "collection_or_series": None, "suggested_search_terms": ["mickey mouse food wine pin"]}
    catalog_match = {"canonical_name": "Mickey Mouse Epcot Food & Wine 2019 LE 3000", "characters": ["Mickey Mouse"], "franchise": "Mickey & Friends", "event": "Epcot Food & Wine Festival", "edition_size": 3000, "release_year": 2019, "pin_type": "limited edition"}
    draft = generate_listing_draft(extraction, catalog_match, pricing=None)
    assert len(draft["title"]) <= 80
    assert "Mickey Mouse" in draft["title"]
    assert draft["description"] is not None
    assert len(draft["tags_keywords"]) > 0

def test_generate_listing_draft_no_match():
    extraction = {"characters": ["Stitch"], "franchise": "Lilo & Stitch", "event_clues": None, "pin_type": "enamel", "edition_size": None, "condition_observations": "Good condition", "visible_dates": None, "text_on_pin": "Disney Parks", "collection_or_series": None, "suggested_search_terms": ["stitch disney parks pin"]}
    draft = generate_listing_draft(extraction, catalog_match=None, pricing=None)
    assert len(draft["title"]) <= 80
    assert "Stitch" in draft["title"]
    assert draft["description"] is not None

def test_compute_pricing():
    comps = [
        {"price": 20.00, "listing_type": "sold", "excluded": False, "match_type": "exact"},
        {"price": 25.00, "listing_type": "sold", "excluded": False, "match_type": "exact"},
        {"price": 30.00, "listing_type": "sold", "excluded": False, "match_type": "exact"},
        {"price": 100.00, "listing_type": "sold", "excluded": True, "match_type": "exact"},
    ]
    pricing = compute_pricing(comps)
    assert pricing["suggested_price"] == 25.00
    assert pricing["quick_sale_price"] == 20.00
    assert pricing["price_confidence"] == "medium"
    assert pricing["comp_count"] == 3

def test_compute_pricing_no_comps():
    pricing = compute_pricing([])
    assert pricing["suggested_price"] is None
    assert pricing["quick_sale_price"] is None
    assert pricing["price_confidence"] == "low"
    assert pricing["comp_count"] == 0

def test_compute_pricing_high_confidence():
    comps = [{"price": p, "listing_type": "sold", "excluded": False, "match_type": "exact"} for p in [22, 23, 24, 25, 24, 23, 25, 24]]
    pricing = compute_pricing(comps)
    assert pricing["price_confidence"] == "high"
    assert pricing["comp_count"] == 8
