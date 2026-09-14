"""Protocol payload builders, semantic validators and hash recipes (blueprint 4.2-4.5).

Hash recipe (contracts/README.md): query, run-plan, each key-round payload,
epoch-manifest, encrypted-count, input-set and decryption-request are SHA-256 of the
canonical payload bytes, excluding envelope and signature. The key-round transcript is
the canonical array of key-round payloads in roster order. The recipient-list hash is
over the canonical ordered recipient-ID array. Mapping and binary artifacts are hashed
as their exact bytes.
"""
from __future__ import annotations
import secrets
from datetime import datetime
from typing import Any, Sequence

from .canonical import (format_utc, hash_list, is_hex64, is_identifier, parse_utc,
                        payload_hash, require_aware)
from .contracts import validate_payload
from .errors import ProtocolError, require

SCHEMA_VERSION = "2.0"
PROFILE_ID = "bgv-count-nofn-v2"
MODULE_ID = "cohort-count-local-v2"
RELEASE_POLICY_ID = "exact-count-restricted-demo-v1"
FORMAT_ID = "openfhe-1.5.1-binary"
LOCAL_ROW_CAP = 10000
MAX_ARTIFACT_BYTES = 16 * 1024**2


def new_nonce() -> str:
    """32 random bytes, hex encoded (contracts/README.md)."""
    return secrets.token_hex(32)


def new_identifier(prefix: str) -> str:
    candidate = f"{prefix}-{secrets.token_hex(8)}"
    if not is_identifier(candidate):
        raise ProtocolError("IDENTIFIER_FORMAT")
    return candidate


def recipients_hash(recipient_ids: Sequence[str]) -> str:
    ids = list(recipient_ids)
    require(ids and len(set(ids)) == len(ids), "RECIPIENT_LIST")
    require(all(is_identifier(r) for r in ids), "RECIPIENT_ID_FORMAT")
    return hash_list(ids)


# --- run plan ---------------------------------------------------------------

def build_run_plan(*, study_id: str, run_id: str, roster: Sequence[dict[str, str]],
                   lead_party: str, recipient_ids: Sequence[str], query_sha256: str,
                   mapping_sha256: str) -> dict[str, Any]:
    plan = {
        "schema_version": SCHEMA_VERSION,
        "study_id": study_id,
        "run_id": run_id,
        "party_count": len(roster),
        "threshold": len(roster),
        "roster": [dict(entry) for entry in roster],
        "lead_party": lead_party,
        "recipient_ids": list(recipient_ids),
        "query_sha256": query_sha256,
        "mapping_sha256": mapping_sha256,
        "profile_id": PROFILE_ID,
        "module_id": MODULE_ID,
        "local_row_cap": LOCAL_ROW_CAP,
        "release_policy_id": RELEASE_POLICY_ID,
    }
    validate_run_plan(plan)
    return plan


def validate_run_plan(plan: Any) -> None:
    validate_payload("run-plan", plan)
    roster = plan["roster"]
    parties = [entry["party_id"] for entry in roster]
    # threshold == party_count == len(roster), enforced here because no schema can.
    require(plan["party_count"] == plan["threshold"] == len(roster), "PLAN_THRESHOLD")
    require(len(set(parties)) == len(parties), "PLAN_DUPLICATE_PARTY")
    tokens = [entry["snapshot_token"] for entry in roster]
    require(len(set(tokens)) == len(tokens), "PLAN_DUPLICATE_SNAPSHOT")
    fingerprints = [entry["identity_key_sha256"] for entry in roster]
    require(len(set(fingerprints)) == len(fingerprints), "PLAN_DUPLICATE_IDENTITY")
    # Roster order is stable and defines lead/main and the addition order.
    require(plan["lead_party"] == parties[0], "PLAN_LEAD_IS_NOT_FIRST")


def roster_parties(plan: dict[str, Any]) -> list[str]:
    return [entry["party_id"] for entry in plan["roster"]]


def role_of(plan: dict[str, Any], party_id: str) -> str:
    parties = roster_parties(plan)
    require(party_id in parties, "PARTY_NOT_IN_ROSTER", {"party": party_id})
    return "lead" if party_id == parties[0] else "main"


# --- acknowledgements (plan acceptance, epoch confirmation) ------------------

def build_acknowledgement(*, run_id: str, party_id: str, object_sha256: str,
                          at: datetime) -> dict[str, Any]:
    acknowledgement = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "party_id": party_id,
        "object_sha256": object_sha256,
        "accepted_at": format_utc(at),
    }
    validate_payload("plan-acceptance", acknowledgement)
    return acknowledgement


# --- key rounds and epoch ---------------------------------------------------

def build_key_round(*, run_id: str, run_plan_sha256: str, context_sha256: str,
                    round_index: int, party_id: str, incoming_public_key_sha256: str | None,
                    outgoing_public_key_sha256: str) -> dict[str, Any]:
    round_payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_plan_sha256": run_plan_sha256,
        "context_sha256": context_sha256,
        "round_index": round_index,
        "party_id": party_id,
        "incoming_public_key_sha256": incoming_public_key_sha256,
        "outgoing_public_key_sha256": outgoing_public_key_sha256,
    }
    validate_payload("key-round", round_payload)
    # The first incoming hash is null; every later round must chain.
    require((round_index == 0) == (incoming_public_key_sha256 is None), "KEY_ROUND_CHAIN_START")
    return round_payload


def key_round_transcript_hash(rounds: Sequence[dict[str, Any]]) -> str:
    return hash_list([dict(entry) for entry in rounds])


def validate_key_round_chain(rounds: Sequence[dict[str, Any]], plan: dict[str, Any], *,
                             run_plan_sha256: str, context_sha256: str) -> str:
    """Verify the complete ordered chain, including this party's own contribution.

    Returns the final public-key hash. Key tags are deliberately not inspected here:
    intermediate key pairs may carry different tags and a tag is not an identity.
    """
    parties = roster_parties(plan)
    require(len(rounds) == len(parties), "KEY_ROUND_COUNT")
    previous: str | None = None
    for index, entry in enumerate(rounds):
        validate_payload("key-round", entry)
        require(entry["run_id"] == plan["run_id"], "KEY_ROUND_RUN")
        require(entry["run_plan_sha256"] == run_plan_sha256, "KEY_ROUND_PLAN")
        require(entry["context_sha256"] == context_sha256, "KEY_ROUND_CONTEXT")
        require(entry["round_index"] == index, "KEY_ROUND_INDEX")
        require(entry["party_id"] == parties[index], "KEY_ROUND_PARTY_ORDER")
        require(entry["incoming_public_key_sha256"] == previous, "KEY_ROUND_CHAIN")
        previous = entry["outgoing_public_key_sha256"]
        require(is_hex64(previous), "KEY_ROUND_OUTGOING")
    require(previous is not None, "KEY_ROUND_EMPTY")
    return previous


def build_epoch_manifest(*, run_id: str, epoch_id: str, run_plan_sha256: str,
                         context_sha256: str, final_public_key_sha256: str,
                         key_round_transcript_sha256: str) -> dict[str, Any]:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "epoch_id": epoch_id,
        "run_plan_sha256": run_plan_sha256,
        "context_sha256": context_sha256,
        "final_public_key_sha256": final_public_key_sha256,
        "key_round_transcript_sha256": key_round_transcript_sha256,
    }
    validate_payload("epoch-manifest", manifest)
    return manifest


# --- submissions ------------------------------------------------------------

def build_encrypted_count(*, run_id: str, epoch_sha256: str, party_id: str,
                          query_sha256: str, snapshot_token: str, ciphertext: bytes,
                          ciphertext_sha256: str, final_key_tag: str) -> dict[str, Any]:
    require(type(ciphertext) is bytes and 0 < len(ciphertext) <= MAX_ARTIFACT_BYTES,
            "CIPHERTEXT_SIZE")
    submission = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "epoch_sha256": epoch_sha256,
        "party_id": party_id,
        "query_sha256": query_sha256,
        "snapshot_token": snapshot_token,
        "ciphertext_sha256": ciphertext_sha256,
        "ciphertext_size": len(ciphertext),
        "final_key_tag": final_key_tag,
        "format_id": FORMAT_ID,
    }
    validate_payload("encrypted-count", submission)
    # No local count, admitted-row number or patient identifier may appear here.
    return submission


def build_input_set(*, run_id: str, epoch_sha256: str,
                    entries: Sequence[dict[str, str]]) -> dict[str, Any]:
    input_set = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "epoch_sha256": epoch_sha256,
        "inputs": [dict(entry) for entry in entries],
    }
    validate_payload("input-set", input_set)
    parties = [entry["party_id"] for entry in input_set["inputs"]]
    require(len(set(parties)) == len(parties), "INPUT_SET_DUPLICATE_PARTY")
    return input_set


# --- request, partial, rejection --------------------------------------------

def build_decryption_request(*, study_id: str, run_id: str, request_id: str,
                             epoch_sha256: str, query_sha256: str, input_set_sha256: str,
                             aggregate_sha256: str, recipients_sha256: str,
                             required_parties: Sequence[str], lead_party: str,
                             created_at: datetime, expires_at: datetime,
                             nonce: str | None = None) -> dict[str, Any]:
    request = {
        "schema_version": SCHEMA_VERSION,
        "study_id": study_id,
        "run_id": run_id,
        "request_id": request_id,
        "epoch_sha256": epoch_sha256,
        "query_sha256": query_sha256,
        "input_set_sha256": input_set_sha256,
        "aggregate_sha256": aggregate_sha256,
        "recipients_sha256": recipients_sha256,
        "required_parties": list(required_parties),
        "threshold": len(required_parties),
        "lead_party": lead_party,
        "nonce": nonce or new_nonce(),
        "created_at": format_utc(created_at),
        "expires_at": format_utc(expires_at),
    }
    validate_decryption_request(request)
    return request


def validate_decryption_request(request: Any) -> None:
    validate_payload("decryption-request", request)
    parties = request["required_parties"]
    require(len(set(parties)) == len(parties), "REQUEST_DUPLICATE_PARTY")
    require(all(is_identifier(p) for p in parties), "REQUEST_PARTY_FORMAT")
    require(request["threshold"] == len(parties), "REQUEST_THRESHOLD")
    require(request["lead_party"] == parties[0], "REQUEST_LEAD_IS_NOT_FIRST")
    created, expires = parse_utc(request["created_at"]), parse_utc(request["expires_at"])
    require(created < expires, "REQUEST_EXPIRY_ORDER")


def request_is_live(request: dict[str, Any], now: datetime) -> bool:
    moment = require_aware(now)
    return parse_utc(request["created_at"]) <= moment < parse_utc(request["expires_at"])


def build_partial(*, party_id: str, request_sha256: str, aggregate_sha256: str,
                  epoch_sha256: str, role: str, approved_at: datetime,
                  partial_bytes: bytes, partial_sha256: str) -> dict[str, Any]:
    require(type(partial_bytes) is bytes and 0 < len(partial_bytes) <= MAX_ARTIFACT_BYTES,
            "PARTIAL_SIZE")
    partial = {
        "schema_version": SCHEMA_VERSION,
        "party_id": party_id,
        "request_sha256": request_sha256,
        "aggregate_sha256": aggregate_sha256,
        "epoch_sha256": epoch_sha256,
        "role": role,
        "decision": "APPROVE",
        "approved_at": format_utc(approved_at),
        "partial_sha256": partial_sha256,
        "partial_size": len(partial_bytes),
    }
    validate_payload("partial", partial)
    # FHE secret-share bytes are never part of this payload.
    return partial


def build_rejection(*, run_id: str, party_id: str, request_sha256: str,
                    rejected_at: datetime, reason_code: str) -> dict[str, Any]:
    rejection = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "party_id": party_id,
        "request_sha256": request_sha256,
        "decision": "REJECT",
        "rejected_at": format_utc(rejected_at),
        "reason_code": reason_code,
    }
    validate_payload("rejection", rejection)
    return rejection


__all__ = [name for name in dir() if not name.startswith("_")]
