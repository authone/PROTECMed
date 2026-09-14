"""Frozen local snapshot and the opaque token that is the only thing allowed to leave.

Blueprint 3.3 / 3.6: the canonical snapshot is frozen before a run plan is accepted;
its source digest and mapping version stay in the local party registry; re-importing a
changed source mints a new token and supersedes the old one, and an operator editing the
file after encryption does not change the already-frozen contribution.

The snapshot token is random, not derived from the source digest: a content-derived token
would let the coordinator confirm guesses about the clinical file.
"""
from __future__ import annotations
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical import FIELDS, assert_canonical
from .errors import ImportRejected

TOKEN_BYTES = 16


@dataclass(frozen=True)
class Snapshot:
    snapshot_token: str
    created_utc: str
    source_sha256: str
    mapping_id: str
    mapping_digest: str
    import_mode: str
    admitted_rows: int
    report: dict[str, Any]
    records: list[dict[str, Any]] = field(repr=False)

    def public_descriptor(self) -> dict[str, str]:
        """Everything a coordinator may see. No count, no digest, no file name."""
        return {"snapshot_token": self.snapshot_token, "mapping_digest": self.mapping_digest}

    def local_metadata(self) -> dict[str, Any]:
        """Local registry record. Stays on the provider endpoint."""
        return {"snapshot_token": self.snapshot_token, "created_utc": self.created_utc,
                "source_sha256": self.source_sha256, "mapping_id": self.mapping_id,
                "mapping_digest": self.mapping_digest, "import_mode": self.import_mode,
                "admitted_rows": self.admitted_rows, "report": self.report}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def freeze(records: list[dict[str, Any]], report: dict[str, Any], *, source_sha256: str,
           mapping_id: str, mapping_digest: str, created_utc: str | None = None) -> Snapshot:
    assert_canonical(records)
    if report.get("invalid_values_total"):
        raise ImportRejected("SNAPSHOT_HAS_INVALID_VALUES")
    frozen = [dict(row) for row in records]
    return Snapshot(
        snapshot_token=secrets.token_hex(TOKEN_BYTES),
        created_utc=created_utc or now_utc(),
        source_sha256=source_sha256,
        mapping_id=mapping_id,
        mapping_digest=mapping_digest,
        import_mode=report.get("import_mode", "unknown"),
        admitted_rows=len(frozen),
        report=json.loads(json.dumps(report)),
        records=frozen,
    )


def _repository_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


class SnapshotStore:
    """Local registry directory. Refuses to persist clinical rows inside a Git work tree."""

    def __init__(self, directory: Path, *, allow_synthetic_in_repository: bool = False) -> None:
        self.directory = Path(directory).resolve()
        root = _repository_root(self.directory)
        if root is not None and not allow_synthetic_in_repository:
            # AGENTS.md: rows and raw clinical artifacts stay outside the Git root and
            # build context. Ignore rules are not access controls.
            raise ImportRejected("SNAPSHOT_STORE_INSIDE_REPOSITORY", {"root": str(root)})
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)

    def _path(self, token: str) -> Path:
        if not (len(token) == TOKEN_BYTES * 2 and all(c in "0123456789abcdef" for c in token)):
            raise ImportRejected("SNAPSHOT_TOKEN_FORMAT")
        return self.directory / f"snapshot-{token}.json"

    def save(self, snapshot: Snapshot) -> Path:
        """Write once. A frozen snapshot is never rewritten in place."""
        path = self._path(snapshot.snapshot_token)
        document = {"schema_version": "2.0", "superseded": False,
                    **snapshot.local_metadata(),
                    "records": snapshot.records, "fields": list(FIELDS)}
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        return path

    def load(self, token: str) -> Snapshot:
        document = json.loads(self._path(token).read_text(encoding="utf-8"))
        return Snapshot(
            snapshot_token=document["snapshot_token"], created_utc=document["created_utc"],
            source_sha256=document["source_sha256"], mapping_id=document["mapping_id"],
            mapping_digest=document["mapping_digest"], import_mode=document["import_mode"],
            admitted_rows=document["admitted_rows"], report=document["report"],
            records=document["records"])

    def is_superseded(self, token: str) -> bool:
        return bool(json.loads(self._path(token).read_text(encoding="utf-8"))["superseded"])

    def supersede_others(self, keep_token: str) -> list[str]:
        """A re-import invalidates earlier selections; it never edits a frozen snapshot."""
        superseded = []
        for path in sorted(self.directory.glob("snapshot-*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            if document["snapshot_token"] == keep_token or document["superseded"]:
                continue
            document["superseded"] = True
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            superseded.append(document["snapshot_token"])
        return superseded
