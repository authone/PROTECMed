# 9. Instructions for AI-assisted development

## 9.1 Rules for every agent

Treat this blueprint as the normative specification. `AGENTS.md` is its compact enforcement checklist. Read the relevant upstream pinned files before introducing an OpenFHE API. Work only on synthetic fixtures. Do not send the IOCN workbook, rows, raw logs, clinical screenshots or secrets to an external model. Keep clinical testing physically outside the agent's accessible workspace.

Do not create a central private key, reconstruct shares, use a debug key-generation overload, bypass an approval gate, decrease the threshold after a failure, or “temporarily” fall back to plaintext. Do not generate new randomness on an idempotent retry. Do not silently substitute CKKS for exact counts, turn off noise flooding, force a small ring, or allow arbitrary query expressions.

Do not claim a function is malicious-secure merely because it checks signatures. Keep source-supported library behavior, application policy and unproven assumptions separate. Missing source or a test failure is a reason to stop and report, not to invent an API or an expected benchmark.

## 9.2 Reusable task prompt

```text
Task: implement [MILESTONE / TICKET] for PROTECMed v2.
Read AGENTS.md, IMPLEMENTATION_BLUEPRINT.md sections [X],
and the pinned upstream files listed in this ticket.

Scope: cohort-count-local-v2, BGV exact integers,
2/2 and 3/3 unanimous decryption. No other statistical module.
Allowed files: [PATHS]. Contracts: [SCHEMA NAMES / VERSIONS].
Use only fixtures/synthetic_cohorts.csv or generated synthetic data.

First state the input/output invariants and the negative tests.
Implement the smallest vertical change that satisfies the ticket.
Never construct a full secret key or bypass local human consent.
Preserve immutable run/epoch/query/input/recipient bindings.

Run [EXACT TEST COMMANDS]. Report separately:
1. files changed and why;
2. tests actually run, environment and evidence paths;
3. tests skipped or blocked, with reason;
4. unresolved security or compatibility questions.
Do not claim completion while required tests are skipped.
Stop for human review before any cryptographic-profile change.
```

## 9.3 Safe parallelism and review

A data-adapter agent can implement schema/normalization tests while a crypto agent completes M0/M2. An API agent can draft state-machine tests against a fake worker, clearly labelled. A UI agent may implement only the approved local forms. The lead engineer reconciles the contracts before integration; agents must not independently invent competing query JSON or role names.

Every merge must preserve one source of truth for the catalogue, schema version, crypto profile and release policy. Update documentation and tests together. If an implementation deviates from v2, record an architectural decision and version the changed contract rather than leaving incompatible examples in the repository.
