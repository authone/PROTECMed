"""PROTECMed signed immutable protocol layer (milestone M3).

Canonical bytes, Ed25519 envelopes, contract validation, state machines, the local
provider approval gate and the coordinator all-party fusion gate.
"""
from __future__ import annotations

from .errors import IntegrityHold, ProtocolError

__all__ = ["ProtocolError", "IntegrityHold"]
