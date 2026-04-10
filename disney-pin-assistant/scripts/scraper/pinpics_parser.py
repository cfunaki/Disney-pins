"""Parser for PinPics pin detail pages."""

import re
from bs4 import BeautifulSoup


# Normalization maps

CHARACTER_ALIASES = {
    "mickey": "Mickey Mouse",
    "minnie": "Minnie Mouse",
    "donald": "Donald Duck",
    "daisy": "Daisy Duck",
    "goofy": "Goofy",
    "pluto": "Pluto",
    "chip": "Chip",
    "dale": "Dale",
    "tinker bell": "Tinker Bell",
    "tinkerbell": "Tinker Bell",
    "tink": "Tinker Bell",
    "stitch": "Stitch",
    "lilo": "Lilo",
    "elsa": "Elsa",
    "anna": "Anna",
    "olaf": "Olaf",
    "ariel": "Ariel",
    "belle": "Belle",
    "cinderella": "Cinderella",
    "aurora": "Aurora",
    "sleeping beauty": "Aurora",
    "rapunzel": "Rapunzel",
    "moana": "Moana",
    "simba": "Simba",
    "pumba": "Pumbaa",
    "pumbaa": "Pumbaa",
    "timon": "Timon",
    "woody": "Woody",
    "buzz": "Buzz Lightyear",
    "buzz lightyear": "Buzz Lightyear",
    "jessie": "Jessie",
    "nemo": "Nemo",
    "dory": "Dory",
    "wall-e": "WALL-E",
    "walle": "WALL-E",
    "jack skellington": "Jack Skellington",
    "jack": "Jack Skellington",
    "sally": "Sally",
}

FRANCHISE_MAP = {
    "Mickey Mouse": "Mickey & Friends",
    "Minnie Mouse": "Mickey & Friends",
    "Donald Duck": "Mickey & Friends",
    "Daisy Duck": "Mickey & Friends",
    "Goofy": "Mickey & Friends",
    "Pluto": "Mickey & Friends",
    "Chip": "Mickey & Friends",
    "Dale": "Mickey & Friends",
    "Stitch": "Lilo & Stitch",
    "Lilo": "Lilo & Stitch",
    "Elsa": "Frozen",
    "Anna": "Frozen",
    "Olaf": "Frozen",
    "Tinker Bell": "Peter Pan",
    "Ariel": "The Little Mermaid",
    "Belle": "Beauty and the Beast",
    "Cinderella": "Cinderella",
    "Aurora": "Sleeping Beauty",
    "Rapunzel": "Tangled",
    "Moana": "Moana",
    "Simba": "The Lion King",
    "Pumbaa": "The Lion King",
    "Timon": "The Lion King",
    "Woody": "Toy Story",
    "Buzz Lightyear": "Toy Story",
    "Jessie": "Toy Story",
    "Nemo": "Finding Nemo",
    "Dory": "Finding Nemo",
    "WALL-E": "WALL-E",
    "Jack Skellington": "The Nightmare Before Christmas",
    "Sally": "The Nightmare Before Christmas",
}

PIN_TYPE_ALIASES = {
    "limited edition": "limited edition",
    "le": "limited edition",
    "open edition": "open edition",
    "oe": "open edition",
    "hidden mickey": "hidden mickey",
    "hm": "hidden mickey",
    "mystery": "mystery",
    "mystery pin": "mystery",
    "pin trading night": "pin trading night",
    "ptn": "pin trading night",
    "completer": "completer",
    "cast exclusive": "cast exclusive",
    "artist proof": "artist proof",
    "ap": "artist proof",
    "jumbo": "jumbo",
    "framed": "framed",
    "dangle": "dangle",
}


def _normalize_character(name: str) -> str:
    """Return the canonical character name for a given raw name."""
    key = name.strip().lower()
    return CHARACTER_ALIASES.get(key, name.strip())


def _parse_characters(raw: str) -> list[str]:
    """Split a character string on commas, slashes, or ampersands and normalize each."""
    parts = re.split(r"[,/&]+", raw)
    result = []
    for part in parts:
        part = part.strip()
        if part:
            result.append(_normalize_character(part))
    return result


def _infer_franchise(characters: list[str]) -> str | None:
    """Return the most common franchise among the given characters, or None."""
    for char in characters:
        if char in FRANCHISE_MAP:
            return FRANCHISE_MAP[char]
    return None


def _parse_edition_size(raw: str) -> int | None:
    """Parse edition size from strings like '3000', 'LE 3000', '3,000'."""
    raw = raw.strip()
    # Remove commas for thousands separators
    raw = raw.replace(",", "")
    # Find first sequence of digits
    match = re.search(r"\d+", raw)
    if match:
        return int(match.group())
    return None


def _parse_release_year(raw: str) -> int | None:
    """Extract a 4-digit year from a date string."""
    match = re.search(r"\b(19|20)\d{2}\b", raw)
    if match:
        return int(match.group())
    return None


def _normalize_pin_type(raw: str) -> str:
    """Normalize pin type to a lowercase standard value."""
    key = raw.strip().lower()
    return PIN_TYPE_ALIASES.get(key, key)


def _extract_fields(soup: BeautifulSoup) -> dict:
    """Extract key-value pairs from the pointed table rows."""
    fields = {}
    table = soup.find("table", class_="pointed")
    if not table:
        return fields

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 2:
            label = cells[0].get_text(strip=True).rstrip(":")
            value = cells[1].get_text(strip=True)
            fields[label] = value
    return fields


def _extract_pin_name(soup: BeautifulSoup) -> str:
    """Extract pin name from bold header cell with colspan or first bold tag."""
    table = soup.find("table", class_="pointed")
    if table:
        # Look for a td with colspan containing bold text
        for td in table.find_all("td", attrs={"colspan": True}):
            b = td.find("b")
            if b:
                return b.get_text(strip=True)
        # Fallback: first bold tag in table
        b = table.find("b")
        if b:
            return b.get_text(strip=True)
    # Fallback: first bold tag anywhere
    b = soup.find("b")
    return b.get_text(strip=True) if b else ""


def _extract_image_url(soup: BeautifulSoup) -> str | None:
    """Extract the first img src from the page."""
    img = soup.find("img")
    if img and img.get("src"):
        return img["src"]
    return None


def parse_pin_page(html: str, pin_id: str) -> dict:
    """Parse a PinPics pin detail page and return a CatalogEntry-compatible dict.

    Args:
        html: Raw HTML string of the PinPics pin detail page.
        pin_id: The PinPics pin identifier (used as source_reference_id).

    Returns:
        A dict matching the CatalogEntry JSON import format.
    """
    soup = BeautifulSoup(html, "html.parser")

    name = _extract_pin_name(soup)
    fields = _extract_fields(soup)

    # Edition size
    edition_size = None
    if "Edition Size" in fields:
        edition_size = _parse_edition_size(fields["Edition Size"])

    # Release year
    release_year = None
    if "Release Date" in fields:
        release_year = _parse_release_year(fields["Release Date"])

    # Characters
    characters = []
    if "Characters" in fields:
        characters = _parse_characters(fields["Characters"])

    # Pin type / category
    pin_type = "open edition"
    if "Pin Category" in fields:
        pin_type = _normalize_pin_type(fields["Pin Category"])

    # Franchise
    franchise = _infer_franchise(characters)

    # Event — prefer "Features" field, fall back to searching name
    event = None
    if "Features" in fields:
        event = fields["Features"]

    # Exclusive source — use "Origin" field if present
    exclusive_source = fields.get("Origin") or None

    # Image URL
    reference_image_url = _extract_image_url(soup)

    return {
        "canonical_name": name,
        "alternate_names": [],
        "characters": characters,
        "franchise": franchise,
        "series_or_collection": None,
        "event": event,
        "edition_size": edition_size,
        "release_year": release_year,
        "pin_type": pin_type,
        "exclusive_source": exclusive_source,
        "source": "pinpics",
        "source_reference_id": pin_id,
        "reference_image_url": reference_image_url,
        "evidence_strength": "medium",
    }
