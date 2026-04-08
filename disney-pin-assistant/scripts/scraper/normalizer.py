"""
Name normalization module for the Disney Pin Listing Assistant scraper.

Normalizes raw scraped pin data before catalog import.
"""

import re


# Acronyms that should be preserved as-is (uppercase)
_PRESERVED_ACRONYMS = {
    "LE", "HM", "OE", "WDW", "DLR", "AP", "AK", "MK", "DHS",
    "DCA", "TDL", "TDS", "HKDL", "SDL", "DLP",
}

# Character name normalization map (lowercase key → full canonical name)
_CHARACTER_MAP = {
    "mickey": "Mickey Mouse",
    "minnie": "Minnie Mouse",
    "donald": "Donald Duck",
    "daisy": "Daisy Duck",
    "stitch": "Stitch",
    "lilo": "Lilo",
    "elsa": "Elsa",
    "simba": "Simba",
    "woody": "Woody",
    "ariel": "Ariel",
    "belle": "Belle",
}

# Character → franchise mapping
_CHARACTER_FRANCHISE_MAP = {
    "Mickey Mouse": "Mickey & Friends",
    "Minnie Mouse": "Mickey & Friends",
    "Donald Duck": "Mickey & Friends",
    "Daisy Duck": "Mickey & Friends",
    "Stitch": "Lilo & Stitch",
    "Lilo": "Lilo & Stitch",
    "Elsa": "Frozen",
    "Simba": "The Lion King",
    "Woody": "Toy Story",
    "Ariel": "The Little Mermaid",
    "Belle": "Beauty and the Beast",
}

# Patterns for extracting edition size
_LE_PATTERNS = [
    re.compile(r'\bLE[/ ](\d[\d,]*)\b', re.IGNORECASE),
    re.compile(r'\bLE(\d[\d,]*)\b', re.IGNORECASE),
]


def normalize_name(name: str) -> str:
    """
    Normalize a pin name string.

    - Collapses multiple whitespace to a single space and strips leading/trailing whitespace
    - Title-cases words EXCEPT preserved acronyms (LE, HM, OE, WDW, DLR, AP, AK, MK, DHS,
      EPCOT, DCA, TDL, TDS, HKDL, SDL, DLP, PIN)
    - Preserves numbers as-is
    """
    if not name:
        return name

    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()

    # Split into tokens and normalize each
    tokens = name.split(' ')
    normalized = []
    for token in tokens:
        upper = token.upper()
        if upper in _PRESERVED_ACRONYMS:
            normalized.append(upper)
        else:
            normalized.append(token.title())

    return ' '.join(normalized)


def extract_edition_from_name(name: str) -> int | None:
    """
    Extract edition size from a pin name string.

    Recognizes patterns like:
    - "LE 3000"
    - "LE/2500"
    - "LE 1,000"

    Returns the edition size as an int, or None if not found.
    """
    if not name:
        return None

    for pattern in _LE_PATTERNS:
        match = pattern.search(name)
        if match:
            raw = match.group(1).replace(',', '')
            return int(raw)

    return None


def normalize_entry(entry: dict) -> dict:
    """
    Normalize a raw scraped entry dict, returning a cleaned copy.

    - Normalizes canonical_name via normalize_name
    - Normalizes character names to canonical forms
    - Infers franchise from characters if not already set
    - Extracts edition_size from name if not already set
    - Lowercases pin_type
    - Title-cases event
    """
    result = dict(entry)

    # Normalize canonical_name
    if "canonical_name" in result and result["canonical_name"] is not None:
        result["canonical_name"] = normalize_name(result["canonical_name"])

    # Normalize character names
    characters = result.get("characters")
    if characters:
        normalized_characters = []
        for char in characters:
            key = char.strip().lower()
            normalized_characters.append(_CHARACTER_MAP.get(key, char.strip().title()))
        result["characters"] = normalized_characters
    else:
        normalized_characters = []

    # Infer franchise from characters if not set
    if not result.get("franchise") and normalized_characters:
        for char in normalized_characters:
            franchise = _CHARACTER_FRANCHISE_MAP.get(char)
            if franchise:
                result["franchise"] = franchise
                break

    # Extract edition_size from name if not already set
    if not result.get("edition_size") and result.get("canonical_name"):
        extracted = extract_edition_from_name(result["canonical_name"])
        if extracted is not None:
            result["edition_size"] = extracted

    # Lowercase pin_type
    if "pin_type" in result and result["pin_type"] is not None:
        result["pin_type"] = result["pin_type"].lower()

    # Title-case event
    if "event" in result and result["event"] is not None:
        result["event"] = result["event"].title()

    return result
