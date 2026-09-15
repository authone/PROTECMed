"""M3: the signed immutable protocol driving the real OpenFHE worker.

The central claim these tests defend is the one the M2 findings made unavoidable:
**the application never calls fusion unless the exact approved set of signed partials is
present.** Several tests assert the worker's `fuse` subcommand was invoked zero times,
rather than assuming the library would have refused.
"""
from __future__ import annotations
import copy
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from . import OPENFHE_LIB, SKIP_REASON, WORKER_AVAILABLE, WORKER_BINARY
from .protocol_harness import NOW, QUERY_SHA256, Deployment
from protecmed_protocol.errors import IntegrityHold, ProtocolError
from protecmed_protocol.identity import Identity, sign
from protecmed_worker import WorkerFailure


@unittest.skipUnless(WORKER_AVAILABLE, SKIP_REASON)
class ProtocolCase(unittest.TestCase):
    parties = 2
    counts = [5, 6]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.deployment = Deployment(root=Path(self.temporary.name),
                                     binary=WORKER_BINARY, library=OPENFHE_LIB,
                                     party_count=self.parties)

    @property
    def coordinator(self):
        return self.deployment.coordinator

    def fuse_calls(self) -> int:
        return self.deployment.workers["coordinator"].count("fuse")

    def assert_no_fusion(self):
        self.assertEqual(self.fuse_calls(), 0, "fusion must not have been invoked")

    def assert_fails(self, token, callable_, *args, **kwargs):
        with self.assertRaises(ProtocolError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.token, token)
        return caught.exception


class HappyPathTests(ProtocolCase):
    def test_two_party_release(self):
        self.deployment.up_to_request(self.counts)
        for name in self.deployment.names:
            self.deployment.approve(name)
        receipt = self.coordinator.fuse(now=NOW)
        self.assertEqual(receipt.aggregate, 11)
        self.assertEqual(self.coordinator.state.state, "REVEALED")
        self.assertEqual(len(receipt.partial_sha256), 2)

    def test_worker_calls_are_split_correctly_between_roles(self):
        self.deployment.up_to_request(self.counts)
        for name in self.deployment.names:
            self.deployment.approve(name)
        self.coordinator.fuse(now=NOW)
        coordinator_calls = self.deployment.workers["coordinator"].calls
        self.assertEqual(coordinator_calls, ["context-create", "add-counts", "fuse"])
        # The coordinator never generates a key or produces a partial.
        self.assertNotIn("keygen-first", coordinator_calls)
        self.assertNotIn("keygen-next", coordinator_calls)
        self.assertNotIn("partial-decrypt", coordinator_calls)
        party_calls = self.deployment.workers["party-a"].calls
        self.assertLess(party_calls.index("verify-aggregate"),
                        party_calls.index("partial-decrypt"))
        self.assertNotIn("fuse", party_calls)

    def test_local_states_advance_to_partial_sent(self):
        self.deployment.up_to_request(self.counts)
        for name in self.deployment.names:
            self.deployment.approve(name)
        for name in self.deployment.names:
            self.assertEqual(self.deployment.parties[name].state.state, "PARTIAL_SENT")


class ThreePartyTests(ProtocolCase):
    parties = 3
    counts = [3, 2, 6]

    def test_three_party_release(self):
        self.deployment.up_to_request(self.counts)
        for name in self.deployment.names:
            self.deployment.approve(name)
        self.assertEqual(self.coordinator.fuse(now=NOW).aggregate, 11)

    def test_two_of_three_never_fuses(self):
        self.deployment.up_to_request(self.counts)
        for name in self.deployment.names[:2]:
            self.deployment.approve(name)
        failure = self.assert_fails("PARTIAL_SET_INCOMPLETE",
                                    self.coordinator.authorize_fusion, now=NOW)
        self.assertEqual(failure.detail["missing"], ["party-c"])
        self.assert_fails("PARTIAL_SET_INCOMPLETE", self.coordinator.fuse, now=NOW)
        self.assert_no_fusion()

    def test_the_threshold_cannot_be_lowered_by_a_caller(self):
        self.deployment.up_to_request(self.counts)
        for name in self.deployment.names[:2]:
            self.deployment.approve(name)
        # There is no expected_parties argument to supply: n comes from the frozen plan.
        self.assertEqual(self.coordinator.plan["threshold"], 3)
        with self.assertRaises(TypeError):
            self.coordinator.fuse(now=NOW, expected_parties=2)
        self.assert_no_fusion()


class MissingShareOrSignatureTests(ProtocolCase):
    def test_a_rejection_blocks_the_release(self):
        self.deployment.up_to_request(self.counts)
        self.deployment.approve("party-a")
        rejection = self.deployment.parties["party-b"].reject(
            self.coordinator.request, reason_code="OPERATOR_DECLINED", now=NOW)
        self.coordinator.accept_rejection(rejection)
        self.assert_fails("REJECTION_PRESENT", self.coordinator.authorize_fusion, now=NOW)
        self.assert_no_fusion()

    def test_a_rejecting_party_produces_no_partial(self):
        self.deployment.up_to_request(self.counts)
        party = self.deployment.parties["party-b"]
        party.reject(self.coordinator.request, reason_code="OPERATOR_DECLINED", now=NOW)
        self.assertEqual(self.deployment.workers["party-b"].count("partial-decrypt"), 0)

    def test_an_operator_who_does_not_approve_produces_no_partial(self):
        self.deployment.up_to_request(self.counts)
        verification = self.deployment.verify("party-b")
        self.assertTrue(verification.verified)
        self.assert_fails("LOCAL_APPROVAL_REQUIRED",
                          self.deployment.parties["party-b"].approve, verification,
                          operator_approved=False, now=NOW)
        self.assertEqual(self.deployment.workers["party-b"].count("partial-decrypt"), 0)
        self.assert_no_fusion()

    def test_a_truthy_non_boolean_does_not_count_as_approval(self):
        self.deployment.up_to_request(self.counts)
        verification = self.deployment.verify("party-b")
        for value in (1, "yes", [1]):
            self.assert_fails("LOCAL_APPROVAL_REQUIRED",
                              self.deployment.parties["party-b"].approve, verification,
                              operator_approved=value, now=NOW)
        self.assertEqual(self.deployment.workers["party-b"].count("partial-decrypt"), 0)

    def test_an_unsigned_request_is_refused_before_any_crypto(self):
        self.deployment.up_to_request(self.counts)
        forged = copy.deepcopy(self.deployment.request_envelope)
        forged["signature_b64"] = "A" * 86 + "=="
        self.deployment.request_envelope = forged
        self.assert_fails("BAD_SIGNATURE", self.deployment.verify, "party-a")
        self.assertEqual(self.deployment.workers["party-a"].count("verify-aggregate"), 0)
        self.assert_no_fusion()

    def test_a_request_signed_by_a_party_is_not_a_coordinator_request(self):
        self.deployment.up_to_request(self.counts)
        impostor = self.deployment.identities["party-b"]
        self.deployment.request_envelope = sign(self.coordinator.request, "party-b",
                                                "decryption-request", impostor)
        self.assert_fails("REQUEST_NOT_FROM_COORDINATOR", self.deployment.verify, "party-a")
        self.assert_no_fusion()

    def test_a_request_from_an_unpinned_signer_is_refused(self):
        self.deployment.up_to_request(self.counts)
        stranger = Identity.generate("party-z")
        self.deployment.request_envelope = sign(self.coordinator.request, "party-z",
                                                "decryption-request", stranger)
        self.assert_fails("UNKNOWN_SIGNER", self.deployment.verify, "party-a")

    def test_a_partial_envelope_cannot_be_replayed_as_another_purpose(self):
        self.deployment.up_to_request(self.counts)
        envelope, artifact = self.deployment.approve("party-a")
        replay = dict(envelope, purpose="rejection")
        self.assert_fails("BAD_SIGNATURE", self.coordinator.accept_rejection, replay)


class WrongContentTests(ProtocolCase):
    def test_a_substituted_aggregate_is_caught_by_its_hash(self):
        self.deployment.up_to_request(self.counts)
        party = self.deployment.parties["party-a"]
        other = self.coordinator.submissions["party-b"].ciphertext
        with self.assertRaises(ProtocolError) as caught:
            party.verify_request(self.deployment.request_envelope,
                                 self.deployment.input_set_envelope,
                                 self.deployment.submission_envelopes(),
                                 self.deployment.published_inputs(), other, now=NOW)
        self.assertEqual(caught.exception.token, "AGGREGATE_HASH")
        self.assert_no_fusion()

    def test_a_subset_sum_is_caught_by_local_recomputation(self):
        """The aggregate hash matches, but it is not the sum of the exact input set."""
        self.deployment.up_to_request(self.counts)
        forged = self.coordinator.storage / "forged-aggregate.bin"
        single = self.coordinator.submissions["party-a"].ciphertext
        forged.write_bytes(single)
        from protecmed_protocol.canonical import sha256_hex
        tampered_request = dict(self.coordinator.request,
                                aggregate_sha256=sha256_hex(single))
        self.deployment.request_envelope = sign(tampered_request, "coordinator",
                                                "decryption-request",
                                                self.deployment.identities["coordinator"])
        party = self.deployment.parties["party-a"]
        with self.assertRaises(WorkerFailure) as caught:
            party.verify_request(self.deployment.request_envelope,
                                 self.deployment.input_set_envelope,
                                 self.deployment.submission_envelopes(),
                                 self.deployment.published_inputs(), single, now=NOW)
        self.assertEqual(caught.exception.returncode, 17)
        self.assertEqual(self.deployment.workers["party-a"].count("partial-decrypt"), 0)
        self.assert_no_fusion()

    def test_a_reordered_input_set_is_refused(self):
        self.deployment.up_to_request(self.counts)
        reordered = copy.deepcopy(self.coordinator.input_set)
        reordered["inputs"].reverse()
        self.deployment.input_set_envelope = sign(
            reordered, "coordinator", "input-set", self.deployment.identities["coordinator"])
        self.assert_fails("INPUT_SET_ROSTER_ORDER", self.deployment.verify, "party-a")

    def test_an_input_set_that_does_not_match_the_request_is_refused(self):
        self.deployment.up_to_request(self.counts)
        altered = dict(copy.deepcopy(self.coordinator.input_set), run_id="synthetic-run")
        altered["inputs"][0]["submission_sha256"] = "f" * 64
        self.deployment.input_set_envelope = sign(
            altered, "coordinator", "input-set", self.deployment.identities["coordinator"])
        self.assert_fails("INPUT_SET_SUBMISSION_HASH", self.deployment.verify, "party-a")

    def test_a_changed_query_hash_in_the_request_is_refused(self):
        self.deployment.up_to_request(self.counts)
        tampered = dict(self.coordinator.request, query_sha256="f" * 64)
        self.deployment.request_envelope = sign(tampered, "coordinator",
                                                "decryption-request",
                                                self.deployment.identities["coordinator"])
        self.assert_fails("REQUEST_QUERY", self.deployment.verify, "party-a")

    def test_a_changed_recipient_list_is_refused(self):
        self.deployment.up_to_request(self.counts)
        tampered = dict(self.coordinator.request, recipients_sha256="f" * 64)
        self.deployment.request_envelope = sign(tampered, "coordinator",
                                                "decryption-request",
                                                self.deployment.identities["coordinator"])
        self.assert_fails("REQUEST_RECIPIENTS", self.deployment.verify, "party-a")

    def test_a_request_for_another_epoch_is_refused(self):
        self.deployment.up_to_request(self.counts)
        tampered = dict(self.coordinator.request, epoch_sha256="f" * 64)
        self.deployment.request_envelope = sign(tampered, "coordinator",
                                                "decryption-request",
                                                self.deployment.identities["coordinator"])
        self.assert_fails("REQUEST_EPOCH", self.deployment.verify, "party-a")

    def test_an_expired_request_produces_no_partial(self):
        self.deployment.up_to_request(self.counts, ttl_seconds=60)
        late = NOW + timedelta(minutes=5)
        self.assert_fails("REQUEST_EXPIRED", self.deployment.verify, "party-a", now=late)
        self.assertEqual(self.deployment.workers["party-a"].count("partial-decrypt"), 0)

    def test_an_expired_request_is_not_fused_even_with_every_partial(self):
        self.deployment.up_to_request(self.counts, ttl_seconds=600)
        for name in self.deployment.names:
            self.deployment.approve(name)
        self.assert_fails("REQUEST_EXPIRED", self.coordinator.authorize_fusion,
                          now=NOW + timedelta(minutes=30))
        self.assert_no_fusion()


class RosterAndConflictTests(ProtocolCase):
    def test_a_submission_from_outside_the_roster_is_refused(self):
        self.deployment.up_to_request(self.counts)
        stranger = Identity.generate("party-z")
        payload = copy.deepcopy(self.coordinator.submissions["party-a"].payload)
        payload["party_id"] = "party-z"
        forged = sign(payload, "party-z", "encrypted-count", stranger)
        self.assert_fails("UNKNOWN_SIGNER", self.deployment.parties["party-a"].verify_request,
                          self.deployment.request_envelope,
                          self.deployment.input_set_envelope,
                          [*self.deployment.submission_envelopes(), forged],
                          self.deployment.published_inputs(),
                          self.deployment.aggregate_path.read_bytes(), now=NOW)

    def test_a_conflicting_submission_puts_the_run_on_integrity_hold(self):
        self.deployment.freeze_plan()
        self.deployment.run_key_ceremony()
        self.deployment.confirm_epoch()
        self.deployment.submit(self.counts)
        party = self.deployment.parties["party-a"]
        # A second, different ciphertext signed by the same authenticated party.
        destination = party.jobs / "second.bin"
        self.deployment.workers["party-a"].run(
            "encrypt-count", ["--context", party.epoch.context_path, "--public",
                              party.epoch.final_public_key_path, "--count-stdin",
                              "--out", destination], stdin_bytes=b"9\n")
        from protecmed_protocol.canonical import sha256_hex
        from protecmed_protocol.objects import build_encrypted_count
        blob = destination.read_bytes()
        payload = build_encrypted_count(
            run_id=party.plan["run_id"], epoch_sha256=party.epoch.epoch_sha256,
            party_id="party-a", query_sha256=QUERY_SHA256,
            snapshot_token=party.snapshot_token, ciphertext=blob,
            ciphertext_sha256=sha256_hex(blob), final_key_tag=party.epoch.final_key_tag)
        conflicting = sign(payload, "party-a", "encrypted-count",
                           self.deployment.identities["party-a"])
        with self.assertRaises(IntegrityHold) as caught:
            self.coordinator.accept_submission(conflicting, blob)
        self.assertEqual(caught.exception.token, "CONFLICTING_SUBMISSION")
        self.assertEqual(self.coordinator.state.state, "INTEGRITY_HOLD")
        self.assert_no_fusion()

    def test_a_byte_identical_retry_is_a_no_op(self):
        self.deployment.freeze_plan()
        self.deployment.run_key_ceremony()
        self.deployment.confirm_epoch()
        self.deployment.submit(self.counts)
        record = self.coordinator.submissions["party-a"]
        self.coordinator.accept_submission(record.envelope, record.ciphertext)
        self.assertEqual(self.coordinator.state.state, "COLLECTING")
        self.assertEqual(len(self.coordinator.submissions), self.parties)

    def test_inputs_cannot_be_locked_before_every_party_submits(self):
        self.deployment.freeze_plan()
        self.deployment.run_key_ceremony()
        self.deployment.confirm_epoch()
        envelope, ciphertext = self.deployment.parties["party-a"].submit_count(5)
        self.coordinator.accept_submission(envelope, ciphertext)
        self.assert_fails("INPUT_SET_INCOMPLETE", self.coordinator.lock_inputs)

    def test_a_ciphertext_is_refused_before_every_epoch_confirmation(self):
        self.deployment.freeze_plan()
        self.deployment.run_key_ceremony()
        manifest = self.coordinator.publish_epoch_manifest()
        rounds = [record.envelope for record in self.coordinator.key_rounds]
        tag = "placeholder-tag"
        confirmation = self.deployment.parties["party-a"].confirm_epoch(
            manifest, rounds, context_path=self.deployment.context_path,
            final_public_key_path=self.deployment.final_public_key,
            final_key_tag=tag, now=NOW)
        self.coordinator.record_epoch_confirmation(confirmation)
        self.assertEqual(self.coordinator.state.state, "KEYGEN")
        self.assert_fails("WRONG_STATE", self.coordinator.accept_submission,
                          confirmation, b"x")


class IdempotencyTests(ProtocolCase):
    def test_resubmitting_resends_the_same_ciphertext(self):
        self.deployment.up_to_request(self.counts)
        party = self.deployment.parties["party-a"]
        before = self.deployment.workers["party-a"].count("encrypt-count")
        envelope, ciphertext = party.submit_count(5)
        self.assertEqual(self.deployment.workers["party-a"].count("encrypt-count"), before)
        self.assertEqual(ciphertext, self.coordinator.submissions["party-a"].ciphertext)
        self.assertEqual(envelope, self.coordinator.submissions["party-a"].envelope)

    def test_reapproving_the_same_verification_resends_the_same_bytes(self):
        self.deployment.up_to_request(self.counts)
        party = self.deployment.parties["party-a"]
        verification = self.deployment.verify("party-a")
        first_envelope, first_bytes = party.approve(verification, operator_approved=True,
                                                    now=NOW)
        calls = self.deployment.workers["party-a"].count("partial-decrypt")
        second_envelope, second_bytes = party.approve(verification, operator_approved=True,
                                                      now=NOW)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first_envelope, second_envelope)
        self.assertEqual(self.deployment.workers["party-a"].count("partial-decrypt"), calls)

    def test_a_lost_response_is_recovered_from_the_outbox_not_recomputed(self):
        self.deployment.up_to_request(self.counts)
        envelope, artifact = self.deployment.approve("party-a")
        party = self.deployment.parties["party-a"]
        calls = self.deployment.workers["party-a"].count("partial-decrypt")
        recovered_envelope, recovered_bytes = party.stored_partial()
        self.assertEqual((recovered_envelope, recovered_bytes), (envelope, artifact))
        self.assertEqual(self.deployment.workers["party-a"].count("partial-decrypt"), calls)

    def test_reverification_is_refused_once_a_partial_exists(self):
        """A second partial under the same epoch must never be generated."""
        self.deployment.up_to_request(self.counts)
        self.deployment.approve("party-a")
        self.assert_fails("PARTIAL_ALREADY_EMITTED", self.deployment.verify, "party-a")
        self.assertEqual(self.deployment.workers["party-a"].count("partial-decrypt"), 1)

    def test_fusing_twice_returns_the_stored_receipt(self):
        self.deployment.up_to_request(self.counts)
        for name in self.deployment.names:
            self.deployment.approve(name)
        first = self.coordinator.fuse(now=NOW)
        second = self.coordinator.fuse(now=NOW)
        self.assertEqual(first.aggregate, second.aggregate)
        self.assertEqual(self.fuse_calls(), 1)

    def test_a_second_release_of_the_same_combination_is_refused_locally(self):
        self.deployment.up_to_request(self.counts)
        for name in self.deployment.names:
            self.deployment.approve(name)
        self.coordinator.fuse(now=NOW)
        party = self.deployment.parties["party-a"]
        self.assert_fails("DISCLOSURE_ALREADY_RELEASED", party.ledger.permits,
                          study_id=party.study_id, query_sha256=QUERY_SHA256,
                          snapshot_token=party.snapshot_token,
                          recipients_sha256=self.coordinator.request["recipients_sha256"],
                          run_id=party.plan["run_id"])


if __name__ == "__main__":
    unittest.main()
