# PROTECMed developer package v2

Exact local cohort counts with OpenFHE and unanimous 2/2 or 3/3 decryption.

**To install and run it, start with [running/README.md](running/README.md).**

## Documentation

| Document | Purpose |
|---|---|
| [running/](running/README.md) | Install, configure, run, and what each role does |
| [IMPLEMENTATION_BLUEPRINT.md](IMPLEMENTATION_BLUEPRINT.md) | The English normative specification |
| [README_START_AICI.md](README_START_AICI.md) | Romanian handover |
| [AGENTS.md](AGENTS.md) | Mandatory rules for anyone, human or agent, changing this code |
| [CHANGELOG.md](CHANGELOG.md) | What changed from v1 and why |
| [verification/README.md](verification/README.md) | What has actually been executed, and what has not |

## Status

Milestones M0–M4 are implemented and their evidence is in `evidence/`: the pinned OpenFHE
build, the local data layer, the process-separated worker, the signed protocol with its
approval gate, and the services with a local browser UI.

Not built: container images, an offline bundle, multi-machine deployment with TLS,
Windows/macOS support, and clinical acceptance. `verification/milestones.json` is the
per-gate record; `verification/verification.json` is the frozen 2026-09-05 ledger for the
original documentation package.

Use synthetic data. No patient-level rows and no private keys are included, and the
restricted clinical aggregate regression appendix must not be published automatically.
