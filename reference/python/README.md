# Python reference helpers

These are small executable references, not the PROTECMed services or an FHE implementation. Run from the package root:

```bash
python -m pip install -r reference/python/requirements-reference.txt
python -m unittest discover -s tests -v
python reference/python/cohort.py fixtures/synthetic_cohorts.csv --catalogue config/query-catalog.json
```

Dependency versions above are those used for this reference test run, not a claim that they are the latest releases. Production dependencies require a reviewed lock file and vulnerability scan. The network-dependent installation command has not been tested offline.

`protocol.gate_partials` verifies a narrow partial-set/signature/byte binding. Its input request must already be locally verified. It does **not** implement the complete Section 4 gate, OpenFHE structure checking, aggregate recomputation, local consent, database state, authentication or expiry/revocation guarantees against dishonest recipients.

`cohort.py` emits aggregate reference counts, never encrypted results. `iocn_audit.py` is an authorized offline inspection utility: read its header and the clinical data rules before running it. Its CLI defaults to rejecting formulas. The supplied workbook contains formula cells and an external-link part; the utility uses reviewed saved values and never refreshes external links. It cannot prove cache freshness.

A canonical CSV contains already-admitted records. Preserve an all-null row rather than reapplying the raw-XLSX blank-row filter.
