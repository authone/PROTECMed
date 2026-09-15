# UI screenshot capture (M4 evidence tool)

Drives the shipped local provider UI through a real Chromium and writes one PNG per
screen. Nothing is stubbed for the camera: real forms, real session cookies, real CSRF
tokens, the real coordinator API and the real OpenFHE worker. Synthetic fixture data only.

## Requirements

- A Chromium binary (`/usr/bin/chromium` by default, override with `--chromium`).
- Playwright's Python package in the interpreter that runs this tool.
- An interpreter with the service dependencies for the demo launcher
  (`--demo-python`, default `python3`).

Playwright is an evidence-tooling dependency, not a runtime dependency of the services:
it is deliberately absent from `services/*/requirements.txt`.

```bash
pip install playwright        # into the tooling interpreter
python tools/ui-screenshots/capture.py --state /tmp/protecmed-shots
```

## What it captures

| File | Screen |
|---|---|
| `01-login.png` | Local operator login |
| `02-import-before.png` | Screen 1 before any import |
| `03-import-validated.png` | Screen 1 with the frozen snapshot and validation report |
| `04-run-before-plan.png` | Screen 2 before the plan is accepted |
| `05-run-local-count.png` | Screen 2 with the local count, visible only here |
| `06-request-before-review.png` | Screen 3 before local verification |
| `07-request-verified.png` | Screen 3 with all local checks and the irreversibility warning |
| `08-approved.png` | Screen 3 after approval, with the decision recorded |
| `release.txt` | Fusion refused with one approval, released with both |

The tool starts its own coordinator and two party agents on loopback ports and stops them
when it finishes. It writes into `evidence/m4/screenshots/` by default.
