"""Symbolic, value-free failure tokens for the local import and query path.

Never attach cell contents, patient values or source paths to these errors: the
token and aggregate positions are the only things allowed to reach a log or UI.
"""
from __future__ import annotations
from typing import Any


class ImportRejected(ValueError):
    """Fail-closed rejection. ``token`` is an uppercase symbolic code."""

    def __init__(self, token: str, detail: dict[str, Any] | None = None) -> None:
        if not token.isascii() or not all(c.isupper() or c.isdigit() or c == "_" for c in token):
            token = "IMPORT_FAILED"
        super().__init__(token)
        self.token = token
        self.detail = detail or {}


class ValidationFailed(ImportRejected):
    """Raised when admitted rows contain unusable values. Carries the local report."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("LOCAL_VALIDATION_FAILED", {"report": report})
        self.report = report
