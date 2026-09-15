"""Party agent runtime: the local steps of blueprint 5.5, wired to M1, M2 and M3.

Local counts, the source digest, the validation report and the canonical rows stay on
this endpoint. Only signed protocol objects and public/encrypted artifacts go out.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protecmed_party.catalogue import count_query, load_catalogue
from protecmed_party.importer import (LITERAL_ONLY, REVIEWED_CACHED, file_digest,
                                      import_workbook, load_mapping, read_canonical_csv)
from protecmed_party.snapshot import Snapshot, SnapshotStore, freeze
from protecmed_protocol.canonical import payload_hash, sha256_hex
from protecmed_protocol.errors import ProtocolError, require
from protecmed_protocol.identity import Identity, Roster
from protecmed_protocol.objects import build_key_round
from protecmed_protocol.party import LocalParty
from protecmed_protocol.store import DisclosureLedger, ImmutableOutbox

from .importdir import ImportDirectory
from .poller import CoordinatorClient


def load_or_create_identity(path: Path) -> Ed25519PrivateKey:
    path = Path(path)
    if path.exists():
        return Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(path.read_text(encoding="ascii").strip()))
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(key.private_bytes_raw().hex())
    return key


@dataclass
class ImportStatus:
    file_name: str | None = None
    mode: str | None = None
    admitted_rows: int | None = None
    skipped_blank_rows: int | None = None
    snapshot_token: str | None = None
    formula_cells: int = 0
    cache_freshness_verified: bool = False
    external_link_parts: int = 0


class AgentRuntime:
    """One provider endpoint. Holds the local snapshot, the share and the outbox."""

    def __init__(self, *, party_id: str, private_directory: Path, import_directory: Path,
                 registry_directory: Path, worker: Any, catalogue_path: Path,
                 mapping_path: Path, coordinator: CoordinatorClient,
                 study_id: str, coordinator_id: str = "coordinator",
                 roster: Roster | None = None) -> None:
        self.party_id = party_id
        self.private = Path(private_directory)
        self.private.mkdir(parents=True, exist_ok=True)
        os.chmod(self.private, 0o700)
        self.import_directory = ImportDirectory(import_directory)
        self.worker = worker
        self.coordinator = coordinator
        self.study_id = study_id
        self.coordinator_id = coordinator_id
        self.catalogue = load_catalogue(catalogue_path)
        self.mapping = load_mapping(mapping_path)
        self.mapping_sha256 = sha256_hex(Path(mapping_path).read_bytes())
        self.identity = Identity(party_id,
                                 load_or_create_identity(self.private / "identity.key"))
        self.roster = roster or Roster({party_id: self.identity.public_key})
        self.snapshot_store = SnapshotStore(Path(registry_directory))
        self.outbox = ImmutableOutbox(self.private / "outbox")
        self.ledger = DisclosureLedger(self.private / "disclosure.jsonl")
        self.party = self._new_local_party()
        self.snapshot: Snapshot | None = None
        self.import_status = ImportStatus()
        self.local_count: int | None = None
        self.local_report: dict[str, Any] | None = None
        self.verification = None
        self.run_id: str | None = None
        self.decision: str | None = None

    def _new_local_party(self) -> LocalParty:
        return LocalParty(party_id=self.party_id, identity=self.identity,
                          roster=self.roster, coordinator_id=self.coordinator_id,
                          study_id=self.study_id, worker=self.worker,
                          outbox=self.outbox, ledger=self.ledger,
                          job_directory=self.private / "jobs")

    def pin_roster(self, roster: Roster) -> None:
        """Identity fingerprints are compared out of band before the roster is locked."""
        self.roster = roster
        self.party.roster = roster

    # --- 1. import and validate ---------------------------------------------
    def list_import_files(self) -> list[dict[str, object]]:
        return self.import_directory.listing()

    def import_selected(self, token: str, *, mode: str = LITERAL_ONLY,
                        operator: str = "local-operator",
                        acknowledge_cache: bool = False) -> ImportStatus:
        path = self.import_directory.resolve(token)
        if path.suffix.lower() == ".csv":
            records, report = read_canonical_csv(path)
        else:
            acknowledgement = None
            if mode == REVIEWED_CACHED:
                require(acknowledge_cache, "CACHE_ACKNOWLEDGEMENT_REQUIRED")
                acknowledgement = {
                    "operator": operator,
                    "acknowledged_utc": datetime.now(timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source_sha256": file_digest(path),
                    "mapping_id": self.mapping.mapping_id,
                    "statement": "Operator confirms IOCN recalculated and saved this file.",
                }
            records, report = import_workbook(path, self.mapping, mode,
                                              cache_acknowledgement=acknowledgement)
        self.snapshot = freeze(records, report, source_sha256=file_digest(path),
                               mapping_id=self.mapping.mapping_id,
                               mapping_digest=self.mapping.digest)
        self.snapshot_store.save(self.snapshot)
        self.snapshot_store.supersede_others(self.snapshot.snapshot_token)
        self.local_report = report
        self.import_status = ImportStatus(
            file_name=path.name, mode=report.get("import_mode"),
            admitted_rows=report.get("admitted_rows"),
            skipped_blank_rows=report.get("skipped_blank_rows"),
            snapshot_token=self.snapshot.snapshot_token,
            formula_cells=sum(report.get("selected_formula_cells", {}).values()),
            cache_freshness_verified=bool(report.get("cache_freshness_verified")),
            external_link_parts=int(report.get("external_link_parts_not_refreshed", 0)))
        # A new snapshot invalidates any unfinished run that used the previous one.
        self.party = self._new_local_party()
        self.local_count = None
        return self.import_status

    # --- 2. plan -------------------------------------------------------------
    def query_for(self, query_sha256: str) -> dict[str, Any]:
        """Render the query from the local approved catalogue, never from the message."""
        for entry in self.catalogue:
            if payload_hash(entry) == query_sha256:
                return entry
        raise ProtocolError("QUERY_NOT_IN_LOCAL_CATALOGUE")

    def accept_plan(self, run_id: str) -> dict[str, Any]:
        require(self.snapshot is not None, "NO_SNAPSHOT")
        state = self.coordinator.get_run(run_id)
        envelope = state["plan_envelope"]
        query_sha256 = envelope["payload"]["query_sha256"]
        self.query_for(query_sha256)  # must exist locally before we accept anything
        acceptance = self.party.accept_plan(
            envelope, snapshot_token=self.snapshot.snapshot_token,
            query_sha256=query_sha256, mapping_sha256=self.mapping_sha256,
            now=datetime.now(timezone.utc))
        self.run_id = run_id
        return self.coordinator.post_envelope(
            run_id, "plan-acceptances", acceptance,
            self.coordinator.stable_key(run_id, self.party_id, "plan-acceptance"))

    # --- 3. key round and epoch ---------------------------------------------
    def key_round(self, run_id: str) -> dict[str, Any]:
        state = self.coordinator.get_run(run_id)
        context = self._artifact(run_id, state["context_sha256"], "context.bin")
        index = len(state["key_rounds"])
        share = self.private / "share.bin"
        outgoing = self.private / "public-out.bin"
        for path in (share, outgoing):
            if path.exists():
                path.unlink()
        if index == 0:
            self.worker.run("keygen-first", ["--context", context, "--secret-out", share,
                                             "--public-out", outgoing])
            incoming = None
        else:
            previous = state["key_rounds"][index - 1]["payload"]["outgoing_public_key_sha256"]
            previous_path = self._artifact(run_id, previous, f"pk-{index - 1}.bin")
            self.worker.run("keygen-next", ["--context", context, "--incoming",
                                            previous_path, "--secret-out", share,
                                            "--public-out", outgoing])
            incoming = previous
        public_bytes = outgoing.read_bytes()
        payload = build_key_round(
            run_id=run_id, run_plan_sha256=self.party.plan_sha256,
            context_sha256=state["context_sha256"], round_index=index,
            party_id=self.party_id, incoming_public_key_sha256=incoming,
            outgoing_public_key_sha256=sha256_hex(public_bytes))
        envelope = self.party.sign_key_round(payload, outgoing_public_key=public_bytes,
                                             expected_round=index)
        self.party.register_share(share_path=share)
        return self.coordinator.post_artifact(
            run_id, "key-rounds", envelope, public_bytes,
            self.coordinator.stable_key(run_id, self.party_id, "key-round"))

    def confirm_epoch(self, run_id: str) -> dict[str, Any]:
        state = self.coordinator.get_run(run_id)
        manifest = state["epoch_envelope"]
        require(manifest is not None, "EPOCH_NOT_PUBLISHED")
        context = self._artifact(run_id, state["context_sha256"], "context.bin")
        final_hash = manifest["payload"]["final_public_key_sha256"]
        public_key = self._artifact(run_id, final_hash, "final-public-key.bin")
        tag = self.worker.run("inspect-public",
                              ["--context", context, "--type", "public-key",
                               "--artifact", public_key]).payload["key_tag"]
        confirmation = self.party.confirm_epoch(
            manifest, state["key_rounds"], context_path=context,
            final_public_key_path=public_key, final_key_tag=tag,
            now=datetime.now(timezone.utc))
        return self.coordinator.post_envelope(
            run_id, "epoch-confirmations", confirmation,
            self.coordinator.stable_key(run_id, self.party_id, "epoch-confirmation"))

    # --- 4. count and submit -------------------------------------------------
    def prepare_count(self) -> int:
        """Evaluate the frozen query on the frozen snapshot. Local display only."""
        require(self.snapshot is not None, "NO_SNAPSHOT")
        require(self.party.query_sha256 is not None, "PLAN_NOT_ACCEPTED")
        query = self.query_for(self.party.query_sha256)
        result = count_query(self.snapshot.records, query, self.catalogue)
        self.local_count = result["count"]
        self.local_query_report = result
        return self.local_count

    def encrypt_submit(self, run_id: str) -> dict[str, Any]:
        require(self.local_count is not None, "COUNT_NOT_PREPARED")
        envelope, ciphertext = self.party.submit_count(self.local_count)
        return self.coordinator.post_artifact(
            run_id, "submissions", envelope, ciphertext,
            self.coordinator.stable_key(run_id, self.party_id, "submission"))

    # --- 5. review, approve, reject -----------------------------------------
    def review_request(self, run_id: str):
        state = self.coordinator.get_run(run_id)
        require(state["request_envelope"] is not None, "NO_REQUEST")
        ciphertexts = {}
        for envelope in state["submission_envelopes"]:
            digest = envelope["payload"]["ciphertext_sha256"]
            ciphertexts[digest] = self.coordinator.get_artifact(run_id, digest)
        aggregate = self.coordinator.get_artifact(run_id, state["aggregate_sha256"])
        self.verification = self.party.verify_request(
            state["request_envelope"], state["input_set_envelope"],
            state["submission_envelopes"], ciphertexts, aggregate,
            now=datetime.now(timezone.utc))
        return self.verification

    def approve(self, run_id: str) -> dict[str, Any]:
        """Called only from an authenticated local form submission."""
        require(self.verification is not None, "REQUEST_NOT_REVIEWED")
        envelope, artifact = self.party.approve(
            self.verification, operator_approved=True, now=datetime.now(timezone.utc))
        self.decision = "APPROVE"
        return self.coordinator.post_artifact(
            run_id, "partials", envelope, artifact,
            self.coordinator.stable_key(run_id, self.party_id, "partial"))

    def reject(self, run_id: str, reason_code: str = "OPERATOR_DECLINED") -> dict[str, Any]:
        state = self.coordinator.get_run(run_id)
        request = state["request_envelope"]["payload"]
        envelope = self.party.reject(request, reason_code=reason_code,
                                     now=datetime.now(timezone.utc))
        self.decision = "REJECT"
        return self.coordinator.post_envelope(
            run_id, "rejections", envelope,
            self.coordinator.stable_key(run_id, self.party_id, "rejection"))

    # --- status --------------------------------------------------------------
    def status(self, run_id: str | None = None) -> dict[str, Any]:
        remote: dict[str, Any] = {}
        if run_id:
            remote = self.coordinator.get_run(run_id)
        return {
            "party_id": self.party_id,
            "local_state": self.party.state.state,
            "import": self.import_status.__dict__,
            "local_count": self.local_count,
            "decision": self.decision,
            "run_state": remote.get("state"),
            "accepted_by": remote.get("accepted_by", []),
            "confirmed_by": remote.get("confirmed_by", []),
            "submitted_by": remote.get("submitted_by", []),
            "approved_by": remote.get("approved_by", []),
            "rejected_by": remote.get("rejected_by", []),
            "has_request": remote.get("request_envelope") is not None,
        }

    def _artifact(self, run_id: str, digest: str, name: str) -> Path:
        path = self.private / "artifacts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or sha256_hex(path.read_bytes()) != digest:
            path.write_bytes(self.coordinator.get_artifact(run_id, digest))
        return path
