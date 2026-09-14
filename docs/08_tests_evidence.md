# 8. Test plan, measurements and TRL evidence

## 8.1 Separate verification layers

The delivered Python helpers test data semantics, canonicalization and a narrow signed-partial gate. They do not implement the production service, OpenFHE serialization, malicious-secure distributed key generation or a complete consent system. `verification/verification.json` records what was actually executed for this revision. Tests below are requirements for the future prototype unless explicitly marked as executed there.

| ID | Scenario | Required outcome |
|---|---|---|
| D01 | Synthetic CSV and Q001–Q006 | Exact expected totals and 2/3-way shards |
| D02 | Supplied IOCN export, locally authorized | Totals 51, 29, 13, 11, 21, 9; matching shard table |
| D03 | WBC formula with valid saved result | Literal-only rejects; reviewed-cache mode accepts |
| D04 | Missing/error formula cache | Whole import fails; no false/zero substitution |
| D05 | Missing or duplicate required header | Fail before any canonical dataset is admitted |
| D06 | `NO`, false, 0, blanks and NA | False and missing remain different |
| D07 | Age 11.5, bool-as-age, unknown diagnosis | Reject, not truncate or guess |
| D08 | Blank selected row; explicit-NA row | Blank skipped; NA row retained for Q001 |
| D09 | Extra identifier/free-text columns | Not present in projection, logs, fixtures or uploads |
| D10 | 10,001 admitted rows | Reject before encryption |
| C01 | 2/2 counts 5 and 6 | Exact 11 under final joint key |
| C02 | 3/3 counts 3, 2 and 6 | Exact 11 under final joint key |
| C03 | Zero and boundary counts | 0, 20,000 or 30,000 as applicable; no wrap |
| C04 | Parameter inspection | Correct n, mode, modulus and secure automatic ring |
| C05 | All operations in separate processes | Same exact result after binary serialization |
| C06 | Intermediate key, wrong context or epoch | Reject before evaluation/partial decryption |
| C07 | Replaced aggregate or omitted/doubled input | Local recomputation rejects before approval |
| C08 | Nonzero unexpected output slots | Flag regression; no silent data leakage |
| C09 | Missing, duplicate or wrong-role partial | Application denies; fusion call count stays zero |
| C10 | Malformed or oversized binary object | Bounded failure in isolated worker; no key/log leak |
| C11 | amd64 ↔ arm64 exchange | Key/ciphertext/partial round trips; exact result |
| P01 | Tampered envelope/hash/signature | Deny before deserialization or use |
| P02 | Unknown signing key or changed roster | Deny; do not trust a key embedded in the message |
| P03 | Expired, replayed or different request | Deny; no new partial generated |
| P04 | Changed query/snapshot/recipient | Deny or create a new approved run; never mutate |
| P05 | One provider rejects | Run remains undecryptable through the honest application |
| P06 | Network disconnect and retry | Pending state; retransmit identical immutable bytes |
| P07 | Crash during partial generation | Recover exact cached artifact or abort; do not regenerate |
| P08 | Party container restart/key loss | Abort epoch and explicitly re-enrol/rekey as needed |
| P09 | Two concurrent approval requests | At most one generated partial; transactional gate |
| P10 | Fresh key for another query | Does not reset study-wide disclosure ledger |
| U01 | Coordinator tries local approve route | Unreachable or unauthorized; no partial |
| U02 | CSRF, untrusted Origin and unauthenticated UI | Deny state-changing actions |
| U03 | Localhost ports share browser cookies | Distinct cookie names/scopes; no credential collision |
| U04 | Import path escape, symlink or remote URL | Deny; read configured import root only |
| U05 | Evidence export | No raw rows, source paths, secrets or full partial set |
| U06 | Separate-host mount/network audit | Coordinator cannot mount provider data or key tmpfs |

Cryptographic negative tests are not proofs of security. In particular, do not infer security from a few wrong numbers obtained with incomplete partials. The protocol's assumptions, upstream design and application controls must all be stated.

## 8.2 Minimal live demonstration script

Use synthetic data first. Start coordinator and two providers. Enrol fingerprints, select Q004, pin the plan, generate the joint key, confirm the epoch, and submit encrypted local counts. Show that the coordinator has no plaintext count and cannot import a spreadsheet. Request the sum. Approve at A only: the result must remain unavailable. Reject at B: the run terminates without a result. Start a **new run with fresh keys**, obtain both approvals, and compare the exact final result with the independent plaintext oracle.

Repeat with three providers. Approve A and B while C is disconnected: no fusion. Reconnect C without destroying its runtime keys, inspect the identical request and approve it: the exact total becomes available. Demonstrate a tampered aggregate and a wrong-epoch partial being rejected. Demonstrate a container restart separately: key loss aborts the epoch, unlike a temporary network interruption.

For clinical acceptance, repeat Q004 on the locally prepared IOCN shards. The expected plaintext total is 11. A permitted test can inspect local 5+6 or 3+2+6 on the provider screens; the coordinator receives only the final result. Explain that splitting one institution's file across laptops is a distributed-processing simulation, not proof of data governance across independent hospitals.

## 8.3 Benchmark methodology

Use synthetic datasets with 100, 1,000 and 10,000 admitted rows **per provider**, and n = 2 and 3. Record dataset generator version and query selectivity. The encrypted payload contains one scalar irrespective of the local row count; local filtering scales with rows, while the baseline FHE operation count depends primarily on n. Do not present a scalar aggregation as server-side encrypted filtering of 30,000 rows.

Measure import, normalization/filtering, context generation, each key-generation round, encryption, serialization, input upload, `EvalAdd`, aggregate verification, each partial, fusion and output serialization separately. Record ciphertext/key/partial byte sizes, peak resident memory, CPU, operating system, architecture, container limits, OpenFHE commit/submodules, effective parameters, compiler and thread settings. Use a monotonic timer; explicitly include or exclude network time.

After a warm-up, collect at least 20 samples per reported configuration. Use fresh keys for each complete run and one partial generation per provider per epoch. Report median and nearest-rank P95 (sorted element at index `ceil(0.95*N)-1`), with N. Human approval time is a separate measure, not cryptographic latency. Failed runs and retries are counted and reported. Do not reuse the same partial-generation call hundreds of times on clinical data for a benchmark.

No measured speed, RAM requirement or latency target is asserted in this document. Set acceptance budgets after M0/M2 measurements and record the rationale. A slow but correct baseline is preferable to silently lowering security or removing unanimous approval.

## 8.4 Evidence package and maturity claims

Create a release-scoped evidence index with build identifiers, test logs, parameter dumps, benchmark CSV, architecture, threat model, installation procedure, sanitized screenshots, observed defects, operator acceptance and the exact capabilities demonstrated. `templates/acceptance_report.md` and `templates/benchmark.csv` provide a starting structure.

Laboratory validation can support a TRL4 argument for the **cohort-count component** when the integrated system works and its tests are documented. Relevant-environment validation at IOCN, on representative machines and workflows with the appropriate authorizations, can support a TRL5 argument. Neither this specification nor a successful in-process smoke test establishes those levels automatically. Do not extend a count-only maturity claim to a future statistical SDK or to the entire platform promised in a funding application.

The default evidence export contains artifact hashes and signed consent metadata, not private shares or a reusable complete set of partial-decryption binaries. A stored aggregate plus all partials remains decryption-capable. Clinical output values and local diagnostics require their own access and retention rules. Use synthetic screenshots for public demonstrations.
