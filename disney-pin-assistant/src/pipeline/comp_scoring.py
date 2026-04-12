"""Pure scoring functions for per-pin sold-data comps. No I/O."""

from datetime import date
import math

CHARACTER_WEIGHT = 0.4
FRANCHISE_WEIGHT = 0.3
EDITION_WEIGHT = 0.2
YEAR_WEIGHT = 0.1


def _normalize_chars(v) -> set[str]:
    if v is None:
        return set()
    if isinstance(v, str):
        v = [v]
    return {str(x).strip().lower() for x in v if x}


def _normalize_str(v) -> str:
    return str(v).strip().lower() if v else ""


def field_overlap_score(pin_fields: dict, comp_fields: dict) -> float:
    """Return a relevance score in [0, 1] based on overlap of parsed fields."""
    score = 0.0

    pin_chars = _normalize_chars(pin_fields.get("characters"))
    comp_chars = _normalize_chars(comp_fields.get("characters"))
    if pin_chars and comp_chars and pin_chars & comp_chars:
        score += CHARACTER_WEIGHT

    pin_fr = _normalize_str(pin_fields.get("franchise"))
    comp_fr = _normalize_str(comp_fields.get("franchise"))
    if pin_fr and pin_fr == comp_fr:
        score += FRANCHISE_WEIGHT

    pin_ed = pin_fields.get("edition_size")
    comp_ed = comp_fields.get("edition_size")
    if pin_ed is not None and comp_ed is not None and pin_ed == comp_ed:
        score += EDITION_WEIGHT

    pin_yr = pin_fields.get("release_year")
    comp_yr = comp_fields.get("release_year")
    if pin_yr is not None and comp_yr is not None and abs(pin_yr - comp_yr) <= 1:
        score += YEAR_WEIGHT

    return round(score, 10)


def recency_weight(sale_date: date, today: date, half_life_days: int) -> float:
    """Exponential decay weight based on how old the sale is.

    Uses the conventional half-life formula: at days = half_life_days,
    the weight is exactly 0.5. Future sale dates are clamped to 1.0.
    """
    days_old = max(0, (today - sale_date).days)
    return math.exp(-days_old * math.log(2) / half_life_days)


def score_comp(
    pin_fields: dict,
    comp_fields: dict,
    sale_date: date,
    today: date,
    half_life_days: int,
) -> float:
    """Combined relevance × recency score."""
    return field_overlap_score(pin_fields, comp_fields) * recency_weight(
        sale_date, today, half_life_days
    )


def weighted_price_recommendation(comps: list[dict]) -> dict:
    """Compute weighted-average price from scored comps.

    Args:
        comps: list of {"price": float, "weight": float}
    Returns:
        {"suggested_price": float | None, "count": int}
    """
    if not comps:
        return {"suggested_price": None, "count": 0}
    total_weight = sum(c["weight"] for c in comps)
    if total_weight == 0:
        return {"suggested_price": None, "count": len(comps)}
    weighted_sum = sum(c["price"] * c["weight"] for c in comps)
    return {
        "suggested_price": weighted_sum / total_weight,
        "count": len(comps),
    }
