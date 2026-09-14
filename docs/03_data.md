# 3. IOCN adapter, queries and test data

## 3.1 Source inspection and limits of the inspection

The attached workbook `Date - craniospinal irradiation - salvarea ultima 4 decembrie.xlsx` was re-inspected for this revision [P3]. Its main sheet is `Date - craniospinal irradiation`, range A1:MG52: one header row, 51 data rows and 345 columns. `Sheet2` is empty. The five required headers are unique after trimming. These are observations about this file, not assumptions to impose on every future export.

| Canonical field | Exact source header | Column in this sample | Canonical type |
|---|---|---|---|
| `diagnosis` | `Diagnostic` | I | enum or null |
| `rt_technique` | `Tehnica RT2` | Q | enum or null |
| `toxicity_wbc_ge2` | `Toxicity >=2 WBC` | LY | boolean or null |
| `age_at_rt` | `Varsta radioterapie ` (trailing space) | H | integer 0–120 or null |
| `surgery_type` | `Tip chirurgie` | M | enum or null |

Locate columns by normalized header, not hardcoded Excel letters. Letters above are for inspection and regression only. Match Unicode-normalized, trimmed headers; reject ambiguous required matches. Never infer the closest similarly named column. A mapping version change changes its hash and requires a new run.

No patient identifiers or patient-level rows are included in this package. Aggregate regression values are still restricted research information: do not automatically publish the clinical appendix, logs or reports to a public repository.

## 3.2 Important correction: WBC flags are formula cells

All **51 cells in the selected WBC toxicity column contain formulas** in the supplied workbook. The other four selected columns contain no formulas in this sample. The observed Yes/No values are saved formula results, not necessarily literal cell values. A library such as openpyxl can return those saved results with `data_only=True`; that option does not recalculate formulas or prove freshness [S12].

The production adapter must have two explicit modes:

- `literal-only`: default for new imports. Reject formulas in selected clinical cells. A values-only export prepared and verified locally by IOCN is acceptable.
- `reviewed-cached-values`: permit formula cells only after the local operator confirms that IOCN has recalculated/reviewed and saved the workbook. Require a non-error, nonempty cached result for every selected formula cell. Record the acknowledgement, local source hash and formula count locally. Show a warning that cache freshness cannot be established from the workbook alone.

For the supplied workbook, the second mode is needed to reproduce the recorded Q004 baseline unless IOCN provides a values-only copy. Do not treat a missing cache as null, false, zero or a reason to quietly exclude the row. Fail the import with `FORMULA_CACHE_MISSING`. The supplied workbook also has one external-link part. Its presence is not a request to refresh it: use only the reviewed cached cells and never follow external targets. Do not evaluate Excel formulas using `eval`, enable macros, refresh external links, or expand the clinical allowlist to recalculate toxicity from laboratory measurements. That would change the approved data processing.

Open the workbook read-only. A normal implementation may use two openpyxl views (`data_only=False` for formula detection and `data_only=True` for saved values), selecting only required columns for the canonical table. The parser may internally load shared strings or XML for the local file; the truthful boundary is that disallowed values are never materialized into the canonical table, emitted, logged or uploaded. Do not promise that the XLSX parser never touches their bytes.

The included `reference/python/iocn_audit.py` is a narrow offline OOXML inspection/reference utility for this sample-shaped XLSX. It is not the production web-upload parser. It calculates only aggregate counts and formula statistics and emits no patient rows. Its restricted format and size checks are documented in its module header.

## 3.3 Normalization and row semantics

Use a positive allowlist. Never create a full patient DataFrame and then delete a few identifier columns. Do not copy names, NIDs, dates, notes or free text into canonical rows or fixtures. Restrict XLSX to the approved sheet and reject encrypted workbooks, macros and external-link workflows. Validate actual file structure and resource limits, not only the filename extension.

Normalize clinical strings by trimming and uppercasing. Missing tokens are empty cells, empty strings, `NA`, `N/A` and `NULL`, case-insensitive. For diagnosis, allow `MBL`, `PNET`, `GLIOMA`, `HAEMA`, `ICGCT`, `PINEAL TUMOR`, `EPD`; for radiotherapy, `3DCRT`, `IMRT`; for surgery, `GTR`, `STR`, `INOP`, `BIOPSIE`. Unknown nonmissing tokens cause a local validation error, not a guessed category.

Boolean normalization accepts actual booleans, numeric 0/1, or exact strings `YES/DA/TRUE/1` and `NO/NU/FALSE/0`. Never use `bool(cell)` on a string: `bool("NO")` is true in Python. Reject numeric values other than 0/1 and distinguish missing from false. Age accepts integer-valued numeric cells or decimal integer strings within 0–120; reject fractions and do not truncate. In query JSON, require an actual integer for age and an actual boolean for toxicity; Python's `bool` subtype must not accidentally pass an integer validator.

Freeze the validated canonical snapshot locally before accepting a run plan. Keep its local source/version digest and mapping version in the party registry. Re-importing a changed source creates a new snapshot token and invalidates unfinished runs that depended on the old selection; it must not silently alter an already-submitted count. Only opaque tokens leave the provider.

A record is *admitted* when at least one of the five raw selected fields is nonblank. A record containing `NA` is still a record; its missing fields affect only queries that use those fields. Skip rows whose five selected raw cells are all blank, and show their number locally. Retain admitted-row order. Assign an internal zero-based admitted-row index only in memory/local metadata; it is not an identity or a deduplication mechanism.

Q001 counts admitted records. Calling these unique patients requires IOCN's explicit confirmation that one row corresponds to one patient and there are no duplicate patients locally or across institutions. This prototype does not implement private record linkage or cross-site deduplication. Without that confirmation, label the result “matching records”, not “unique patients”.

For each query, a row missing any field required by that query is excluded; fields not used by the query do not affect eligibility. A local validation report shows admitted rows, skipped blank rows, missing/invalid values per field, and eligible/excluded rows per query. These diagnostics and local counts are not sent to the coordinator.

## 3.4 Fixed query catalogue

The catalogue is immutable within a release. Its canonical JSON is in `config/query-catalog.json`. The engine supports a bounded AND-list of typed predicates, but the MVP UI offers only these six catalogue entries. Matching a JSON schema alone is insufficient: the query must exactly match its allowlisted catalogue entry and hash.

| ID | Query | IOCN total | IOCN 2-provider split | IOCN 3-provider split |
|---|---|---:|---|---|
| Q001 | All admitted records | 51 | 26 + 25 | 17 + 17 + 17 |
| Q002 | Diagnosis = MBL | 29 | 14 + 15 | 8 + 11 + 10 |
| Q003 | MBL AND IMRT | 13 | 6 + 7 | 3 + 4 + 6 |
| Q004 | MBL AND IMRT AND WBC toxicity >=2 = true | 11 | 5 + 6 | 3 + 2 + 6 |
| Q005 | Age at radiotherapy <12 AND MBL | 21 | 8 + 13 | 5 + 7 + 9 |
| Q006 | Surgery = GTR AND IMRT | 9 | 4 + 5 | 3 + 3 + 3 |

These values were recalculated in this revision and agree with v1. They are plaintext import/query regression values, **not OpenFHE benchmark results**. They depend on this workbook and its saved formula results. A changed export, row order or clinical correction may change the expected totals or shard values; do not adjust code to force the number 11.

The primary restricted acceptance query is Q004. Its literal clinical meaning is the stored toxicity flag, not a new medical interpretation of raw WBC measurements.

```json
{
  "schema_version": "2.0",
  "query_id": "Q004",
  "query_version": 1,
  "logic": "AND",
  "filters": [
    {"field": "diagnosis", "operator": "eq", "value": "MBL"},
    {"field": "rt_technique", "operator": "eq", "value": "IMRT"},
    {"field": "toxicity_wbc_ge2", "operator": "eq", "value": true}
  ],
  "missing_value_policy": "exclude_required_missing"
}
```

Use explicit typed comparisons; no SQL text, Python expressions, regex predicates, `eval`, `exec` or `pandas.query`. Empty filters are allowed only for Q001. Unknown IDs, fields, operators, values, extra keys, excessive nesting or more than five filters fail before any patient data is evaluated.

## 3.5 Demo splitting and independent synthetic fixtures

The local splitter first creates the validated canonical projection, then assigns admitted row index j to provider `j % n`. It outputs only the five canonical fields, in fixed order. There is no need to include an ID column in transmitted shards. Retain the original order within each shard. Prove disjointness and coverage by local index checks before writing files; do not report those indices centrally.

Split only on an authorized local machine, never at the coordinator. In a real deployment, institutions already possess their own distinct datasets; the artificial split must be labelled a simulation. Do not give the full workbook to each party and rely on a runtime modulo filter to simulate separate ownership.

The package includes a **fully synthetic** 24-row CSV generated independently of patient rows, with its own expected counts in `fixtures/synthetic_expected.json`. It intentionally has different totals from the IOCN file. CI uses this fixture only. Local IOCN acceptance uses `config/iocn_expected_counts.json` and the original private workbook. Never copy clinical rows into tests or an AI prompt to fix a failed test.

## 3.6 Formula-cache and import acceptance tests

Required tests include a formula with a valid saved result, a formula with no cache, an Excel error result, a changed formula-cache acknowledgement, extra source columns, missing/duplicate required headers, lower/upper case, blanks, `NA`, string `NO`, boolean `false`, invalid age 11.5, a wholly blank selected row and a row whose selected values are all explicit missing tokens. The implementation must fail closed where specified and preserve the stated record semantics.

The local source file and canonical snapshot are frozen for a run. An operator changing the file after encryption does not change the frozen contribution. Any intended data correction, query change or mapping change starts a fresh run. The source file SHA-256 stays local; the coordinator receives an opaque snapshot token, not a content hash of clinical data.
