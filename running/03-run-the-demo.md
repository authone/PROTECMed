# 3. Run the demo

One complete release on a single Linux machine with invented data.

> Three processes on one laptop are a **simulation**. The host administrator can read
> every party's directory. Do not present this as institutional separation.

## 3.1 Start

```bash
.venv/bin/python deployment/synthetic_demo.py --parties 2 --state /tmp/protecmed-demo
```

Options: `--parties 2|3`, `--state <dir>` (required, wiped and recreated is *not*
automatic — pick a fresh directory), `--worker`, `--openfhe-lib`.

It prints:

```
=== PROTECMed synthetic single-host demo (D1) ===
SIMULATION: separate directories on one host, not separate institutions.

coordinator API   http://127.0.0.1:8080/api/v2
operator token    <one-time token>
party-a   UI      http://127.0.0.1:8081/local/v2/login
party-a   token   <one-time token>
party-a   finger  bdd1301c132ac6fe35c268a2087b40a0122949d443262a12ddc0fb7e41df030e
party-b   UI      http://127.0.0.1:8082/local/v2/login
party-b   token   <one-time token>
party-b   finger  a6f8861dce0a308d89538ea9932dc0f1a75d5e41dffee62abcf916d56af7c568

Ctrl-C to stop.
```

Tokens are generated at start and are **not** stored in the repository or in any image.
They change on every run. The launcher also splits `fixtures/synthetic_cohorts.csv` into
one shard per party and drops it in each party's import directory — that split is an
artificial simulation; real institutions already hold distinct datasets.

Keep this terminal open: `Ctrl-C` stops all services.

## 3.2 The sequence

Ten steps, alternating between the providers' browsers and the coordinator operator's
API client. Each row says who acts.

| # | Who | Action |
|---|---|---|
| 1 | Each provider | Log in, select the file, import and validate |
| 2 | Operator | Create the study, freeze the run plan |
| 3 | Each provider | Accept the plan |
| 4 | Operator | Create the FHE context |
| 5 | Providers **in roster order** | Generate the local key share |
| 6 | Operator | Publish the epoch manifest |
| 7 | Each provider | Confirm the epoch |
| 8 | Each provider | Compute the local count, encrypt and submit |
| 9 | Operator | Evaluate the inputs, issue the decryption request |
| 10 | Each provider | Review the request, then Approve or Reject |
| 11 | Operator | Fuse — succeeds only when every provider approved |

Two ordering rules the services enforce, so you cannot get them wrong silently:

- **Key generation is sequential.** party-a must complete step 5 before party-b, because
  each round extends the previous public key. A party acting out of turn is refused with
  `KEY_ROUND_OUT_OF_ORDER`.
- **No ciphertext is accepted before every epoch confirmation is present.** Submitting
  early returns `WRONG_STATE`.

## 3.3 Walk it through

Step by step with screenshots: [Role: local provider operator](04-role-provider.md).
The API calls for steps 2, 4, 6, 9 and 11: [Role: coordinator operator](05-role-coordinator.md).

## 3.4 What success looks like

With the delivered synthetic fixture and Q004 on two parties, the local counts are 5 and
0, and the released total is **5**. On three parties they are 0, 3 and 2, and the total is
still 5. Those numbers come from `fixtures/synthetic_expected.json`; they are invented and
have no clinical meaning.

The final fusion returns:

```json
{"request_sha256": "...", "aggregate": 5, "fused_at": "...", "partial_sha256": ["...", "..."]}
```

## 3.5 Things worth trying

They demonstrate the properties the design exists for:

- **Withhold one approval.** Have one provider Reject, or simply not approve, then call
  fuse. It returns `400 PARTIAL_SET_INCOMPLETE` or `400 REJECTION_PRESENT`, and the result
  route keeps reporting `"released": false`. A missing participant blocks the release —
  there is no administrator bypass.
- **Stop the coordinator** (`Ctrl-C`) and click a provider action. The screen reports
  `OFFLINE` and the local state does not change. Restart and retry: the same bytes are
  resent, never a newly generated artifact.
- **Approve twice.** The second attempt returns the stored partial from the outbox. A
  provider can never emit two different partials for one epoch.
- **Look for a local count in the coordinator's database.** There isn't one:
  `sqlite3 /tmp/protecmed-demo/coordinator.db 'select * from messages'` shows hashes,
  tokens and signatures only.

## 3.6 Stop and reset

`Ctrl-C` in the launcher terminal. To start clean, delete the state directory — it holds
the databases, identity keys, shares and artifacts.

A restart always means a fresh run: the FHE shares are gone and an unfinished epoch cannot
be resumed. That is intentional.

Next: [Role: local provider operator](04-role-provider.md).
