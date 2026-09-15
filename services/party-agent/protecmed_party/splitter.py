"""Demo splitter for the synthetic single-host simulation only (blueprint 3.5).

In a real deployment each institution already holds its own distinct dataset. This
splitter exists to build a reproducible demonstration from one authorized local file and
every output it produces must be labelled a simulation. It runs on an authorized local
machine, never at the coordinator, and it never reports row indices centrally.
"""
from __future__ import annotations
import csv
from pathlib import Path
from typing import Any

from .canonical import FIELDS, assert_canonical
from .errors import ImportRejected

SIMULATION_LABEL = "SIMULATED_SPLIT_OF_ONE_LOCAL_SOURCE_NOT_INDEPENDENT_INSTITUTIONS"


def split_rows(records: list[dict[str, Any]], parties: int) -> list[list[dict[str, Any]]]:
    """Admitted row j goes to provider j % parties, preserving order within each shard."""
    if type(parties) is not int or parties not in (2, 3):
        raise ImportRejected("PARTY_COUNT")
    assert_canonical(records)
    shards = [records[index::parties] for index in range(parties)]
    _assert_disjoint_and_complete(len(records), parties, shards)
    return shards


def _assert_disjoint_and_complete(total: int, parties: int,
                                  shards: list[list[dict[str, Any]]]) -> None:
    """Local index check proving coverage and disjointness. Indices never leave here."""
    covered: set[int] = set()
    for offset in range(parties):
        indices = set(range(offset, total, parties))
        if covered & indices:
            raise ImportRejected("SPLIT_NOT_DISJOINT")
        if len(indices) != len(shards[offset]):
            raise ImportRejected("SPLIT_SHARD_SIZE")
        covered |= indices
    if covered != set(range(total)):
        raise ImportRejected("SPLIT_NOT_COMPLETE")


def write_shards(shards: list[list[dict[str, Any]]], directory: Path,
                 prefix: str = "shard") -> list[Path]:
    """Write the five canonical columns only, in fixed order. No identifier column."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for index, shard in enumerate(shards):
        path = directory / f"{prefix}-{index + 1}-of-{len(shards)}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(FIELDS)
            for row in shard:
                writer.writerow(["" if row[f] is None else _cell(row[f]) for f in FIELDS])
        written.append(path)
    return written


def _cell(value: Any) -> str:
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    return str(value)
