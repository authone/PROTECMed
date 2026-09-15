"""Symbolic protocol failures. Never carry a key, a count or a raw exception string."""
from __future__ import annotations
from typing import Any


class ProtocolError(ValueError):
    """Fail-closed protocol rejection. ``token`` is an uppercase symbolic code."""

    def __init__(self, token: str, detail: dict[str, Any] | None = None) -> None:
        if not token.isascii() or not all(c.isupper() or c.isdigit() or c == "_" for c in token):
            token = "PROTOCOL_FAILED"
        super().__init__(token)
        self.token = token
        self.detail = detail or {}


class IntegrityHold(ProtocolError):
    """Authenticated but conflicting messages. Requires operator review (blueprint 4.7).

    An unauthenticated or forged message must NOT raise this: otherwise any network
    user could trivially stop a run.
    """


def require(condition: object, token: str, detail: dict[str, Any] | None = None) -> None:
    if not condition:
        raise ProtocolError(token, detail)
