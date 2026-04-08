"""Tests for eBay listing parser field extraction."""

from scripts.ebay_import.listing_parser import parse_listing


def test_parse_listing_with_full_item_specifics():
    """Extract all fields from a listing with complete item specifics."""
    listing = {
        "itemId": "v1|123456789|0",
        "title": "Disney Mickey Mouse LE 3000 Pin",
        "price": {"value": "25.99", "currency": "USD"},
        "condition": "New",
        "image": {"imageUrl": "https://i.ebayimg.com/images/g/abc/s-l1600.jpg"},
        "localizedAspects": [
            {"name": "Character", "value": "Mickey Mouse"},
            {"name": "Theme", "value": "Mickey & Friends"},
            {"name": "Type", "value": "Limited Edition"},
            {"name": "Edition Size", "value": "3000"},
            {"name": "Year", "value": "2024"},
        ],
    }
    result = parse_listing(listing, status="sold")

    assert result["source_reference_id"] == "v1|123456789|0"
    assert result["canonical_name"] == "Disney Mickey Mouse LE 3000 Pin"
    assert result["characters"] == ["Mickey Mouse"]
    assert result["franchise"] == "Mickey & Friends"
    assert result["pin_type"] == "limited edition"
    assert result["edition_size"] == 3000
    assert result["release_year"] == 2024
    assert result["price"] == 25.99
    assert result["image_url"] == "https://i.ebayimg.com/images/g/abc/s-l1600.jpg"
    assert result["status"] == "sold"


def test_parse_listing_multiple_characters():
    """Split comma-separated characters from item specifics."""
    listing = {
        "itemId": "v1|999|0",
        "title": "Mickey and Minnie Pin",
        "price": {"value": "10.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
        "localizedAspects": [
            {"name": "Character", "value": "Mickey Mouse, Minnie Mouse"},
        ],
    }
    result = parse_listing(listing, status="active")
    assert result["characters"] == ["Mickey Mouse", "Minnie Mouse"]


def test_parse_listing_fallback_to_title_for_edition_size():
    """Extract edition size from title when item specifics lack it."""
    listing = {
        "itemId": "v1|888|0",
        "title": "Stitch LE/2500 Disney Pin",
        "price": {"value": "15.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
        "localizedAspects": [],
    }
    result = parse_listing(listing, status="sold")
    assert result["edition_size"] == 2500


def test_parse_listing_no_item_specifics():
    """Handle listing with no localizedAspects at all."""
    listing = {
        "itemId": "v1|777|0",
        "title": "Disney Trading Pin Lot",
        "price": {"value": "5.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
    }
    result = parse_listing(listing, status="active")
    assert result["characters"] == []
    assert result["franchise"] is None
    assert result["edition_size"] is None
    assert result["pin_type"] is None


def test_parse_listing_infers_franchise_from_character():
    """Infer franchise from character when Theme is missing."""
    listing = {
        "itemId": "v1|666|0",
        "title": "Ariel Pin",
        "price": {"value": "12.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
        "localizedAspects": [
            {"name": "Character", "value": "Ariel"},
        ],
    }
    result = parse_listing(listing, status="sold")
    assert result["franchise"] == "The Little Mermaid"


def test_parse_listing_html_description_stripped():
    """Strip HTML tags from description field."""
    listing = {
        "itemId": "v1|555|0",
        "title": "Test Pin",
        "price": {"value": "8.00", "currency": "USD"},
        "image": {"imageUrl": "https://example.com/img.jpg"},
        "localizedAspects": [],
        "description": "<p>Beautiful <b>Disney</b> pin in <i>mint</i> condition.</p>",
    }
    result = parse_listing(listing, status="active")
    assert result["description"] == "Beautiful Disney pin in mint condition."
    assert "<" not in result["description"]
