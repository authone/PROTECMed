"""Fixed query catalogue, typed predicate validation and local counting (blueprint 3.4).

No SQL text, Python expression, regex predicate, ``eval``/``exec`` or dataframe query
is accepted anywhere in this path. A query must match an allowlisted catalogue entry
exactly, structurally and by canonical hash, before any clinical value is read.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any

from .canonical import ENUMS, FIELDS, AGE_MAX, AGE_MIN, MAX_ROWS, assert_canonical
from .errors import ImportRejected

QUERY_KEYS = {"schema_version", "query_id", "query_version", "logic",
              "filters", "missing_value_policy"}
PREDICATE_KEYS = {"field", "operator", "value"}
SCHEMA_VERSION = "2.0"
MAX_FILTERS = 5
CATALOGUE_IDS = tuple(f"Q{i:03d}" for i in range(1, 7))


def canonical_query_bytes(query: dict[str, Any]) -> bytes:
    """Deterministic bytes for hashing; the same encoding the protocol envelopes use."""
    return json.dumps(query, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def query_hash(query: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_query_bytes(query)).hexdigest()


def validate_query(query: Any) -> None:
    if type(query) is not dict or set(query) != QUERY_KEYS:
        raise ImportRejected("QUERY_FIELDS")
    if query["schema_version"] != SCHEMA_VERSION or query["logic"] != "AND":
        raise ImportRejected("QUERY_VERSION_OR_LOGIC")
    if type(query["query_version"]) is not int or query["query_version"] != 1:
        raise ImportRejected("QUERY_VERSION")
    if query["missing_value_policy"] != "exclude_required_missing":
        raise ImportRejected("MISSING_POLICY")
    if query["query_id"] not in CATALOGUE_IDS:
        raise ImportRejected("QUERY_ID")
    filters = query["filters"]
    if type(filters) is not list or len(filters) > MAX_FILTERS:
        raise ImportRejected("QUERY_FILTERS")
    # Empty filters are allowed only for Q001.
    if (query["query_id"] == "Q001") != (len(filters) == 0):
        raise ImportRejected("EMPTY_QUERY")
    seen: set[str] = set()
    for predicate in filters:
        _validate_predicate(predicate, seen)


def _validate_predicate(predicate: Any, seen: set[str]) -> None:
    if type(predicate) is not dict or set(predicate) != PREDICATE_KEYS:
        raise ImportRejected("PREDICATE_FIELDS")
    field, operator, value = predicate["field"], predicate["operator"], predicate["value"]
    if field not in FIELDS or field in seen:
        raise ImportRejected("PREDICATE_FIELD")
    seen.add(field)
    if field in ENUMS:
        if operator != "eq" or type(value) is not str or value not in ENUMS[field]:
            raise ImportRejected("ENUM_PREDICATE")
    elif field == "toxicity_wbc_ge2":
        # type(value) is bool, never isinstance: an int 1 must not pass a bool validator.
        if operator != "eq" or type(value) is not bool:
            raise ImportRejected("BOOL_PREDICATE")
    elif operator != "lt" or type(value) is not int or not AGE_MIN <= value <= AGE_MAX:
        raise ImportRejected("AGE_PREDICATE")


def load_catalogue(path: Path) -> list[dict[str, Any]]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if type(document) is not dict or document.get("schema_version") != SCHEMA_VERSION:
        raise ImportRejected("CATALOGUE_VERSION")
    queries = document.get("queries")
    if type(queries) is not list or len(queries) != len(CATALOGUE_IDS):
        raise ImportRejected("CATALOGUE_SIZE")
    for entry in queries:
        validate_query(entry)
    if [q["query_id"] for q in queries] != list(CATALOGUE_IDS):
        raise ImportRejected("CATALOGUE_IDS")
    return queries


def assert_catalogue_member(query: Any, catalogue: list[dict[str, Any]]) -> dict[str, Any]:
    """Structural validation first, then exact allowlist and hash equality."""
    validate_query(query)
    for entry in catalogue:
        validate_query(entry)
    wanted = query_hash(query)
    for entry in catalogue:
        # Compare hashes and structure: True == 1 in Python, so equality alone is unsafe.
        if query_hash(entry) == wanted and entry == query and _same_types(entry, query):
            return entry
    raise ImportRejected("QUERY_NOT_ALLOWLISTED")


def _same_types(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(_same_types(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(_same_types(a, b) for a, b in zip(left, right))
    return left == right


def count_query(rows: list[dict[str, Any]], query: dict[str, Any],
                catalogue: list[dict[str, Any]]) -> dict[str, int]:
    """Exact local count plus the per-query eligibility diagnostics (local only)."""
    assert_catalogue_member(query, catalogue)
    assert_canonical(rows)
    if len(rows) > MAX_ROWS:
        raise ImportRejected("LOCAL_ROW_LIMIT")
    filters = query["filters"]
    matches = eligible = 0
    for row in rows:
        # A row missing any field required by THIS query is excluded; unused fields do not matter.
        if any(row[predicate["field"]] is None for predicate in filters):
            continue
        eligible += 1
        if all(_holds(row, predicate) for predicate in filters):
            matches += 1
    return {"admitted": len(rows), "eligible": eligible,
            "excluded_missing": len(rows) - eligible, "count": matches}


def _holds(row: dict[str, Any], predicate: dict[str, Any]) -> bool:
    value, wanted = row[predicate["field"]], predicate["value"]
    if predicate["operator"] == "eq":
        return type(value) is type(wanted) and value == wanted
    return type(value) is int and type(wanted) is int and value < wanted


def query_report(rows: list[dict[str, Any]],
                 catalogue: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Local diagnostics for every catalogue entry. Never sent to the coordinator."""
    return {entry["query_id"]: count_query(rows, entry, catalogue) for entry in catalogue}
