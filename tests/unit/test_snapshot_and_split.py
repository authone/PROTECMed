"""Frozen snapshots, opaque tokens and the simulated demo split (blueprint 3.3, 3.5)."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from . import ROOT
from protecmed_party.catalogue import count_query, load_catalogue
from protecmed_party.errors import ImportRejected
from protecmed_party.importer import read_canonical_csv
from protecmed_party.snapshot import Snapshot, SnapshotStore, freeze
from protecmed_party.splitter import SIMULATION_LABEL, split_rows, write_shards

CATALOGUE = load_catalogue(ROOT / "config/query-catalog.json")
EXPECTED = json.loads((ROOT / "fixtures/synthetic_expected.json").read_text())["counts"]


def load_fixture():
    return read_canonical_csv(ROOT / "fixtures/synthetic_cohorts.csv")


def make_snapshot(**overrides):
    records, report = load_fixture()
    arguments = {"source_sha256": "a" * 64, "mapping_id": "iocn-csi-v2",
                 "mapping_digest": "b" * 64}
    arguments.update(overrides)
    return freeze(records, report, **arguments)


class SnapshotTests(unittest.TestCase):
    def test_token_is_opaque_and_not_derived_from_the_source_digest(self):
        first, second = make_snapshot(), make_snapshot()
        self.assertNotEqual(first.snapshot_token, second.snapshot_token)
        self.assertEqual(len(first.snapshot_token), 32)
        self.assertNotIn(first.source_sha256, first.snapshot_token)

    def test_public_descriptor_leaks_no_count_and_no_source_digest(self):
        snapshot = make_snapshot()
        descriptor = snapshot.public_descriptor()
        self.assertEqual(set(descriptor), {"snapshot_token", "mapping_digest"})
        # A substring check on the random token would be flaky; check the values instead.
        self.assertNotIn(snapshot.source_sha256, descriptor.values())
        self.assertNotIn(snapshot.admitted_rows, descriptor.values())
        self.assertNotIn("admitted_rows", descriptor)
        self.assertNotIn(snapshot.source_sha256, json.dumps(descriptor))

    def test_local_metadata_keeps_the_source_digest_and_report(self):
        snapshot = make_snapshot()
        metadata = snapshot.local_metadata()
        self.assertEqual(metadata["source_sha256"], "a" * 64)
        self.assertEqual(metadata["admitted_rows"], 24)
        self.assertIn("report", metadata)

    def test_frozen_records_are_copies(self):
        records, report = load_fixture()
        snapshot = freeze(records, report, source_sha256="a" * 64,
                          mapping_id="iocn-csi-v2", mapping_digest="b" * 64)
        records[0]["diagnosis"] = "EPD"
        self.assertNotEqual(snapshot.records[0]["diagnosis"], "EPD")

    def test_count_on_the_frozen_snapshot_is_stable(self):
        snapshot = make_snapshot()
        before = count_query(snapshot.records, CATALOGUE[3], CATALOGUE)["count"]
        self.assertEqual(before, EXPECTED["Q004"]["total"])


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = SnapshotStore(Path(self.temporary.name) / "registry")

    def test_store_refuses_a_directory_inside_a_git_work_tree(self):
        with self.assertRaises(ImportRejected) as caught:
            SnapshotStore(ROOT / "fixtures/local-registry")
        self.assertEqual(caught.exception.token, "SNAPSHOT_STORE_INSIDE_REPOSITORY")
        self.assertFalse((ROOT / "fixtures/local-registry").exists())

    def test_directory_is_owner_only(self):
        self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)

    def test_round_trip(self):
        snapshot = make_snapshot()
        path = self.store.save(snapshot)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        loaded = self.store.load(snapshot.snapshot_token)
        self.assertEqual(loaded.records, snapshot.records)
        self.assertEqual(loaded.source_sha256, snapshot.source_sha256)

    def test_a_frozen_snapshot_is_never_rewritten(self):
        snapshot = make_snapshot()
        self.store.save(snapshot)
        with self.assertRaises(FileExistsError):
            self.store.save(snapshot)

    def test_reimport_supersedes_the_previous_selection(self):
        first = make_snapshot()
        self.store.save(first)
        second = make_snapshot(source_sha256="c" * 64)
        self.store.save(second)
        superseded = self.store.supersede_others(second.snapshot_token)
        self.assertEqual(superseded, [first.snapshot_token])
        self.assertTrue(self.store.is_superseded(first.snapshot_token))
        self.assertFalse(self.store.is_superseded(second.snapshot_token))
        # The superseded snapshot's frozen contribution is unchanged.
        self.assertEqual(self.store.load(first.snapshot_token).records, first.records)

    def test_malformed_token_is_refused(self):
        with self.assertRaises(ImportRejected) as caught:
            self.store.load("../../etc/passwd")
        self.assertEqual(caught.exception.token, "SNAPSHOT_TOKEN_FORMAT")


class SplitterTests(unittest.TestCase):
    def setUp(self):
        self.records, _ = load_fixture()

    def test_two_and_three_way_splits_match_the_delivered_expectations(self):
        for parties, key in ((2, "two_parties"), (3, "three_parties")):
            shards = split_rows(self.records, parties)
            for query_id, expected in EXPECTED.items():
                entry = next(e for e in CATALOGUE if e["query_id"] == query_id)
                counts = [count_query(shard, entry, CATALOGUE)["count"] for shard in shards]
                self.assertEqual(counts, expected[key], (query_id, parties))

    def test_shards_are_disjoint_and_cover_every_admitted_row(self):
        for parties in (2, 3):
            shards = split_rows(self.records, parties)
            self.assertEqual(sum(len(shard) for shard in shards), len(self.records))
            rebuilt = []
            for index in range(max(len(shard) for shard in shards)):
                for shard in shards:
                    if index < len(shard):
                        rebuilt.append(shard[index])
            self.assertEqual(rebuilt, self.records)

    def test_only_two_or_three_parties(self):
        for parties in (0, 1, 4, "2", True):
            with self.assertRaises(ImportRejected) as caught:
                split_rows(self.records, parties)
            self.assertEqual(caught.exception.token, "PARTY_COUNT")

    def test_written_shards_contain_only_the_five_canonical_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_shards(split_rows(self.records, 3), Path(directory))
            self.assertEqual(len(paths), 3)
            header = paths[0].read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(header, "diagnosis,rt_technique,toxicity_wbc_ge2,"
                                     "age_at_rt,surgery_type")
            reloaded, _ = read_canonical_csv(paths[0])
            self.assertEqual(reloaded, split_rows(self.records, 3)[0])

    def test_simulation_label_exists(self):
        self.assertIn("NOT_INDEPENDENT_INSTITUTIONS", SIMULATION_LABEL)


if __name__ == "__main__":
    unittest.main()
