"""Classify a pin into a single user-facing risk badge."""

AMBIGUOUS_TOP_SCORE_THRESHOLD = 0.9
AMBIGUOUS_GAP_THRESHOLD = 0.1
LOW_EXTRACTION_THRESHOLD = 0.6


def classify_pin_risk(pin: dict) -> str:
    """Return one of: ready, ambiguous_match, low_extraction, no_match, approved, exported.

    `pin` is the dict produced by `_pin_to_dict` in src/routes/pins.py.
    Severity order (highest first): exported, approved, no_match, ambiguous_match, low_extraction, ready.
    """
    status = pin.get("status")
    if status == "exported":
        return "exported"
    if status == "approved":
        return "approved"

    if pin.get("no_catalog_match"):
        return "no_match"

    matches = pin.get("catalog_matches") or []
    if not matches:
        return "no_match"

    sorted_matches = sorted(matches, key=lambda m: m.get("match_confidence", 0), reverse=True)
    top = sorted_matches[0].get("match_confidence", 0)
    second = sorted_matches[1].get("match_confidence", 0) if len(sorted_matches) > 1 else 0

    if top < AMBIGUOUS_TOP_SCORE_THRESHOLD or (top - second) < AMBIGUOUS_GAP_THRESHOLD:
        return "ambiguous_match"

    extraction = pin.get("extraction") or {}
    if extraction.get("confidence_score", 1.0) < LOW_EXTRACTION_THRESHOLD:
        return "low_extraction"

    return "ready"
