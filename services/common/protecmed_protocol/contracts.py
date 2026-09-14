"""Schema layer: `contracts/*.schema.json` plus the purpose-to-schema binding.

JSON Schema checks structure only. Every cross-object relationship — equal n and
threshold, exact roster, identity pinning, chronological validity, matching hashes,
correct state, immutable input snapshots — is enforced in `objects.py`, `party.py` and
`coordinator.py`, because a schema cannot establish any of them.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .errors import ProtocolError

CONTRACTS_DIRECTORY = Path(__file__).resolve().parents[3] / "contracts"

# Which payload contract each envelope purpose carries. plan-acceptance and
# epoch-confirmation share the acknowledgement contract; purpose plus the acknowledged
# object hash is what distinguishes them.
PURPOSE_SCHEMA = {
    "run-plan": "run-plan",
    "plan-acceptance": "acknowledgement",
    "key-round": "key-round",
    "epoch-manifest": "epoch-manifest",
    "epoch-confirmation": "acknowledgement",
    "encrypted-count": "encrypted-count",
    "input-set": "input-set",
    "decryption-request": "decryption-request",
    "partial": "partial",
    "rejection": "rejection",
}


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    path = CONTRACTS_DIRECTORY / f"{name}.schema.json"
    if not path.is_file():
        raise ProtocolError("SCHEMA_MISSING", {"schema": name})
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_against(name: str, document: Any) -> None:
    try:
        _validator(name).validate(document)
    except ValidationError as error:
        # Only the failing path, never the offending value.
        raise ProtocolError("SCHEMA_INVALID",
                            {"schema": name,
                             "path": list(error.absolute_path)}) from None


def validate_payload(purpose: str, payload: Any) -> None:
    name = PURPOSE_SCHEMA.get(purpose)
    if name is None:
        raise ProtocolError("UNKNOWN_PURPOSE")
    validate_against(name, payload)


def validate_envelope(envelope: Any) -> None:
    """Both layers: the generic envelope, then the payload contract for its purpose."""
    validate_against("envelope", envelope)
    validate_payload(envelope["purpose"], envelope["payload"])
