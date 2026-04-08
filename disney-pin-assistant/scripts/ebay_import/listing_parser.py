"""Extract structured fields from eBay listing data."""

import re
from html.parser import HTMLParser

from scripts.scraper.normalizer import (
    _CHARACTER_FRANCHISE_MAP,
    _CHARACTER_MAP,
    extract_edition_from_name,
)


class _HTMLStripper(HTMLParser):
    """Simple HTML tag stripper."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html(html: str) -> str:
    """Remove HTML tags from a string, returning plain text."""
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text().strip()


def _get_aspect(aspects: list[dict], name: str) -> str | None:
    """Get a single item specific value by name."""
    for aspect in aspects:
        if aspect.get("name", "").lower() == name.lower():
            return aspect.get("value")
    return None


def _parse_characters(raw: str | None) -> list[str]:
    """Split comma-separated character string and normalize names."""
    if not raw:
        return []
    chars = []
    for part in raw.split(","):
        part = part.strip()
        key = part.lower()
        chars.append(_CHARACTER_MAP.get(key, part))
    return chars


def _infer_franchise(characters: list[str], aspects: list[dict]) -> str | None:
    """Get franchise from item specifics or infer from characters."""
    franchise = _get_aspect(aspects, "Theme") or _get_aspect(aspects, "Franchise")
    if franchise:
        return franchise
    for char in characters:
        if char in _CHARACTER_FRANCHISE_MAP:
            return _CHARACTER_FRANCHISE_MAP[char]
    return None


def _parse_pin_type(aspects: list[dict]) -> str | None:
    """Get pin type from item specifics, lowercased."""
    raw = _get_aspect(aspects, "Type")
    return raw.lower() if raw else None


def _parse_edition_size(aspects: list[dict], title: str) -> int | None:
    """Get edition size from item specifics or parse from title."""
    raw = _get_aspect(aspects, "Edition Size")
    if raw:
        cleaned = raw.replace(",", "")
        try:
            return int(cleaned)
        except ValueError:
            pass
    return extract_edition_from_name(title)


def _parse_release_year(aspects: list[dict]) -> int | None:
    """Get release year from item specifics."""
    raw = _get_aspect(aspects, "Year")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


def parse_listing(listing: dict, status: str) -> dict:
    """Parse an eBay listing dict into a structured record.

    Args:
        listing: eBay Browse API item or item summary dict.
        status: "sold" or "active".

    Returns:
        Dict with normalized fields for catalog and ground truth output.
    """
    aspects = listing.get("localizedAspects", [])
    title = listing.get("title", "")
    characters = _parse_characters(_get_aspect(aspects, "Character"))

    price_data = listing.get("price", {})
    price = None
    if price_data.get("value"):
        try:
            price = float(price_data["value"])
        except (ValueError, TypeError):
            pass

    image_url = None
    image_data = listing.get("image")
    if image_data:
        image_url = image_data.get("imageUrl")

    description = ""
    raw_desc = listing.get("description", "")
    if raw_desc:
        description = strip_html(raw_desc)

    return {
        "source_reference_id": listing.get("itemId", ""),
        "canonical_name": title,
        "characters": characters,
        "franchise": _infer_franchise(characters, aspects),
        "pin_type": _parse_pin_type(aspects),
        "edition_size": _parse_edition_size(aspects, title),
        "release_year": _parse_release_year(aspects),
        "price": price,
        "image_url": image_url,
        "description": description,
        "status": status,
    }
