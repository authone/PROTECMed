"""Immutable local outbox and the study-wide disclosure ledger (blueprint 2.8, 4.4, 4.7).

The outbox gives the reserve -> compute -> commit -> send sequence its durability. A
retry resends the *same bytes*; it never regenerates a randomized artifact. If a crash
leaves a reservation without a commit, the epoch is aborted rather than re-run, because
it is not known whether different bytes already left this endpoint.

The disclosure ledger is study-wide, survives a container restart and is NOT reset by
creating a new epoch. It is a local policy record under `exact-count-restricted-demo-v1`
— not differential privacy and not a formal query budget.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .canonical import format_utc, is_hex64, is_identifier, sha256_hex
from .errors import ProtocolError, require

ARTIFACT_KINDS = frozenset({"key-round", "submission", "partial", "fusion-receipt"})


@dataclass(frozen=True)
class OutboxEntry:
    key: str
    artifact: bytes
    receipt: dict[str, Any]


class ImmutableOutbox:
    """Write-once artifacts keyed by (run_id, party_id, artifact_kind[, discriminator])."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)

    @staticmethod
    def key(run_id: str, party_id: str, kind: str, discriminator: str = "") -> str:
        require(is_identifier(run_id) and is_identifier(party_id), "OUTBOX_KEY_FORMAT")
        require(kind in ARTIFACT_KINDS, "OUTBOX_KIND")
        require(discriminator == "" or is_hex64(discriminator) or is_identifier(discriminator),
                "OUTBOX_DISCRIMINATOR")
        return "__".join(part for part in (run_id, party_id, kind, discriminator) if part)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        stem = self.directory / key
        return (stem.with_suffix(".reserved"), stem.with_suffix(".bin"),
                stem.with_suffix(".json"))

    def is_reserved(self, key: str) -> bool:
        return self._paths(key)[0].exists()

    def is_committed(self, key: str) -> bool:
        reserved, artifact, receipt = self._paths(key)
        return artifact.exists() and receipt.exists()

    def reserve(self, key: str) -> None:
        """Atomically claim this artifact slot before any computation starts."""
        reserved = self._paths(key)[0]
        try:
            descriptor = os.open(reserved, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise ProtocolError("OUTBOX_ALREADY_RESERVED", {"key": key}) from None
        os.close(descriptor)

    def assert_resumable(self, key: str) -> None:
        """A reservation with no commit means an emission of unknown content."""
        if self.is_reserved(key) and not self.is_committed(key):
            raise ProtocolError("OUTBOX_UNCERTAIN_EMISSION", {"key": key})

    def commit(self, key: str, artifact: bytes, receipt: dict[str, Any]) -> OutboxEntry:
        require(type(artifact) is bytes and artifact, "OUTBOX_ARTIFACT")
        reserved, artifact_path, receipt_path = self._paths(key)
        require(reserved.exists(), "OUTBOX_NOT_RESERVED", {"key": key})
        if artifact_path.exists() or receipt_path.exists():
            raise ProtocolError("OUTBOX_ALREADY_COMMITTED", {"key": key})
        record = {**receipt, "artifact_sha256": sha256_hex(artifact),
                  "artifact_size": len(artifact)}
        self._write(artifact_path, artifact)
        self._write(receipt_path, json.dumps(record, sort_keys=True).encode("ascii"))
        return OutboxEntry(key, artifact, record)

    @staticmethod
    def _write(path: Path, payload: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def get(self, key: str) -> OutboxEntry | None:
        """Return the stored bytes for an idempotent resend, or None if absent."""
        _, artifact_path, receipt_path = self._paths(key)
        if not (artifact_path.exists() and receipt_path.exists()):
            return None
        return OutboxEntry(key, artifact_path.read_bytes(),
                           json.loads(receipt_path.read_text(encoding="ascii")))


class DisclosureLedger:
    """Append-only local record of what this provider has already helped release."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)

    def entries(self) -> list[dict[str, Any]]:
        text = self.path.read_text(encoding="ascii")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    @staticmethod
    def _combination(record: dict[str, Any]) -> tuple[str, str, str, str]:
        return (record["study_id"], record["query_sha256"], record["snapshot_token"],
                record["recipients_sha256"])

    def permits(self, *, study_id: str, query_sha256: str, snapshot_token: str,
                recipients_sha256: str, run_id: str) -> None:
        """Refuse a repeat of the same query on the same snapshot to the same recipients.

        A fixed catalogue and fresh keys do not remove repeated-query differencing
        (blueprint 4.1), so the local policy is to answer each combination once. This is
        a policy, not a privacy proof.
        """
        wanted = (study_id, query_sha256, snapshot_token, recipients_sha256)
        for record in self.entries():
            if record["decision"] != "APPROVE":
                continue
            if self._combination(record) == wanted:
                raise ProtocolError("DISCLOSURE_ALREADY_RELEASED",
                                    {"study": study_id, "run": record["run_id"]})
            if record["run_id"] == run_id:
                # One output per epoch; a new query needs a new run.
                raise ProtocolError("DISCLOSURE_RUN_ALREADY_USED", {"run": run_id})

    def record(self, *, study_id: str, run_id: str, query_sha256: str,
               snapshot_token: str, recipients_sha256: str, decision: str,
               at: datetime) -> None:
        require(decision in {"APPROVE", "REJECT"}, "LEDGER_DECISION")
        entry = {"study_id": study_id, "run_id": run_id, "query_sha256": query_sha256,
                 "snapshot_token": snapshot_token, "recipients_sha256": recipients_sha256,
                 "decision": decision, "decided_at": format_utc(at)}
        with self.path.open("a", encoding="ascii") as stream:
            stream.write(json.dumps(entry, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
