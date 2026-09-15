"""Coordinator persistence (blueprint 4.7, 5.6).

SQLite with foreign keys, transactions and the unique constraints the protocol needs:
one artifact of each kind per (run, party), one request per run, one fusion receipt per
run. Compare-and-set is how a run changes state, so two concurrent requests cannot both
believe they advanced it.

No clinical row ever reaches this database. It stores run plans, epoch records,
submission metadata, requests, approvals, receipts and audit events; binaries live in a
restricted content-addressed directory.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    role            TEXT NOT NULL CHECK (role IN ('coordinator', 'party', 'recipient')),
    token_sha256    TEXT NOT NULL UNIQUE,
    -- Raw Ed25519 public key, enrolled out of band. The coordinator never holds a
    -- party identity private key and never holds an FHE share.
    public_key_hex  TEXT
);

CREATE TABLE IF NOT EXISTS studies (
    study_id      TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    study_id          TEXT NOT NULL REFERENCES studies(study_id),
    state             TEXT NOT NULL,
    plan_json         TEXT,
    plan_envelope     TEXT,
    plan_sha256       TEXT,
    context_sha256    TEXT,
    epoch_json        TEXT,
    epoch_envelope    TEXT,
    epoch_sha256      TEXT,
    input_set_json    TEXT,
    input_set_envelope TEXT,
    aggregate_sha256  TEXT,
    request_json      TEXT,
    request_envelope  TEXT,
    created_at        TEXT NOT NULL
);

-- One artifact of each kind per party per run. A retry of the same bytes is a no-op;
-- different bytes are a conflict, not a silent overwrite.
CREATE TABLE IF NOT EXISTS messages (
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    party_id      TEXT NOT NULL,
    kind          TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    received_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, party_id, kind)
);

CREATE TABLE IF NOT EXISTS artifacts (
    sha256     TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    kind       TEXT NOT NULL,
    size       INTEGER NOT NULL,
    stored_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    run_id       TEXT PRIMARY KEY REFERENCES runs(run_id),
    receipt_json TEXT NOT NULL,
    fused_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    agent_id        TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    route           TEXT NOT NULL,
    request_sha256  TEXT NOT NULL,
    response_json   TEXT NOT NULL,
    status_code     INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (agent_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT,
    agent_id   TEXT,
    event      TEXT NOT NULL,
    detail     TEXT,
    at         TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), isolation_level=None,
                                 check_same_thread=False, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """IMMEDIATE so a concurrent writer blocks instead of racing a read-modify-write."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def compare_and_set_state(connection: sqlite3.Connection, run_id: str,
                          expected: str, target: str) -> bool:
    """Advance a run only from the state the caller actually observed."""
    cursor = connection.execute(
        "UPDATE runs SET state = ? WHERE run_id = ? AND state = ?",
        (target, run_id, expected))
    return cursor.rowcount == 1


def record_audit(connection: sqlite3.Connection, *, run_id: str | None,
                 agent_id: str | None, event: str, detail: dict[str, Any] | None,
                 at: str) -> None:
    """Allowlisted fields only. Never a request body, a count or key material."""
    connection.execute(
        "INSERT INTO audit (run_id, agent_id, event, detail, at) VALUES (?, ?, ?, ?, ?)",
        (run_id, agent_id, event, json.dumps(detail or {}, sort_keys=True), at))
