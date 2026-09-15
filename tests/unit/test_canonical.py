"""Strict value normalization (blueprint 3.3, 3.6)."""
from __future__ import annotations
import unittest

from . import ROOT  # noqa: F401  (installs the service path)
from protecmed_party.canonical import (FIELDS, is_raw_blank, normalize, project_raw_rows)
from protecmed_party.errors import ImportRejected, ValidationFailed


def raw(**overrides):
    row = {f: None for f in FIELDS}
    row.update(overrides)
    return row


class NormalizationTests(unittest.TestCase):
    def test_enum_is_trimmed_and_uppercased(self):
        self.assertEqual(normalize("diagnosis", "  mbl "), "MBL")
        self.assertEqual(normalize("rt_technique", "imrt"), "IMRT")
        self.assertEqual(normalize("surgery_type", "biopsie"), "BIOPSIE")

    def test_multiword_enum_keeps_inner_space(self):
        self.assertEqual(normalize("diagnosis", "pineal tumor"), "PINEAL TUMOR")

    def test_unknown_enum_token_is_rejected_not_guessed(self):
        with self.assertRaises(ImportRejected) as caught:
            normalize("diagnosis", "MBL2")
        self.assertEqual(caught.exception.token, "UNKNOWN_ENUM_VALUE")

    def test_missing_tokens_map_to_none(self):
        for token in ("", "  ", "NA", "n/a", "null", "N/A"):
            self.assertIsNone(normalize("diagnosis", token), token)
        self.assertIsNone(normalize("age_at_rt", "NA"))
        self.assertIsNone(normalize("toxicity_wbc_ge2", "NULL"))

    def test_string_no_is_false_not_truthy(self):
        # bool("NO") is True in Python; the importer must never do that.
        self.assertIs(normalize("toxicity_wbc_ge2", "NO"), False)
        self.assertIs(normalize("toxicity_wbc_ge2", "nu"), False)
        self.assertIs(normalize("toxicity_wbc_ge2", "FALSE"), False)
        self.assertIs(normalize("toxicity_wbc_ge2", "0"), False)

    def test_boolean_false_survives_as_false_not_missing(self):
        self.assertIs(normalize("toxicity_wbc_ge2", False), False)
        self.assertIs(normalize("toxicity_wbc_ge2", 0), False)
        self.assertIs(normalize("toxicity_wbc_ge2", True), True)
        self.assertIs(normalize("toxicity_wbc_ge2", 1), True)

    def test_numeric_boolean_other_than_zero_or_one_is_rejected(self):
        with self.assertRaises(ImportRejected) as caught:
            normalize("toxicity_wbc_ge2", 2)
        self.assertEqual(caught.exception.token, "INVALID_BOOLEAN_NUMERIC")

    def test_age_accepts_integers_and_integer_strings(self):
        self.assertEqual(normalize("age_at_rt", 11), 11)
        self.assertEqual(normalize("age_at_rt", 11.0), 11)
        self.assertEqual(normalize("age_at_rt", " 7 "), 7)

    def test_age_fraction_is_rejected_not_truncated(self):
        with self.assertRaises(ImportRejected) as caught:
            normalize("age_at_rt", 11.5)
        self.assertEqual(caught.exception.token, "AGE_NOT_INTEGER")
        with self.assertRaises(ImportRejected):
            normalize("age_at_rt", "11.5")

    def test_age_range_and_boolean_confusion(self):
        with self.assertRaises(ImportRejected) as caught:
            normalize("age_at_rt", 121)
        self.assertEqual(caught.exception.token, "AGE_OUT_OF_RANGE")
        with self.assertRaises(ImportRejected) as caught:
            normalize("age_at_rt", True)
        self.assertEqual(caught.exception.token, "BOOLEAN_IS_NOT_AGE")

    def test_enum_type_must_be_string(self):
        with self.assertRaises(ImportRejected) as caught:
            normalize("diagnosis", 3)
        self.assertEqual(caught.exception.token, "INVALID_ENUM_TYPE")


class AdmissionTests(unittest.TestCase):
    def test_blank_detection_treats_na_as_present(self):
        self.assertTrue(is_raw_blank(None))
        self.assertTrue(is_raw_blank("   "))
        self.assertFalse(is_raw_blank("NA"))
        self.assertFalse(is_raw_blank(False))

    def test_wholly_blank_row_is_skipped_and_counted(self):
        rows, report = project_raw_rows([raw(diagnosis="MBL"), raw(), raw(diagnosis="  ")])
        self.assertEqual(report["admitted_rows"], 1)
        self.assertEqual(report["skipped_blank_rows"], 2)
        self.assertEqual(len(rows), 1)

    def test_all_explicit_missing_tokens_row_is_admitted(self):
        rows, report = project_raw_rows([raw(**{f: "NA" for f in FIELDS})])
        self.assertEqual(report["admitted_rows"], 1)
        self.assertEqual(rows[0], {f: None for f in FIELDS})
        self.assertEqual(report["fields"]["diagnosis"]["missing"], 1)

    def test_admitted_order_is_retained(self):
        rows, _ = project_raw_rows([raw(diagnosis="MBL"), raw(diagnosis="EPD"),
                                    raw(diagnosis="PNET")])
        self.assertEqual([row["diagnosis"] for row in rows], ["MBL", "EPD", "PNET"])

    def test_invalid_value_fails_closed_with_a_local_report(self):
        with self.assertRaises(ValidationFailed) as caught:
            project_raw_rows([raw(diagnosis="MBL"), raw(age_at_rt="11.5", diagnosis="MBL")])
        report = caught.exception.report
        self.assertEqual(report["invalid_values_total"], 1)
        self.assertEqual(report["fields"]["age_at_rt"]["invalid_codes"],
                         {"INVALID_AGE_TYPE": 1})
        self.assertEqual(report["fields"]["age_at_rt"]["invalid_rows"], [1])

    def test_report_never_carries_the_offending_value(self):
        with self.assertRaises(ValidationFailed) as caught:
            project_raw_rows([raw(diagnosis="SECRET-DIAGNOSIS")])
        self.assertNotIn("SECRET-DIAGNOSIS", repr(caught.exception.report))
        self.assertNotIn("SECRET-DIAGNOSIS", str(caught.exception))

    def test_projection_must_be_exactly_the_five_fields(self):
        with self.assertRaises(ImportRejected) as caught:
            project_raw_rows([{**raw(diagnosis="MBL"), "patient_name": "x"}])
        self.assertEqual(caught.exception.token, "PROJECTION_FIELDS_MISMATCH")


if __name__ == "__main__":
    unittest.main()
