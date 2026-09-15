"""Ed25519 agent identities, the pinned roster and signed envelopes (blueprint 4.2, 4.3).

Each endpoint generates its own identity key locally. The coordinator must never
generate all party identity private keys, and a signature is verified against the key
pinned in the roster — never against a key supplied by the message.

These signatures give message integrity and attribution to provisioned agents. They are
not qualified electronic signatures and not proof of medical consent.
"""
from __future__ import annotations
import base64
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (Ed25519PrivateKey,
                                                               Ed25519PublicKey)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .canonical import DOMAIN, canonical_bytes, is_identifier, sha256_hex
from .errors import ProtocolError

SIGNATURE_BYTES = 64
ENVELOPE_FIELDS = {"signer_id", "purpose", "payload", "signature_b64"}
PURPOSES = frozenset({"run-plan", "plan-acceptance", "key-round", "epoch-manifest",
                      "epoch-confirmation", "encrypted-count", "input-set",
                      "decryption-request", "partial", "rejection"})


def public_bytes(key: Ed25519PublicKey) -> bytes:
    """The one fixed raw encoding used for fingerprints; never a PEM text form."""
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def fingerprint(key: Ed25519PublicKey) -> str:
    return sha256_hex(public_bytes(key))


@dataclass(frozen=True)
class Identity:
    """An agent's own key. Generated on its own endpoint and never exported."""

    agent_id: str
    private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls, agent_id: str) -> "Identity":
        if not is_identifier(agent_id):
            raise ProtocolError("AGENT_ID_FORMAT")
        return cls(agent_id, Ed25519PrivateKey.generate())

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self.private_key.public_key()

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.public_key)


class Roster:
    """Identity keys pinned out of band before the run is locked.

    A central registration page is not proof that independent institutions control the
    listed keys; these fingerprints are what the operators compared by another channel.
    """

    def __init__(self, pinned: Mapping[str, Ed25519PublicKey]) -> None:
        for agent_id in pinned:
            if not is_identifier(agent_id):
                raise ProtocolError("AGENT_ID_FORMAT")
        self._pinned = dict(pinned)

    @classmethod
    def from_identities(cls, identities: Iterable[Identity]) -> "Roster":
        return cls({identity.agent_id: identity.public_key for identity in identities})

    def __contains__(self, agent_id: object) -> bool:
        return agent_id in self._pinned

    def fingerprint_of(self, agent_id: str) -> str:
        if agent_id not in self._pinned:
            raise ProtocolError("UNKNOWN_SIGNER")
        return fingerprint(self._pinned[agent_id])

    def key_of(self, agent_id: str) -> Ed25519PublicKey:
        if agent_id not in self._pinned:
            raise ProtocolError("UNKNOWN_SIGNER")
        return self._pinned[agent_id]

    def assert_pinned(self, agent_id: str, expected_fingerprint: str) -> None:
        """A changed identity key requires a new enrollment and run, not a silent accept."""
        if self.fingerprint_of(agent_id) != expected_fingerprint:
            raise ProtocolError("IDENTITY_FINGERPRINT_MISMATCH", {"agent": agent_id})


def sign(payload: dict[str, Any], signer_id: str, purpose: str,
         identity: Identity) -> dict[str, Any]:
    if purpose not in PURPOSES:
        raise ProtocolError("UNKNOWN_PURPOSE")
    if signer_id != identity.agent_id:
        raise ProtocolError("SIGNER_IS_NOT_THIS_AGENT")
    body = {"signer_id": signer_id, "purpose": purpose, "payload": payload}
    signature = identity.private_key.sign(DOMAIN + canonical_bytes(body))
    return {**body, "signature_b64": base64.b64encode(signature).decode("ascii")}


def verify(envelope: Any, expected_purpose: str, roster: Roster) -> dict[str, Any]:
    """Verify one envelope against the pinned roster and the purpose this endpoint wants.

    A valid submission signature is not a valid approval: the caller always names the
    purpose it is willing to accept.
    """
    if expected_purpose not in PURPOSES:
        raise ProtocolError("UNKNOWN_PURPOSE")
    if type(envelope) is not dict or set(envelope) != ENVELOPE_FIELDS:
        raise ProtocolError("ENVELOPE_FIELDS")
    canonical_bytes(envelope)  # restricted profile applies to the whole envelope
    signer_id = envelope["signer_id"]
    if not is_identifier(signer_id) or signer_id not in roster:
        raise ProtocolError("UNKNOWN_SIGNER")
    if envelope["purpose"] != expected_purpose:
        raise ProtocolError("WRONG_PURPOSE")
    encoded = envelope["signature_b64"]
    if type(encoded) is not str:
        raise ProtocolError("SIGNATURE_TYPE")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ProtocolError("SIGNATURE_ENCODING") from None
    if len(signature) != SIGNATURE_BYTES:
        raise ProtocolError("SIGNATURE_LENGTH")
    payload = envelope["payload"]
    if type(payload) is not dict:
        raise ProtocolError("PAYLOAD_TYPE")
    body = {key: envelope[key] for key in ("signer_id", "purpose", "payload")}
    try:
        roster.key_of(signer_id).verify(signature, DOMAIN + canonical_bytes(body))
    except InvalidSignature:
        raise ProtocolError("BAD_SIGNATURE") from None
    return payload
