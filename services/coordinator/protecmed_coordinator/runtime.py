"""Durable coordinator service: SQLite state plus the M3 protocol object (4.7, 5.4, 5.6).

Each operation opens an IMMEDIATE transaction, rehydrates the in-memory protocol object
from durable rows, runs the M3 logic, then writes the resulting rows and the new run
state in the same transaction. A crash between two operations leaves the run resumable
from durable public/encrypted state; nothing is half-applied.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (Ed25519PrivateKey,
                                                               Ed25519PublicKey)

from protecmed_protocol.canonical import payload_hash, sha256_hex
from protecmed_protocol.coordinator import (Coordinator, KeyRoundRecord, PartialRecord,
                                            SubmissionRecord)
from protecmed_protocol.identity import Identity, Roster
from protecmed_protocol.state import run_machine

from .artifacts import ArtifactStore
from .db import connect, record_audit, transaction
from .security import now_utc

KIND_ARTIFACT = {"key-round": "public-key", "encrypted-count": "ciphertext",
                 "partial": "partial"}


def load_or_create_identity(path: Path) -> Ed25519PrivateKey:
    """Generated on this endpoint at runtime, never shipped inside an image."""
    path = Path(path)
    if path.exists():
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
            path.read_text(encoding="ascii").strip()))
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(key.private_bytes_raw().hex())
    return key


class CoordinatorService:
    def __init__(self, *, database: Path, storage: Path, worker: Any,
                 coordinator_id: str = "coordinator") -> None:
        self.storage = Path(storage)
        self.storage.mkdir(parents=True, exist_ok=True)
        os.chmod(self.storage, 0o700)
        self.connection = connect(Path(database))
        self.artifacts = ArtifactStore(self.storage / "artifacts")
        self.worker = worker
        self.coordinator_id = coordinator_id
        self.identity = Identity(coordinator_id,
                                 load_or_create_identity(self.storage / "identity.key"))
        self.connection.execute(
            "INSERT OR IGNORE INTO agents (agent_id, role, token_sha256, public_key_hex) "
            "VALUES (?, 'coordinator', ?, ?)",
            (coordinator_id, f"bootstrap-{coordinator_id}",
             self.identity.public_key.public_bytes_raw().hex()))

    # --- roster --------------------------------------------------------------
    def roster(self) -> Roster:
        pinned: dict[str, Ed25519PublicKey] = {}
        for row in self.connection.execute(
                "SELECT agent_id, public_key_hex FROM agents "
                "WHERE public_key_hex IS NOT NULL"):
            pinned[row["agent_id"]] = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(row["public_key_hex"]))
        return Roster(pinned)

    def run_directory(self, run_id: str) -> Path:
        path = self.storage / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    # --- hydration -----------------------------------------------------------
    def hydrate(self, run_id: str) -> Coordinator:
        row = self.connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("RUN_NOT_FOUND")
        coordinator = Coordinator(coordinator_id=self.coordinator_id,
                                  identity=self.identity, roster=self.roster(),
                                  study_id=row["study_id"], worker=self.worker,
                                  storage=self.run_directory(run_id))
        coordinator.state = run_machine(row["state"])
        coordinator.plan = json.loads(row["plan_json"]) if row["plan_json"] else None
        coordinator.plan_sha256 = row["plan_sha256"]
        coordinator.plan_envelope = (json.loads(row["plan_envelope"])
                                     if row["plan_envelope"] else None)
        coordinator.context_sha256 = row["context_sha256"]
        if row["context_sha256"]:
            coordinator.context_path = self.artifacts.path_for(row["context_sha256"])
        coordinator.epoch_manifest = json.loads(row["epoch_json"]) if row["epoch_json"] else None
        coordinator.epoch_envelope = (json.loads(row["epoch_envelope"])
                                      if row["epoch_envelope"] else None)
        coordinator.epoch_sha256 = row["epoch_sha256"]
        coordinator.input_set = (json.loads(row["input_set_json"])
                                 if row["input_set_json"] else None)
        coordinator.input_set_envelope = (json.loads(row["input_set_envelope"])
                                          if row["input_set_envelope"] else None)
        coordinator.aggregate_sha256 = row["aggregate_sha256"]
        if row["aggregate_sha256"]:
            coordinator.aggregate_path = self.artifacts.path_for(row["aggregate_sha256"])
        coordinator.request = json.loads(row["request_json"]) if row["request_json"] else None
        coordinator.request_envelope = (json.loads(row["request_envelope"])
                                        if row["request_envelope"] else None)

        for message in self.connection.execute(
                "SELECT party_id, kind, envelope_json FROM messages WHERE run_id = ?",
                (run_id,)):
            envelope = json.loads(message["envelope_json"])
            payload = envelope["payload"]
            kind, party_id = message["kind"], message["party_id"]
            if kind == "plan-acceptance":
                coordinator.acceptances[party_id] = payload
            elif kind == "epoch-confirmation":
                coordinator.confirmations[party_id] = payload
            elif kind == "key-round":
                blob = self.artifacts.get(self.connection, run_id=run_id,
                                          digest=payload["outgoing_public_key_sha256"])
                coordinator.key_rounds.append(KeyRoundRecord(payload, envelope, blob))
            elif kind == "encrypted-count":
                blob = self.artifacts.get(self.connection, run_id=run_id,
                                          digest=payload["ciphertext_sha256"])
                coordinator.submissions[party_id] = SubmissionRecord(payload, envelope, blob)
            elif kind == "partial":
                blob = self.artifacts.get(self.connection, run_id=run_id,
                                          digest=payload["partial_sha256"])
                coordinator.partials[party_id] = PartialRecord(payload, envelope, blob)
            elif kind == "rejection":
                coordinator.rejections[party_id] = payload
        coordinator.key_rounds.sort(key=lambda record: record.payload["round_index"])
        return coordinator

    # --- persistence ---------------------------------------------------------
    def _save_run(self, connection: sqlite3.Connection, coordinator: Coordinator) -> None:
        connection.execute(
            "UPDATE runs SET state = ?, plan_json = ?, plan_envelope = ?, plan_sha256 = ?,"
            " context_sha256 = ?, epoch_json = ?, epoch_envelope = ?, epoch_sha256 = ?,"
            " input_set_json = ?, input_set_envelope = ?, aggregate_sha256 = ?,"
            " request_json = ?, request_envelope = ? WHERE run_id = ?",
            (coordinator.state.state,
             json.dumps(coordinator.plan) if coordinator.plan else None,
             json.dumps(coordinator.plan_envelope) if coordinator.plan_envelope else None,
             coordinator.plan_sha256, coordinator.context_sha256,
             json.dumps(coordinator.epoch_manifest) if coordinator.epoch_manifest else None,
             json.dumps(coordinator.epoch_envelope) if coordinator.epoch_envelope else None,
             coordinator.epoch_sha256,
             json.dumps(coordinator.input_set) if coordinator.input_set else None,
             json.dumps(coordinator.input_set_envelope)
             if coordinator.input_set_envelope else None,
             coordinator.aggregate_sha256,
             json.dumps(coordinator.request) if coordinator.request else None,
             json.dumps(coordinator.request_envelope)
             if coordinator.request_envelope else None,
             coordinator.plan["run_id"] if coordinator.plan else None))

    def _store_message(self, connection: sqlite3.Connection, *, run_id: str,
                       party_id: str, kind: str, envelope: dict[str, Any]) -> bool:
        """Unique on (run_id, party_id, kind). A byte-identical retry is a no-op."""
        digest = payload_hash(envelope["payload"])
        row = connection.execute(
            "SELECT envelope_json FROM messages WHERE run_id = ? AND party_id = ? "
            "AND kind = ?", (run_id, party_id, kind)).fetchone()
        if row is not None:
            return json.loads(row["envelope_json"]) == envelope
        connection.execute(
            "INSERT INTO messages (run_id, party_id, kind, envelope_json, payload_sha256,"
            " received_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, party_id, kind, json.dumps(envelope, sort_keys=True), digest,
             now_utc()))
        return True

    def audit(self, connection: sqlite3.Connection, *, run_id: str | None,
              agent_id: str | None, event: str, detail: dict[str, Any] | None = None) -> None:
        record_audit(connection, run_id=run_id, agent_id=agent_id, event=event,
                     detail=detail, at=now_utc())

    # --- operations ----------------------------------------------------------
    def create_study(self, study_id: str) -> None:
        with transaction(self.connection) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO studies (study_id, created_at) VALUES (?, ?)",
                (study_id, now_utc()))

    def create_run(self, *, study_id: str, run_id: str, roster_entries: list[dict[str, str]],
                   recipient_ids: list[str], query_sha256: str,
                   mapping_sha256: str) -> dict[str, Any]:
        with transaction(self.connection) as connection:
            connection.execute(
                "INSERT INTO runs (run_id, study_id, state, created_at) "
                "VALUES (?, ?, 'DRAFT', ?)", (run_id, study_id, now_utc()))
            coordinator = Coordinator(coordinator_id=self.coordinator_id,
                                      identity=self.identity, roster=self.roster(),
                                      study_id=study_id, worker=self.worker,
                                      storage=self.run_directory(run_id))
            envelope = coordinator.create_plan(
                run_id=run_id, roster_entries=roster_entries,
                recipient_ids=recipient_ids, query_sha256=query_sha256,
                mapping_sha256=mapping_sha256)
            self._save_run(connection, coordinator)
            self.audit(connection, run_id=run_id, agent_id=self.coordinator_id,
                       event="run.created", detail={"parties": len(roster_entries)})
            return envelope

    def accept_message(self, *, run_id: str, party_id: str, kind: str,
                       envelope: dict[str, Any], artifact: bytes | None = None) -> dict[str, Any]:
        """One entry point for every party-signed message, always transactional."""
        with transaction(self.connection) as connection:
            coordinator = self.hydrate(run_id)
            if artifact is not None:
                expected = {"key-round": "outgoing_public_key_sha256",
                            "encrypted-count": "ciphertext_sha256",
                            "partial": "partial_sha256"}[kind]
                self.artifacts.put(connection, run_id=run_id, kind=KIND_ARTIFACT[kind],
                                   payload=artifact,
                                   expected_sha256=envelope["payload"][expected])
            if kind == "plan-acceptance":
                coordinator.record_plan_acceptance(envelope)
            elif kind == "key-round":
                coordinator.record_key_round(envelope, artifact)
            elif kind == "epoch-confirmation":
                coordinator.record_epoch_confirmation(envelope)
            elif kind == "encrypted-count":
                coordinator.accept_submission(envelope, artifact)
            elif kind == "partial":
                coordinator.accept_partial(envelope, artifact)
            elif kind == "rejection":
                coordinator.accept_rejection(envelope)
            else:
                raise KeyError("UNKNOWN_KIND")
            if not self._store_message(connection, run_id=run_id, party_id=party_id,
                                       kind=kind, envelope=envelope):
                coordinator.state = run_machine("INTEGRITY_HOLD")
                self._save_run(connection, coordinator)
                self.audit(connection, run_id=run_id, agent_id=party_id,
                           event="integrity.hold", detail={"kind": kind})
                raise ValueError("CONFLICTING_MESSAGE")
            self._save_run(connection, coordinator)
            self.audit(connection, run_id=run_id, agent_id=party_id,
                       event=f"message.{kind}")
            return {"state": coordinator.state.state}

    def key_round_payload(self, *, run_id: str, party_id: str,
                          public_key: bytes) -> dict[str, Any]:
        coordinator = self.hydrate(run_id)
        return coordinator.key_round_payload(round_index=len(coordinator.key_rounds),
                                             party_id=party_id,
                                             outgoing_public_key=public_key)

    def create_context(self, run_id: str) -> str:
        with transaction(self.connection) as connection:
            coordinator = self.hydrate(run_id)
            path = coordinator.create_context()
            payload = path.read_bytes()
            digest = self.artifacts.put(connection, run_id=run_id, kind="context",
                                        payload=payload,
                                        expected_sha256=sha256_hex(payload))
            coordinator.context_sha256 = digest
            self._save_run(connection, coordinator)
            self.audit(connection, run_id=run_id, agent_id=self.coordinator_id,
                       event="context.created")
            return digest

    def publish_epoch(self, run_id: str) -> dict[str, Any]:
        with transaction(self.connection) as connection:
            coordinator = self.hydrate(run_id)
            envelope = coordinator.publish_epoch_manifest()
            self._save_run(connection, coordinator)
            self.audit(connection, run_id=run_id, agent_id=self.coordinator_id,
                       event="epoch.published")
            return envelope

    def evaluate(self, run_id: str) -> dict[str, Any]:
        with transaction(self.connection) as connection:
            coordinator = self.hydrate(run_id)
            input_set_envelope = coordinator.lock_inputs()
            aggregate_path = coordinator.evaluate()
            payload = aggregate_path.read_bytes()
            self.artifacts.put(connection, run_id=run_id, kind="aggregate",
                               payload=payload,
                               expected_sha256=coordinator.aggregate_sha256)
            self._save_run(connection, coordinator)
            self.audit(connection, run_id=run_id, agent_id=self.coordinator_id,
                       event="inputs.evaluated")
            return input_set_envelope

    def create_request(self, run_id: str, *, ttl_seconds: int = 900) -> dict[str, Any]:
        with transaction(self.connection) as connection:
            coordinator = self.hydrate(run_id)
            envelope = coordinator.create_request(now=datetime.now(timezone.utc),
                                                  ttl_seconds=ttl_seconds)
            self._save_run(connection, coordinator)
            self.audit(connection, run_id=run_id, agent_id=self.coordinator_id,
                       event="request.created")
            return envelope

    def fuse(self, run_id: str) -> dict[str, Any]:
        with transaction(self.connection) as connection:
            existing = connection.execute(
                "SELECT receipt_json FROM receipts WHERE run_id = ?", (run_id,)).fetchone()
            if existing is not None:
                return json.loads(existing["receipt_json"])
            coordinator = self.hydrate(run_id)
            receipt = coordinator.fuse(now=datetime.now(timezone.utc))
            document = dict(receipt.__dict__)
            connection.execute(
                "INSERT INTO receipts (run_id, receipt_json, fused_at) VALUES (?, ?, ?)",
                (run_id, json.dumps(document, sort_keys=True), receipt.fused_at))
            self._save_run(connection, coordinator)
            self.audit(connection, run_id=run_id, agent_id=self.coordinator_id,
                       event="run.revealed")
            return document

    def receipt(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT receipt_json FROM receipts WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row["receipt_json"]) if row else None

    def run_row(self, run_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
