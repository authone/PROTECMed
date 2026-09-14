"""State machines, immutable outbox and disclosure ledger (blueprint 2.8, 4.1, 4.7)."""
from __future__ import annotations
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from . import ROOT  # noqa: F401
from protecmed_protocol.errors import ProtocolError
from protecmed_protocol.state import party_machine, run_machine
from protecmed_protocol.store import DisclosureLedger, ImmutableOutbox

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)


class RunStateTests(unittest.TestCase):
    def test_happy_path(self):
        machine = run_machine()
        for target in ("PLAN_ACCEPTED", "CONTEXT_READY", "KEYGEN", "EPOCH_CONFIRMED",
                       "COLLECTING", "INPUTS_LOCKED", "EVALUATED", "APPROVAL_PENDING",
                       "PARTIALS_IN_PROGRESS", "REVEALED", "CLOSED"):
            machine.transition(target)
        self.assertEqual(machine.state, "CLOSED")

    def test_phases_cannot_be_skipped(self):
        machine = run_machine()
        with self.assertRaises(ProtocolError) as caught:
            machine.transition("REVEALED")
        self.assertEqual(caught.exception.token, "ILLEGAL_TRANSITION")

    def test_terminal_states_are_final(self):
        for terminal in ("REJECTED", "EXPIRED", "ABORTED", "INTEGRITY_HOLD", "CLOSED"):
            machine = run_machine(terminal)
            with self.assertRaises(ProtocolError):
                machine.transition("COLLECTING")

    def test_any_active_phase_can_fail_into_integrity_hold(self):
        for state in ("COLLECTING", "EVALUATED", "PARTIALS_IN_PROGRESS"):
            self.assertTrue(run_machine(state).can("INTEGRITY_HOLD"))

    def test_revealed_cannot_go_back_to_collecting(self):
        machine = run_machine("REVEALED")
        self.assertFalse(machine.can("COLLECTING"))
        self.assertTrue(machine.can("CLOSED"))

    def test_require_names_the_expected_state(self):
        machine = run_machine("KEYGEN")
        machine.require("KEYGEN")
        with self.assertRaises(ProtocolError) as caught:
            machine.require("COLLECTING")
        self.assertEqual(caught.exception.token, "WRONG_STATE")


class PartyStateTests(unittest.TestCase):
    def test_local_happy_path(self):
        machine = party_machine()
        for target in ("PLAN_ACCEPTED", "SHARE_CREATED", "EPOCH_CONFIRMED", "SUBMITTED",
                       "REQUEST_VERIFIED", "PARTIAL_RESERVED", "PARTIAL_COMMITTED",
                       "PARTIAL_SENT", "CLOSED"):
            machine.transition(target)

    def test_a_partial_cannot_precede_verification(self):
        machine = party_machine("SUBMITTED")
        with self.assertRaises(ProtocolError):
            machine.transition("PARTIAL_RESERVED")


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.outbox = ImmutableOutbox(Path(self.temporary.name) / "outbox")
        self.key = self.outbox.key("synthetic-run", "party-a", "partial")

    def test_directory_is_owner_only(self):
        self.assertEqual(self.outbox.directory.stat().st_mode & 0o777, 0o700)

    def test_reserve_then_commit_then_resend_same_bytes(self):
        self.outbox.reserve(self.key)
        self.outbox.commit(self.key, b"partial-bytes", {"envelope": {"x": 1}})
        first = self.outbox.get(self.key)
        second = self.outbox.get(self.key)
        self.assertEqual(first.artifact, b"partial-bytes")
        self.assertEqual(first.artifact, second.artifact)
        self.assertEqual(first.receipt["artifact_size"], len(b"partial-bytes"))

    def test_double_reservation_is_refused(self):
        self.outbox.reserve(self.key)
        with self.assertRaises(ProtocolError) as caught:
            self.outbox.reserve(self.key)
        self.assertEqual(caught.exception.token, "OUTBOX_ALREADY_RESERVED")

    def test_commit_without_reservation_is_refused(self):
        with self.assertRaises(ProtocolError) as caught:
            self.outbox.commit(self.key, b"bytes", {})
        self.assertEqual(caught.exception.token, "OUTBOX_NOT_RESERVED")

    def test_second_commit_is_refused(self):
        self.outbox.reserve(self.key)
        self.outbox.commit(self.key, b"bytes", {})
        with self.assertRaises(ProtocolError) as caught:
            self.outbox.commit(self.key, b"other", {})
        self.assertEqual(caught.exception.token, "OUTBOX_ALREADY_COMMITTED")

    def test_a_reservation_without_a_commit_aborts_the_epoch(self):
        # A crash here leaves it unknown whether different bytes already left.
        self.outbox.reserve(self.key)
        with self.assertRaises(ProtocolError) as caught:
            self.outbox.assert_resumable(self.key)
        self.assertEqual(caught.exception.token, "OUTBOX_UNCERTAIN_EMISSION")

    def test_committed_slot_is_resumable(self):
        self.outbox.reserve(self.key)
        self.outbox.commit(self.key, b"bytes", {})
        self.outbox.assert_resumable(self.key)

    def test_key_format_is_validated(self):
        with self.assertRaises(ProtocolError):
            self.outbox.key("synthetic-run", "party-a", "not-a-kind")
        with self.assertRaises(ProtocolError):
            self.outbox.key("../escape", "party-a", "partial")

    def test_separate_kinds_and_parties_do_not_collide(self):
        keys = {self.outbox.key("synthetic-run", "party-a", "partial"),
                self.outbox.key("synthetic-run", "party-a", "submission"),
                self.outbox.key("synthetic-run", "party-b", "partial")}
        self.assertEqual(len(keys), 3)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "disclosure.jsonl"
        self.ledger = DisclosureLedger(self.path)
        self.combination = {"study_id": "synthetic-study", "query_sha256": "a" * 64,
                            "snapshot_token": "snap-1", "recipients_sha256": "b" * 64}

    def test_first_release_is_permitted(self):
        self.ledger.permits(**self.combination, run_id="run-one")

    def test_same_query_snapshot_and_recipients_is_refused_afterwards(self):
        self.ledger.record(**self.combination, run_id="run-one", decision="APPROVE", at=NOW)
        with self.assertRaises(ProtocolError) as caught:
            self.ledger.permits(**self.combination, run_id="run-two")
        self.assertEqual(caught.exception.token, "DISCLOSURE_ALREADY_RELEASED")

    def test_a_different_snapshot_or_recipient_set_is_still_permitted(self):
        self.ledger.record(**self.combination, run_id="run-one", decision="APPROVE", at=NOW)
        self.ledger.permits(**{**self.combination, "snapshot_token": "snap-2"},
                            run_id="run-two")
        self.ledger.permits(**{**self.combination, "recipients_sha256": "c" * 64},
                            run_id="run-three")

    def test_one_output_per_run(self):
        self.ledger.record(**self.combination, run_id="run-one", decision="APPROVE", at=NOW)
        with self.assertRaises(ProtocolError) as caught:
            self.ledger.permits(**{**self.combination, "query_sha256": "d" * 64},
                                run_id="run-one")
        self.assertEqual(caught.exception.token, "DISCLOSURE_RUN_ALREADY_USED")

    def test_a_rejection_does_not_consume_the_combination(self):
        self.ledger.record(**self.combination, run_id="run-one", decision="REJECT", at=NOW)
        self.ledger.permits(**self.combination, run_id="run-two")

    def test_history_survives_a_restart(self):
        self.ledger.record(**self.combination, run_id="run-one", decision="APPROVE", at=NOW)
        reopened = DisclosureLedger(self.path)
        with self.assertRaises(ProtocolError):
            reopened.permits(**self.combination, run_id="run-two")
        self.assertEqual(len(reopened.entries()), 1)


if __name__ == "__main__":
    unittest.main()
