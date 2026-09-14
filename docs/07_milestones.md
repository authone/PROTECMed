# 7. Implementation plan and acceptance gates

## 7.1 Work in vertical increments

One engineer can follow these milestones sequentially. AI agents may work on independent fixtures, UI layout and documentation, but a human owns the cryptographic boundary and merges one reviewed change at a time. Do not start by generating an entire application from a single prompt. There is no calendar promise: close a gate only when its evidence exists.

| Gate | Implement | Required evidence before proceeding |
|---|---|---|
| M0 — reproducible upstream build | Pin source/submodules, build OpenFHE and the supplied smoke source; capture effective 2/2 and 3/3 profiles | Build log, full commits, compiler/CMake flags, successful exact sums, no forced insecure parameters |
| M1 — reference data semantics | Port the fixed catalogue and strict import rules; keep the clinical file outside the development environment | Synthetic tests; formula-cache tests; separately authorized IOCN plaintext regression |
| M2 — process-separated crypto | Implement the nine worker commands, serialization, private directories and deterministic recomputation | Distinct processes; positive 2/2 and 3/3 flows; wrong epoch/input/aggregate rejected |
| M3 — signed immutable protocol | Implement plans, key rounds, epoch confirmations, submissions, requests, local approvals and exact partial set | Signed contract fixtures and negative tests; no fusion call when a share or signature is missing |
| M4 — services and minimal UI | Add coordinator, party poller, local import selector, approval forms, transactions and immutable outbox | Browser/API end-to-end tests, CSRF/auth tests, rejection/offline/retry scenarios |
| M5 — packaging | Build pinned amd64 and arm64 images, same-host synthetic Compose and separate-host profiles | Image IDs, installation scripts, secret/data mount inspection, offline install rehearsal |
| M6 — relevant-environment pilot | Test two and three endpoints, including intended IOCN Windows/macOS hardware | Operator acceptance, mixed-platform artifact exchange, clinical comparison, failure/recovery evidence |
| M7 — handover | Freeze release, export sanitized evidence, document limitations and operator recovery | Signed acceptance report, reproducible test instructions, retained risk register |

M1 can proceed in parallel with M0. M3 may use a fake worker for state-machine unit tests, but those tests must be labelled as such; they do not validate threshold encryption. M4 cannot be accepted until M2 and M3 work with the real worker. M5 is not a substitute for M6.

## 7.2 First engineer session

Read `README_START_AICI.md`, this blueprint's Sections 1–4, and `AGENTS.md`. Run the delivered Python unit tests on synthetic data. Review the verification ledger before treating any file as executable product code. Then perform M0: acquire the pinned upstream source in an environment with network access, build it, build `reference/cpp/count_smoke.cpp`, and record the results. Do not change the cryptographic scheme merely because compilation or serialization needs a small fix.

The C++ smoke source deliberately holds all separate shares in one test process. That makes it an API/correctness smoke test only. It must never become the coordinator implementation or receive patient data. M2 replaces this arrangement with independent private namespaces and processes.

## 7.3 Task card template

Each implementation ticket must contain: requirement IDs or section numbers; files allowed to change; input/output contracts; threat-model assumptions; positive and negative tests; exact commands to run; evidence paths; and an explicit stop condition. Use `templates/task_card.md`.

A completed ticket includes the patch, test output, remaining failures and a short explanation of any changed assumption. “It should work” is not an acceptance result. A coding agent must not mark skipped tests as passed, fabricate benchmarks, or weaken validation to make a test green.

## 7.4 Human review responsibilities

The programmer owns implementation and reproducibility. A cryptography reviewer approves effective parameters, key generation, aggregate verification, share handling and extension designs. IOCN confirms the mapping, formula-value provenance, record/patient semantics and output recipients. A local IT/security reviewer approves deployment, identity enrolment, network access and clinical-data handling. These are roles to assign, not assertions that approvals have already been obtained.

Before merging, answer four questions: does any new path expose a local count or secret; can a remote request cause a partial without local approval; can a run mix keys, snapshots or ciphertexts; and does the test evidence support the exact claim made in the documentation?
