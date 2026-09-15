"""Canonical five-field projection and strict value normalization (blueprint 3.3).

Production party-agent implementation. It is deliberately independent of
``reference/python/cohort.py``: the reference kit stays frozen under its own
verification ledger, and ``tests/unit/test_canonical_equivalence.py`` asserts the
two agree on the synthetic fixture.

No value from a rejected cell is ever returned, logged or embedded in an error.
"""
from __future__ import annotations
import math
import unicodedata
from typing import Any, Iterable

FIELDS = ("diagnosis", "rt_technique", "toxicity_wbc_ge2", "age_at_rt", "surgery_type")
ENUMS = {
    "diagnosis": {"MBL", "PNET", "GLIOMA", "HAEMA", "ICGCT", "PINEAL TUMOR", "EPD"},
    "rt_technique": {"3DCRT", "IMRT"},
    "surgery_type": {"GTR", "STR", "INOP", "BIOPSIE"},
}
MISSING_TOKENS = {"", "NA", "N/A", "NULL"}
TRUE_TOKENS = {"YES", "DA", "TRUE", "1"}
FALSE_TOKENS = {"NO", "NU", "FALSE", "0"}
AGE_MIN, AGE_MAX = 0, 120
MAX_ROWS = 10000

from .errors import ImportRejected, ValidationFailed


def normalized_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value)).strip().upper()


def header_key(value: Any) -> str:
    """Headers are matched Unicode-normalized and trimmed, case sensitively."""
    return unicodedata.normalize("NFKC", "" if value is None else str(value)).strip()


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    # bool is an int subtype; an actual boolean is never a missing token.
    if type(value) is bool:
        return False
    return isinstance(value, str) and normalized_text(value) in MISSING_TOKENS


def is_raw_blank(value: Any) -> bool:
    """Blank for record admission. Explicit NA/NULL tokens are NOT blank."""
    if value is None:
        return True
    if type(value) is bool:
        return False
    return isinstance(value, str) and value.strip() == ""


def normalize(field: str, value: Any) -> str | int | bool | None:
    """Return the canonical value or raise ImportRejected with a symbolic token."""
    if field not in FIELDS:
        raise ImportRejected("UNKNOWN_FIELD")
    if is_missing(value):
        return None
    if field in ENUMS:
        if not isinstance(value, str):
            raise ImportRejected("INVALID_ENUM_TYPE")
        token = normalized_text(value)
        if token not in ENUMS[field]:
            raise ImportRejected("UNKNOWN_ENUM_VALUE")
        return token
    if field == "toxicity_wbc_ge2":
        return _normalize_boolean(value)
    return _normalize_age(value)


def _normalize_boolean(value: Any) -> bool:
    # bool(cell) must never be used: bool("NO") is True in Python.
    if type(value) is bool:
        return value
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        if value == 0:
            return False
        if value == 1:
            return True
        raise ImportRejected("INVALID_BOOLEAN_NUMERIC")
    if isinstance(value, str):
        token = normalized_text(value)
        if token in TRUE_TOKENS:
            return True
        if token in FALSE_TOKENS:
            return False
    raise ImportRejected("INVALID_BOOLEAN")


def _normalize_age(value: Any) -> int:
    if type(value) is bool:
        raise ImportRejected("BOOLEAN_IS_NOT_AGE")
    if type(value) is int:
        age = value
    elif type(value) is float:
        if not math.isfinite(value) or not value.is_integer():
            raise ImportRejected("AGE_NOT_INTEGER")
        age = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not (text.isascii() and text.isdigit()):
            raise ImportRejected("INVALID_AGE_TYPE")
        age = int(text)
    else:
        raise ImportRejected("INVALID_AGE_TYPE")
    if not AGE_MIN <= age <= AGE_MAX:
        raise ImportRejected("AGE_OUT_OF_RANGE")
    return age


def empty_field_report() -> dict[str, dict[str, Any]]:
    return {f: {"missing": 0, "invalid": 0, "invalid_codes": {}, "invalid_rows": []}
            for f in FIELDS}


def project_raw_rows(raw_rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Admit rows, normalize the five selected fields and build the local report.

    Admission: at least one of the five raw selected cells is nonblank. Rows whose
    five selected cells are all blank are skipped and counted, never normalized.
    Any invalid value fails the import closed; the report records the row index and
    symbolic code only, never the offending value.
    """
    records: list[dict[str, Any]] = []
    per_field = empty_field_report()
    skipped_blank = 0
    for raw in raw_rows:
        if set(raw) != set(FIELDS):
            raise ImportRejected("PROJECTION_FIELDS_MISMATCH")
        if all(is_raw_blank(raw[f]) for f in FIELDS):
            skipped_blank += 1
            continue
        index = len(records)
        record: dict[str, Any] = {}
        for field in FIELDS:
            try:
                value = normalize(field, raw[field])
            except ImportRejected as error:
                stats = per_field[field]
                stats["invalid"] += 1
                stats["invalid_codes"][error.token] = stats["invalid_codes"].get(error.token, 0) + 1
                if len(stats["invalid_rows"]) < 50:
                    stats["invalid_rows"].append(index)
                record[field] = None
                continue
            if value is None:
                per_field[field]["missing"] += 1
            record[field] = value
        records.append(record)
        if len(records) > MAX_ROWS:
            raise ImportRejected("LOCAL_ROW_LIMIT")
    report = {
        "admitted_rows": len(records),
        "skipped_blank_rows": skipped_blank,
        "fields": per_field,
        "invalid_values_total": sum(s["invalid"] for s in per_field.values()),
    }
    if report["invalid_values_total"]:
        raise ValidationFailed(report)
    return records, report


def assert_canonical(rows: list[dict[str, Any]]) -> None:
    """Reject an already-canonical table whose values are not exactly canonical."""
    if len(rows) > MAX_ROWS:
        raise ImportRejected("LOCAL_ROW_LIMIT")
    for row in rows:
        if set(row) != set(FIELDS):
            raise ImportRejected("CANONICAL_FIELDS")
        for field in FIELDS:
            value = row[field]
            if value is None:
                continue
            normalized = normalize(field, value)
            if type(normalized) is not type(value) or normalized != value:
                raise ImportRejected("NONCANONICAL_VALUE")
