"""Synthetic/reference cohort semantics; not a clinical web-upload implementation."""
from __future__ import annotations
import csv
import json
import math
import unicodedata
from pathlib import Path
from typing import Any, Iterable

FIELDS = ("diagnosis", "rt_technique", "toxicity_wbc_ge2", "age_at_rt", "surgery_type")
ENUMS = {
    "diagnosis": {"MBL", "PNET", "GLIOMA", "HAEMA", "ICGCT", "PINEAL TUMOR", "EPD"},
    "rt_technique": {"3DCRT", "IMRT"},
    "surgery_type": {"GTR", "STR", "INOP", "BIOPSIE"},
}
MISSING = {"", "NA", "N/A", "NULL"}
MAX_ROWS = 10000


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().upper()


def normalize(field: str, value: Any) -> str | int | bool | None:
    if field not in FIELDS:
        raise ValueError("UNKNOWN_FIELD")
    if value is None or (isinstance(value, str) and normalized_text(value) in MISSING):
        return None
    if field in ENUMS:
        if not isinstance(value, str):
            raise ValueError("INVALID_ENUM_TYPE")
        result = normalized_text(value)
        if result not in ENUMS[field]:
            raise ValueError("UNKNOWN_ENUM_VALUE")
        return result
    if field == "toxicity_wbc_ge2":
        if type(value) is bool:
            return value
        if type(value) in (int, float) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            token = normalized_text(value)
            if token in {"YES", "DA", "TRUE", "1"}:
                return True
            if token in {"NO", "NU", "FALSE", "0"}:
                return False
        raise ValueError("INVALID_BOOLEAN")
    if type(value) is bool:
        raise ValueError("BOOLEAN_IS_NOT_AGE")
    if type(value) is int:
        age = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        age = int(value)
    elif isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        age = int(value.strip())
    else:
        raise ValueError("INVALID_AGE_TYPE")
    if not 0 <= age <= 120:
        raise ValueError("AGE_OUT_OF_RANGE")
    return age


def is_raw_blank(value: Any) -> bool:
    # Explicit NA tokens are NOT blank for record admission.
    return value is None or (isinstance(value, str) and value.strip() == "")


def project_raw_rows(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    result, skipped = [], 0
    for raw in rows:
        if set(raw) != set(FIELDS):
            raise ValueError("PROJECTION_FIELDS_MISMATCH")
        if all(is_raw_blank(raw[f]) for f in FIELDS):
            skipped += 1
            continue
        result.append({f: normalize(f, raw[f]) for f in FIELDS})
        if len(result) > MAX_ROWS:
            raise ValueError("LOCAL_ROW_LIMIT")
    return result, skipped


def read_canonical_csv(path: Path) -> list[dict[str, Any]]:
    """Every record is already admitted; preserve an all-null canonical record."""
    result = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        if next(reader, None) != list(FIELDS):
            raise ValueError("CANONICAL_HEADER_MISMATCH")
        for cells in reader:
            if len(cells) != len(FIELDS):
                raise ValueError("CANONICAL_ROW_WIDTH")
            result.append({f: normalize(f, v) for f, v in zip(FIELDS, cells)})
            if len(result) > MAX_ROWS:
                raise ValueError("LOCAL_ROW_LIMIT")
    return result


def validate_query(query: Any) -> None:
    if type(query) is not dict or set(query) != {
        "schema_version", "query_id", "query_version", "logic", "filters", "missing_value_policy"
    }:
        raise ValueError("QUERY_FIELDS")
    if query["schema_version"] != "2.0" or query["logic"] != "AND":
        raise ValueError("QUERY_VERSION_OR_LOGIC")
    if type(query["query_version"]) is not int or query["query_version"] != 1:
        raise ValueError("QUERY_VERSION")
    if query["missing_value_policy"] != "exclude_required_missing":
        raise ValueError("MISSING_POLICY")
    qid = query["query_id"]
    if qid not in {f"Q{i:03d}" for i in range(1, 7)}:
        raise ValueError("QUERY_ID")
    filters = query["filters"]
    if type(filters) is not list or len(filters) > 5:
        raise ValueError("QUERY_FILTERS")
    if (qid == "Q001") != (len(filters) == 0):
        raise ValueError("EMPTY_QUERY")
    seen = set()
    for predicate in filters:
        if type(predicate) is not dict or set(predicate) != {"field", "operator", "value"}:
            raise ValueError("PREDICATE_FIELDS")
        field, op, value = predicate["field"], predicate["operator"], predicate["value"]
        if field not in FIELDS or field in seen:
            raise ValueError("PREDICATE_FIELD")
        seen.add(field)
        if field in ENUMS:
            if op != "eq" or type(value) is not str or value not in ENUMS[field]:
                raise ValueError("ENUM_PREDICATE")
        elif field == "toxicity_wbc_ge2":
            if op != "eq" or type(value) is not bool:
                raise ValueError("BOOL_PREDICATE")
        elif op != "lt" or type(value) is not int or not 0 <= value <= 120:
            raise ValueError("AGE_PREDICATE")


def assert_catalogue_member(query: Any, catalogue: list[dict[str, Any]]) -> None:
    validate_query(query)
    # Typed query validation precedes comparison (True == 1 in Python).
    for item in catalogue:
        validate_query(item)
    if not any(query == item for item in catalogue):
        raise ValueError("QUERY_NOT_ALLOWLISTED")


def count_query(rows: list[dict[str, Any]], query: dict[str, Any],
                catalogue: list[dict[str, Any]]) -> dict[str, int]:
    assert_catalogue_member(query, catalogue)
    if len(rows) > MAX_ROWS:
        raise ValueError("LOCAL_ROW_LIMIT")
    matches = eligible = 0
    for row in rows:
        if set(row) != set(FIELDS):
            raise ValueError("CANONICAL_FIELDS")
        # Reject incorrectly typed 'canonical' values rather than silently coercing them.
        for field in FIELDS:
            normalized = normalize(field, row[field])
            if type(normalized) is not type(row[field]) or normalized != row[field]:
                raise ValueError("NONCANONICAL_VALUE")
        filters = query["filters"]
        if any(row[p["field"]] is None for p in filters):
            continue
        eligible += 1
        if all((row[p["field"]] == p["value"] if p["operator"] == "eq"
                else row[p["field"]] < p["value"]) for p in filters):
            matches += 1
    return {"admitted": len(rows), "eligible": eligible,
            "excluded_missing": len(rows) - eligible, "count": matches}


def split_rows(rows: list[dict[str, Any]], parties: int) -> list[list[dict[str, Any]]]:
    if type(parties) is not int or parties not in (2, 3):
        raise ValueError("PARTY_COUNT")
    return [rows[i::parties] for i in range(parties)]


def summarize(rows: list[dict[str, Any]], catalogue: list[dict[str, Any]]) -> dict[str, Any]:
    answer = {}
    for q in catalogue:
        total = count_query(rows, q, catalogue)["count"]
        answer[q["query_id"]] = {
            "total": total,
            "two_parties": [count_query(r, q, catalogue)["count"] for r in split_rows(rows, 2)],
            "three_parties": [count_query(r, q, catalogue)["count"] for r in split_rows(rows, 3)],
        }
    return answer


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Offline synthetic/reference counts; no FHE.")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--catalogue", type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalogue.read_text(encoding="utf-8"))["queries"]
    print(json.dumps(summarize(read_canonical_csv(args.csv), catalog), indent=2))
