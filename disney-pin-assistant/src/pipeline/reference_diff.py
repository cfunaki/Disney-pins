"""Per-field diff between a tool-side pin view and a parsed reference label.

Shared logic so that:
- server-side code (if ever added) can reuse the same rules, and
- the JS `renderReferenceLabel` in static/review.js can mirror the same
  field list without drifting.

Tested in tests/test_reference_diff.py; the JS side is a thin visual wrapper.
"""

from dataclasses import dataclass
from enum import Enum


class DiffStatus(str, Enum):
    AGREE = "agree"
    MISMATCH = "mismatch"
    ONE_SIDE_ONLY = "one_side_only"
    MUTED = "muted"


@dataclass(frozen=True)
class FieldDiff:
    field: str
    status: DiffStatus
    tool_value: object
    reference_value: object


# Bucket A (image-inferable) + Bucket B (catalog-derived) — graded.
GRADED_FIELDS: frozenset[str] = frozenset({
    "characters",
    "franchise",
    "canonical_name",
    "series_or_collection",
    "release_year",
    "edition_size",
    "is_limited_edition",
})

# Bucket C — rendered but noise.
UNGRADED_FIELDS: frozenset[str] = frozenset({
    "event",
    "pin_type",
    "exclusive_source",
})

ALL_FIELDS: tuple[str, ...] = tuple(GRADED_FIELDS | UNGRADED_FIELDS)


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)) and len(value) == 0:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def _norm_list(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(v).strip().lower() for v in value if str(v).strip()}


def _compare_characters(tool: object, reference: object) -> DiffStatus:
    return DiffStatus.AGREE if _norm_list(tool) == _norm_list(reference) else DiffStatus.MISMATCH


def _compare_string(tool: object, reference: object) -> DiffStatus:
    a = str(tool).strip().lower()
    b = str(reference).strip().lower()
    if a == b or a in b or b in a:
        return DiffStatus.AGREE
    return DiffStatus.MISMATCH


def _compare_exact(tool: object, reference: object) -> DiffStatus:
    return DiffStatus.AGREE if tool == reference else DiffStatus.MISMATCH


_COMPARATORS = {
    "characters": _compare_characters,
    "franchise": _compare_string,
    "canonical_name": _compare_string,
    "series_or_collection": _compare_string,
    "event": _compare_string,
    "pin_type": _compare_string,
    "exclusive_source": _compare_string,
    "release_year": _compare_exact,
    "edition_size": _compare_exact,
    "is_limited_edition": _compare_exact,
}


def diff_pin_fields(tool: dict, reference: dict) -> dict[str, FieldDiff]:
    """Return a per-field diff for every known field in ALL_FIELDS.

    `tool` is the flattened tool-side view (vision + matched catalog entry).
    `reference` is the parser output dict from `parse_listing_label`.
    """
    out: dict[str, FieldDiff] = {}
    for field in ALL_FIELDS:
        t = tool.get(field)
        r = reference.get(field)
        t_present = _present(t)
        r_present = _present(r)
        if not t_present and not r_present:
            status = DiffStatus.MUTED
        elif t_present != r_present:
            status = DiffStatus.ONE_SIDE_ONLY
        else:
            status = _COMPARATORS[field](t, r)
        out[field] = FieldDiff(field=field, status=status, tool_value=t, reference_value=r)
    return out
