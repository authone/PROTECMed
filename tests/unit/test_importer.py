"""XLSX and canonical-CSV import, including every case required by blueprint 3.6.

All workbooks here are invented in-process. No clinical file is read.
"""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from . import ROOT
from .synthetic_workbook import (HEADERS, blank_cell, boolean_cell, build_workbook,
                                 formula_cell, number_cell, text_cell)
from protecmed_party.errors import ImportRejected
from protecmed_party.importer import (LITERAL_ONLY, REVIEWED_CACHED, file_digest,
                                      import_workbook, load_mapping, read_canonical_csv)

MAPPING = load_mapping(ROOT / "config/iocn-mapping.json")


def row(**overrides):
    cells = {"diagnosis": text_cell("MBL"), "rt_technique": text_cell("IMRT"),
             "toxicity_wbc_ge2": boolean_cell(True), "age_at_rt": number_cell("9"),
             "surgery_type": text_cell("GTR")}
    cells.update(overrides)
    return cells


class WorkbookCase(unittest.TestCase):
    def build(self, rows, **kwargs):
        directory = Path(tempfile.mkdtemp(dir=self.temporary.name))
        return build_workbook(directory / "synthetic.xlsx", rows, **kwargs)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def acknowledgement(self, path, **overrides):
        record = {"operator": "local-operator", "acknowledged_utc": "2026-09-14T09:00:00Z",
                  "source_sha256": file_digest(path), "mapping_id": MAPPING.mapping_id,
                  "statement": "IOCN recalculated and saved this workbook."}
        record.update(overrides)
        return record

    def reviewed(self, path, **overrides):
        return import_workbook(path, MAPPING, REVIEWED_CACHED,
                               cache_acknowledgement=self.acknowledgement(path, **overrides))


class FormulaModeTests(WorkbookCase):
    def test_formula_rejected_in_default_literal_mode(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING)
        self.assertEqual(caught.exception.token, "FORMULA_NOT_ALLOWED")

    def test_formula_with_valid_saved_result_accepted_when_reviewed(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        records, report = self.reviewed(path)
        self.assertIs(records[0]["toxicity_wbc_ge2"], True)
        self.assertEqual(report["selected_formula_cells"]["toxicity_wbc_ge2"], 1)
        self.assertIs(report["cache_freshness_verified"], False)
        self.assertIn("freshness", report["cache_warning"])

    def test_saved_false_result_is_false_not_missing(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "0"))])
        records, _ = self.reviewed(path)
        self.assertIs(records[0]["toxicity_wbc_ge2"], False)

    def test_formula_without_cache_fails_closed(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", None))])
        with self.assertRaises(ImportRejected) as caught:
            self.reviewed(path)
        self.assertEqual(caught.exception.token, "FORMULA_CACHE_MISSING")

    def test_formula_with_empty_cache_fails_closed(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1&\"\"", "",
                                                             cell_type="str"))])
        with self.assertRaises(ImportRejected) as caught:
            self.reviewed(path)
        self.assertEqual(caught.exception.token, "FORMULA_CACHE_MISSING")

    def test_excel_error_result_is_rejected(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("1/0", "#DIV/0!",
                                                             cell_type="e"))])
        with self.assertRaises(ImportRejected) as caught:
            self.reviewed(path)
        self.assertEqual(caught.exception.token, "EXCEL_ERROR_CELL")

    def test_literal_cells_need_no_acknowledgement(self):
        path = self.build([row()])
        records, report = import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(len(records), 1)
        self.assertEqual(report["import_mode"], LITERAL_ONLY)
        self.assertEqual(report["selected_formula_cells"]["toxicity_wbc_ge2"], 0)

    def test_unknown_mode_rejected(self):
        path = self.build([row()])
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, "trust-me")
        self.assertEqual(caught.exception.token, "IMPORT_MODE")


class AcknowledgementTests(WorkbookCase):
    def test_reviewed_mode_requires_an_acknowledgement(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, REVIEWED_CACHED)
        self.assertEqual(caught.exception.token, "CACHE_ACKNOWLEDGEMENT_REQUIRED")

    def test_acknowledgement_for_a_different_source_is_refused(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        with self.assertRaises(ImportRejected) as caught:
            self.reviewed(path, source_sha256="0" * 64)
        self.assertEqual(caught.exception.token, "CACHE_ACKNOWLEDGEMENT_SOURCE_MISMATCH")

    def test_changed_workbook_invalidates_the_previous_acknowledgement(self):
        first = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        stale = self.acknowledgement(first)
        second = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "0")),
                             row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(second, MAPPING, REVIEWED_CACHED, cache_acknowledgement=stale)
        self.assertEqual(caught.exception.token, "CACHE_ACKNOWLEDGEMENT_SOURCE_MISMATCH")

    def test_acknowledgement_for_a_different_mapping_is_refused(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        with self.assertRaises(ImportRejected) as caught:
            self.reviewed(path, mapping_id="some-other-mapping")
        self.assertEqual(caught.exception.token, "CACHE_ACKNOWLEDGEMENT_MAPPING_MISMATCH")

    def test_incomplete_acknowledgement_is_refused(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        record = self.acknowledgement(path)
        record.pop("statement")
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, REVIEWED_CACHED, cache_acknowledgement=record)
        self.assertEqual(caught.exception.token, "CACHE_ACKNOWLEDGEMENT_FIELDS")

    def test_acknowledgement_is_recorded_locally(self):
        path = self.build([row(toxicity_wbc_ge2=formula_cell("A1=1", "1"))])
        _, report = self.reviewed(path)
        self.assertEqual(report["cache_acknowledgement"]["operator"], "local-operator")
        self.assertEqual(report["cache_acknowledgement"]["source_sha256"], file_digest(path))


class HeaderTests(WorkbookCase):
    def test_extra_source_columns_are_ignored(self):
        headers = ["Nume pacient", *HEADERS.values(), "Observatii"]
        cells = [blank_cell(), text_cell("MBL"), text_cell("IMRT"), boolean_cell(True),
                 number_cell("9"), text_cell("GTR"), blank_cell()]
        path = self.build([dict(enumerate(cells))], headers=headers)
        records, report = import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(len(records), 1)
        self.assertEqual(set(records[0]), set(HEADERS))
        self.assertEqual(report["admitted_rows"], 1)

    def test_missing_required_header_is_refused(self):
        headers = [h for k, h in HEADERS.items() if k != "surgery_type"]
        path = self.build([], headers=headers)
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(caught.exception.token, "REQUIRED_HEADER_MISSING_OR_AMBIGUOUS")

    def test_duplicate_required_header_is_refused(self):
        headers = [*HEADERS.values(), "Diagnostic"]
        path = self.build([], headers=headers)
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(caught.exception.token, "REQUIRED_HEADER_MISSING_OR_AMBIGUOUS")

    def test_similar_header_is_not_accepted_as_a_near_match(self):
        headers = [h.replace("Diagnostic", "Diagnostic 2") for h in HEADERS.values()]
        path = self.build([], headers=headers)
        with self.assertRaises(ImportRejected):
            import_workbook(path, MAPPING, LITERAL_ONLY)

    def test_header_whitespace_is_trimmed_before_matching(self):
        headers = [f"  {h.strip()} " for h in HEADERS.values()]
        path = self.build([row()], headers=headers)
        records, _ = import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(len(records), 1)

    def test_wrong_sheet_is_refused(self):
        path = self.build([row()], sheet="Sheet2")
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(caught.exception.token, "SHEET_MISSING_OR_AMBIGUOUS")


class PackageGuardTests(WorkbookCase):
    def test_macro_workbook_is_refused(self):
        path = self.build([row()], macro=True)
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(caught.exception.token, "MACRO_WORKBOOK")

    def test_encrypted_package_part_is_refused(self):
        path = self.build([row()], encrypted_part=True)
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(caught.exception.token, "ENCRYPTED_WORKBOOK")

    def test_non_zip_file_is_refused_by_structure_not_extension(self):
        path = Path(self.temporary.name) / "fake.xlsx"
        path.write_bytes(b"\xd0\xcf\x11\xe0not really a workbook")
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(caught.exception.token, "ENCRYPTED_OR_INVALID_WORKBOOK")

    def test_external_link_parts_are_counted_and_not_refreshed(self):
        path = self.build([row()], external_link=True)
        _, report = import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(report["external_link_parts_not_refreshed"], 1)


class RowSemanticsTests(WorkbookCase):
    def test_blank_row_skipped_and_na_row_admitted(self):
        rows = [row(),
                {field: blank_cell() for field in HEADERS},
                {field: text_cell("NA") for field in HEADERS}]
        path = self.build(rows)
        records, report = import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(report["admitted_rows"], 2)
        self.assertEqual(report["skipped_blank_rows"], 1)
        self.assertEqual(records[1], {field: None for field in HEADERS})

    def test_string_no_is_imported_as_false(self):
        path = self.build([row(toxicity_wbc_ge2=text_cell("NO"))])
        records, _ = import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertIs(records[0]["toxicity_wbc_ge2"], False)

    def test_invalid_age_fails_the_import(self):
        path = self.build([row(age_at_rt=number_cell("11.5"))])
        with self.assertRaises(ImportRejected) as caught:
            import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(caught.exception.token, "LOCAL_VALIDATION_FAILED")
        self.assertEqual(
            caught.exception.detail["report"]["fields"]["age_at_rt"]["invalid_codes"],
            {"AGE_NOT_INTEGER": 1})

    def test_mixed_case_values_are_normalized(self):
        path = self.build([row(diagnosis=text_cell("  mbl"), rt_technique=text_cell("imrt"),
                               surgery_type=text_cell("gtr"))])
        records, _ = import_workbook(path, MAPPING, LITERAL_ONLY)
        self.assertEqual(records[0]["diagnosis"], "MBL")
        self.assertEqual(records[0]["rt_technique"], "IMRT")
        self.assertEqual(records[0]["surgery_type"], "GTR")


class MappingTests(unittest.TestCase):
    def test_delivered_mapping_loads(self):
        self.assertEqual(MAPPING.mapping_id, "iocn-csi-v2")
        self.assertEqual(len(MAPPING.digest), 64)

    def test_mapping_digest_changes_with_the_mapping(self):
        import json
        original = json.loads((ROOT / "config/iocn-mapping.json").read_text(encoding="utf-8"))
        changed = dict(original, mapping_id="iocn-csi-v3")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            self.assertNotEqual(load_mapping(path).digest, MAPPING.digest)

    def test_mapping_requiring_external_link_refresh_is_refused(self):
        import json
        original = json.loads((ROOT / "config/iocn-mapping.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.json"
            path.write_text(json.dumps(dict(original, external_link_refresh=True)),
                            encoding="utf-8")
            with self.assertRaises(ImportRejected) as caught:
                load_mapping(path)
        self.assertEqual(caught.exception.token, "EXTERNAL_LINK_REFRESH_FORBIDDEN")


class CanonicalCsvTests(unittest.TestCase):
    def test_delivered_synthetic_fixture_loads(self):
        records, report = read_canonical_csv(ROOT / "fixtures/synthetic_cohorts.csv")
        self.assertEqual(len(records), 24)
        self.assertEqual(report["admitted_rows"], 24)

    def test_header_must_match_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("diagnosis,rt_technique\nMBL,IMRT\n", encoding="utf-8")
            with self.assertRaises(ImportRejected) as caught:
                read_canonical_csv(path)
        self.assertEqual(caught.exception.token, "CANONICAL_HEADER_MISMATCH")

    def test_row_width_must_match_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("diagnosis,rt_technique,toxicity_wbc_ge2,age_at_rt,surgery_type\n"
                            "MBL,IMRT,true,9\n", encoding="utf-8")
            with self.assertRaises(ImportRejected) as caught:
                read_canonical_csv(path)
        self.assertEqual(caught.exception.token, "CANONICAL_ROW_WIDTH")


if __name__ == "__main__":
    unittest.main()
