from datetime import date
import math
from src.pipeline.comp_scoring import (
    field_overlap_score,
    recency_weight,
    score_comp,
    weighted_price_recommendation,
)


def test_field_overlap_character_match():
    pin = {"characters": ["Stitch"]}
    comp = {"characters": ["Stitch"]}
    assert field_overlap_score(pin, comp) == 0.4


def test_field_overlap_character_case_insensitive():
    pin = {"characters": ["STITCH"]}
    comp = {"characters": ["stitch"]}
    assert field_overlap_score(pin, comp) == 0.4


def test_field_overlap_franchise():
    pin = {"franchise": "Lilo & Stitch"}
    comp = {"franchise": "Lilo & Stitch"}
    assert field_overlap_score(pin, comp) == 0.3


def test_field_overlap_edition_size_exact():
    pin = {"edition_size": 2000}
    comp = {"edition_size": 2000}
    assert field_overlap_score(pin, comp) == 0.2


def test_field_overlap_edition_size_mismatch():
    pin = {"edition_size": 2000}
    comp = {"edition_size": 1000}
    assert field_overlap_score(pin, comp) == 0.0


def test_field_overlap_year_within_one():
    pin = {"release_year": 2019}
    comp = {"release_year": 2020}
    assert field_overlap_score(pin, comp) == 0.1


def test_field_overlap_year_outside_one():
    pin = {"release_year": 2015}
    comp = {"release_year": 2020}
    assert field_overlap_score(pin, comp) == 0.0


def test_field_overlap_all_fields_sum():
    pin = {"characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000, "release_year": 2019}
    comp = {"characters": ["Stitch"], "franchise": "Lilo & Stitch", "edition_size": 2000, "release_year": 2019}
    assert field_overlap_score(pin, comp) == 1.0


def test_field_overlap_empty():
    assert field_overlap_score({}, {}) == 0.0


def test_recency_weight_today():
    assert recency_weight(date(2026, 4, 12), date(2026, 4, 12), half_life_days=90) == 1.0


def test_recency_weight_half_life():
    w = recency_weight(date(2026, 1, 12), date(2026, 4, 12), half_life_days=90)
    assert abs(w - 0.5) < 0.01


def test_recency_weight_future_sale_clamped():
    w = recency_weight(date(2026, 5, 1), date(2026, 4, 12), half_life_days=90)
    assert w == 1.0


def test_score_comp_combines_relevance_and_recency():
    pin = {"characters": ["Stitch"]}
    comp = {"characters": ["Stitch"]}
    s = score_comp(pin, comp, sale_date=date(2026, 1, 12), today=date(2026, 4, 12), half_life_days=90)
    assert abs(s - 0.4 * 0.5) < 0.01


def test_weighted_price_recommendation_basic():
    comps = [
        {"price": 10.0, "weight": 1.0},
        {"price": 20.0, "weight": 1.0},
    ]
    result = weighted_price_recommendation(comps)
    assert result["suggested_price"] == 15.0
    assert result["count"] == 2


def test_weighted_price_recommendation_weights_bias():
    comps = [
        {"price": 10.0, "weight": 3.0},
        {"price": 20.0, "weight": 1.0},
    ]
    result = weighted_price_recommendation(comps)
    assert abs(result["suggested_price"] - 12.5) < 0.01


def test_weighted_price_recommendation_empty():
    result = weighted_price_recommendation([])
    assert result["suggested_price"] is None
    assert result["count"] == 0
