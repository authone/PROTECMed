"""Coordinator orchestration and the all-party fusion gate (blueprint 4.2-4.5, 4.7).

The coordinator is not a data provider and holds no FHE secret share. It freezes the
plan, relays public key rounds, verifies submissions, adds ciphertexts, publishes one
immutable request per epoch and — only when every condition of 4.5 holds — calls fusion.

`n` always comes from the frozen local run plan. No API argument can lower it.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .canonical import payload_hash, plus_seconds, require_aware, sha256_hex
from .errors import IntegrityHold, ProtocolError, require
from .identity import Identity, Roster, sign, verify
from .objects import (build_decryption_request, build_epoch_manifest, build_input_set,
                      build_key_round, build_run_plan, key_round_transcript_hash,
                      new_identifier, parse_utc, recipients_hash, role_of, roster_parties,
                      validate_key_round_chain)
from .state import run_machine
from .store import ImmutableOutbox

DEFAULT_REQUEST_TTL_SECONDS = 900


@dataclass
class KeyRoundRecord:
    payload: dict[str, Any]
    envelope: dict[str, Any]
    public_key_bytes: bytes


@dataclass
class SubmissionRecord:
    payload: dict[str, Any]
    envelope: dict[str, Any]
    ciphertext: bytes


@dataclass
class PartialRecord:
    payload: dict[str, Any]
    envelope: dict[str, Any]
    artifact: bytes


@dataclass
class FusionReceipt:
    request_sha256: str
    aggregate: int
    fused_at: str
    partial_sha256: list[str] = field(default_factory=list)


class Coordinator:
    def __init__(self, *, coordinator_id: str, identity: Identity, roster: Roster,
                 study_id: str, worker: Any, storage: Path) -> None:
        self.coordinator_id = coordinator_id
        self.identity = identity
        self.roster = roster
        self.study_id = study_id
        self.worker = worker
        self.storage = Path(storage)
        self.storage.mkdir(parents=True, exist_ok=True)
        self.outbox = ImmutableOutbox(self.storage / "outbox")
        self.state = run_machine("DRAFT")
        self._lock = threading.Lock()

        self.plan: dict[str, Any] | None = None
        self.plan_sha256: str | None = None
        self.plan_envelope: dict[str, Any] | None = None
        self.acceptances: dict[str, dict[str, Any]] = {}
        self.context_path: Path | None = None
        self.context_sha256: str | None = None
        self.key_rounds: list[KeyRoundRecord] = []
        self.epoch_manifest: dict[str, Any] | None = None
        self.epoch_sha256: str | None = None
        self.epoch_envelope: dict[str, Any] | None = None
        self.confirmations: dict[str, dict[str, Any]] = {}
        self.submissions: dict[str, SubmissionRecord] = {}
        self.input_set: dict[str, Any] | None = None
        self.input_set_envelope: dict[str, Any] | None = None
        self.aggregate_path: Path | None = None
        self.aggregate_sha256: str | None = None
        self.request: dict[str, Any] | None = None
        self.request_envelope: dict[str, Any] | None = None
        self.partials: dict[str, PartialRecord] = {}
        self.rejections: dict[str, dict[str, Any]] = {}

    # --- plan ---------------------------------------------------------------
    def create_plan(self, *, run_id: str, roster_entries: Sequence[dict[str, str]],
                    recipient_ids: Sequence[str], query_sha256: str,
                    mapping_sha256: str) -> dict[str, Any]:
        self.state.require("DRAFT")
        plan = build_run_plan(study_id=self.study_id, run_id=run_id, roster=roster_entries,
                              lead_party=roster_entries[0]["party_id"],
                              recipient_ids=recipient_ids, query_sha256=query_sha256,
                              mapping_sha256=mapping_sha256)
        for entry in plan["roster"]:
            self.roster.assert_pinned(entry["party_id"], entry["identity_key_sha256"])
        self.plan = plan
        self.plan_sha256 = payload_hash(plan)
        self.plan_envelope = sign(plan, self.coordinator_id, "run-plan", self.identity)
        return self.plan_envelope

    def record_plan_acceptance(self, envelope: Any) -> None:
        payload = verify(envelope, "plan-acceptance", self.roster)
        party_id = self._roster_signer(envelope, payload)
        require(payload["object_sha256"] == self.plan_sha256, "ACCEPTANCE_OBJECT")
        self._record_once(self.acceptances, party_id, payload, "ACCEPTANCE")
        if len(self.acceptances) == len(roster_parties(self.plan)):
            self.state.transition("PLAN_ACCEPTED")

    # --- context and key rounds ---------------------------------------------
    def create_context(self) -> Path:
        self.state.require("PLAN_ACCEPTED")
        parties = len(roster_parties(self.plan))
        path = self.storage / "context.bin"
        self.worker.run("context-create", ["--parties", str(parties), "--out", path])
        self.context_path = path
        self.context_sha256 = sha256_hex(path.read_bytes())
        self.state.transition("CONTEXT_READY")
        self.state.transition("KEYGEN")
        return path

    def key_round_payload(self, *, round_index: int, party_id: str,
                          outgoing_public_key: bytes) -> dict[str, Any]:
        """Build the payload the party will sign; the coordinator never signs it."""
        incoming = (None if round_index == 0
                    else self.key_rounds[round_index - 1].payload["outgoing_public_key_sha256"])
        return build_key_round(run_id=self.plan["run_id"], run_plan_sha256=self.plan_sha256,
                               context_sha256=self.context_sha256, round_index=round_index,
                               party_id=party_id,
                               incoming_public_key_sha256=incoming,
                               outgoing_public_key_sha256=sha256_hex(outgoing_public_key))

    def record_key_round(self, envelope: Any, public_key_bytes: bytes) -> None:
        self.state.require("KEYGEN")
        payload = verify(envelope, "key-round", self.roster)
        parties = roster_parties(self.plan)
        index = payload["round_index"]
        require(index == len(self.key_rounds), "KEY_ROUND_OUT_OF_ORDER")
        require(envelope["signer_id"] == parties[index], "KEY_ROUND_WRONG_PARTY")
        require(payload["party_id"] == envelope["signer_id"], "KEY_ROUND_SIGNER_CLAIM")
        require(payload["outgoing_public_key_sha256"] == sha256_hex(public_key_bytes),
                "KEY_ROUND_ARTIFACT_HASH")
        self.key_rounds.append(KeyRoundRecord(payload, envelope, public_key_bytes))

    def publish_epoch_manifest(self) -> dict[str, Any]:
        self.state.require("KEYGEN")
        rounds = [record.payload for record in self.key_rounds]
        final_key_hash = validate_key_round_chain(rounds, self.plan,
                                                  run_plan_sha256=self.plan_sha256,
                                                  context_sha256=self.context_sha256)
        manifest = build_epoch_manifest(
            run_id=self.plan["run_id"], epoch_id=new_identifier("epoch"),
            run_plan_sha256=self.plan_sha256, context_sha256=self.context_sha256,
            final_public_key_sha256=final_key_hash,
            key_round_transcript_sha256=key_round_transcript_hash(rounds))
        self.epoch_manifest = manifest
        self.epoch_sha256 = payload_hash(manifest)
        self.epoch_envelope = sign(manifest, self.coordinator_id, "epoch-manifest",
                                   self.identity)
        return self.epoch_envelope

    def record_epoch_confirmation(self, envelope: Any) -> None:
        payload = verify(envelope, "epoch-confirmation", self.roster)
        party_id = self._roster_signer(envelope, payload)
        require(payload["object_sha256"] == self.epoch_sha256, "CONFIRMATION_OBJECT")
        self._record_once(self.confirmations, party_id, payload, "CONFIRMATION")
        if len(self.confirmations) == len(roster_parties(self.plan)):
            self.state.transition("EPOCH_CONFIRMED")
            self.state.transition("COLLECTING")

    # --- submissions ---------------------------------------------------------
    def accept_submission(self, envelope: Any, ciphertext: bytes) -> None:
        # No input ciphertext is accepted before every epoch confirmation is present.
        self.state.require("COLLECTING")
        payload = verify(envelope, "encrypted-count", self.roster)
        party_id = self._roster_signer(envelope, payload)
        require(payload["run_id"] == self.plan["run_id"], "SUBMISSION_RUN")
        require(payload["epoch_sha256"] == self.epoch_sha256, "SUBMISSION_EPOCH")
        require(payload["query_sha256"] == self.plan["query_sha256"], "SUBMISSION_QUERY")
        entry = {e["party_id"]: e for e in self.plan["roster"]}[party_id]
        require(payload["snapshot_token"] == entry["snapshot_token"], "SUBMISSION_SNAPSHOT")
        require(sha256_hex(ciphertext) == payload["ciphertext_sha256"], "SUBMISSION_HASH")
        require(len(ciphertext) == payload["ciphertext_size"], "SUBMISSION_SIZE")
        existing = self.submissions.get(party_id)
        if existing is not None:
            # A byte-identical retry is a no-op; anything else is a conflict.
            if existing.envelope == envelope and existing.ciphertext == ciphertext:
                return
            self._integrity_hold("CONFLICTING_SUBMISSION", party_id)
        self.submissions[party_id] = SubmissionRecord(payload, envelope, ciphertext)

    def lock_inputs(self) -> dict[str, Any]:
        self.state.require("COLLECTING")
        parties = roster_parties(self.plan)
        require(set(self.submissions) == set(parties), "INPUT_SET_INCOMPLETE")
        tags = {record.payload["final_key_tag"] for record in self.submissions.values()}
        require(len(tags) == 1, "INPUT_KEY_TAG_DISAGREEMENT")
        entries = [{"party_id": party_id,
                    "submission_sha256": payload_hash(self.submissions[party_id].payload),
                    "ciphertext_sha256": self.submissions[party_id].payload["ciphertext_sha256"]}
                   for party_id in parties]
        self.input_set = build_input_set(run_id=self.plan["run_id"],
                                         epoch_sha256=self.epoch_sha256, entries=entries)
        self.input_set_envelope = sign(self.input_set, self.coordinator_id, "input-set",
                                       self.identity)
        self.state.transition("INPUTS_LOCKED")
        return self.input_set_envelope

    def evaluate(self) -> Path:
        self.state.require("INPUTS_LOCKED")
        parties = roster_parties(self.plan)
        flags: list[Any] = []
        for party_id in parties:
            path = self.storage / f"input-{party_id}.bin"
            if not path.exists():
                path.write_bytes(self.submissions[party_id].ciphertext)
            flags += ["--input", path]
        aggregate = self.storage / "aggregate.bin"
        tag = next(iter({r.payload["final_key_tag"] for r in self.submissions.values()}))
        self.worker.run("add-counts", ["--context", self.context_path, *flags,
                                       "--expect-key-tag", tag, "--out", aggregate])
        self.aggregate_path = aggregate
        self.aggregate_sha256 = sha256_hex(aggregate.read_bytes())
        self.state.transition("EVALUATED")
        return aggregate

    # --- request -------------------------------------------------------------
    def create_request(self, *, now: datetime,
                       ttl_seconds: int = DEFAULT_REQUEST_TTL_SECONDS) -> dict[str, Any]:
        self.state.require("EVALUATED")
        require(self.request is None, "REQUEST_ALREADY_ISSUED")  # one request per epoch
        moment = require_aware(now)
        parties = roster_parties(self.plan)
        self.request = build_decryption_request(
            study_id=self.study_id, run_id=self.plan["run_id"],
            request_id=new_identifier("req"), epoch_sha256=self.epoch_sha256,
            query_sha256=self.plan["query_sha256"],
            input_set_sha256=payload_hash(self.input_set),
            aggregate_sha256=self.aggregate_sha256,
            recipients_sha256=recipients_hash(self.plan["recipient_ids"]),
            required_parties=parties, lead_party=self.plan["lead_party"],
            created_at=moment, expires_at=plus_seconds(moment, ttl_seconds))
        self.request_envelope = sign(self.request, self.coordinator_id,
                                     "decryption-request", self.identity)
        self.state.transition("APPROVAL_PENDING")
        return self.request_envelope

    def accept_partial(self, envelope: Any, artifact: bytes) -> None:
        self.state.require("APPROVAL_PENDING", "PARTIALS_IN_PROGRESS")
        payload = verify(envelope, "partial", self.roster)
        party_id = self._roster_signer(envelope, payload)
        require(party_id not in self.rejections, "PARTY_ALREADY_REJECTED")
        require(payload["request_sha256"] == payload_hash(self.request), "PARTIAL_REQUEST")
        require(payload["epoch_sha256"] == self.epoch_sha256, "PARTIAL_EPOCH")
        require(payload["aggregate_sha256"] == self.aggregate_sha256, "PARTIAL_AGGREGATE")
        require(payload["role"] == role_of(self.plan, party_id), "PARTIAL_ROLE")
        require(payload["decision"] == "APPROVE", "PARTIAL_DECISION")
        require(sha256_hex(artifact) == payload["partial_sha256"], "PARTIAL_HASH")
        require(len(artifact) == payload["partial_size"], "PARTIAL_SIZE")
        created = parse_utc(self.request["created_at"])
        approved = parse_utc(payload["approved_at"])
        require(created <= approved < parse_utc(self.request["expires_at"]),
                "PARTIAL_APPROVAL_TIME")
        existing = self.partials.get(party_id)
        if existing is not None:
            if existing.envelope == envelope and existing.artifact == artifact:
                return
            self._integrity_hold("CONFLICTING_PARTIAL", party_id)
        self.partials[party_id] = PartialRecord(payload, envelope, artifact)
        if self.state.state == "APPROVAL_PENDING":
            self.state.transition("PARTIALS_IN_PROGRESS")

    def accept_rejection(self, envelope: Any) -> None:
        self.state.require("APPROVAL_PENDING", "PARTIALS_IN_PROGRESS")
        payload = verify(envelope, "rejection", self.roster)
        party_id = self._roster_signer(envelope, payload)
        require(payload["request_sha256"] == payload_hash(self.request), "REJECTION_REQUEST")
        require(payload["decision"] == "REJECT", "REJECTION_DECISION")
        if party_id in self.partials:
            self._integrity_hold("REJECTION_AFTER_PARTIAL", party_id)
        self.rejections[party_id] = payload

    # --- the all-party gate (blueprint 4.5) ----------------------------------
    def authorize_fusion(self, *, now: datetime) -> list[Path]:
        """Every condition of 4.5, or an exception. Never returns a partial set early."""
        moment = require_aware(now)
        require(self.state.state == "PARTIALS_IN_PROGRESS", "RUN_NOT_AWAITING_FUSION",
                {"state": self.state.state})
        require(self.plan is not None and self.request is not None, "RUN_INCOMPLETE")

        parties = roster_parties(self.plan)
        # n comes from the frozen plan; no caller argument can lower it.
        require(len(self.confirmations) == len(parties), "EPOCH_NOT_FULLY_CONFIRMED")
        require(set(self.confirmations) == set(parties), "EPOCH_CONFIRMATION_SET")
        require(not self.rejections, "REJECTION_PRESENT", {"parties": sorted(self.rejections)})

        # the immutable request and input set still match the frozen run
        require(payload_hash(self.input_set) == self.request["input_set_sha256"],
                "INPUT_SET_CHANGED")
        require(self.request["aggregate_sha256"] == self.aggregate_sha256,
                "AGGREGATE_CHANGED")
        require(self.request["query_sha256"] == self.plan["query_sha256"], "QUERY_CHANGED")
        require(self.request["recipients_sha256"] == recipients_hash(self.plan["recipient_ids"]),
                "RECIPIENTS_CHANGED")
        require(self.request["epoch_sha256"] == self.epoch_sha256, "EPOCH_CHANGED")
        require(self.request["required_parties"] == parties, "ROSTER_CHANGED")

        # the honest application refuses to complete a release after expiry
        require(parse_utc(self.request["created_at"]) <= moment <
                parse_utc(self.request["expires_at"]), "REQUEST_EXPIRED")

        # the set of verified partial signers is EXACTLY the roster
        require(set(self.partials) == set(parties), "PARTIAL_SET_INCOMPLETE",
                {"missing": sorted(set(parties) - set(self.partials))})
        roles = [self.partials[party_id].payload["role"] for party_id in parties]
        require(roles.count("lead") == 1 and roles[0] == "lead", "PARTIAL_LEAD_SET")
        require(roles.count("main") == len(parties) - 1, "PARTIAL_MAIN_SET")

        request_hash = payload_hash(self.request)
        digests = set()
        for party_id in parties:
            record = self.partials[party_id]
            require(record.payload["party_id"] == party_id, "PARTIAL_PARTY_CLAIM")
            require(record.envelope["signer_id"] == party_id, "PARTIAL_SIGNER")
            require(record.payload["request_sha256"] == request_hash, "PARTIAL_REQUEST_HASH")
            require(record.payload["epoch_sha256"] == self.epoch_sha256, "PARTIAL_EPOCH_HASH")
            require(record.payload["aggregate_sha256"] == self.aggregate_sha256,
                    "PARTIAL_AGGREGATE_HASH")
            require(sha256_hex(record.artifact) == record.payload["partial_sha256"],
                    "PARTIAL_ARTIFACT_HASH")
            require(record.payload["partial_sha256"] not in digests, "PARTIAL_DUPLICATE_BYTES")
            digests.add(record.payload["partial_sha256"])

        require(self.outbox.get(self._receipt_key()) is None, "FUSION_RECEIPT_EXISTS")

        ordered = []
        for party_id in parties:
            path = self.storage / f"partial-{party_id}.bin"
            if not path.exists():
                path.write_bytes(self.partials[party_id].artifact)
            ordered.append(path)
        return ordered

    def fuse(self, *, now: datetime) -> FusionReceipt:
        """Serialized under an exclusive run lock; a stored receipt answers retries."""
        with self._lock:
            stored = self.outbox.get(self._receipt_key())
            if stored is not None:
                receipt = stored.receipt["receipt"]
                return FusionReceipt(**receipt)
            ordered = self.authorize_fusion(now=now)
            flags: list[Any] = []
            for path in ordered:
                flags += ["--partial", path]
            result = self.worker.run("fuse", ["--context", self.context_path, "--parties",
                                              str(len(ordered)), *flags])
            aggregate = result.payload["aggregate"]
            receipt = FusionReceipt(
                request_sha256=payload_hash(self.request), aggregate=aggregate,
                fused_at=require_aware(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
                partial_sha256=[self.partials[p].payload["partial_sha256"]
                                for p in roster_parties(self.plan)])
            key = self._receipt_key()
            self.outbox.reserve(key)
            self.outbox.commit(key, str(aggregate).encode("ascii"),
                               {"receipt": receipt.__dict__})
            self.state.transition("REVEALED")
            return receipt

    def _receipt_key(self) -> str:
        return self.outbox.key(self.plan["run_id"], self.coordinator_id, "fusion-receipt")

    # --- helpers -------------------------------------------------------------
    def _roster_signer(self, envelope: dict[str, Any], payload: dict[str, Any]) -> str:
        party_id = envelope["signer_id"]
        require(party_id in roster_parties(self.plan), "SIGNER_NOT_IN_ROSTER")
        if "party_id" in payload:
            require(payload["party_id"] == party_id, "SIGNER_CLAIM_MISMATCH")
        if "run_id" in payload:
            require(payload["run_id"] == self.plan["run_id"], "SIGNER_RUN_MISMATCH")
        return party_id

    @staticmethod
    def _record_once(store: dict[str, Any], party_id: str, payload: dict[str, Any],
                     token: str) -> None:
        existing = store.get(party_id)
        if existing is not None and existing != payload:
            raise IntegrityHold(f"CONFLICTING_{token}", {"party": party_id})
        store[party_id] = payload

    def _integrity_hold(self, token: str, party_id: str) -> None:
        """Authenticated conflicting messages stop the run and need operator review.

        A forged or unauthenticated message never reaches here: it is rejected by
        signature verification, so a network user cannot trivially abort a run.
        """
        self.state.transition("INTEGRITY_HOLD")
        raise IntegrityHold(token, {"party": party_id})
