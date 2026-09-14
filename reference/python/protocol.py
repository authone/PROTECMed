"""Reference byte/signature and partial-set checks; NOT the full production gate.
Does not verify OpenFHE structures, aggregate computation, consent UI, state,
input sets, key ceremonies or disclosure ledgers. Call only after those checks.
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

HASH = re.compile(r"^[0-9a-f]{64}$")
DOMAIN = b"PROTECMed/v2/"
MAX_SAFE = 2**53 - 1


def _validate(value: Any, depth: int = 0) -> None:
    if depth > 16:
        raise ValueError("JSON_DEPTH")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > MAX_SAFE:
            raise ValueError("JSON_INTEGER_RANGE")
        return
    if type(value) is str:
        if not value.isascii():
            raise ValueError("JSON_ASCII_ONLY")
        return
    if type(value) is list:
        for item in value:
            _validate(item, depth + 1)
        return
    if type(value) is dict:
        if any(type(k) is not str or not k.isascii() for k in value):
            raise ValueError("JSON_KEY")
        for item in value.values():
            _validate(item, depth + 1)
        return
    raise ValueError("JSON_UNSUPPORTED_TYPE")


def canonical_bytes(value: Any) -> bytes:
    _validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def parse_json(raw: bytes) -> Any:
    if len(raw) > 65536:
        raise ValueError("JSON_SIZE")
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("JSON_DUPLICATE_KEY")
            result[k] = v
        return result
    def reject_constant(_):
        raise ValueError("JSON_CONSTANT")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                       parse_constant=reject_constant)
    _validate(value)
    return value


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def payload_hash(payload: Any) -> str:
    return sha256(canonical_bytes(payload))


def sign(payload: dict, signer: str, purpose: str,
         private_key: Ed25519PrivateKey) -> dict:
    body = {"signer_id": signer, "purpose": purpose, "payload": payload}
    signature = private_key.sign(DOMAIN + canonical_bytes(body))
    return {**body, "signature_b64": base64.b64encode(signature).decode("ascii")}


def verify(envelope: dict, expected_purpose: str,
           pinned_keys: Mapping[str, Ed25519PublicKey]) -> dict:
    if type(envelope) is not dict or set(envelope) != {
        "signer_id", "purpose", "payload", "signature_b64"
    }:
        raise ValueError("ENVELOPE_FIELDS")
    canonical_bytes(envelope)
    signer = envelope["signer_id"]
    if type(signer) is not str or signer not in pinned_keys:
        raise ValueError("UNKNOWN_SIGNER")
    if envelope["purpose"] != expected_purpose:
        raise ValueError("WRONG_PURPOSE")
    sig = envelope["signature_b64"]
    if type(sig) is not str:
        raise ValueError("SIGNATURE_TYPE")
    signature = base64.b64decode(sig, validate=True)
    if len(signature) != 64:
        raise ValueError("SIGNATURE_LENGTH")
    body = {k: envelope[k] for k in ("signer_id", "purpose", "payload")}
    pinned_keys[signer].verify(signature, DOMAIN + canonical_bytes(body))
    return envelope["payload"]


def utc_time(value: str) -> datetime:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("UTC_FORMAT")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def gate_partials(request: dict, envelopes: list[dict], artifacts: Mapping[str, bytes],
                  pinned_keys: Mapping[str, Ed25519PublicKey], now: datetime) -> list[bytes]:
    """Narrow structural/signature guard; caller supplies a locally verified request.
    Production must additionally enforce Section 4.5 transaction/state/consent checks.
    This function does not invoke fusion and cannot validate FHE ciphertext algebra.
    """
    canonical_bytes(request)
    roster = request["required_parties"]
    if type(roster) is not list or len(roster) not in (2, 3) or len(set(roster)) != len(roster):
        raise ValueError("ROSTER")
    if request["lead_party"] != roster[0]:
        raise ValueError("LEAD")
    if type(request["threshold"]) is not int or request["threshold"] != len(roster):
        raise ValueError("THRESHOLD")
    if now.tzinfo is None:
        raise ValueError("NAIVE_CLOCK")
    created = utc_time(request["created_at"])
    expiry = utc_time(request["expires_at"])
    if not created <= now < expiry:
        raise ValueError("REQUEST_TIME")
    if len(envelopes) != len(roster):
        raise ValueError("PARTIAL_COUNT")
    expected_hash = payload_hash(request)
    collected = {}
    fields = {"schema_version", "party_id", "request_sha256", "aggregate_sha256", "epoch_sha256",
              "role", "decision", "approved_at", "partial_sha256", "partial_size"}
    for env in envelopes:
        p = verify(env, "partial", pinned_keys)
        if type(p) is not dict or set(p) != fields or p["schema_version"] != "2.0":
            raise ValueError("PARTIAL_FIELDS")
        party = p["party_id"]
        if party != env["signer_id"] or party not in roster or party in collected:
            raise ValueError("PARTIAL_SIGNER_SET")
        if (p["request_sha256"] != expected_hash or
            p["aggregate_sha256"] != request["aggregate_sha256"] or
            p["epoch_sha256"] != request["epoch_sha256"]):
            raise ValueError("PARTIAL_BINDING")
        expected_role = "lead" if party == roster[0] else "main"
        if p["role"] != expected_role or p["decision"] != "APPROVE":
            raise ValueError("PARTIAL_ROLE_OR_DECISION")
        when = utc_time(p["approved_at"])
        if not created <= when <= now or when >= expiry:
            raise ValueError("APPROVAL_TIME")
        digest = p["partial_sha256"]
        if type(digest) is not str or not HASH.fullmatch(digest) or digest not in artifacts:
            raise ValueError("PARTIAL_ARTIFACT_MISSING")
        blob = artifacts[digest]
        if type(blob) is not bytes or not 0 < len(blob) <= 16 * 1024**2:
            raise ValueError("ARTIFACT_SIZE")
        if type(p["partial_size"]) is not int or p["partial_size"] != len(blob) or sha256(blob) != digest:
            raise ValueError("ARTIFACT_HASH_SIZE")
        collected[party] = blob
    if set(collected) != set(roster):
        raise ValueError("PARTIAL_SET")
    return [collected[party] for party in roster]
