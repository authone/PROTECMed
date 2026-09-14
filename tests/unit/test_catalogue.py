"""Fixed query catalogue and exact local counting (blueprint 3.4)."""
from __future__ import annotations
import copy
import json
import unittest

from . import ROOT
from protecmed_party.catalogue import (assert_catalogue_member, count_query, load_catalogue,
                                       query_hash, query_report, validate_query)
from protecmed_party.errors import ImportRejected
from protecmed_party.importer import read_canonical_csv

CATALOGUE = load_catalogue(ROOT / "config/query-catalog.json")
EXPECTED = json.loads((ROOT / "fixtures/synthetic_expected.json").read_text())["counts"]


def q(query_id):
    return copy.deepcopy(next(e for e in CATALOGUE if e["query_id"] == query_id))


class CatalogueTests(unittest.TestCase):
    def test_delivered_catalogue_is_six_valid_queries(self):
        self.assertEqual([e["query_id"] for e in CATALOGUE],
                         ["Q001", "Q002", "Q003", "Q004", "Q005", "Q006"])
        for entry in CATALOGUE:
            validate_query(entry)

    def test_q004_matches_the_blueprint_definition(self):
        self.assertEqual(q("Q004")["filters"], [
            {"field": "diagnosis", "operator": "eq", "value": "MBL"},
            {"field": "rt_technique", "operator": "eq", "value": "IMRT"},
            {"field": "toxicity_wbc_ge2", "operator": "eq", "value": True},
        ])

    def test_query_hash_is_stable_and_distinct(self):
        self.assertEqual(query_hash(q("Q004")), query_hash(q("Q004")))
        self.assertNotEqual(query_hash(q("Q004")), query_hash(q("Q003")))


class RejectionTests(unittest.TestCase):
    def test_unknown_query_id(self):
        bad = dict(q("Q002"), query_id="Q099")
        with self.assertRaises(ImportRejected) as caught:
            validate_query(bad)
        self.assertEqual(caught.exception.token, "QUERY_ID")

    def test_extra_key_is_refused(self):
        bad = dict(q("Q002"), limit=10)
        with self.assertRaises(ImportRejected) as caught:
            validate_query(bad)
        self.assertEqual(caught.exception.token, "QUERY_FIELDS")

    def test_more_than_five_filters(self):
        bad = q("Q002")
        bad["filters"] = bad["filters"] * 6
        with self.assertRaises(ImportRejected) as caught:
            validate_query(bad)
        self.assertEqual(caught.exception.token, "QUERY_FILTERS")

    def test_empty_filters_allowed_only_for_q001(self):
        bad = q("Q002")
        bad["filters"] = []
        with self.assertRaises(ImportRejected) as caught:
            validate_query(bad)
        self.assertEqual(caught.exception.token, "EMPTY_QUERY")

    def test_integer_one_does_not_satisfy_the_boolean_predicate(self):
        bad = q("Q004")
        bad["filters"][2]["value"] = 1
        with self.assertRaises(ImportRejected) as caught:
            validate_query(bad)
        self.assertEqual(caught.exception.token, "BOOL_PREDICATE")

    def test_boolean_does_not_satisfy_the_age_predicate(self):
        bad = q("Q005")
        for predicate in bad["filters"]:
            if predicate["field"] == "age_at_rt":
                predicate["value"] = True
        with self.assertRaises(ImportRejected) as caught:
            validate_query(bad)
        self.assertEqual(caught.exception.token, "AGE_PREDICATE")

    def test_unknown_operator_or_field(self):
        bad = q("Q002")
        bad["filters"][0]["operator"] = "like"
        with self.assertRaises(ImportRejected):
            validate_query(bad)
        bad = q("Q002")
        bad["filters"][0]["field"] = "patient_name"
        with self.assertRaises(ImportRejected) as caught:
            validate_query(bad)
        self.assertEqual(caught.exception.token, "PREDICATE_FIELD")

    def test_sql_like_payloads_are_refused_before_any_row_is_read(self):
        for payload in ("MBL' OR 1=1 --", "__import__('os')", "MBL%"):
            bad = q("Q002")
            bad["filters"][0]["value"] = payload
            with self.assertRaises(ImportRejected) as caught:
                validate_query(bad)
            self.assertEqual(caught.exception.token, "ENUM_PREDICATE")

    def test_valid_but_unlisted_query_is_refused(self):
        unlisted = q("Q002")
        unlisted["filters"] = [{"field": "diagnosis", "operator": "eq", "value": "EPD"}]
        validate_query(unlisted)  # structurally fine
        with self.assertRaises(ImportRejected) as caught:
            assert_catalogue_member(unlisted, CATALOGUE)
        self.assertEqual(caught.exception.token, "QUERY_NOT_ALLOWLISTED")

    def test_duplicate_field_in_filters(self):
        bad = q("Q003")
        bad["filters"] = [bad["filters"][0], bad["filters"][0]]
        with self.assertRaises(ImportRejected) as caught:
            validate_query(bad)
        self.assertEqual(caught.exception.token, "PREDICATE_FIELD")


class CountingTests(unittest.TestCase):
    def setUp(self):
        self.records, _ = read_canonical_csv(ROOT / "fixtures/synthetic_cohorts.csv")

    def test_synthetic_totals_match_the_delivered_expectations(self):
        report = query_report(self.records, CATALOGUE)
        for query_id, expected in EXPECTED.items():
            self.assertEqual(report[query_id]["count"], expected["total"], query_id)

    def test_rows_missing_a_required_field_are_excluded_only_for_that_query(self):
        rows = [{"diagnosis": "MBL", "rt_technique": "IMRT", "toxicity_wbc_ge2": None,
                 "age_at_rt": 9, "surgery_type": "GTR"}]
        self.assertEqual(count_query(rows, q("Q003"), CATALOGUE)["count"], 1)
        result = count_query(rows, q("Q004"), CATALOGUE)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["eligible"], 0)
        self.assertEqual(result["excluded_missing"], 1)

    def test_false_toxicity_is_counted_as_eligible_and_not_matching(self):
        rows = [{"diagnosis": "MBL", "rt_technique": "IMRT", "toxicity_wbc_ge2": False,
                 "age_at_rt": 9, "surgery_type": "GTR"}]
        result = count_query(rows, q("Q004"), CATALOGUE)
        self.assertEqual((result["eligible"], result["count"]), (1, 0))

    def test_age_predicate_is_strictly_less_than(self):
        rows = [{"diagnosis": "MBL", "rt_technique": "IMRT", "toxicity_wbc_ge2": True,
                 "age_at_rt": 12, "surgery_type": "GTR"}]
        self.assertEqual(count_query(rows, q("Q005"), CATALOGUE)["count"], 0)
        rows[0]["age_at_rt"] = 11
        self.assertEqual(count_query(rows, q("Q005"), CATALOGUE)["count"], 1)

    def test_noncanonical_row_is_refused(self):
        rows = [{"diagnosis": "mbl", "rt_technique": "IMRT", "toxicity_wbc_ge2": True,
                 "age_at_rt": 9, "surgery_type": "GTR"}]
        with self.assertRaises(ImportRejected) as caught:
            count_query(rows, q("Q004"), CATALOGUE)
        self.assertEqual(caught.exception.token, "NONCANONICAL_VALUE")

    def test_integer_one_in_a_row_is_not_accepted_as_true(self):
        rows = [{"diagnosis": "MBL", "rt_technique": "IMRT", "toxicity_wbc_ge2": 1,
                 "age_at_rt": 9, "surgery_type": "GTR"}]
        with self.assertRaises(ImportRejected) as caught:
            count_query(rows, q("Q004"), CATALOGUE)
        self.assertEqual(caught.exception.token, "NONCANONICAL_VALUE")


if __name__ == "__main__":
    unittest.main()
