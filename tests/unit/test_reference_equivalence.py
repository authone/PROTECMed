"""The production party-agent module must agree with the delivered reference helper.

`reference/python/cohort.py` is frozen under the 2026-09-05 verification ledger, so the
M1 implementation is a separate port rather than an import of it. This test is what keeps
the two honest: a divergence here is a release-blocking defect, not a style difference.
"""
from __future__ import annotations
import json
import sys
import unittest

from . import ROOT

sys.path.insert(0, str(ROOT / "reference/python"))
import cohort as reference  # noqa: E402

from protecmed_party import canonical as production  # noqa: E402
from protecmed_party.catalogue import count_query, load_catalogue  # noqa: E402
from protecmed_party.importer import read_canonical_csv  # noqa: E402
from protecmed_party.splitter import split_rows  # noqa: E402

CATALOGUE = load_catalogue(ROOT / "config/query-catalog.json")
EXPECTED = json.loads((ROOT / "fixtures/synthetic_expected.json").read_text())["counts"]

VALUES = ["MBL", " mbl ", "PINEAL TUMOR", "EPD", "MBL2", "", "  ", "NA", "n/a", "NULL",
          "IMRT", "3dcrt", "GTR", "biopsie", "YES", "NO", "DA", "NU", "TRUE", "FALSE",
          "1", "0", "11", " 7 ", "11.5", "-3", "121", None, True, False, 0, 1, 2, 9,
          9.0, 11.5, 121, "x"]


def outcome(module, field, value):
    try:
        result = module.normalize(field, value)
    except ValueError:
        return ("rejected",)
    return ("accepted", type(result).__name__, result)


class EquivalenceTests(unittest.TestCase):
    def test_normalization_agrees_on_every_probe_value(self):
        for field in production.FIELDS:
            for value in VALUES:
                self.assertEqual(outcome(production, field, value),
                                 outcome(reference, field, value),
                                 (field, repr(value)))

    def test_blank_detection_agrees(self):
        for value in VALUES:
            self.assertEqual(production.is_raw_blank(value), reference.is_raw_blank(value),
                             repr(value))

    def test_canonical_fixture_parses_identically(self):
        mine, _ = read_canonical_csv(ROOT / "fixtures/synthetic_cohorts.csv")
        theirs = reference.read_canonical_csv(ROOT / "fixtures/synthetic_cohorts.csv")
        self.assertEqual(mine, theirs)

    def test_counts_and_splits_agree_with_the_reference_summary(self):
        records, _ = read_canonical_csv(ROOT / "fixtures/synthetic_cohorts.csv")
        theirs = reference.summarize(records, [dict(entry) for entry in CATALOGUE])
        for entry in CATALOGUE:
            query_id = entry["query_id"]
            mine_total = count_query(records, entry, CATALOGUE)["count"]
            self.assertEqual(mine_total, theirs[query_id]["total"], query_id)
            self.assertEqual(mine_total, EXPECTED[query_id]["total"], query_id)
            for parties, key in ((2, "two_parties"), (3, "three_parties")):
                mine_split = [count_query(shard, entry, CATALOGUE)["count"]
                              for shard in split_rows(records, parties)]
                self.assertEqual(mine_split, theirs[query_id][key], (query_id, parties))


if __name__ == "__main__":
    unittest.main()
