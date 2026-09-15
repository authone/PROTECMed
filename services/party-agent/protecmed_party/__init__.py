"""PROTECMed party-agent local data layer (milestone M1).

Import, canonical normalization, the fixed query catalogue and frozen local snapshots.
No cryptography, no network and no coordinator code lives in this package.
"""
from __future__ import annotations

from .errors import ImportRejected, ValidationFailed

__all__ = ["ImportRejected", "ValidationFailed"]
