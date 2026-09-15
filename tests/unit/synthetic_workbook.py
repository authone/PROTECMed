"""Synthetic OOXML builder for the M1 import tests. Invented data only.

Real Excel writes saved formula results as <f> plus <v>. openpyxl cannot produce that
pair, so the fixtures are assembled as XML here. Nothing in this file is derived from a
clinical workbook.
"""
from __future__ import annotations
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
SHEET = "Date - craniospinal irradiation"
HEADERS = {
    "diagnosis": "Diagnostic", "rt_technique": "Tehnica RT2",
    "toxicity_wbc_ge2": "Toxicity >=2 WBC", "age_at_rt": "Varsta radioterapie ",
    "surgery_type": "Tip chirurgie",
}


def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def text_cell(value: str) -> dict:
    return {"type": "inlineStr", "value": value}


def number_cell(value: str) -> dict:
    return {"type": None, "value": value}


def boolean_cell(value: bool) -> dict:
    return {"type": "b", "value": "1" if value else "0"}


def formula_cell(formula: str, cache: str | None, cell_type: str | None = "b") -> dict:
    return {"type": cell_type, "formula": formula, "value": cache}


def blank_cell() -> dict:
    return {}


def _render(reference: str, cell: dict) -> str:
    if not cell:
        return ""
    attributes = f' t="{cell["type"]}"' if cell.get("type") else ""
    body = ""
    if cell.get("formula") is not None:
        body += f"<f>{escape(cell['formula'])}</f>"
    value = cell.get("value")
    if cell.get("type") == "inlineStr":
        body += f"<is><t xml:space=\"preserve\">{escape(str(value))}</t></is>"
    elif value is not None:
        body += f"<v>{escape(str(value))}</v>"
    return f'<c r="{reference}"{attributes}>{body}</c>'


def build_workbook(path: Path, rows: list[dict[str, dict]], *,
                   headers: list[str] | None = None, sheet: str = SHEET,
                   macro: bool = False, encrypted_part: bool = False,
                   external_link: bool = False, extra_sheet: str | None = None) -> Path:
    """Write a minimal but openpyxl-readable workbook. `headers` overrides the header row."""
    header_names = headers if headers is not None else list(HEADERS.values())
    order = list(HEADERS) if headers is None else None
    header_xml = "".join(
        _render(f"{column_letter(i)}1", text_cell(name))
        for i, name in enumerate(header_names))
    body = ""
    for position, row in enumerate(rows, start=2):
        keys = order if order is not None else list(row)
        cells = "".join(
            _render(f"{column_letter(i)}{position}", row.get(key, blank_cell()))
            for i, key in enumerate(keys))
        body += f'<row r="{position}">{cells}</row>'
    sheets = f'<sheet name="{escape(sheet)}" sheetId="1" r:id="rId1"/>'
    if extra_sheet:
        sheets += f'<sheet name="{escape(extra_sheet)}" sheetId="2" r:id="rId2"/>'
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml",
            f'<Types xmlns="{CONTENT}">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            + ('<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
               if extra_sheet else "") + '</Types>')
        archive.writestr("_rels/.rels",
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{RELS}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{RELS}"><sheets>{sheets}</sheets></workbook>')
        relationships = (f'<Relationship Id="rId1" Type="{RELS}/worksheet" '
                         'Target="worksheets/sheet1.xml"/>')
        if extra_sheet:
            relationships += (f'<Relationship Id="rId2" Type="{RELS}/worksheet" '
                              'Target="worksheets/sheet2.xml"/>')
        if external_link:
            relationships += (f'<Relationship Id="rId9" Type="{RELS}/externalLink" '
                              'Target="externalLinks/externalLink1.xml"/>')
        archive.writestr("xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PKG}">{relationships}</Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{MAIN}"><sheetData><row r="1">{header_xml}</row>'
            f'{body}</sheetData></worksheet>')
        if extra_sheet:
            archive.writestr("xl/worksheets/sheet2.xml",
                f'<worksheet xmlns="{MAIN}"><sheetData/></worksheet>')
        if external_link:
            archive.writestr("xl/externalLinks/externalLink1.xml",
                f'<externalLink xmlns="{MAIN}"><externalBook/></externalLink>')
        if macro:
            archive.writestr("xl/vbaProject.bin", b"not-a-real-macro")
        if encrypted_part:
            archive.writestr("EncryptedPackage", b"not-a-real-encrypted-package")
    return path
