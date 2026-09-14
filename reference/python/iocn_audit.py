"""Offline, narrow XLSX/OOXML audit for the approved five-column IOCN projection.
NOT a production upload parser. No network/formula evaluation; no patient-row output.
Supports ordinary unencrypted XLSX, shared/inline strings and numeric cached values.
Rejects macros, duplicate ZIP entries, >64 MiB input or >128 MiB uncompressed package,
>16 MiB individual XML, ambiguous headers, errors and missing formula caches.
External-link parts may exist but are NOT followed or refreshed; their count is reported.
The source may contain identifiers in unrelated XML; they remain local and are not emitted.
Use only with authorization and outside the AI-agent/Git/build workspace.
"""
from __future__ import annotations
import argparse
import json
import posixpath
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from defusedxml import ElementTree as ET
from cohort import FIELDS, normalize, project_raw_rows, summarize

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
N = {"m": MAIN}
HEADERS = {
    "diagnosis": "Diagnostic", "rt_technique": "Tehnica RT2",
    "toxicity_wbc_ge2": "Toxicity >=2 WBC", "age_at_rt": "Varsta radioterapie ",
    "surgery_type": "Tip chirurgie",
}
SHEET = "Date - craniospinal irradiation"


def header_key(value) -> str:
    import unicodedata
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def audit_rows(path: Path, mode: str) -> tuple[list[dict], dict]:
    if mode not in {"literal-only", "reviewed-cached-values"}:
        raise ValueError("IMPORT_MODE")
    if path.stat().st_size > 64 * 1024**2:
        raise ValueError("XLSX_SIZE")
    with ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise ValueError("DUPLICATE_ZIP_ENTRY")
        if sum(i.file_size for i in infos) > 128 * 1024**2:
            raise ValueError("XLSX_EXPANDED_SIZE")
        if any("vbaproject" in n.lower() for n in names):
            raise ValueError("MACRO_WORKBOOK")
        def xml(name):
            if z.getinfo(name).file_size > 16 * 1024**2:
                raise ValueError("XML_SIZE")
            return ET.fromstring(z.read(name))
        strings = []
        if "xl/sharedStrings.xml" in names:
            for si in xml("xl/sharedStrings.xml").findall("m:si", N):
                strings.append("".join(t.text or "" for t in si.iter(f"{{{MAIN}}}t")))
        book = xml("xl/workbook.xml")
        matches = [s for s in book.findall("m:sheets/m:sheet", N) if s.attrib["name"] == SHEET]
        if len(matches) != 1:
            raise ValueError("SHEET_MISSING_OR_AMBIGUOUS")
        rid = matches[0].attrib[f"{{{REL}}}id"]
        relations = xml("xl/_rels/workbook.xml.rels")
        rels = [r for r in relations if r.attrib.get("Id") == rid]
        if len(rels) != 1 or rels[0].attrib.get("TargetMode") == "External":
            raise ValueError("SHEET_RELATION")
        target = rels[0].attrib["Target"]
        name = (target.lstrip("/") if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target)))
        if not name.startswith("xl/worksheets/") or ".." in name.split("/"):
            raise ValueError("SHEET_PATH")
        sheet = xml(name)
        row_elems = sheet.findall("m:sheetData/m:row", N)
        if len(row_elems) > 10002:
            raise ValueError("ROW_LIMIT")
        def cell_value(cell, selected=False):
            if cell is None:
                return None
            typ = cell.attrib.get("t")
            if typ == "e":
                raise ValueError("EXCEL_ERROR_CELL")
            formula = cell.find("m:f", N) is not None
            value_node = cell.find("m:v", N)
            if selected and formula:
                if mode == "literal-only":
                    raise ValueError("FORMULA_NOT_ALLOWED")
                if value_node is None or value_node.text in (None, ""):
                    raise ValueError("FORMULA_CACHE_MISSING")
            if typ == "inlineStr":
                return "".join(t.text or "" for t in cell.findall("m:is//m:t", N))
            if value_node is None or value_node.text is None:
                return None
            text = value_node.text
            if typ == "s":
                return strings[int(text)]
            if typ == "b":
                if text not in {"0", "1"}:
                    raise ValueError("EXCEL_BOOLEAN")
                return text == "1"
            if typ == "str":
                return text
            if typ in (None, "n"):
                try:
                    return int(text)
                except ValueError:
                    return float(text)
            raise ValueError("CELL_TYPE_UNSUPPORTED")
        header_row = [r for r in row_elems if r.attrib.get("r") == "1"]
        if len(header_row) != 1:
            raise ValueError("HEADER_ROW")
        by_header = {}
        for c in header_row[0].findall("m:c", N):
            k = header_key(cell_value(c))
            col = "".join(ch for ch in c.attrib["r"] if ch.isalpha())
            by_header.setdefault(k, []).append(col)
        column_map = {}
        for field, header in HEADERS.items():
            cols = by_header.get(header_key(header), [])
            if len(cols) != 1:
                raise ValueError("REQUIRED_HEADER_MISSING_OR_AMBIGUOUS")
            column_map[field] = cols[0]
        formula_counts = {field: 0 for field in FIELDS}
        raw_rows = []
        for r in row_elems:
            if r.attrib.get("r") == "1":
                continue
            cells = {"".join(ch for ch in c.attrib["r"] if ch.isalpha()): c
                     for c in r.findall("m:c", N)}
            raw = {}
            for field, col in column_map.items():
                c = cells.get(col)
                if c is not None and c.find("m:f", N) is not None:
                    formula_counts[field] += 1
                raw[field] = cell_value(c, selected=True)
            raw_rows.append(raw)
        records, skipped = project_raw_rows(raw_rows)
        return records, {
            "sheet": SHEET, "admitted_rows": len(records), "skipped_blank_rows": skipped,
            "selected_formula_cells": formula_counts, "import_mode": mode,
            "external_link_parts_not_refreshed": sum(n.startswith("xl/externalLinks/") and
                                                       n.endswith(".xml") for n in names),
            "cache_freshness_verified": False,
        }


def main() -> None:
    p = argparse.ArgumentParser(description="Authorized local audit; outputs aggregates only; NOT FHE.")
    p.add_argument("workbook", type=Path)
    p.add_argument("--catalogue", type=Path, required=True)
    p.add_argument("--mode", choices=["literal-only", "reviewed-cached-values"], default="literal-only")
    p.add_argument("--acknowledge-local-authorization", action="store_true")
    p.add_argument("--acknowledge-reviewed-cache", action="store_true")
    args = p.parse_args()
    if not args.acknowledge_local_authorization:
        p.error("Local authorization acknowledgement is required")
    if args.mode == "reviewed-cached-values" and not args.acknowledge_reviewed_cache:
        p.error("Reviewed-cache acknowledgement is required")
    try:
        rows, metadata = audit_rows(args.workbook, args.mode)
        catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))["queries"]
        print(json.dumps({"metadata": metadata, "counts": summarize(rows, catalogue)}, indent=2))
    except (ValueError, KeyError, BadZipFile, OSError, IndexError) as error:
        # Only symbolic errors produced by this module; no raw cell/path exception strings.
        token = str(error)
        if not token.isascii() or not all(c.isupper() or c.isdigit() or c == "_" for c in token):
            token = "IMPORT_FAILED"
        p.exit(1, token + "\n")


if __name__ == "__main__":
    main()
