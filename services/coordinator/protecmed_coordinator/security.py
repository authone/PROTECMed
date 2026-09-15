"""Authentication, authorization and idempotency for the coordinator API (4.8, 5.4).

Every POST needs an authenticated identity, a purpose-specific role and an idempotency
key. Tokens are generated on this endpoint at runtime and only their SHA-256 is stored;
they never appear in a log, a URL or an error body.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

MAX_JSON_BYTES = 64 * 1024          # blueprint 5.6
MAX_BINARY_BYTES = 16 * 1024**2     # provisional, measured against M2 artifacts
IDEMPOTENCY_HEADER = "idempotency-key"


@dataclass(frozen=True)
class Agent:
    agent_id: str
    role: str


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def provision_agent(connection: sqlite3.Connection, agent_id: str, role: str, *,
                    public_key_hex: str | None = None) -> str:
    """Create an agent and return its bearer token once. Never stored in plaintext."""
    token = secrets.token_urlsafe(32)
    connection.execute(
        "INSERT INTO agents (agent_id, role, token_sha256, public_key_hex) "
        "VALUES (?, ?, ?, ?)", (agent_id, role, token_digest(token), public_key_hex))
    return token


def authenticate(connection: sqlite3.Connection, request: Request) -> Agent:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="UNAUTHENTICATED")
    digest = token_digest(token)
    rows = connection.execute(
        "SELECT agent_id, role, token_sha256 FROM agents").fetchall()
    for row in rows:
        # Constant-time compare so a token cannot be probed by timing.
        if hmac.compare_digest(row["token_sha256"], digest):
            return Agent(row["agent_id"], row["role"])
    raise HTTPException(status_code=401, detail="UNAUTHENTICATED")


def require_role(agent: Agent, *roles: str) -> None:
    if agent.role not in roles:
        raise HTTPException(status_code=403, detail="FORBIDDEN")


def require_self(agent: Agent, claimed: str) -> None:
    """An authenticated party may only act as itself."""
    if agent.agent_id != claimed:
        raise HTTPException(status_code=403, detail="SIGNER_IS_NOT_CALLER")


async def read_json_body(request: Request) -> tuple[dict[str, Any], bytes]:
    raw = await request.body()
    if len(raw) > MAX_JSON_BYTES:
        raise HTTPException(status_code=413, detail="JSON_TOO_LARGE")
    from protecmed_protocol.canonical import parse_json
    from protecmed_protocol.errors import ProtocolError
    try:
        document = parse_json(raw)
    except ProtocolError as error:
        raise HTTPException(status_code=400, detail=error.token) from None
    if type(document) is not dict:
        raise HTTPException(status_code=400, detail="JSON_OBJECT_REQUIRED")
    return document, raw


def idempotency_key(request: Request) -> str:
    key = request.headers.get(IDEMPOTENCY_HEADER, "")
    if not (8 <= len(key) <= 128) or not all(
            c.isalnum() or c in "-_" for c in key):
        raise HTTPException(status_code=400, detail="IDEMPOTENCY_KEY_REQUIRED")
    return key


def replay(connection: sqlite3.Connection, agent: Agent, key: str, route: str,
           body: bytes) -> tuple[int, dict[str, Any]] | None:
    """Return the stored response for a byte-identical retry; 409 on a reused key."""
    row = connection.execute(
        "SELECT route, request_sha256, response_json, status_code FROM idempotency "
        "WHERE agent_id = ? AND idempotency_key = ?", (agent.agent_id, key)).fetchone()
    if row is None:
        return None
    if row["route"] != route or row["request_sha256"] != hashlib.sha256(body).hexdigest():
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_KEY_REUSED")
    return row["status_code"], json.loads(row["response_json"])


def remember(connection: sqlite3.Connection, agent: Agent, key: str, route: str,
             body: bytes, status_code: int, response: dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO idempotency (agent_id, idempotency_key, route, request_sha256, "
        "response_json, status_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (agent.agent_id, key, route, hashlib.sha256(body).hexdigest(),
         json.dumps(response, sort_keys=True), status_code, now_utc()))
