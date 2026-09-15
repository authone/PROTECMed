"""End-to-end harness: signed protocol (M3) driving the real OpenFHE worker (M2).

Separate directories on one host are a SIMULATION of institutional separation. Counts
here are invented; no clinical value appears anywhere.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from protecmed_protocol.coordinator import Coordinator
from protecmed_protocol.identity import Identity, Roster
from protecmed_protocol.party import LocalParty
from protecmed_protocol.store import DisclosureLedger, ImmutableOutbox
from protecmed_worker import WorkerClient

STUDY_ID = "synthetic-study"
QUERY_SHA256 = "a" * 64
MAPPING_SHA256 = "b" * 64
RECIPIENTS = ["recipient-one"]
NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)


class CountingWorker:
    """Wraps the real worker so a test can prove which subcommands were invoked."""

    def __init__(self, client: WorkerClient) -> None:
        self._client = client
        self.calls: list[str] = []

    def run(self, command: str, arguments=(), **kwargs):
        self.calls.append(command)
        return self._client.run(command, arguments, **kwargs)

    def count(self, command: str) -> int:
        return self.calls.count(command)


@dataclass
class Deployment:
    root: Path
    binary: Path
    library: Path
    party_count: int
    run_id: str = "synthetic-run"
    coordinator: Coordinator = field(init=False)
    parties: dict[str, LocalParty] = field(init=False)
    workers: dict[str, CountingWorker] = field(init=False)

    def __post_init__(self) -> None:
        names = ["party-a", "party-b", "party-c"][: self.party_count]
        self.coordinator_id = "coordinator"
        identities = {name: Identity.generate(name) for name in names}
        identities[self.coordinator_id] = Identity.generate(self.coordinator_id)
        # Fingerprints are compared out of band before the roster is locked.
        self.roster = Roster.from_identities(identities.values())
        self.identities = identities
        self.snapshot_tokens = {name: f"snap-{index:028x}"
                                for index, name in enumerate(names, start=1)}

        self.workers = {}
        self.parties = {}
        coordinator_worker = self._worker(self.coordinator_id)
        self.coordinator = Coordinator(
            coordinator_id=self.coordinator_id, identity=identities[self.coordinator_id],
            roster=self.roster, study_id=STUDY_ID, worker=coordinator_worker,
            storage=self._private(self.coordinator_id))
        for name in names:
            private = self._private(name)
            self.parties[name] = LocalParty(
                party_id=name, identity=identities[name], roster=self.roster,
                coordinator_id=self.coordinator_id, study_id=STUDY_ID,
                worker=self._worker(name), outbox=ImmutableOutbox(private / "outbox"),
                ledger=DisclosureLedger(private / "disclosure.jsonl"),
                job_directory=private / "jobs")
        self.names = names

    def _private(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    def _worker(self, name: str) -> CountingWorker:
        worker = CountingWorker(WorkerClient(self.binary, library_path=self.library))
        self.workers[name] = worker
        return worker

    # --- protocol phases -----------------------------------------------------
    def freeze_plan(self) -> None:
        entries = [{"party_id": name,
                    "identity_key_sha256": self.identities[name].fingerprint,
                    "snapshot_token": self.snapshot_tokens[name]} for name in self.names]
        plan_envelope = self.coordinator.create_plan(
            run_id=self.run_id, roster_entries=entries, recipient_ids=RECIPIENTS,
            query_sha256=QUERY_SHA256, mapping_sha256=MAPPING_SHA256)
        for name in self.names:
            acceptance = self.parties[name].accept_plan(
                plan_envelope, snapshot_token=self.snapshot_tokens[name],
                query_sha256=QUERY_SHA256, mapping_sha256=MAPPING_SHA256, now=NOW)
            self.coordinator.record_plan_acceptance(acceptance)

    def run_key_ceremony(self) -> None:
        context = self.coordinator.create_context()
        previous_public: Path | None = None
        for index, name in enumerate(self.names):
            private = self._private(name)
            share = private / "share.bin"
            outgoing = private / "public-out.bin"
            worker = self.workers[name]
            if index == 0:
                worker.run("keygen-first", ["--context", context, "--secret-out", share,
                                            "--public-out", outgoing])
            else:
                worker.run("keygen-next", ["--context", context, "--incoming",
                                           previous_public, "--secret-out", share,
                                           "--public-out", outgoing])
            public_bytes = outgoing.read_bytes()
            payload = self.coordinator.key_round_payload(
                round_index=index, party_id=name, outgoing_public_key=public_bytes)
            envelope = self.parties[name].sign_key_round(
                payload, outgoing_public_key=public_bytes, expected_round=index)
            self.coordinator.record_key_round(envelope, public_bytes)
            self.parties[name].register_share(share_path=share)
            previous_public = outgoing
        self.final_public_key = previous_public
        self.context_path = context

    def confirm_epoch(self) -> None:
        manifest_envelope = self.coordinator.publish_epoch_manifest()
        rounds = [record.envelope for record in self.coordinator.key_rounds]
        tag = self.workers[self.coordinator_id]._client.run(
            "inspect-public", ["--context", self.context_path, "--type", "public-key",
                               "--artifact", self.final_public_key]).payload["key_tag"]
        self.final_key_tag = tag
        for name in self.names:
            confirmation = self.parties[name].confirm_epoch(
                manifest_envelope, rounds, context_path=self.context_path,
                final_public_key_path=self.final_public_key, final_key_tag=tag, now=NOW)
            self.coordinator.record_epoch_confirmation(confirmation)

    def submit(self, counts: list[int]) -> None:
        for name, count in zip(self.names, counts):
            envelope, ciphertext = self.parties[name].submit_count(count)
            self.coordinator.accept_submission(envelope, ciphertext)

    def evaluate(self) -> None:
        self.input_set_envelope = self.coordinator.lock_inputs()
        self.aggregate_path = self.coordinator.evaluate()

    def issue_request(self, *, now: datetime = NOW, ttl_seconds: int = 900) -> dict[str, Any]:
        self.request_envelope = self.coordinator.create_request(now=now,
                                                               ttl_seconds=ttl_seconds)
        return self.request_envelope

    def published_inputs(self) -> dict[str, bytes]:
        return {record.payload["ciphertext_sha256"]: record.ciphertext
                for record in self.coordinator.submissions.values()}

    def submission_envelopes(self) -> list[dict[str, Any]]:
        return [self.coordinator.submissions[name].envelope for name in self.names]

    def verify(self, name: str, *, now: datetime = NOW):
        return self.parties[name].verify_request(
            self.request_envelope, self.input_set_envelope, self.submission_envelopes(),
            self.published_inputs(), self.aggregate_path.read_bytes(), now=now)

    def approve(self, name: str, *, now: datetime = NOW, operator_approved: bool = True):
        verification = self.verify(name, now=now)
        envelope, artifact = self.parties[name].approve(
            verification, operator_approved=operator_approved, now=now)
        self.coordinator.accept_partial(envelope, artifact)
        return envelope, artifact

    def up_to_request(self, counts: list[int], **kwargs) -> None:
        self.freeze_plan()
        self.run_key_ceremony()
        self.confirm_epoch()
        self.submit(counts)
        self.evaluate()
        self.issue_request(**kwargs)
