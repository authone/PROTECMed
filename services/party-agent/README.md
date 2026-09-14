# Party agent — local data layer (milestone M1)

`protecmed_party` implements blueprint §3: the strict local import, the canonical
five-field projection, the fixed query catalogue and the frozen local snapshot. It is
the **only** place that touches provider data.

It contains no cryptography, no network client and no coordinator code. FHE work is the
M2 C++ worker; protocol envelopes and the approval gate are M3; the HTTP service and UI
are M4.

## Modules

| Module | Responsibility |
|---|---|
| `canonical.py` | Field allowlist, value normalization, record admission, local validation report |
| `catalogue.py` | Catalogue load/validation, typed predicates, exact counting, query hash |
| `importer.py` | XLSX (two formula modes) and strict canonical CSV import, mapping resolution, package guards |
| `snapshot.py` | Snapshot freezing, opaque token, local registry, supersede-on-reimport |
| `splitter.py` | Simulated demo split for the synthetic single-host demonstration only |
| `errors.py` | Symbolic, value-free failure tokens |

## What never leaves the provider

`Snapshot.public_descriptor()` is the whole outbound surface: the opaque
`snapshot_token` and the mapping digest. The source SHA-256, the admitted-row count,
the per-field validation report, the local query counts and the records themselves stay
in `local_metadata()` and the local registry. The snapshot token is random — deriving it
from the source digest would let a coordinator confirm guesses about the clinical file.

`SnapshotStore` refuses to create a registry inside a Git work tree. Point it at a
provider-controlled directory outside the repository and outside any Docker build
context; `.gitignore` is not an access control.

## Formula modes (§3.2)

`literal-only` is the default and rejects any formula in a selected clinical cell.
`reviewed-cached-values` accepts saved formula results only when the local operator
supplies an acknowledgement bound to **this** source digest and mapping id, and only when
every selected formula cell carries a non-error, nonempty saved result. A missing cache
is never read as null, false or zero — the import fails with `FORMULA_CACHE_MISSING`.
Cache freshness cannot be established from the workbook: `cache_freshness_verified` is
always `false` and the report carries an explicit warning.

Formulas are never evaluated, macros and encrypted workbooks are rejected, and
external-link parts are counted but never followed or refreshed.

## Relationship to `reference/python/cohort.py`

The reference helper is frozen under the 2026-09-05 verification ledger. This package is
an independent port, and `tests/unit/test_reference_equivalence.py` asserts the two agree
on normalization, blank detection, the synthetic fixture and every catalogue count and
split. A divergence is a release-blocking defect.

## Tests

```bash
python -m unittest discover -s tests -v
```

Synthetic data only. The IOCN plaintext regression is run separately, on an authorized
endpoint, with `reference/python/iocn_audit.py` and the private workbook.
