# M4 browser verification

Real Chromium against the real services over loopback HTTP. Two passes were made:

1. **A manual walk-through** driven interactively, recorded as accessibility trees and
   rendered page text.
2. **A scripted capture** with Playwright driving the same system Chromium, which
   produced the PNGs in `evidence/m4/screenshots/` and is reproducible with
   `tools/ui-screenshots/capture.py`.

Neither is an automated browser *test suite*: there are no browser assertions in
`python -m unittest discover -s tests`. The end-to-end assertions live in `tests/e2e/`
over ASGI transports; the browser work verifies that the shipped HTML, forms, cookies and
CSRF tokens actually work in a browser engine.

In both passes party-a was driven through the browser, while party-b and the coordinator
operator steps were driven by ordinary HTTP calls against the same live servers.
Servers: `python deployment/synthetic_demo.py --parties 2 --state <scratch>` —
coordinator `127.0.0.1:8080`, party-a `127.0.0.1:8081`, party-b `127.0.0.1:8082`.

## Screenshots

`evidence/m4/screenshots/`, captured by `tools/ui-screenshots/capture.py`:

| File | What it shows |
|---|---|
| `01-login.png` | Local operator login; the token is generated at launch, not shipped |
| `02-import-before.png` | Screen 1, approved import directory listed, nothing frozen yet |
| `03-import-validated.png` | Screen 1 after import: 12 admitted records, 0 blank rows, 0 formula cells, 0 external-link parts, opaque snapshot token |
| `04-run-before-plan.png` | Screen 2 before the plan is accepted |
| `05-run-local-count.png` | Screen 2 with `Numar local calculat: 5 (vizibil doar pe acest ecran; coordonatorul nu il primeste)` |
| `06-request-before-review.png` | Screen 3 before local verification |
| `07-request-verified.png` | Screen 3: Q004 rendered from the local catalogue, role `lead`, six local checks OK, irreversibility warning, Approve/Reject |
| `08-approved.png` | Screen 3 after approval: decision recorded, no approve button left |
| `release.txt` | The coordinator's responses either side of the last approval |

## Release, from `screenshots/release.txt`

```
fuse with one approval : 400 {"detail":"PARTIAL_SET_INCOMPLETE"}
fuse with both         : 200 {"aggregate":5, ...}
```

5 is the expected Q004 total for the synthetic 24-row fixture (`5 + 0`). It is not a
clinical result.

## What the screens confirm

- The file radio carries an opaque HMAC selection token, never a path.
- The local count is rendered only on the provider's own authenticated screen; the
  coordinator's `GET /runs/{run}` response has no count field.
- The query on the approval screen is rendered from the **local** approved catalogue, not
  from a description supplied by the coordinator.
- The irreversibility warning is present before the Approve button exists, and the button
  disappears once a decision is recorded.

## Defects found by running it for real

1. The launcher banner was block-buffered when stdout was redirected, so an operator saw
   a truncated banner with party-b's URL, token and fingerprint missing.
   `deployment/synthetic_demo.py` now line-buffers stdout.
2. The notice bar was rendered outside the page container, so it spanned the full window
   and overflowed the viewport edge. It now sits inside `main` with the page width.

Both were visible only in a rendered browser, not in the HTML assertions.
