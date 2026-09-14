# Implementation task — M1 reference data semantics

Ticket / milestone: **M1 — reference data semantics** (blueprint §7.1)
Owner / human reviewer: programmer implemented; **IOCN confirmation of mapping,
formula-value provenance and record/patient semantics still required** (§7.4)
Specification sections: §3.1–§3.6, §5.1, §7.1
Allowed files: `services/party-agent/`, `tests/unit/`, `evidence/m1/`,
`verification/milestones.json`. `config/`, `contracts/`, `fixtures/` and
`reference/python/` were **not** modified.

## What was implemented
`services/party-agent/protecmed_party/` — the local data layer:

| Module | Responsibility |
|---|---|
| `canonical.py` | Five-field allowlist, normalization, record admission, local validation report |
| `catalogue.py` | Catalogue load/validation, typed predicates, exact counting, query hash |
| `importer.py` | XLSX (both formula modes) and strict canonical CSV, mapping resolution, package guards |
| `snapshot.py` | Snapshot freezing, opaque token, owner-only local registry, supersede-on-reimport |
| `splitter.py` | Simulated demo split with local disjointness/coverage proof |
| `errors.py` | Symbolic, value-free failure tokens |

## Input and output contracts
Input: `config/iocn-mapping.json`, `config/query-catalog.json`, one local XLSX or strict
canonical CSV, and — in reviewed-cache mode — an operator acknowledgement bound to the
source digest and mapping id.
Output: canonical records (local), a local validation/import report, and a frozen
`Snapshot` whose `public_descriptor()` is the entire outbound surface:
`{snapshot_token, mapping_digest}`.

## Security and data-handling invariants
- Positive allowlist: only the five mapped columns of the one approved sheet are read.
  No patient frame is built and then trimmed; no identifier, date, note or free-text
  column is copied anywhere.
- `bool(cell)` is never applied to a string. `"NO"` imports as `False`; `False` is kept
  distinct from missing; numeric values other than 0/1 are rejected.
- Age accepts integers, integer-valued numerics and decimal integer strings in 0–120.
  `11.5` is rejected, never truncated.
- A missing formula cache is never read as null, false or zero — `FORMULA_CACHE_MISSING`.
- `cache_freshness_verified` is always `false`, with an explicit warning in the report.
- Formulas are never evaluated; macros, encrypted packages and non-ZIP containers are
  rejected structurally, not by file extension; external-link parts are counted and never
  followed or refreshed.
- Errors carry only uppercase symbolic tokens and aggregate positions. A regression test
  asserts a rejected cell value never appears in the error or the report.
- The snapshot token is `secrets.token_hex(16)`, not derived from the source digest.
- `SnapshotStore` refuses to create a registry inside a Git work tree, writes with
  `O_EXCL | O_NOFOLLOW`, mode 0600 in a 0700 directory, and never rewrites a frozen
  snapshot in place.
- A re-import mints a new token and marks earlier snapshots superseded; the superseded
  snapshot's frozen records are unchanged, so an already-submitted contribution cannot be
  altered by editing the source file.

## Positive tests — run and passed
Blueprint §3.6 requires specific import cases. All are implemented and passing:

| §3.6 required case | Test |
|---|---|
| Formula with a valid saved result | `test_formula_with_valid_saved_result_accepted_when_reviewed` |
| Formula with no cache | `test_formula_without_cache_fails_closed` |
| Excel error result | `test_excel_error_result_is_rejected` |
| Changed formula-cache acknowledgement | `test_changed_workbook_invalidates_the_previous_acknowledgement` |
| Extra source columns | `test_extra_source_columns_are_ignored` |
| Missing / duplicate required headers | `test_missing_required_header_is_refused`, `test_duplicate_required_header_is_refused` |
| Lower / upper case | `test_mixed_case_values_are_normalized` |
| Blanks | `test_blank_row_skipped_and_na_row_admitted` |
| `NA` | `test_all_explicit_missing_tokens_row_is_admitted` |
| String `NO` | `test_string_no_is_false_not_truthy`, `test_string_no_is_imported_as_false` |
| Boolean `false` | `test_boolean_false_survives_as_false_not_missing`, `test_saved_false_result_is_false_not_missing` |
| Invalid age 11.5 | `test_age_fraction_is_rejected_not_truncated`, `test_invalid_age_fails_the_import` |
| Wholly blank selected row | `test_wholly_blank_row_is_skipped_and_counted` |
| All explicit missing tokens in a row | `test_all_explicit_missing_tokens_row_is_admitted` |

Catalogue counting reproduces every value in `fixtures/synthetic_expected.json` — six
queries, totals plus 2-way and 3-way splits.

## Negative tests — run and passed
Formula in literal-only mode; unknown import mode; missing, mismatched-source,
mismatched-mapping and incomplete acknowledgements; near-match header; wrong sheet; macro
workbook; encrypted package part; non-ZIP file; malformed snapshot token; snapshot store
inside a Git tree; rewriting a frozen snapshot; unknown query id; extra query key; more
than five filters; empty filters outside Q001; integer `1` offered as a boolean predicate
value and as a row value; boolean offered as an age; `LIKE`/SQL-injection/`__import__`
payloads in an enum value; duplicate predicate field; a structurally valid but unlisted
query; non-canonical row values; split with a party count other than 2 or 3.

## Exact commands
```bash
python -m unittest discover -s tests -v
```

## Tests actually run
**148 passed, 0 failed, 0 skipped** — 57 pre-existing reference tests plus 91 new M1
tests. Full output: `evidence/m1/unittest-full.txt`. The suite was run five consecutive
times to confirm it is not order- or randomness-dependent (one draft assertion was
substring-matching a random hex token and was corrected).

## Tests NOT run and why
- **The IOCN plaintext regression was not run.** No clinical workbook exists in this
  workspace and none may be placed here (AGENTS.md). The expected values in
  `config/iocn_expected_counts.json` were neither reproduced nor contradicted by this
  work. That check belongs on an authorized endpoint, using
  `reference/python/iocn_audit.py` and the private file.
- No OpenFHE, service, HTTP, browser, container or cross-platform behaviour is exercised
  by this milestone; M1 is plaintext data semantics only.
- No real Excel application was used. The XLSX fixtures are synthetic OOXML assembled in
  `tests/unit/synthetic_workbook.py`, because openpyxl cannot write a formula together
  with a saved result. Behaviour against files produced by a real Excel version is
  therefore asserted only through the OOXML structures those versions emit.

## Deviations and decisions
1. **The production module is a port, not an import, of `reference/python/cohort.py`.**
   The reference kit is frozen under the 2026-09-05 ledger and §5.1 marks `reference/` as
   examples rather than product code. To stop the two drifting,
   `tests/unit/test_reference_equivalence.py` asserts they agree on a 37-value probe grid
   for all five fields, on blank detection, on the synthetic fixture and on every
   catalogue count and split.
2. **`openpyxl==3.1.5` is a new pinned dependency** (`services/party-agent/requirements.txt`),
   as §3.2 permits. The delivered reference audit utility keeps using `defusedxml` and is
   unchanged.
3. `tests/unit/` needs `__init__.py` for `unittest discover` to recurse; it also installs
   the service path. `tests/test_reference.py` is untouched and still passes.
4. No new contract schema was needed: M1 adds no protocol message. `contracts/` is
   unchanged.

## Evidence paths
- `evidence/m1/unittest-full.txt` — full verbose run, 148 tests
- `evidence/m1/M1_REPORT.md` — this report
- `services/party-agent/README.md` — module scope and outbound-surface documentation

## Status
**PASSED (programmer evidence complete).** Two approvals remain outstanding before this
gate can be called closed for the clinical path: IOCN confirmation of the mapping and
record semantics (§7.4), and an authorized local run of the IOCN plaintext regression.

## Stop conditions / unresolved questions
- Whether one row equals one patient is an IOCN decision. Until it is confirmed, Q001
  must be labelled "matching records", never "unique patients" (§3.3).
- Whether the supplied workbook can be re-exported values-only by IOCN. If it can,
  `literal-only` suffices and `reviewed-cached-values` need not be used for the pilot.
