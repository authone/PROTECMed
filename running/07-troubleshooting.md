# 7. Troubleshooting

Every failure surfaces as an uppercase symbolic token, never a stack trace or a raw
exception. In the provider UI it appears in the notice bar; in the API it is the `detail`
field.

## 7.1 Install and build

| Symptom | Cause and fix |
|---|---|
| `Expected OpenFHE 1.5.1; inspect the pinned install/config` | `CMAKE_PREFIX_PATH` points at a different OpenFHE. Rebuild [§1.2](01-install.md#12-build-openfhe-v151). |
| `This baseline requires OpenFHE native size 64` | OpenFHE was configured without `-DNATIVE_SIZE=64`. |
| `error while loading shared libraries: libOPENFHEpke.so` | Running the worker by hand without `LD_LIBRARY_PATH="$PWD/.local/openfhe/lib"`. The services set this themselves. |
| Build killed, out of memory | Use `--parallel 2`, not an unbounded `--parallel`. |
| Test run reports ~255 tests instead of 311 | `reference/python/requirements-reference.txt` was not installed (`defusedxml`). |
| Integration and e2e tests skip | The worker binary is missing. The skip message names the expected path. |

## 7.2 Import

| Token | Meaning |
|---|---|
| `UNKNOWN_SELECTION_TOKEN` | The file is not in the configured import directory, or the agent restarted since the page was rendered. Reload screen 1. |
| `FORMULA_NOT_ALLOWED` | A selected clinical cell contains a formula while in `literal-only` mode. Use a values-only export, or switch mode with the acknowledgement. |
| `FORMULA_CACHE_MISSING` | A selected formula cell has no saved result. **Fail closed by design** — a missing cache is never read as null, false or zero. |
| `EXCEL_ERROR_CELL` | A selected cell holds an Excel error such as `#REF!`. |
| `CACHE_ACKNOWLEDGEMENT_SOURCE_MISMATCH` | The file changed since the acknowledgement. A changed file needs a new review. |
| `REQUIRED_HEADER_MISSING_OR_AMBIGUOUS` | A required header is absent or appears twice. The importer never guesses a similarly named column. |
| `MACRO_WORKBOOK`, `ENCRYPTED_WORKBOOK`, `ENCRYPTED_OR_INVALID_WORKBOOK` | Macros, encrypted packages and non-ZIP containers are refused by structure, not by file extension. |
| `LOCAL_VALIDATION_FAILED` | One or more values are unusable — an unknown category, a fractional age, an out-of-range value. The local report names the field and row index, never the value. |
| `SNAPSHOT_STORE_INSIDE_REPOSITORY` | The registry directory is inside a Git work tree. Move it outside. |

## 7.3 Protocol and approval

| Token | Meaning |
|---|---|
| `WRONG_STATE` | Acted out of order — most often submitting a ciphertext before every epoch confirmation is in. |
| `KEY_ROUND_OUT_OF_ORDER`, `KEY_ROUND_WRONG_PARTY` | Key generation is sequential in roster order. |
| `BAD_SIGNATURE`, `UNKNOWN_SIGNER` | The signature does not verify against the pinned roster key, or the signer is not enrolled. Re-check the fingerprint comparison. |
| `IDENTITY_FINGERPRINT_MISMATCH` | A roster identity is not the key this endpoint pinned. This is a new enrolment and a new run, never a silent accept. |
| `PLAN_SNAPSHOT_TOKEN`, `PLAN_QUERY_HASH`, `PLAN_MAPPING_HASH` | The plan does not match local records. The coordinator froze something other than what you hold. |
| `QUERY_NOT_IN_LOCAL_CATALOGUE` | The plan names a query this provider does not have. |
| `REQUEST_EXPIRED` | The request's expiry has passed. Issue a new request, or a new epoch if the old one is finished. |
| `AGGREGATE_HASH`, exit 17 from `verify-aggregate` | The candidate aggregate is not the sum of the exact input set — a substituted input, a subset sum or a re-randomized result. **Do not approve.** |
| `PARTIAL_ALREADY_EMITTED` | This provider already emitted a partial for this epoch. The stored bytes are resent; a second one is never generated. |
| `OUTBOX_UNCERTAIN_EMISSION` | A crash left a reservation with no commit, so it is unknown whether different bytes already left. Abandon the epoch and start a fresh run. |
| `DISCLOSURE_ALREADY_RELEASED` | The local ledger already answered this query, snapshot and recipient combination. |
| `PARTIAL_SET_INCOMPLETE` | Fusion attempted without every approval. Expected until the last provider approves. |
| `REJECTION_PRESENT` | A provider rejected. The run cannot release. |
| `CONFLICTING_SUBMISSION`, `CONFLICTING_PARTIAL` | An authenticated party sent two different artifacts. The run goes to `INTEGRITY_HOLD` and needs operator review. |

## 7.4 API

| Status | Token | Fix |
|---|---|---|
| 401 | `UNAUTHENTICATED` | Missing or wrong bearer token. |
| 403 | `FORBIDDEN` | Wrong role for the route. |
| 403 | `SIGNER_IS_NOT_CALLER` | The envelope's signer is not the authenticated caller. |
| 403 | `NOT_A_RUN_MEMBER`, `NOT_A_RECIPIENT` | Not a member of this run, or a party asking for the result. |
| 400 | `IDEMPOTENCY_KEY_REQUIRED` | Every POST needs one, 8–128 characters of `A-Za-z0-9-_`. |
| 409 | `IDEMPOTENCY_KEY_REUSED` | The same key with a different body. Use a new key. |
| 404 | `ARTIFACT_NOT_FOUND` | Unknown digest, or the artifact belongs to another run. |
| 413 | `JSON_TOO_LARGE`, `ARTIFACT_SIZE` | Over the 64 KiB / 16 MiB limits. |

## 7.5 Local UI

| Symptom | Cause |
|---|---|
| Redirected to the login page | No session, or it expired after 60 minutes. Sessions are in memory and are cleared when the agent restarts. |
| `CSRF_TOKEN_INVALID` | The form was stale or submitted from outside the page. Reload and retry. |
| `HOST_NOT_ALLOWED` | Reached the agent under a hostname it was not started with. Use the exact URL printed by the launcher. |
| `ORIGIN_NOT_ALLOWED` | A cross-origin form post. Rejected by design. |
| `OFFLINE` in the notice bar | The coordinator is unreachable. The local state is unchanged; retry when it is back. |
| 405 on a link you expected to work | State-changing actions are POST-only. There are no state-changing GET routes. |

## 7.6 Worker exit codes

Relevant when running `build/worker/protecmed-worker` by hand.

| Code | Meaning |
|---|---|
| 0 | Success |
| 10 | Invalid command or schema |
| 11 | Profile mismatch |
| 12 | Serialization failure |
| 13 | Context, key or shape mismatch |
| 14 | Cryptographic failure |
| 15 | Missing, duplicate or incorrect role |
| 16 | Input or output out of range |
| 17 | Aggregate mismatch |
| 20 | Filesystem failure |
| 21 | Timeout or resource limit |

## 7.7 Recovery

- **Coordinator restart** — resumes from durable state in `coordinator.db` and the
  artifact store.
- **Provider restart** — destroys the ephemeral FHE share. An unfinished epoch **cannot**
  be resumed; start a fresh run. The disclosure ledger, the snapshot registry and the
  outbox survive, and creating a new epoch does not reset the ledger.
- **Lost upload** — the stored bytes are resent from the outbox. The cryptographic
  operation is never repeated.
- **Uncertain emission after a crash** — abandon the epoch. Generating a second partial is
  worse than losing a run.

## 7.8 When to stop rather than work around

Stop and get a human decision if you hit an unsupported API, a parameter failure, a
missing dependency, or any situation where the obvious fix is to weaken a check. Lowering
a threshold, skipping a verification, disabling a guard or editing
`config/crypto-profile.json` to make something pass defeats the only property this system
exists to provide.
