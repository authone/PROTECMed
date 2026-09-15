"""Canonical bytes, envelopes and contract objects (blueprint 4.2-4.3). No worker."""
from __future__ import annotations
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from . import ROOT
from protecmed_protocol.canonical import (canonical_bytes, hash_list, parse_json,
                                          payload_hash, parse_utc, format_utc, sha256_hex)
from protecmed_protocol.contracts import validate_envelope, validate_payload
from protecmed_protocol.errors import ProtocolError
from protecmed_protocol.identity import Identity, Roster, fingerprint, sign, verify
from protecmed_protocol import objects

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)


class CanonicalTests(unittest.TestCase):
    def test_keys_are_sorted_and_whitespace_free(self):
        self.assertEqual(canonical_bytes({"b": 1, "a": 2}), b'{"a":2,"b":1}')

    def test_non_ascii_is_refused(self):
        for value in ({"a": "sănătate"}, {"cheieé": 1}, ["✓"]):
            with self.assertRaises(ProtocolError) as caught:
                canonical_bytes(value)
            self.assertIn(caught.exception.token, {"JSON_ASCII_ONLY", "JSON_KEY"})

    def test_floats_and_unsupported_types_are_refused(self):
        for value in ({"a": 1.5}, {"a": (1, 2)}, {"a": b"x"}, {"a": {1, 2}}):
            with self.assertRaises(ProtocolError) as caught:
                canonical_bytes(value)
            self.assertEqual(caught.exception.token, "JSON_UNSUPPORTED_TYPE")

    def test_integers_beyond_2_53_are_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            canonical_bytes({"a": 2**53})
        self.assertEqual(caught.exception.token, "JSON_INTEGER_RANGE")
        self.assertEqual(canonical_bytes({"a": 2**53 - 1}), b'{"a":9007199254740991}')

    def test_depth_limit(self):
        value = current = {}
        for _ in range(20):
            current["a"] = {}
            current = current["a"]
        with self.assertRaises(ProtocolError) as caught:
            canonical_bytes(value)
        self.assertEqual(caught.exception.token, "JSON_DEPTH")

    def test_duplicate_keys_are_refused_while_parsing(self):
        with self.assertRaises(ProtocolError) as caught:
            parse_json(b'{"a":1,"a":2}')
        self.assertEqual(caught.exception.token, "JSON_DUPLICATE_KEY")

    def test_json_constants_and_oversize_are_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            parse_json(b'{"a":NaN}')
        self.assertEqual(caught.exception.token, "JSON_CONSTANT")
        with self.assertRaises(ProtocolError) as caught:
            parse_json(b'{"a":"' + b'x' * 70000 + b'"}')
        self.assertEqual(caught.exception.token, "JSON_SIZE")

    def test_hashing_an_envelope_is_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            payload_hash({"payload": {}, "signature_b64": "x"})
        self.assertEqual(caught.exception.token, "HASH_OF_SIGNED_ENVELOPE")

    def test_ordered_array_hash_depends_on_order(self):
        self.assertNotEqual(hash_list([{"a": 1}, {"a": 2}]), hash_list([{"a": 2}, {"a": 1}]))

    def test_utc_round_trip_and_rejection(self):
        self.assertEqual(format_utc(NOW), "2026-09-14T12:00:00Z")
        self.assertEqual(parse_utc("2026-09-14T12:00:00Z"), NOW)
        for bad in ("2026-09-14 12:00:00Z", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z",
                    "2026-09-14T12:00:00+02:00"):
            with self.assertRaises(ProtocolError):
                parse_utc(bad)

    def test_naive_clock_is_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            format_utc(datetime(2026, 9, 14, 12, 0, 0))
        self.assertEqual(caught.exception.token, "NAIVE_CLOCK")


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.party = Identity.generate("party-a")
        self.other = Identity.generate("party-b")
        self.roster = Roster.from_identities([self.party, self.other])
        self.payload = objects.build_acknowledgement(
            run_id="synthetic-run", party_id="party-a", object_sha256="c" * 64, at=NOW)

    def envelope(self, purpose="plan-acceptance"):
        return sign(self.payload, "party-a", purpose, self.party)

    def test_round_trip(self):
        envelope = self.envelope()
        self.assertEqual(verify(envelope, "plan-acceptance", self.roster), self.payload)
        validate_envelope(envelope)

    def test_signature_covers_the_payload(self):
        envelope = self.envelope()
        tampered = copy.deepcopy(envelope)
        tampered["payload"]["object_sha256"] = "d" * 64
        with self.assertRaises(ProtocolError) as caught:
            verify(tampered, "plan-acceptance", self.roster)
        self.assertEqual(caught.exception.token, "BAD_SIGNATURE")

    def test_purpose_is_enforced_at_the_endpoint(self):
        envelope = self.envelope()
        with self.assertRaises(ProtocolError) as caught:
            verify(envelope, "epoch-confirmation", self.roster)
        self.assertEqual(caught.exception.token, "WRONG_PURPOSE")

    def test_purpose_cannot_be_swapped_after_signing(self):
        envelope = self.envelope()
        envelope["purpose"] = "epoch-confirmation"
        with self.assertRaises(ProtocolError) as caught:
            verify(envelope, "epoch-confirmation", self.roster)
        self.assertEqual(caught.exception.token, "BAD_SIGNATURE")

    def test_signer_must_be_pinned_not_supplied(self):
        stranger = Identity.generate("party-z")
        envelope = sign(self.payload, "party-z", "plan-acceptance", stranger)
        with self.assertRaises(ProtocolError) as caught:
            verify(envelope, "plan-acceptance", self.roster)
        self.assertEqual(caught.exception.token, "UNKNOWN_SIGNER")

    def test_another_pinned_party_cannot_impersonate(self):
        envelope = sign(self.payload, "party-b", "plan-acceptance", self.other)
        envelope["signer_id"] = "party-a"
        with self.assertRaises(ProtocolError) as caught:
            verify(envelope, "plan-acceptance", self.roster)
        self.assertEqual(caught.exception.token, "BAD_SIGNATURE")

    def test_envelope_shape_is_exact(self):
        envelope = self.envelope()
        with self.assertRaises(ProtocolError):
            verify({**envelope, "extra": 1}, "plan-acceptance", self.roster)
        missing = {k: v for k, v in envelope.items() if k != "signature_b64"}
        with self.assertRaises(ProtocolError) as caught:
            verify(missing, "plan-acceptance", self.roster)
        self.assertEqual(caught.exception.token, "ENVELOPE_FIELDS")

    def test_bad_signature_encoding_and_length(self):
        envelope = self.envelope()
        with self.assertRaises(ProtocolError) as caught:
            verify({**envelope, "signature_b64": "not base64!"}, "plan-acceptance", self.roster)
        self.assertEqual(caught.exception.token, "SIGNATURE_ENCODING")
        with self.assertRaises(ProtocolError) as caught:
            verify({**envelope, "signature_b64": "AAAA"}, "plan-acceptance", self.roster)
        self.assertEqual(caught.exception.token, "SIGNATURE_LENGTH")

    def test_signing_for_another_agent_is_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            sign(self.payload, "party-b", "plan-acceptance", self.party)
        self.assertEqual(caught.exception.token, "SIGNER_IS_NOT_THIS_AGENT")

    def test_fingerprint_is_over_raw_public_bytes(self):
        self.assertEqual(self.party.fingerprint, fingerprint(self.party.public_key))
        self.assertEqual(len(self.party.fingerprint), 64)
        self.assertNotEqual(self.party.fingerprint, self.other.fingerprint)

    def test_changed_identity_key_breaks_pinning(self):
        with self.assertRaises(ProtocolError) as caught:
            self.roster.assert_pinned("party-a", self.other.fingerprint)
        self.assertEqual(caught.exception.token, "IDENTITY_FINGERPRINT_MISMATCH")


class ContractObjectTests(unittest.TestCase):
    def roster_entries(self, count=3):
        return [{"party_id": p, "identity_key_sha256": f"{index}" * 64,
                 "snapshot_token": f"snap-{index}"}
                for index, p in enumerate(["party-a", "party-b", "party-c"][:count], start=1)]

    def plan(self, count=3):
        return objects.build_run_plan(
            study_id="synthetic-study", run_id="synthetic-run",
            roster=self.roster_entries(count), lead_party="party-a",
            recipient_ids=["recipient-one"], query_sha256="a" * 64, mapping_sha256="b" * 64)

    def test_plan_binds_threshold_to_the_roster(self):
        plan = self.plan(3)
        self.assertEqual((plan["party_count"], plan["threshold"]), (3, 3))
        self.assertEqual(plan["release_policy_id"], "exact-count-restricted-demo-v1")

    def test_lowered_threshold_is_refused(self):
        plan = dict(self.plan(3), threshold=2)
        with self.assertRaises(ProtocolError) as caught:
            objects.validate_run_plan(plan)
        self.assertIn(caught.exception.token, {"PLAN_THRESHOLD", "SCHEMA_INVALID"})

    def test_lead_must_be_the_first_roster_entry(self):
        plan = dict(self.plan(3), lead_party="party-b")
        with self.assertRaises(ProtocolError) as caught:
            objects.validate_run_plan(plan)
        self.assertEqual(caught.exception.token, "PLAN_LEAD_IS_NOT_FIRST")

    def test_duplicate_party_snapshot_or_identity_is_refused(self):
        entries = self.roster_entries(2)
        for field, value in (("party_id", "party-a"), ("snapshot_token", "snap-1"),
                             ("identity_key_sha256", "1" * 64)):
            broken = [dict(entries[0]), dict(entries[1], **{field: value})]
            with self.assertRaises(ProtocolError):
                objects.build_run_plan(
                    study_id="synthetic-study", run_id="synthetic-run", roster=broken,
                    lead_party="party-a", recipient_ids=["recipient-one"],
                    query_sha256="a" * 64, mapping_sha256="b" * 64)

    def test_role_follows_roster_order(self):
        plan = self.plan(3)
        self.assertEqual(objects.role_of(plan, "party-a"), "lead")
        self.assertEqual(objects.role_of(plan, "party-c"), "main")
        with self.assertRaises(ProtocolError):
            objects.role_of(plan, "party-z")

    def test_key_round_chain_must_link(self):
        plan = self.plan(2)
        plan_hash, context_hash = payload_hash(plan), "c" * 64
        first = objects.build_key_round(
            run_id="synthetic-run", run_plan_sha256=plan_hash, context_sha256=context_hash,
            round_index=0, party_id="party-a", incoming_public_key_sha256=None,
            outgoing_public_key_sha256="d" * 64)
        second = objects.build_key_round(
            run_id="synthetic-run", run_plan_sha256=plan_hash, context_sha256=context_hash,
            round_index=1, party_id="party-b", incoming_public_key_sha256="d" * 64,
            outgoing_public_key_sha256="e" * 64)
        final = objects.validate_key_round_chain([first, second], plan,
                                                 run_plan_sha256=plan_hash,
                                                 context_sha256=context_hash)
        self.assertEqual(final, "e" * 64)
        broken = dict(second, incoming_public_key_sha256="f" * 64)
        with self.assertRaises(ProtocolError) as caught:
            objects.validate_key_round_chain([first, broken], plan,
                                             run_plan_sha256=plan_hash,
                                             context_sha256=context_hash)
        self.assertEqual(caught.exception.token, "KEY_ROUND_CHAIN")

    def test_first_round_must_have_a_null_incoming_hash(self):
        with self.assertRaises(ProtocolError) as caught:
            objects.build_key_round(
                run_id="synthetic-run", run_plan_sha256="a" * 64, context_sha256="c" * 64,
                round_index=0, party_id="party-a", incoming_public_key_sha256="d" * 64,
                outgoing_public_key_sha256="e" * 64)
        self.assertEqual(caught.exception.token, "KEY_ROUND_CHAIN_START")

    def test_key_round_order_must_match_the_roster(self):
        plan = self.plan(2)
        plan_hash, context_hash = payload_hash(plan), "c" * 64
        swapped = [
            objects.build_key_round(run_id="synthetic-run", run_plan_sha256=plan_hash,
                                    context_sha256=context_hash, round_index=0,
                                    party_id="party-b", incoming_public_key_sha256=None,
                                    outgoing_public_key_sha256="d" * 64),
            objects.build_key_round(run_id="synthetic-run", run_plan_sha256=plan_hash,
                                    context_sha256=context_hash, round_index=1,
                                    party_id="party-a", incoming_public_key_sha256="d" * 64,
                                    outgoing_public_key_sha256="e" * 64),
        ]
        with self.assertRaises(ProtocolError) as caught:
            objects.validate_key_round_chain(swapped, plan, run_plan_sha256=plan_hash,
                                             context_sha256=context_hash)
        self.assertEqual(caught.exception.token, "KEY_ROUND_PARTY_ORDER")

    def test_submission_carries_no_count(self):
        submission = objects.build_encrypted_count(
            run_id="synthetic-run", epoch_sha256="a" * 64, party_id="party-a",
            query_sha256="b" * 64, snapshot_token="snap-1", ciphertext=b"xyz",
            ciphertext_sha256=sha256_hex(b"xyz"), final_key_tag="tag")
        self.assertNotIn("count", submission)
        self.assertNotIn("admitted_rows", submission)
        self.assertEqual(submission["format_id"], "openfhe-1.5.1-binary")

    def test_request_threshold_and_lead_are_derived(self):
        request = objects.build_decryption_request(
            study_id="synthetic-study", run_id="synthetic-run", request_id="req-1",
            epoch_sha256="a" * 64, query_sha256="b" * 64, input_set_sha256="c" * 64,
            aggregate_sha256="d" * 64, recipients_sha256="e" * 64,
            required_parties=["party-a", "party-b"], lead_party="party-a",
            created_at=NOW, expires_at=NOW + timedelta(minutes=15))
        self.assertEqual(request["threshold"], 2)
        self.assertEqual(len(request["nonce"]), 64)
        self.assertTrue(objects.request_is_live(request, NOW))
        self.assertFalse(objects.request_is_live(request, NOW + timedelta(minutes=16)))

    def test_request_with_a_mismatched_lead_is_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            objects.build_decryption_request(
                study_id="synthetic-study", run_id="synthetic-run", request_id="req-1",
                epoch_sha256="a" * 64, query_sha256="b" * 64, input_set_sha256="c" * 64,
                aggregate_sha256="d" * 64, recipients_sha256="e" * 64,
                required_parties=["party-a", "party-b"], lead_party="party-b",
                created_at=NOW, expires_at=NOW + timedelta(minutes=15))
        self.assertEqual(caught.exception.token, "REQUEST_LEAD_IS_NOT_FIRST")

    def test_recipient_hash_is_order_sensitive(self):
        self.assertNotEqual(objects.recipients_hash(["a-one", "b-two"]),
                            objects.recipients_hash(["b-two", "a-one"]))

    def test_delivered_examples_validate_against_their_contracts(self):
        from protecmed_protocol.contracts import validate_against
        examples = json.loads((ROOT / "fixtures/contract_examples.json").read_text())
        self.assertEqual(len(examples), 10)
        for name, document in examples.items():
            validate_against(name, document)

    def test_a_document_is_refused_by_the_wrong_contract(self):
        from protecmed_protocol.contracts import validate_against
        examples = json.loads((ROOT / "fixtures/contract_examples.json").read_text())
        with self.assertRaises(ProtocolError) as caught:
            validate_against("partial", examples["run-plan"])
        self.assertEqual(caught.exception.token, "SCHEMA_INVALID")

    def test_purpose_selects_the_payload_contract(self):
        examples = json.loads((ROOT / "fixtures/contract_examples.json").read_text())
        # plan-acceptance and epoch-confirmation share the acknowledgement contract.
        validate_payload("plan-acceptance", examples["acknowledgement"])
        validate_payload("epoch-confirmation", examples["acknowledgement"])
        with self.assertRaises(ProtocolError):
            validate_payload("partial", examples["acknowledgement"])


if __name__ == "__main__":
    unittest.main()
