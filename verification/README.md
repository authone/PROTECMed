# Verification ledger

Read verification.json and python_reference_tests.txt. These are results of producing the documentation/reference package, not certification of the prototype.

57 local unit tests exercised only synthetic/reference Python logic, schema validation and minimal synthetic OOXML cache cases. The clinical cached-value counts were checked separately and match config/iocn_expected_counts.json; no patient rows are stored here. No cached-formula freshness or clinical semantic correctness was established.

C++, OpenFHE runtime, services, containers and Windows/Mac execution remain NOT RUN. Fill a new release-scoped acceptance report after the programmer actually completes those gates. Do not overwrite NOT RUN with PASS merely because the source looks plausible.

## Milestone executions after delivery

`verification.json` above is the frozen ledger of the 5 September 2026 documentation and
reference package. Gate executions performed after that date are recorded separately in
`milestones.json`, with the evidence under `evidence/<gate>/`:

- **M0 — reproducible upstream build: PASS (2026-09-14).** OpenFHE v1.5.1 commit
  `1306d14f8c26bb6150d3e6ad54f28dfe1007689e` built on linux/arm64; upstream threshold and
  serialization examples ran; `count_smoke` passed 2/2 and 3/3 with exact sums; effective
  parameters recorded for both profiles. Report: `evidence/m0/M0_REPORT.md`.
- **M1 — reference data semantics: PASS (2026-09-14).** Party-agent import, catalogue and
  snapshot layer implemented with 148 passing unit tests on synthetic data. The IOCN
  plaintext regression remains NOT RUN — it requires the private workbook on an authorized
  endpoint. Report: `evidence/m1/M1_REPORT.md`.
- **M2 — process-separated crypto: PASS (2026-09-14).** The nine-subcommand OpenFHE
  worker, exercised by 32 integration tests in separate processes with per-party
  owner-only directories; 180 tests pass in total. Two negative findings are recorded
  rather than hidden: a same-profile context does not identify an epoch, and fusion with
  a wrong share returned a plausible in-range integer. Report: `evidence/m2/M2_REPORT.md`.

- **M3 — signed immutable protocol: PASS (2026-09-14).** Run plans, key rounds, epoch
  confirmations, submissions, input sets, decryption requests, the local approval gate and
  the coordinator all-party fusion gate, driven end-to-end against the real worker; 274
  tests pass in total. Six tests assert that fusion is never invoked when a share,
  approval or signature is missing. Report: `evidence/m3/M3_REPORT.md`.

- **M4 — services and minimal UI: PASS (2026-09-15).** Coordinator FastAPI/SQLite service
  and party agent with three server-rendered Romanian screens, poller, import selector,
  transactions and immutable outbox; 311 tests pass, including 37 end-to-end tests over
  real HTTP with CSRF, auth, rejection, offline and retry scenarios. Browser verification with
  eight screenshots of the shipped UI is recorded in `evidence/m4/screenshots/`, but no
  browser assertion runs in the test suite. Report: `evidence/m4/M4_REPORT.md`.

The C++/OpenFHE entries in `verification.json` were NOT RUN at delivery and were not
edited; `milestones.json` records that M0 has since executed them. Everything else there
— services, containers, Windows/macOS, clinical pilot — is still NOT RUN.
