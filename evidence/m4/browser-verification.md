# M4 manual browser verification

Real Chromium against the real services over loopback HTTP — **not** an automated
browser test suite, and **no screenshot was captured**: the browser pane was not being
composited in this environment, so `screenshot` timed out every time. The evidence below
is the accessibility tree and rendered page text read from the live pages, plus the
coordinator's responses.

Servers: `python deployment/synthetic_demo.py --parties 2 --state <scratch>`
coordinator `127.0.0.1:8080`, party-a `127.0.0.1:8081`, party-b `127.0.0.1:8082`.
party-a was driven entirely through the browser; party-b and the coordinator operator
steps were driven by a script against the same live servers.

## Login screen
```
banner "DEMONSTRATIE SINTETICA · party-a"
heading "Autentificare operator local"
textbox type="password"        button "Intra"
"Tokenul este generat local la pornirea agentului si nu este stocat in imagine."
```
The operator token printed by the launcher was typed into the form; login succeeded and
set the agent-specific session cookie.

## Screen 1 — import and mapping status
The file radio's value is the opaque selection token, never a path:
```
radio "d7616062653501b6249df461dd10f63d"   generic "cohort.csv"   "334 B"
```
After submitting the CSRF-protected form:
```
Stare validare
Fisier cohort.csv | Mod canonical-csv | Inregistrari admise 12
Randuri goale ignorate 0 | Celule cu formule selectate 0
Parti externe (neactualizate) 0
Token instantaneu snap-01bd658818e5cde48a38b87b28f5
```

## Screen 2 — run, key and submission
Live state, updated between steps:
```
Stare locala EPOCH_CONFIRMED | Stare rulare (coordonator) COLLECTING
Au acceptat planul party-a, party-b | Au confirmat epoca party-a, party-b

Numar local calculat: 5 (vizibil doar pe acest ecran; coordonatorul nu il primeste)
```
The local count appears **only** here. The coordinator's `GET /runs/{run}` response
carries no count field.

## Screen 3 — verified decryption request
```
Interogare            Q004 (din catalogul local aprobat)
Parti necesare        party-a, party-b
Rolul acestei parti   lead
Expira la             2026-09-15T09:09:09Z

Verificari locale
  signature_schema_epoch
  query_roster_recipients
  inputs_authenticated
  exact_input_set
  aggregate_recomputed
  share_epoch_and_policy

"Aprobarea autorizeaza aceasta divulgare. O contributie deja emisa nu poate fi retrasa
 criptografic: expirarea sau inchiderea rularii nu face acei octeti indecriptabili."

button "Aproba si emite partea de decriptare"   button "Respinge"
```
The query is rendered from the **local** approved catalogue, not from a description in
the coordinator's message.

## Release
party-a approved by clicking the button in the browser. Then, against the live API:

```
fuse before party-b approves: 400 {"detail": "PARTIAL_SET_INCOMPLETE"}
b approve:                    /local/v2/request?notice=OK
fuse after both approve:      200 {"aggregate": 5, ...}
result:                       {"state": "REVEALED", "released": true, "aggregate": 5}
evidence partial_binaries_included: False
evidence decisions: [("party-a", "APPROVE"), ("party-b", "APPROVE")]
```

5 is the expected Q004 total for the synthetic 24-row fixture (`5 + 0`). It is not a
clinical result.

## Defect found and fixed during this session
The launcher's banner was block-buffered when stdout was redirected, so an operator saw
only part of it — the party-b URL, token and fingerprint were missing. `synthetic_demo.py`
now line-buffers stdout.
