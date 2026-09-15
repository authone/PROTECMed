# Implementation task — M4 services and minimal UI

Ticket / milestone: **M4 — services and minimal UI** (blueprint §7.1)
Owner / human reviewer: programmer implemented; **local IT/security reviewer approval of
deployment, identity enrolment and network access still required** (§7.4)
Specification sections: §4.7, §4.8, §5.4, §5.5, §5.6, §6.3, §7.1
Allowed files: `services/coordinator/`, `services/party-agent/protecmed_agent/`,
`deployment/synthetic_demo.py`, `tests/e2e/`, `evidence/m4/`,
`verification/milestones.json`

## What was implemented

**Coordinator** (`services/coordinator/protecmed_coordinator/`): FastAPI over SQLite.
`db.py` (schema, IMMEDIATE transactions, compare-and-set state, unique constraints),
`security.py` (bearer auth, roles, idempotency), `artifacts.py` (content-addressed store
with run-scoped reads), `runtime.py` (durable state that rehydrates the M3 protocol
object per operation), `app.py` (the §5.4 routes).

**Party agent** (`services/party-agent/protecmed_agent/`): `sessions.py` (local operator
session, CSRF, Host/Origin), `importdir.py` (read-only directory, opaque selection
tokens), `poller.py` (outbound-only coordinator client), `runtime.py` (the §5.5 actions
wired to M1/M2/M3), `app.py` plus five Jinja templates and one local stylesheet.

**Launcher** (`deployment/synthetic_demo.py`): the D1 synthetic single-host demo, all
ports bound to `127.0.0.1`.

## Security invariants
- Every POST requires a bearer token, a role and an idempotency key. Tokens are generated
  on the endpoint at runtime; only their SHA-256 is stored and comparison is constant-time.
- A party may act only as itself: an envelope whose `signer_id` is not the caller is
  rejected with `SIGNER_IS_NOT_CALLER` before any protocol logic runs.
- `GET /runs/{run}/artifacts/{sha256}` checks run membership even for a known content
  hash. A result is readable by recipients only, and only after release; a party asking
  for the result gets 403.
- The evidence export contains hashes and signed decisions and sets
  `partial_binaries_included: false` — the full partial set plus the aggregate would be a
  decryption-capable archive (§4.6).
- No route accepts a clinical XLSX/CSV, a filesystem path or a URL. Storage paths are
  server-generated from the content digest.
- CORS is not installed, public API documentation is disabled (`/docs`, `/redoc`,
  `/openapi.json` all 404) and the exception handlers return symbolic tokens, never a
  stack trace.
- Local UI: session cookie is `HttpOnly`, `SameSite=Strict` and **agent-specific**
  (`protecmed_session_party_a`), because cookies do not isolate applications by port.
  CSRF token on every form, exact Host check, exact Origin check when the browser sends
  one, and no state-changing GET (those routes return 405).
- The import directory returns opaque HMAC tokens carrying no path. Symlinks, non-regular
  files, disallowed suffixes and path escapes are refused.
- `n` still comes from the frozen plan. `POST /runs/{run}/fuse` takes no party count.

## Tests actually run
**311 passed, 0 failed, 0 skipped** — `python -m unittest discover -s tests -v`
(57 reference + 151 unit + 66 integration + **37 new end-to-end**). Full output:
`evidence/m4/unittest-full.txt`.

The end-to-end tests drive the real coordinator app and the real agent apps over ASGI
transports with real headers, cookies, CSRF tokens and multipart bodies, against the real
OpenFHE worker.

Release: 2/2 and 3/3 through the UI, aggregate equal to the synthetic fixture's Q004
total, and the per-party local counts equal to the fixture's two- and three-way splits.

Security: missing/invalid bearer token; party attempting a coordinator route; a party
replaying another party's envelope; docs disabled; idempotency key missing, replayed and
reused with a different body; artifact membership; oversized JSON; login required on
every screen; wrong operator token; cookie attributes; CSRF missing and wrong;
cross-origin POST; unexpected Host; state-changing GET; no external assets in the HTML;
selection token carries no path; an arbitrary path cannot be imported.

Scenarios: rejection blocks the release and the rejecting party emits no partial; an
offline coordinator leaves local state unchanged and the run screen says so; a retried
submission resends the same ciphertext; fusing twice returns the same receipt; a second
approval resends the stored partial; 2-of-3 approvals do not release.

Privacy: no local count appears in any stored envelope or audit row, and the count is
rendered only on the provider's own authenticated screen.

## Browser verification and screenshots
A real Chromium drove party-a end to end against live loopback servers: login, import,
plan acceptance, key round, epoch confirmation, local count, encrypted submission,
request review and approval. Fusion was refused with one approval
(`PARTIAL_SET_INCOMPLETE`) and released after both.

Eight screenshots are in `evidence/m4/screenshots/`, produced by
`tools/ui-screenshots/capture.py`, which drives the shipped UI through Playwright against
the system Chromium. Nothing is stubbed for the camera: real forms, real session cookies,
real CSRF tokens, the real coordinator API and the real worker. The capture is
reproducible, and `evidence/m4/browser-verification.md` describes each image.

This is **not** an automated browser test suite: no browser assertion runs as part of
`python -m unittest discover -s tests`. Playwright is an evidence-tooling dependency and
is deliberately not in any `services/*/requirements.txt`.

## Defects found by running it for real
1. The launcher's banner was block-buffered when stdout was redirected, so an operator
   saw a truncated banner missing party-b's URL, token and fingerprint.
   `synthetic_demo.py` now line-buffers stdout.
2. The notice bar rendered outside the page container, spanning the full window and
   overflowing the viewport edge. It now sits inside `main` at the page width.

Neither was visible in the HTML assertions; both needed a rendered browser.

## Tests NOT run and why
- **No automated browser suite.** Playwright was installed as an evidence tool and the
  screenshots are reproducible, but no browser assertion runs in the unittest suite. A
  regression in the rendered UI would not fail CI.
- **No real TLS, private CA or multi-machine transport.** Everything is loopback HTTP in
  one process tree. §4.8's HTTPS, pinned CA and `verify=False` prohibition are configured
  for D2 in M5/M6, not exercised here.
- **No Docker, no images, no Compose, no offline bundle** — M5.
- **No Windows/macOS, no mixed-architecture run, no clinical data, no pilot** — M6.
- **No concurrency or load test.** The compare-and-set and IMMEDIATE-transaction paths are
  exercised sequentially; no two writers were run in parallel.
- **No crash recovery by killing a live service.** Durable rehydration is exercised by
  reloading state per operation, not by a real restart mid-run.
- No benchmark; no timing is claimed.

## Deviations
1. `services/common/` continues to hold the shared protocol and worker client (flagged in
   M2 and M3, still not in the §5.1 layout).
2. Two convenience coordinator routes beyond the §5.4 table, both operator-only and
   idempotent: `POST /runs/{run}/context` and `POST /runs/{run}/epoch`. §5.4 lists the
   party-facing and release routes; the context and epoch publication steps need an
   endpoint too.
3. `GET /runs/{run}` returns the signed objects a member needs (plan, epoch, key rounds,
   input set, submissions, request) alongside the sanitized state, so the poller needs one
   round trip rather than six. It remains a read: a poll announces a request and cannot
   approve it.
4. The party agent keeps its run state in memory, not SQLite. Its durable state is the
   immutable outbox, the snapshot registry and the disclosure ledger, all on disk. A party
   restart loses ephemeral keys and must abort unfinished runs (§4.7) — which is the
   specified behaviour, but it means the agent has no restart-resume path to test.
5. Bearer tokens rather than mutual TLS for agent authentication, matching §6.6's
   "ephemeral random local operator token" baseline.

## Evidence paths
- `evidence/m4/unittest-full.txt` — full verbose run, 311 tests
- `evidence/m4/browser-verification.md` — browser verification notes
- `evidence/m4/screenshots/` — eight PNGs of the shipped UI plus `release.txt`
- `evidence/m4/browser-release-transcript.txt` — live API responses from the first pass
- `evidence/m4/demo-launcher-banner.txt` — launcher output, tokens redacted
- `evidence/m4/M4_REPORT.md` — this report

## Status
**PASSED (programmer evidence complete).** §7.1 requires that M4 not be accepted until
M2 and M3 work with the real worker: they do, and the end-to-end tests exercise all four
layers together. Outstanding before any clinical use: local IT/security review of
deployment, identity enrolment and network access (§7.4), and everything in the NOT RUN
list above.

## Stop conditions / unresolved questions
- Identity enrolment is currently "the operator provisions an agent and pins the
  fingerprint". The out-of-band comparison procedure itself is a human process that needs
  writing down before D2.
- The synthetic demo binds loopback HTTP with no TLS. That is acceptable only for D1 and
  must not be presented as an institutional trust boundary.
- Session lifetime, token rotation and lockout policy are placeholders (60 minutes, no
  rotation, no lockout) and need the security reviewer's decision.
