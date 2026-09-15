"""Process-separated crypto flows against the real OpenFHE worker (milestone M2).

Every party runs in its own private directory and every worker call is a separate
process. Same-host separate directories are a SIMULATION of institutional separation,
not a demonstration of it: one host administrator can read all of them.

Counts here are invented. No clinical value appears anywhere in this file.
"""
from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path

from . import OPENFHE_LIB, SKIP_REASON, WORKER_AVAILABLE, WORKER_BINARY
from protecmed_worker import WorkerClient, WorkerFailure


@unittest.skipUnless(WORKER_AVAILABLE, SKIP_REASON)
class WorkerCase(unittest.TestCase):
    """One epoch per test; a fresh context, fresh shares and a fresh job directory."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.public = self.root / "public"
        self.public.mkdir()
        self.client = WorkerClient(WORKER_BINARY, library_path=OPENFHE_LIB)

    def private_directory(self, name: str) -> Path:
        """A party's own namespace. Owner-only, as the worker requires for a share."""
        path = self.root / name
        path.mkdir()
        os.chmod(path, 0o700)
        return path

    # --- flow helpers ------------------------------------------------------
    def create_context(self, parties: int) -> Path:
        context = self.public / "context.bin"
        result = self.client.run("context-create",
                                 ["--parties", str(parties), "--out", context])
        self.assertEqual(result.payload["threshold_num_of_parties"], parties)
        self.assertEqual(result.payload["security_level"], "HEStd_128_classic")
        self.assertEqual(result.payload["multiparty_mode"], "NOISE_FLOODING_MULTIPARTY")
        return context

    def key_rounds(self, context: Path, parties: int,
                   epoch: str = "e1") -> tuple[list[Path], Path]:
        """Sequential distributed key generation; each share stays in its own directory."""
        shares, public_key = [], None
        for index in range(parties):
            private = self.private_directory(f"{epoch}-party-{index}")
            share = private / "share.bin"
            outgoing = self.public / f"pk-{epoch}-{index}.bin"
            if index == 0:
                self.client.run("keygen-first", ["--context", context,
                                                 "--secret-out", share,
                                                 "--public-out", outgoing])
            else:
                result = self.client.run("keygen-next", ["--context", context,
                                                         "--incoming", public_key,
                                                         "--secret-out", share,
                                                         "--public-out", outgoing])
                self.assertIs(result.payload["fresh"], False)
            shares.append(share)
            public_key = outgoing
        return shares, public_key

    def encrypt(self, context: Path, public_key: Path, count: int, name: str) -> Path:  # noqa: D401
        out = self.public / f"{name}.bin"
        result = self.client.run("encrypt-count",
                                 ["--context", context, "--public", public_key,
                                  "--count-stdin", "--out", out],
                                 stdin_bytes=f"{count}\n".encode())
        # The worker must not echo, return or log the local count.
        self.assertEqual(set(result.payload), {"command", "key_tag", "elements"})
        self.assertEqual(result.payload["elements"], 2)
        return out

    def full_flow(self, parties: int, counts: list[int]) -> int:
        context = self.create_context(parties)
        shares, public_key = self.key_rounds(context, parties)
        inputs = [self.encrypt(context, public_key, count, f"input-{i}")
                  for i, count in enumerate(counts)]
        aggregate = self.public / "aggregate.bin"
        flags = []
        for path in inputs:
            flags += ["--input", path]
        self.client.run("add-counts", ["--context", context, *flags, "--out", aggregate])
        verified = self.client.run("verify-aggregate",
                                   ["--context", context, *flags, "--candidate", aggregate])
        self.assertIs(verified.payload["equal"], True)
        partials = []
        for index, share in enumerate(shares):
            partial = share.parent / "partial.bin"
            self.client.run("partial-decrypt",
                            ["--context", context, "--secret", share,
                             "--ciphertext", aggregate,
                             "--role", "lead" if index == 0 else "main",
                             "--out", partial])
            partials.append(partial)
        partial_flags = []
        for path in partials:
            partial_flags += ["--partial", path]
        fused = self.client.run("fuse", ["--context", context, "--parties", str(parties),
                                         *partial_flags])
        self.context_path, self.shares, self.public_key = context, shares, public_key
        self.inputs, self.aggregate, self.partials = inputs, aggregate, partials
        self.key_tag = self.client.run(
            "inspect-public", ["--context", context, "--type", "public-key",
                               "--artifact", public_key]).payload["key_tag"]
        return fused.payload["aggregate"]


class PositiveFlowTests(WorkerCase):
    def test_two_party_exact_sum(self):
        self.assertEqual(self.full_flow(2, [5, 6]), 11)

    def test_three_party_exact_sum(self):
        self.assertEqual(self.full_flow(3, [3, 2, 6]), 11)

    def test_zero_counts(self):
        self.assertEqual(self.full_flow(2, [0, 0]), 0)

    def test_upper_bound_counts(self):
        self.assertEqual(self.full_flow(3, [10000, 10000, 10000]), 30000)

    def test_shares_are_owner_only_and_in_separate_directories(self):
        self.full_flow(2, [1, 2])
        self.assertNotEqual(self.shares[0].parent, self.shares[1].parent)
        for share in self.shares:
            self.assertEqual(share.stat().st_mode & 0o777, 0o600)
            self.assertEqual(share.parent.stat().st_mode & 0o777, 0o700)

    def test_inspect_public_describes_artifacts_without_decrypting(self):
        self.full_flow(2, [4, 7])
        context = self.client.run("inspect-public",
                                  ["--type", "context", "--artifact", self.context_path])
        self.assertEqual(context.payload["ring_dimension"], 8192)
        ciphertext = self.client.run("inspect-public",
                                     ["--context", self.context_path, "--type", "ciphertext",
                                      "--artifact", self.inputs[0]])
        self.assertEqual(ciphertext.payload["elements"], 2)
        partial = self.client.run("inspect-public",
                                  ["--context", self.context_path, "--type", "partial",
                                   "--artifact", self.partials[0]])
        self.assertEqual(partial.payload["elements"], 1)
        self.assertNotIn("aggregate", partial.payload)
        self.assertNotIn("plaintext", partial.payload)


class RejectionTests(WorkerCase):
    def setUp(self):
        super().setUp()
        self.parties = 2

    def prepared(self):
        self.full_flow(self.parties, [5, 6])

    def assert_fails(self, code, token, command, arguments, **kwargs):
        with self.assertRaises(WorkerFailure) as caught:
            self.client.run(command, arguments, **kwargs)
        self.assertEqual((caught.exception.returncode, caught.exception.token), (code, token))
        return caught.exception

    # --- wrong epoch -------------------------------------------------------
    def test_a_same_profile_context_is_deterministic_and_interchangeable(self):
        """Recorded measurement and limitation, not a defect being hidden.

        In this pinned build two `context-create` runs with the same profile serialize
        to BYTE-IDENTICAL files, and the worker accepts either one for artifacts made
        under the other. So a context hash identifies the PROFILE, not an epoch. Epoch
        identity comes from the signed plan, the recorded artifact hashes and the joint
        public-key tag (blueprint 2.2, 2.4) — application state built in M3.

        The determinism is a property of this build and architecture. It is what makes a
        canonical context hash usable as an additional cross-party check (blueprint 2.5);
        it must be re-measured on amd64 before any interoperability claim.
        """
        import hashlib
        self.prepared()
        second_context = self.root / "context-two.bin"
        self.client.run("context-create", ["--parties", "2", "--out", second_context])
        digest = hashlib.sha256(second_context.read_bytes()).hexdigest()
        self.assertEqual(digest,
                         hashlib.sha256(self.context_path.read_bytes()).hexdigest())
        described = self.client.run("inspect-public",
                                    ["--context", second_context, "--type", "ciphertext",
                                     "--artifact", self.inputs[0]])
        self.assertEqual(described.payload["key_tag"], self.key_tag)

    def test_input_from_another_key_epoch_is_refused_when_the_tag_is_pinned(self):
        """A real epoch change is a new key chain, and that changes the key tag."""
        context = self.create_context(2)
        _, first_key = self.key_rounds(context, 2, epoch="e1")
        _, second_key = self.key_rounds(context, 2, epoch="e2")
        first_tag = self.client.run(
            "inspect-public", ["--context", context, "--type", "public-key",
                               "--artifact", first_key]).payload["key_tag"]
        stale = self.encrypt(context, first_key, 5, "stale")
        fresh = self.encrypt(context, second_key, 6, "fresh")
        self.assert_fails(13, "INPUT_KEY_TAG_DISAGREEMENT", "add-counts",
                          ["--context", context, "--input", stale, "--input", fresh,
                           "--out", self.public / "aggregate-mixed.bin"])
        good = self.encrypt(context, second_key, 7, "good")
        self.assert_fails(13, "INPUT_KEY_TAG_MISMATCH", "add-counts",
                          ["--context", context, "--input", fresh, "--input", good,
                           "--expect-key-tag", first_tag,
                           "--out", self.public / "aggregate-pinned.bin"])

    def test_a_share_from_another_key_epoch_does_not_release_the_true_sum(self):
        """The worker is not an authorization layer.

        Nothing in the library ties a private share to the epoch that produced the
        aggregate. This test records what actually happens when a share from a second
        key chain is used: fusion either fails or yields a value that is not the true
        sum. It must never be read as the library enforcing epoch binding — the local
        key registry and the signed epoch manifest do that (blueprint 2.4).
        """
        self.prepared()
        other_shares, _ = self.key_rounds(self.context_path, 2, epoch="e2")
        foreign_partial = other_shares[0].parent / "foreign-partial.bin"
        self.client.run("partial-decrypt",
                        ["--context", self.context_path, "--secret", other_shares[0],
                         "--ciphertext", self.aggregate, "--role", "lead",
                         "--out", foreign_partial])
        try:
            fused = self.client.run("fuse", ["--context", self.context_path,
                                             "--parties", "2",
                                             "--partial", foreign_partial,
                                             "--partial", self.partials[1]])
        except WorkerFailure as failure:
            self.assertIn(failure.returncode, (14, 16))
            return
        self.assertNotEqual(fused.payload["aggregate"], 11)

    def test_input_under_an_intermediate_key_is_refused(self):
        context = self.create_context(2)
        _, public_key = self.key_rounds(context, 2)
        intermediate = self.public / "pk-e1-0.bin"
        good = self.encrypt(context, public_key, 5, "good")
        bad = self.encrypt(context, intermediate, 6, "bad")
        self.assertNotEqual(intermediate, public_key)
        self.assert_fails(13, "INPUT_KEY_TAG_DISAGREEMENT", "add-counts",
                          ["--context", context, "--input", good, "--input", bad,
                           "--out", self.public / "aggregate-bad.bin"])

    def test_expected_key_tag_is_enforced_when_supplied(self):
        self.prepared()
        self.assert_fails(13, "INPUT_KEY_TAG_MISMATCH", "add-counts",
                          ["--context", self.context_path,
                           "--input", self.inputs[0], "--input", self.inputs[1],
                           "--expect-key-tag", "0" * 32,
                           "--out", self.public / "aggregate-tagged.bin"])

    # --- wrong input / wrong aggregate -------------------------------------
    def test_substituted_input_makes_verification_fail(self):
        self.prepared()
        substitute = self.encrypt(self.context_path, self.public_key, 99, "substitute")
        with self.assertRaises(WorkerFailure) as caught:
            self.client.run("verify-aggregate",
                            ["--context", self.context_path,
                             "--input", self.inputs[0], "--input", substitute,
                             "--candidate", self.aggregate])
        self.assertEqual(caught.exception.returncode, 17)

    def test_candidate_that_is_not_the_sum_is_refused(self):
        self.prepared()
        with self.assertRaises(WorkerFailure) as caught:
            self.client.run("verify-aggregate",
                            ["--context", self.context_path,
                             "--input", self.inputs[0], "--input", self.inputs[1],
                             "--candidate", self.inputs[0]])
        self.assertEqual(caught.exception.returncode, 17)

    def test_input_count_must_equal_the_context_party_count(self):
        self.prepared()
        self.assert_fails(13, "INPUT_COUNT_MISMATCH", "add-counts",
                          ["--context", self.context_path, "--input", self.inputs[0],
                           "--out", self.public / "aggregate-short.bin"])

    def test_duplicate_input_is_refused(self):
        self.prepared()
        self.assert_fails(13, "DUPLICATE_INPUT", "add-counts",
                          ["--context", self.context_path,
                           "--input", self.inputs[0], "--input", self.inputs[0],
                           "--out", self.public / "aggregate-dup.bin"])

    def test_partial_cannot_be_used_as_an_input_count(self):
        self.prepared()
        self.assert_fails(13, "INPUT_NOT_A_FRESH_CIPHERTEXT", "add-counts",
                          ["--context", self.context_path,
                           "--input", self.partials[0], "--input", self.inputs[1],
                           "--out", self.public / "aggregate-partial.bin"])

    # --- missing share / role ----------------------------------------------
    def test_fuse_refuses_a_missing_partial_and_returns_no_value(self):
        self.prepared()
        failure = self.assert_fails(15, "PARTIAL_COUNT_MISMATCH", "fuse",
                                    ["--context", self.context_path, "--parties", "2",
                                     "--partial", self.partials[0]])
        self.assertNotIn("aggregate", str(failure))

    def test_fuse_refuses_a_duplicated_partial(self):
        self.prepared()
        self.assert_fails(15, "DUPLICATE_PARTIAL", "fuse",
                          ["--context", self.context_path, "--parties", "2",
                           "--partial", self.partials[0], "--partial", self.partials[0]])

    def test_fuse_party_count_must_match_the_context(self):
        self.prepared()
        self.assert_fails(10, "PARTY_COUNT", "fuse",
                          ["--context", self.context_path, "--parties", "4",
                           "--partial", self.partials[0], "--partial", self.partials[1]])

    def test_unknown_role_is_refused(self):
        self.prepared()
        self.assert_fails(15, "INVALID_ROLE", "partial-decrypt",
                          ["--context", self.context_path, "--secret", self.shares[0],
                           "--ciphertext", self.aggregate, "--role", "coordinator",
                           "--out", self.root / "party-0" / "bad-partial.bin"])

    def test_partial_decrypt_refuses_a_partial_as_its_ciphertext(self):
        self.prepared()
        self.assert_fails(13, "AGGREGATE_NOT_A_FRESH_CIPHERTEXT", "partial-decrypt",
                          ["--context", self.context_path, "--secret", self.shares[0],
                           "--ciphertext", self.partials[1], "--role", "main",
                           "--out", self.root / "party-0" / "bad-partial-2.bin"])

    # --- ranges and argument hygiene ---------------------------------------
    def test_count_above_the_local_cap_is_refused(self):
        context = self.create_context(2)
        _, public_key = self.key_rounds(context, 2)
        self.assert_fails(16, "COUNT_OUT_OF_RANGE", "encrypt-count",
                          ["--context", context, "--public", public_key,
                           "--count-stdin", "--out", self.public / "too-big.bin"],
                          stdin_bytes=b"10001\n")

    def test_non_numeric_count_is_refused(self):
        context = self.create_context(2)
        _, public_key = self.key_rounds(context, 2)
        for payload in (b"-1\n", b"5.0\n", b"", b"abc\n", b"0x10\n"):
            self.assert_fails(16, "COUNT_FORMAT", "encrypt-count",
                              ["--context", context, "--public", public_key,
                               "--count-stdin", "--out", self.public / f"bad-{len(payload)}.bin"],
                              stdin_bytes=payload)

    def test_a_roster_without_a_lead_does_not_reliably_fail(self):
        """Blueprint 2.6: a missing-share test must verify that the APPLICATION never
        invokes fusion, not assume the library throws.

        Here two `main` partials and no `lead` are fused. Observed on this build: the
        result is either an out-of-range failure or a wrong integer. Either way it is
        never the true sum, and neither outcome is an enforcement mechanism.
        """
        self.prepared()
        second_main = self.shares[1].parent / "second-main.bin"
        self.client.run("partial-decrypt",
                        ["--context", self.context_path, "--secret", self.shares[1],
                         "--ciphertext", self.aggregate, "--role", "main",
                         "--out", second_main])
        try:
            fused = self.client.run("fuse", ["--context", self.context_path,
                                             "--parties", "2",
                                             "--partial", self.partials[1],
                                             "--partial", second_main])
        except WorkerFailure as failure:
            self.assertIn(failure.returncode, (14, 16))
            return
        self.assertNotEqual(fused.payload["aggregate"], 11)

    def test_aggregation_commands_reject_a_secret_flag(self):
        self.prepared()
        self.assert_fails(10, "FLAG_NOT_ALLOWED_FOR_COMMAND", "add-counts",
                          ["--context", self.context_path, "--secret", self.shares[0],
                           "--input", self.inputs[0], "--input", self.inputs[1],
                           "--out", self.public / "aggregate-secret.bin"])

    def test_fuse_rejects_the_input_flag(self):
        self.prepared()
        self.assert_fails(10, "FLAG_NOT_ALLOWED_FOR_COMMAND", "fuse",
                          ["--context", self.context_path, "--parties", "2",
                           "--input", self.partials[0], "--input", self.partials[1]])

    def test_repeated_flag_is_refused(self):
        self.prepared()
        self.assert_fails(10, "REPEATED_FLAG", "inspect-public",
                          ["--type", "context", "--artifact", self.context_path,
                           "--artifact", self.context_path])

    def test_positional_argument_is_refused(self):
        self.assert_fails(10, "UNEXPECTED_POSITIONAL_ARGUMENT", "context-create",
                          ["2", "--out", self.public / "ctx.bin"])

    # --- filesystem rules ---------------------------------------------------
    def test_existing_output_is_never_overwritten(self):
        context = self.create_context(2)
        self.assert_fails(20, "OUTPUT_EXISTS", "context-create",
                          ["--parties", "2", "--out", context])

    def test_symlinked_input_is_refused(self):
        context = self.create_context(2)
        link = self.public / "context-link.bin"
        link.symlink_to(context)
        self.assert_fails(20, "SYMLINK_REFUSED", "inspect-public",
                          ["--type", "context", "--artifact", link])

    def test_share_is_not_written_into_a_group_readable_directory(self):
        context = self.create_context(2)
        shared = self.root / "not-private"
        shared.mkdir()
        os.chmod(shared, 0o755)
        self.assert_fails(20, "SECRET_DIRECTORY_NOT_PRIVATE", "keygen-first",
                          ["--context", context, "--secret-out", shared / "share.bin",
                           "--public-out", self.public / "pk-loose.bin"])

    def test_garbage_artifact_is_refused_as_a_serialization_failure(self):
        path = self.public / "garbage.bin"
        path.write_bytes(b"not an openfhe artifact")
        self.assert_fails(12, "CONTEXT_DESERIALIZE_FAILED", "inspect-public",
                          ["--type", "context", "--artifact", path])


if __name__ == "__main__":
    unittest.main()
