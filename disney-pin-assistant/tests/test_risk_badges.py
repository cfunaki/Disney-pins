from src.pipeline.risk_badges import classify_pin_risk


def _pin(**kwargs):
    return {
        "status": "matched",
        "no_catalog_match": False,
        "extraction": {"confidence_score": 0.9},
        "catalog_matches": [
            {"match_confidence": 0.92, "rank": 1},
            {"match_confidence": 0.55, "rank": 2},
        ],
        **kwargs,
    }


def test_ready_when_high_confidence_and_clear_winner():
    assert classify_pin_risk(_pin()) == "ready"


def test_no_match_when_no_candidates():
    assert classify_pin_risk(_pin(catalog_matches=[])) == "no_match"


def test_no_match_when_user_marked_no_catalog_match():
    assert classify_pin_risk(_pin(no_catalog_match=True)) == "no_match"


def test_ambiguous_when_top_score_below_0_9():
    assert classify_pin_risk(_pin(catalog_matches=[
        {"match_confidence": 0.85, "rank": 1},
        {"match_confidence": 0.40, "rank": 2},
    ])) == "ambiguous_match"


def test_ambiguous_when_top_two_within_0_1():
    assert classify_pin_risk(_pin(catalog_matches=[
        {"match_confidence": 0.95, "rank": 1},
        {"match_confidence": 0.88, "rank": 2},
    ])) == "ambiguous_match"


def test_low_extraction_when_extraction_confidence_below_0_6():
    assert classify_pin_risk(_pin(extraction={"confidence_score": 0.4})) == "low_extraction"


def test_severity_no_match_beats_ambiguous():
    assert classify_pin_risk(_pin(catalog_matches=[], extraction={"confidence_score": 0.4})) == "no_match"


def test_severity_ambiguous_beats_low_extraction():
    pin = _pin(
        extraction={"confidence_score": 0.4},
        catalog_matches=[
            {"match_confidence": 0.85, "rank": 1},
            {"match_confidence": 0.40, "rank": 2},
        ],
    )
    assert classify_pin_risk(pin) == "ambiguous_match"


def test_approved_status_overrides_other_signals():
    assert classify_pin_risk(_pin(status="approved")) == "approved"


def test_exported_status_overrides_other_signals():
    assert classify_pin_risk(_pin(status="exported")) == "exported"
