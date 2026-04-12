from src.pipeline.reference_diff import (
    DiffStatus, diff_pin_fields, GRADED_FIELDS, UNGRADED_FIELDS,
)


def _base_tool():
    return {
        "characters": ["Lilo", "Stitch"],
        "franchise": "Classic Disney",
        "canonical_name": None,
        "series_or_collection": None,
        "release_year": None,
        "edition_size": None,
        "event": None,
        "pin_type": None,
        "exclusive_source": None,
        "is_limited_edition": None,
    }


def test_character_sets_agree_when_equal():
    ref = {"characters": ["stitch", "lilo"]}
    diff = diff_pin_fields(tool=_base_tool(), reference=ref)
    assert diff["characters"].status is DiffStatus.AGREE


def test_character_sets_disagree_on_partial_overlap():
    ref = {"characters": ["Lilo"]}
    diff = diff_pin_fields(tool=_base_tool(), reference=ref)
    assert diff["characters"].status is DiffStatus.MISMATCH


def test_string_substring_either_direction_agrees():
    tool = _base_tool()
    tool["series_or_collection"] = "Hidden Mickey 2023 Series 1"
    ref = {"series_or_collection": "Hidden Mickey"}
    diff = diff_pin_fields(tool=tool, reference=ref)
    assert diff["series_or_collection"].status is DiffStatus.AGREE


def test_string_no_overlap_mismatches():
    tool = _base_tool()
    tool["franchise"] = "Star Wars"
    ref = {"franchise": "Classic Disney"}
    diff = diff_pin_fields(tool=tool, reference=ref)
    assert diff["franchise"].status is DiffStatus.MISMATCH


def test_numeric_exact_equality():
    tool = _base_tool()
    tool["release_year"] = 2019
    ref = {"release_year": 2019}
    diff = diff_pin_fields(tool=tool, reference=ref)
    assert diff["release_year"].status is DiffStatus.AGREE

    ref2 = {"release_year": 2020}
    diff2 = diff_pin_fields(tool=tool, reference=ref2)
    assert diff2["release_year"].status is DiffStatus.MISMATCH


def test_one_side_only_when_tool_has_and_reference_missing():
    tool = _base_tool()
    tool["edition_size"] = 2000
    diff = diff_pin_fields(tool=tool, reference={})
    assert diff["edition_size"].status is DiffStatus.ONE_SIDE_ONLY


def test_muted_when_neither_side_present():
    diff = diff_pin_fields(tool=_base_tool(), reference={})
    assert diff["event"].status is DiffStatus.MUTED


def test_graded_fields_excludes_bucket_c():
    assert "canonical_name" in GRADED_FIELDS
    assert "characters" in GRADED_FIELDS
    assert "event" in UNGRADED_FIELDS
    assert "pin_type" in UNGRADED_FIELDS
    assert "exclusive_source" in UNGRADED_FIELDS
    assert not (GRADED_FIELDS & UNGRADED_FIELDS)
