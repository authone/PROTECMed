"""Read-only import directory with opaque selection tokens (blueprint 5.5).

The UI lists files in one configured directory and submits an opaque token. A browser
cannot safely supply a general host path, and no route accepts one: symlinks, path
escapes and non-regular files are refused.

Tokens are an HMAC of the file name under a per-process secret. They carry no path
information, and they stay stable while the agent runs, so re-rendering the page does not
invalidate the operator's selection.
"""
from __future__ import annotations
import hmac
import os
import secrets
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from fastapi import HTTPException

ALLOWED_SUFFIXES = {".xlsx", ".csv"}
MAX_LISTED = 200


@dataclass
class ImportDirectory:
    directory: Path
    _secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))

    def __post_init__(self) -> None:
        self.directory = Path(self.directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _token(self, name: str) -> str:
        return hmac.new(self._secret, name.encode("utf-8"), sha256).hexdigest()[:32]

    def _candidates(self) -> list[Path]:
        entries = []
        for path in sorted(self.directory.iterdir())[:MAX_LISTED]:
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            entries.append(path)
        return entries

    def listing(self) -> list[dict[str, object]]:
        """Names and sizes only. No content is read and no path leaves this service."""
        return [{"token": self._token(path.name), "name": path.name,
                 "size": path.stat().st_size} for path in self._candidates()]

    def resolve(self, token: str) -> Path:
        for path in self._candidates():
            if hmac.compare_digest(self._token(path.name), token):
                return self._verify(path)
        raise HTTPException(status_code=400, detail="UNKNOWN_SELECTION_TOKEN")

    def _verify(self, path: Path) -> Path:
        # Re-checked at use time: the listing may be stale.
        resolved = path.resolve()
        if not resolved.is_file() or path.is_symlink():
            raise HTTPException(status_code=400, detail="SELECTION_NOT_A_FILE")
        if os.path.commonpath([str(self.directory), str(resolved)]) != str(self.directory):
            raise HTTPException(status_code=400, detail="SELECTION_OUTSIDE_DIRECTORY")
        return resolved
