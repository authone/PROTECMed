"""The local provider gate (blueprint 4.4, 4.5) — the application half of unanimity.

OpenFHE does not know which hospital signed an approval. Everything that makes a release
*unanimous* lives here: the pinned roster, the exact input set, the recomputed aggregate,
the epoch binding of the local share, the disclosure ledger and an authenticated local
operator action. `isValid` is not consent and a signature over an opaque hash is not
proof that the approved operation was performed.

Nothing in this module may produce a partial without passing every check below.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .canonical import payload_hash, require_aware, sha256_hex
from .errors import ProtocolError, require
from .identity import Identity, Roster, sign, verify
from .objects import (build_acknowledgement, build_encrypted_count, build_partial,
                      build_rejection, key_round_transcript_hash, recipients_hash,
                      request_is_live, role_of, roster_parties, validate_decryption_request,
                      validate_key_round_chain, validate_run_plan)
from .store import DisclosureLedger, ImmutableOutbox
from .state import party_machine


@dataclass(frozen=True)
class EpochBinding:
    """This party's share, bound to one epoch. A share from another epoch is not usable."""

    epoch_sha256: str
    context_path: Path
    final_public_key_path: Path
    share_path: Path
    final_key_tag: str


@dataclass
class RequestVerification:
    request: dict[str, Any]
    request_sha256: str
    role: str
    ordered_ciphertexts: list[Path]
    aggregate_path: Path
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        return bool(self.checks) and all(self.checks.values())


class LocalParty:
    def __init__(self, *, party_id: str, identity: Identity, roster: Roster,
                 coordinator_id: str, study_id: str, worker: Any,
                 outbox: ImmutableOutbox, ledger: DisclosureLedger,
                 job_directory: Path) -> None:
        self.party_id = party_id
        self.identity = identity
        self.roster = roster
        self.coordinator_id = coordinator_id
        self.study_id = study_id
        self.worker = worker
        self.outbox = outbox
        self.ledger = ledger
        self.jobs = Path(job_directory)
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.state = party_machine("IMPORTED")
        self.plan: dict[str, Any] | None = None
        self.plan_sha256: str | None = None
        self.query_sha256: str | None = None
        self.snapshot_token: str | None = None
        self.epoch: EpochBinding | None = None

    # --- plan ---------------------------------------------------------------
    def accept_plan(self, envelope: Any, *, snapshot_token: str, query_sha256: str,
                    mapping_sha256: str, now: datetime) -> dict[str, Any]:
        plan = verify(envelope, "run-plan", self.roster)
        require(envelope["signer_id"] == self.coordinator_id, "PLAN_NOT_FROM_COORDINATOR")
        validate_run_plan(plan)
        require(plan["study_id"] == self.study_id, "PLAN_STUDY")
        entries = {entry["party_id"]: entry for entry in plan["roster"]}
        require(self.party_id in entries, "PLAN_PARTY_NOT_IN_ROSTER")
        # Every roster identity must be one this endpoint already pinned out of band.
        for party_id, entry in entries.items():
            self.roster.assert_pinned(party_id, entry["identity_key_sha256"])
        require(entries[self.party_id]["snapshot_token"] == snapshot_token,
                "PLAN_SNAPSHOT_TOKEN")
        require(plan["query_sha256"] == query_sha256, "PLAN_QUERY_HASH")
        require(plan["mapping_sha256"] == mapping_sha256, "PLAN_MAPPING_HASH")
        self.plan = plan
        self.plan_sha256 = payload_hash(plan)
        self.query_sha256 = query_sha256
        self.snapshot_token = snapshot_token
        self.state.transition("PLAN_ACCEPTED")
        return self._sign("plan-acceptance",
                          build_acknowledgement(run_id=plan["run_id"],
                                                party_id=self.party_id,
                                                object_sha256=self.plan_sha256, at=now))

    # --- epoch --------------------------------------------------------------
    def register_share(self, *, share_path: Path) -> None:
        """Record that a private share now exists locally for the run in progress."""
        require(self.plan is not None, "PLAN_NOT_ACCEPTED")
        require(Path(share_path).is_file(), "SHARE_MISSING")
        self.state.transition("SHARE_CREATED")
        self._share_path = Path(share_path)

    def sign_key_round(self, payload: dict[str, Any], *, outgoing_public_key: bytes,
                       expected_round: int) -> dict[str, Any]:
        """Sign this party's own key-round record after checking what it binds.

        A party never signs a round record handed to it without verifying that it names
        this party, this run, this plan and the public key this endpoint just produced.
        """
        require(self.plan is not None and self.plan_sha256 is not None, "PLAN_NOT_ACCEPTED")
        require(payload["party_id"] == self.party_id, "KEY_ROUND_NOT_MINE")
        require(payload["run_id"] == self.plan["run_id"], "KEY_ROUND_RUN")
        require(payload["run_plan_sha256"] == self.plan_sha256, "KEY_ROUND_PLAN")
        require(payload["round_index"] == expected_round, "KEY_ROUND_INDEX")
        require(payload["outgoing_public_key_sha256"] == sha256_hex(outgoing_public_key),
                "KEY_ROUND_ARTIFACT_HASH")
        require(roster_parties(self.plan)[expected_round] == self.party_id,
                "KEY_ROUND_PARTY_ORDER")
        return self._sign("key-round", payload)

    def confirm_epoch(self, manifest_envelope: Any, key_round_envelopes: Sequence[Any], *,
                      context_path: Path, final_public_key_path: Path,
                      final_key_tag: str, now: datetime) -> dict[str, Any]:
        require(self.plan is not None and self.plan_sha256 is not None, "PLAN_NOT_ACCEPTED")
        manifest = verify(manifest_envelope, "epoch-manifest", self.roster)
        require(manifest_envelope["signer_id"] == self.coordinator_id,
                "EPOCH_NOT_FROM_COORDINATOR")
        require(manifest["run_id"] == self.plan["run_id"], "EPOCH_RUN")
        require(manifest["run_plan_sha256"] == self.plan_sha256, "EPOCH_PLAN_HASH")

        context_bytes = Path(context_path).read_bytes()
        public_key_bytes = Path(final_public_key_path).read_bytes()
        require(sha256_hex(context_bytes) == manifest["context_sha256"], "EPOCH_CONTEXT_HASH")
        require(sha256_hex(public_key_bytes) == manifest["final_public_key_sha256"],
                "EPOCH_PUBLIC_KEY_HASH")

        # Verify every round's signature against its own party, then the whole chain,
        # including this party's own contribution.
        parties = roster_parties(self.plan)
        rounds = []
        for index, envelope in enumerate(key_round_envelopes):
            payload = verify(envelope, "key-round", self.roster)
            require(envelope["signer_id"] == parties[index], "KEY_ROUND_SIGNER")
            require(payload["party_id"] == envelope["signer_id"], "KEY_ROUND_SIGNER_CLAIM")
            rounds.append(payload)
        final_hash = validate_key_round_chain(rounds, self.plan,
                                              run_plan_sha256=self.plan_sha256,
                                              context_sha256=manifest["context_sha256"])
        require(final_hash == manifest["final_public_key_sha256"], "EPOCH_CHAIN_FINAL_KEY")
        require(key_round_transcript_hash(rounds) == manifest["key_round_transcript_sha256"],
                "EPOCH_TRANSCRIPT_HASH")
        mine = [entry for entry in rounds if entry["party_id"] == self.party_id]
        require(len(mine) == 1, "EPOCH_OWN_ROUND_MISSING")

        self.epoch = EpochBinding(epoch_sha256=payload_hash(manifest),
                                  context_path=Path(context_path),
                                  final_public_key_path=Path(final_public_key_path),
                                  share_path=self._share_path,
                                  final_key_tag=final_key_tag)
        self.state.transition("EPOCH_CONFIRMED")
        return self._sign("epoch-confirmation",
                          build_acknowledgement(run_id=manifest["run_id"],
                                                party_id=self.party_id,
                                                object_sha256=self.epoch.epoch_sha256,
                                                at=now))

    # --- submission ---------------------------------------------------------
    def submit_count(self, count: int) -> tuple[dict[str, Any], bytes]:
        """Encrypt exactly one count. A retry resends the stored bytes, never a new one."""
        require(self.plan is not None and self.epoch is not None, "EPOCH_NOT_CONFIRMED")
        require(type(count) is int and 0 <= count <= 10000, "COUNT_RANGE")
        key = self.outbox.key(self.plan["run_id"], self.party_id, "submission")
        stored = self.outbox.get(key)
        if stored is not None:
            return stored.receipt["envelope"], stored.artifact
        self.outbox.assert_resumable(key)
        self.outbox.reserve(key)
        destination = self.jobs / f"submission-{self.party_id}.bin"
        self.worker.run("encrypt-count",
                        ["--context", self.epoch.context_path,
                         "--public", self.epoch.final_public_key_path,
                         "--count-stdin", "--out", destination],
                        stdin_bytes=f"{count}\n".encode())
        ciphertext = destination.read_bytes()
        payload = build_encrypted_count(
            run_id=self.plan["run_id"], epoch_sha256=self.epoch.epoch_sha256,
            party_id=self.party_id, query_sha256=self.query_sha256,
            snapshot_token=self.snapshot_token, ciphertext=ciphertext,
            ciphertext_sha256=sha256_hex(ciphertext),
            final_key_tag=self.epoch.final_key_tag)
        envelope = self._sign("encrypted-count", payload)
        self.outbox.commit(key, ciphertext, {"envelope": envelope})
        if self.state.state != "SUBMITTED":
            self.state.transition("SUBMITTED")
        return envelope, ciphertext

    # --- request verification (blueprint 4.4, steps 1-6) --------------------
    def verify_request(self, request_envelope: Any, input_set_envelope: Any,
                       submission_envelopes: Sequence[Any],
                       ciphertexts: dict[str, bytes], aggregate_bytes: bytes, *,
                       now: datetime) -> RequestVerification:
        moment = require_aware(now)
        require(self.plan is not None and self.epoch is not None, "EPOCH_NOT_CONFIRMED")
        checks: dict[str, bool] = {}

        # 1. coordinator signature, schema, purpose, expiry, locally pinned run/epoch.
        request = verify(request_envelope, "decryption-request", self.roster)
        require(request_envelope["signer_id"] == self.coordinator_id,
                "REQUEST_NOT_FROM_COORDINATOR")
        validate_decryption_request(request)
        require(request["study_id"] == self.study_id, "REQUEST_STUDY")
        require(request["run_id"] == self.plan["run_id"], "REQUEST_RUN")
        require(request["epoch_sha256"] == self.epoch.epoch_sha256, "REQUEST_EPOCH")
        require(request_is_live(request, moment), "REQUEST_EXPIRED")
        checks["signature_schema_epoch"] = True

        # 2. query, roster, lead and recipients against local records.
        require(request["query_sha256"] == self.query_sha256, "REQUEST_QUERY")
        parties = roster_parties(self.plan)
        require(request["required_parties"] == parties, "REQUEST_ROSTER")
        require(request["lead_party"] == self.plan["lead_party"], "REQUEST_LEAD")
        require(request["recipients_sha256"] == recipients_hash(self.plan["recipient_ids"]),
                "REQUEST_RECIPIENTS")
        checks["query_roster_recipients"] = True

        # 3. every signed submission, its ciphertext, and our own byte-for-byte.
        by_party: dict[str, dict[str, Any]] = {}
        for envelope in submission_envelopes:
            payload = verify(envelope, "encrypted-count", self.roster)
            signer = envelope["signer_id"]
            require(payload["party_id"] == signer, "SUBMISSION_SIGNER_CLAIM")
            require(signer in parties and signer not in by_party, "SUBMISSION_SIGNER_SET")
            require(payload["run_id"] == self.plan["run_id"], "SUBMISSION_RUN")
            require(payload["epoch_sha256"] == self.epoch.epoch_sha256, "SUBMISSION_EPOCH")
            require(payload["query_sha256"] == self.query_sha256, "SUBMISSION_QUERY")
            require(payload["final_key_tag"] == self.epoch.final_key_tag,
                    "SUBMISSION_KEY_TAG")
            blob = ciphertexts.get(payload["ciphertext_sha256"])
            require(type(blob) is bytes, "SUBMISSION_ARTIFACT_MISSING")
            require(sha256_hex(blob) == payload["ciphertext_sha256"], "SUBMISSION_HASH")
            require(len(blob) == payload["ciphertext_size"], "SUBMISSION_SIZE")
            by_party[signer] = {"payload": payload, "bytes": blob}
        own = by_party.get(self.party_id)
        require(own is not None, "OWN_SUBMISSION_MISSING")
        stored = self.outbox.get(self.outbox.key(self.plan["run_id"], self.party_id,
                                                 "submission"))
        require(stored is not None, "OWN_SUBMISSION_NOT_IN_OUTBOX")
        require(own["bytes"] == stored.artifact, "OWN_SUBMISSION_BYTES_DIFFER")
        require(own["payload"] == stored.receipt["envelope"]["payload"],
                "OWN_SUBMISSION_PAYLOAD_DIFFERS")
        checks["inputs_authenticated"] = True

        # 4. exactly one input per required party, in roster order, matching the set hash.
        input_set = verify(input_set_envelope, "input-set", self.roster)
        require(input_set_envelope["signer_id"] == self.coordinator_id,
                "INPUT_SET_NOT_FROM_COORDINATOR")
        require(input_set["run_id"] == self.plan["run_id"], "INPUT_SET_RUN")
        require(input_set["epoch_sha256"] == self.epoch.epoch_sha256, "INPUT_SET_EPOCH")
        listed = [entry["party_id"] for entry in input_set["inputs"]]
        require(listed == parties, "INPUT_SET_ROSTER_ORDER")
        for entry in input_set["inputs"]:
            record = by_party[entry["party_id"]]
            require(entry["submission_sha256"] == payload_hash(record["payload"]),
                    "INPUT_SET_SUBMISSION_HASH")
            require(entry["ciphertext_sha256"] == record["payload"]["ciphertext_sha256"],
                    "INPUT_SET_CIPHERTEXT_HASH")
        require(payload_hash(input_set) == request["input_set_sha256"], "INPUT_SET_HASH")
        checks["exact_input_set"] = True

        # 5. recompute the aggregate locally over exactly these ordered inputs.
        require(sha256_hex(aggregate_bytes) == request["aggregate_sha256"],
                "AGGREGATE_HASH")
        ordered = self._materialize(parties, by_party)
        aggregate_path = self.jobs / f"candidate-{request['request_id']}.bin"
        if not aggregate_path.exists():
            aggregate_path.write_bytes(aggregate_bytes)
        flags: list[Any] = []
        for path in ordered:
            flags += ["--input", path]
        self.worker.run("verify-aggregate",
                        ["--context", self.epoch.context_path, *flags,
                         "--candidate", aggregate_path,
                         "--expect-key-tag", self.epoch.final_key_tag])
        checks["aggregate_recomputed"] = True

        # 6. own share belongs to this epoch, no prior partial, ledger permits.
        require(self.epoch.share_path.is_file(), "SHARE_MISSING")
        partial_key = self.outbox.key(self.plan["run_id"], self.party_id, "partial")
        self.outbox.assert_resumable(partial_key)
        require(not self.outbox.is_committed(partial_key), "PARTIAL_ALREADY_EMITTED")
        self.ledger.permits(study_id=self.study_id, query_sha256=self.query_sha256,
                            snapshot_token=self.snapshot_token,
                            recipients_sha256=request["recipients_sha256"],
                            run_id=self.plan["run_id"])
        checks["share_epoch_and_policy"] = True

        verification = RequestVerification(request=request, request_sha256=payload_hash(request),
                                           role=role_of(self.plan, self.party_id),
                                           ordered_ciphertexts=ordered,
                                           aggregate_path=aggregate_path, checks=checks)
        if self.state.state != "REQUEST_VERIFIED":
            self.state.transition("REQUEST_VERIFIED")
        return verification

    def _materialize(self, parties: Sequence[str],
                     by_party: dict[str, dict[str, Any]]) -> list[Path]:
        ordered = []
        for party_id in parties:
            path = self.jobs / f"input-{party_id}.bin"
            if not path.exists():
                path.write_bytes(by_party[party_id]["bytes"])
            ordered.append(path)
        return ordered

    # --- approval and partial (blueprint 4.5) -------------------------------
    def approve(self, verification: RequestVerification, *, operator_approved: bool,
                now: datetime) -> tuple[dict[str, Any], bytes]:
        """Step 7: an authenticated local operator action. There is no remote approval."""
        moment = require_aware(now)
        require(self.plan is not None and self.epoch is not None, "EPOCH_NOT_CONFIRMED")
        require(verification.verified, "REQUEST_NOT_VERIFIED")
        # A boolean from a poll, a plan field or a coordinator message can never satisfy
        # this: the caller is the local authenticated UI action (M4).
        require(operator_approved is True, "LOCAL_APPROVAL_REQUIRED")
        require(request_is_live(verification.request, moment), "REQUEST_EXPIRED")

        run_id = self.plan["run_id"]
        key = self.outbox.key(run_id, self.party_id, "partial")
        stored = self.outbox.get(key)
        if stored is not None:
            # Idempotent retry: the same bytes, never a newly randomized partial.
            require(stored.receipt["request_sha256"] == verification.request_sha256,
                    "PARTIAL_FOR_ANOTHER_REQUEST")
            return stored.receipt["envelope"], stored.artifact

        self.outbox.assert_resumable(key)
        self.outbox.reserve(key)
        if self.state.state != "PARTIAL_RESERVED":
            self.state.transition("PARTIAL_RESERVED")
        destination = self.jobs / f"partial-{verification.request['request_id']}.bin"
        self.worker.run("partial-decrypt",
                        ["--context", self.epoch.context_path,
                         "--secret", self.epoch.share_path,
                         "--ciphertext", verification.aggregate_path,
                         "--role", verification.role,
                         "--out", destination])
        artifact = destination.read_bytes()
        payload = build_partial(party_id=self.party_id,
                                request_sha256=verification.request_sha256,
                                aggregate_sha256=verification.request["aggregate_sha256"],
                                epoch_sha256=self.epoch.epoch_sha256,
                                role=verification.role, approved_at=moment,
                                partial_bytes=artifact,
                                partial_sha256=sha256_hex(artifact))
        envelope = self._sign("partial", payload)
        self.outbox.commit(key, artifact, {"envelope": envelope,
                                           "request_sha256": verification.request_sha256})
        self.state.transition("PARTIAL_COMMITTED")
        self.ledger.record(study_id=self.study_id, run_id=run_id,
                           query_sha256=self.query_sha256,
                           snapshot_token=self.snapshot_token,
                           recipients_sha256=verification.request["recipients_sha256"],
                           decision="APPROVE", at=moment)
        self.state.transition("PARTIAL_SENT")
        return envelope, artifact

    def stored_partial(self) -> tuple[dict[str, Any], bytes] | None:
        """Recover an already-emitted partial for a lost response (blueprint 2.8).

        A lost upload is recovered by fetching the stored bytes, never by redoing the
        cryptographic operation. `verify_request` deliberately refuses once a partial
        exists, so this is the only resend path.
        """
        require(self.plan is not None, "PLAN_NOT_ACCEPTED")
        stored = self.outbox.get(self.outbox.key(self.plan["run_id"], self.party_id,
                                                 "partial"))
        if stored is None:
            return None
        return stored.receipt["envelope"], stored.artifact

    def reject(self, request: dict[str, Any], *, reason_code: str,
               now: datetime) -> dict[str, Any]:
        """A rejection creates no partial, ever."""
        moment = require_aware(now)
        require(self.plan is not None, "PLAN_NOT_ACCEPTED")
        key = self.outbox.key(self.plan["run_id"], self.party_id, "partial")
        require(not self.outbox.is_committed(key), "PARTIAL_ALREADY_EMITTED")
        payload = build_rejection(run_id=self.plan["run_id"], party_id=self.party_id,
                                  request_sha256=payload_hash(request),
                                  rejected_at=moment, reason_code=reason_code)
        self.ledger.record(study_id=self.study_id, run_id=self.plan["run_id"],
                           query_sha256=self.query_sha256 or "",
                           snapshot_token=self.snapshot_token or "",
                           recipients_sha256=request["recipients_sha256"],
                           decision="REJECT", at=moment)
        return self._sign("rejection", payload)

    def _sign(self, purpose: str, payload: dict[str, Any]) -> dict[str, Any]:
        return sign(payload, self.party_id, purpose, self.identity)
