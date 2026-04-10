"""Parser for PinTradingDB pin detail pages and list pages."""

import re
from bs4 import BeautifulSoup


def _parse_edition_size_from_text(text: str) -> int | None:
    """Parse edition size from strings like 'Limited Edition 250' or 'LE 3000'."""
    text = text.replace(",", "")
    match = re.search(r"\d+", text)
    if match:
        val = int(match.group())
        # Edition size of 0 means unknown/not set — treat as None
        if val == 0:
            return None
        return val
    return None


def _parse_release_year_from_date(date_str: str) -> int | None:
    """Extract a 4-digit year from a date string like '01/23/2014'."""
    match = re.search(r"\b(19|20)\d{2}\b", date_str)
    if match:
        return int(match.group())
    return None


def _parse_pin_type_from_h3(h3_text: str) -> str:
    """Infer pin type from the h3 text after 'Released: DATE - '.

    Examples:
        'Released: 01/23/2014 - Limited Edition 250' -> 'limited edition'
        'Released: 05/01/2020 - '                    -> 'open edition'
        'Released: 05/01/2020 - Hidden Mickey'        -> 'hidden mickey'
        'Released: 05/01/2020 - HM 5 of 9'           -> 'hidden mickey'
    """
    # Strip the "Released: DATE - " prefix to get the edition part
    edition_part = re.sub(r"^Released:\s*\S+\s*-\s*", "", h3_text, flags=re.IGNORECASE).strip()

    lower = edition_part.lower()

    if re.search(r"\bhidden mickey\b", lower):
        return "hidden mickey"
    if re.search(r"\bhm\b", lower):
        return "hidden mickey"
    if re.search(r"\blimited edition\b", lower) or re.search(r"\ble\b", lower):
        return "limited edition"
    if re.search(r"\bopen edition\b", lower) or re.search(r"\boe\b", lower):
        return "open edition"
    if re.search(r"\bmystery\b", lower):
        return "mystery"

    # No edition marker found — default to open edition
    return "open edition"


def _extract_full_image_url(soup: BeautifulSoup) -> str | None:
    """Extract the full-size image URL from #picDiv.

    Thumbnail srcs end in '_thumb.jpg'; replace that suffix with '.jpg'.
    """
    pic_div = soup.find("div", id="picDiv")
    if not pic_div:
        return None
    img = pic_div.find("img")
    if not img or not img.get("src"):
        return None
    src = img["src"]
    # Convert thumbnail to full-size
    if src.endswith("_thumb.jpg"):
        src = src[: -len("_thumb.jpg")] + ".jpg"
    return src


def parse_pin_detail(html: str, pin_id: str) -> dict:
    """Parse a PinTradingDB pin detail page.

    Args:
        html: Raw HTML string of the PinTradingDB pin detail page.
        pin_id: The PinTradingDB pin identifier (used as source_reference_id).

    Returns:
        A dict matching the CatalogEntry JSON import format with keys:
        canonical_name, characters, franchise, series_or_collection, event,
        edition_size, release_year, pin_type, exclusive_source,
        reference_image_url, source, source_reference_id, evidence_strength.
    """
    soup = BeautifulSoup(html, "html.parser")

    # --- Pin name ---
    # From <h2 class="title"> in sidebar: "{id} - {name}"
    canonical_name = ""
    title_h2 = soup.find("h2", class_="title")
    if title_h2:
        raw_title = title_h2.get_text(strip=True)
        # Strip the leading "{id} - " prefix
        name_match = re.match(r"^\d+\s*-\s*(.+)$", raw_title)
        if name_match:
            canonical_name = name_match.group(1).strip()
        else:
            canonical_name = raw_title

    # --- H3 tag: release date + edition info ---
    h3_text = ""
    sidebar = soup.find("div", id="sidebar")
    if sidebar:
        h3 = sidebar.find("h3")
        if h3:
            h3_text = h3.get_text(strip=True)

    # Release year from h3
    release_year: int | None = None
    date_match = re.search(r"Released:\s*(\S+)", h3_text, re.IGNORECASE)
    if date_match:
        release_year = _parse_release_year_from_date(date_match.group(1))

    # Pin type from h3
    pin_type = _parse_pin_type_from_h3(h3_text) if h3_text else "open edition"

    # --- Details table ---
    edition_size: int | None = None
    exclusive_source: str | None = None

    details_table = soup.find("table", class_="details_table")
    if details_table:
        for row in details_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) == 2:
                label = cells[0].get_text(strip=True)
                value_cell = cells[1]
                value_text = value_cell.get_text(separator=", ", strip=True)

                if label == "Edition Size":
                    edition_size = _parse_edition_size_from_text(value_text)
                elif label == "Release Date" and release_year is None:
                    # Fallback: parse year from table if h3 didn't have it
                    release_year = _parse_release_year_from_date(value_text)
                elif label == "Origin":
                    # Origin may contain multiple <a> links — join their text
                    links = value_cell.find_all("a")
                    if links:
                        exclusive_source = ", ".join(a.get_text(strip=True) for a in links) or None
                    else:
                        exclusive_source = value_text or None

    # --- Image URL ---
    reference_image_url = _extract_full_image_url(soup)

    return {
        "canonical_name": canonical_name,
        "characters": [],
        "franchise": None,
        "series_or_collection": None,
        "event": None,
        "edition_size": edition_size,
        "release_year": release_year,
        "pin_type": pin_type,
        "exclusive_source": exclusive_source,
        "reference_image_url": reference_image_url,
        "source": "pintradingdb",
        "source_reference_id": pin_id,
        "evidence_strength": "high",
    }


def extract_pin_ids_from_list(html: str) -> list[str]:
    """Extract pin IDs from a PinTradingDB list page.

    Finds all <a href="pin/{id}"> patterns and returns the ID strings.

    Args:
        html: Raw HTML string of a PinTradingDB list page.

    Returns:
        List of pin ID strings (e.g. ['59707', '59706', ...]).
    """
    soup = BeautifulSoup(html, "html.parser")
    ids = []
    for a_tag in soup.find_all("a", href=re.compile(r"^pin/\d+$")):
        href = a_tag["href"]
        match = re.match(r"^pin/(\d+)$", href)
        if match:
            ids.append(match.group(1))
    return ids
