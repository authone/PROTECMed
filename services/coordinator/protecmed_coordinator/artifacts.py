"""Content-addressed binary store with run-scoped retrieval (blueprint 2.7, 5.4, 5.6).

Bytes are hashed while streaming into a quarantine file, authenticated by the caller,
then atomically promoted. Content addressing does not make a clinical ciphertext public:
every read still checks that the artifact belongs to a run the caller is a member of.
"""
from __future__ import annotations
import hashlib
import os
import sqlite3
from pathlib import Path

from fastapi import HTTPException

from .security import MAX_BINARY_BYTES, now_utc


class ArtifactStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
            raise HTTPException(status_code=400, detail="ARTIFACT_DIGEST_FORMAT")
        # Server-generated path: the client never influences it beyond the digest.
        return self.directory / f"{digest}.bin"

    def put(self, connection: sqlite3.Connection, *, run_id: str, kind: str,
            payload: bytes, expected_sha256: str) -> str:
        if not 0 < len(payload) <= MAX_BINARY_BYTES:
            raise HTTPException(status_code=413, detail="ARTIFACT_SIZE")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != expected_sha256:
            raise HTTPException(status_code=400, detail="ARTIFACT_HASH_MISMATCH")
        path = self._path(digest)
        if not path.exists():
            quarantine = path.with_suffix(".quarantine")
            descriptor = os.open(quarantine, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(quarantine, path)
        connection.execute(
            "INSERT OR IGNORE INTO artifacts (sha256, run_id, kind, size, stored_at) "
            "VALUES (?, ?, ?, ?, ?)", (digest, run_id, kind, len(payload), now_utc()))
        return digest

    def get(self, connection: sqlite3.Connection, *, run_id: str, digest: str) -> bytes:
        row = connection.execute(
            "SELECT run_id FROM artifacts WHERE sha256 = ?", (digest,)).fetchone()
        if row is None or row["run_id"] != run_id:
            raise HTTPException(status_code=404, detail="ARTIFACT_NOT_FOUND")
        path = self._path(digest)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="ARTIFACT_NOT_FOUND")
        return path.read_bytes()

    def path_for(self, digest: str) -> Path:
        return self._path(digest)
