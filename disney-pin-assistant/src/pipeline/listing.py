import statistics
from src.pipeline.comp_scoring import weighted_price_recommendation

def generate_listing_draft(extraction: dict, catalog_match: dict | None, pricing: dict | None) -> dict:
    title = _build_title(extraction, catalog_match)
    description = _build_description(extraction, catalog_match)
    tags = _build_tags(extraction)
    draft = {
        "title": title[:80],
        "description": description,
        "item_specifics": _build_item_specifics(extraction, catalog_match),
        "suggested_price": pricing["suggested_price"] if pricing else None,
        "quick_sale_price": pricing["quick_sale_price"] if pricing else None,
        "price_confidence": pricing["price_confidence"] if pricing else "low",
        "pricing_reasoning": pricing.get("reasoning") if pricing else None,
        "tags_keywords": tags,
        "export_status": "draft",
    }
    return draft

def _build_title(extraction: dict, catalog_match: dict | None) -> str:
    parts = ["Disney"]
    characters = extraction.get("characters") or []
    if characters:
        parts.append(" ".join(characters[:2]))
    event = None
    if catalog_match and catalog_match.get("event"):
        event = catalog_match["event"]
    elif extraction.get("event_clues"):
        event = extraction["event_clues"]
    if event:
        parts.append(event)
    year = None
    if catalog_match and catalog_match.get("release_year"):
        year = str(catalog_match["release_year"])
    elif extraction.get("visible_dates"):
        year = extraction["visible_dates"]
    if year:
        parts.append(year)
    parts.append("Pin")
    pin_type = extraction.get("pin_type", "")
    edition = extraction.get("edition_size")
    if pin_type == "limited edition" and edition:
        parts.append(f"LE/{edition}")
    elif pin_type == "limited edition":
        parts.append("LE")
    return " ".join(parts)

def _build_description(extraction: dict, catalog_match: dict | None) -> str:
    lines = []
    name = ""
    if catalog_match:
        name = catalog_match.get("canonical_name", "")
    if not name:
        chars = ", ".join(extraction.get("characters") or ["Unknown"])
        name = f"{chars} Disney Pin"
    lines.append(name)
    pin_type = extraction.get("pin_type")
    edition = extraction.get("edition_size")
    if pin_type:
        type_line = f"Type: {pin_type}"
        if edition:
            type_line += f" (edition size: {edition})"
        lines.append(type_line)
    event = extraction.get("event_clues")
    if event:
        lines.append(f"Event: {event}")
    condition = extraction.get("condition_observations")
    if condition:
        lines.append(f"Condition: {condition}")
    return "\n".join(lines)

def _build_tags(extraction: dict) -> list[str]:
    tags = set()
    for char in extraction.get("characters") or []:
        tags.add(char.lower())
    franchise = extraction.get("franchise")
    if franchise:
        tags.add(franchise.lower())
    pin_type = extraction.get("pin_type")
    if pin_type:
        tags.add(pin_type.lower())
    event = extraction.get("event_clues")
    if event:
        tags.add(event.lower())
    tags.add("disney pin")
    return sorted(tags)

def _build_item_specifics(extraction: dict, catalog_match: dict | None) -> dict:
    specifics = {"Brand": "Disney"}
    characters = extraction.get("characters") or []
    if characters:
        specifics["Character"] = ", ".join(characters)
    franchise = extraction.get("franchise")
    if franchise:
        specifics["Franchise"] = franchise
    pin_type = extraction.get("pin_type")
    if pin_type:
        specifics["Type"] = pin_type
    edition = extraction.get("edition_size")
    if edition:
        specifics["Edition Size"] = str(edition)
    year = None
    if catalog_match and catalog_match.get("release_year"):
        year = catalog_match["release_year"]
    if year:
        specifics["Year"] = str(year)
    return specifics

def compute_pricing(comps: list[dict]) -> dict:
    valid_comps = [c for c in comps if not c.get("excluded") and c.get("listing_type") == "sold"]
    if not valid_comps:
        return {"suggested_price": None, "quick_sale_price": None, "price_confidence": "low", "comp_count": 0, "reasoning": "No valid sold comps found"}
    prices = sorted(c["price"] for c in valid_comps)
    low_price = round(prices[0], 2)
    high_price = prices[-1]
    comp_count = len(valid_comps)
    if comp_count >= 5:
        confidence = "high"
    elif comp_count >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    weighted = [c for c in valid_comps if c.get("weight", 0) > 0]
    if weighted:
        rec = weighted_price_recommendation(
            [{"price": c["price"], "weight": c["weight"]} for c in weighted]
        )
        suggested = round(rec["suggested_price"], 2) if rec["suggested_price"] is not None else None
        reasoning = (
            f"Based on {comp_count} sold comps (weighted by recency/relevance). "
            f"Range: ${low_price}-${high_price:.2f}, Weighted: ${suggested}"
        )
    else:
        suggested = round(statistics.median(prices), 2)
        reasoning = f"Based on {comp_count} sold comps. Range: ${low_price}-${high_price:.2f}, Median: ${suggested}"

    return {"suggested_price": suggested, "quick_sale_price": low_price, "price_confidence": confidence, "comp_count": comp_count, "reasoning": reasoning}
