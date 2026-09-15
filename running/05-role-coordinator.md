# 5. Role: coordinator operator

The person who orchestrates a run. They hold **no FHE secret share**, receive **no
clinical data**, and cannot produce a result on their own.

> **There is no coordinator browser UI.** Milestone M4 built the coordinator as an HTTP
> API only. The status and result screens described in the specification are not
> implemented. Use `curl`, an HTTP client, or a short script.

Base URL: `http://127.0.0.1:8080/api/v2`

## 5.1 Every request

| Requirement | Detail |
|---|---|
| `Authorization: Bearer <token>` | The operator token printed at launch. Roles are enforced per route. |
| `Idempotency-Key: <key>` | Required on **every** POST. 8–128 characters of `A-Za-z0-9-_`. |
| Content | JSON, at most 64 KiB. Binary uploads are multipart, at most 16 MiB. |

A byte-identical retry with the same key returns the stored response. The same key with a
different body returns `409 IDEMPOTENCY_KEY_REUSED`.

There is no public API documentation: `/docs`, `/redoc` and `/openapi.json` all return
404. Errors are symbolic tokens, never stack traces.

A convenience shell function for the examples below:

```bash
COORD=http://127.0.0.1:8080/api/v2
TOKEN=<operator token from the launcher>
api() { curl -s -X "$1" "$COORD$2" \
  -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $3" \
  -H 'Content-Type: application/json' -d "${4:-\{\}}"; }
```

## 5.2 Freeze the study and the run

Collect from each provider, out of band: their **identity fingerprint** and their
**snapshot token**. Compare the fingerprints by a channel that is not this service — that
comparison is the entire basis for believing the roster is who it claims to be.

```bash
api POST /studies key-study-0001 '{"study_id":"synthetic-study"}'

api POST /studies/synthetic-study/runs key-run-0001 '{
  "run_id": "synthetic-run",
  "roster": [
    {"party_id":"party-a","identity_key_sha256":"<fingerprint a>","snapshot_token":"snap-..."},
    {"party_id":"party-b","identity_key_sha256":"<fingerprint b>","snapshot_token":"snap-..."}
  ],
  "recipient_ids": ["recipient-one"],
  "query_sha256": "59544300891e03b9002cb74a8fa708797a8fae2d770e6f44446b1628269c054f",
  "mapping_sha256": "9ce1b019263bb9501742ab1a40aedffde79fca00f576ddfe6d92313a564bf1c9"
}'
```

Returns the signed run plan. **Roster order is meaningful**: the first entry is the lead
party and defines the addition order. The threshold always equals the roster size — there
is no field to lower it.

The query and mapping hashes come from [Configure §2.1](02-configure.md#query-and-mapping-hashes).
`59544...` is Q004.

Now wait for every provider to accept the plan. Check with:

```bash
curl -s "$COORD/runs/synthetic-run" -H "Authorization: Bearer $TOKEN" \
  | python -m json.tool | grep -E 'state|accepted_by|confirmed_by|submitted_by|approved_by'
```

## 5.3 Context and key ceremony

```bash
api POST /runs/synthetic-run/context key-ctx-0001
```

Then each provider generates its key share **in roster order** (their screen 2, action 2).
Watch `key_rounds` in the run view grow to the roster size, then:

```bash
api POST /runs/synthetic-run/epoch key-epoch-0001
```

This publishes the epoch manifest, binding the run-plan hash, the context hash, the final
public-key hash and the ordered key-round transcript. Every provider must then confirm it
before any ciphertext is accepted.

## 5.4 Evaluate and request

Once `submitted_by` lists every party:

```bash
api POST /runs/synthetic-run/evaluate key-eval-0001
api POST /runs/synthetic-run/decryption-request key-req-0001 '{"ttl_seconds":900}'
```

`evaluate` locks the input set and performs the ordered homomorphic addition. The
coordinator never decrypts anything.

`decryption-request` publishes **one immutable request per epoch**, binding the run, the
epoch, the query, the input-set hash, the aggregate hash, the recipient-list hash, the
required parties, the lead, a nonce and a UTC expiry. Keep the lifetime short but long
enough for people to read the screen. A second request for the same epoch is refused.

## 5.5 Fuse

```bash
api POST /runs/synthetic-run/fuse key-fuse-0001
```

Succeeds **only** when all of the following hold:

- the epoch was confirmed by the whole roster and the run is not closed, rejected or on
  integrity hold;
- the request and input set still match the frozen run, and the request has not expired;
- the set of verified partial signers is **exactly** the roster, with one lead and n−1
  mains, each bound to the same request, epoch and aggregate hash;
- no rejection, conflicting partial, or change of recipients or query has been accepted;
- no fusion receipt exists yet.

Otherwise it returns `400` with a symbolic token — `PARTIAL_SET_INCOMPLETE`,
`REJECTION_PRESENT`, `REQUEST_EXPIRED`, and so on. **You cannot override this.** There is
no party-count parameter on this route: `n` comes from the frozen plan, so an API caller
cannot ask a three-party run to release on two approvals.

Fusing twice returns the stored receipt; it does not re-fuse.

## 5.6 Read the outcome

```bash
curl -s "$COORD/runs/synthetic-run/result"   -H "Authorization: Bearer $TOKEN"
curl -s "$COORD/runs/synthetic-run/evidence" -H "Authorization: Bearer $TOKEN"
```

Before release, `result` reports `"released": false` and carries no value.

`evidence` is the sanitized export: object hashes, each party's signed decision with its
timestamp and role, and the released aggregate. It sets `partial_binaries_included: false`
— the full set of partial decryptions together with the aggregate is a
**decryption-capable archive**, not harmless metadata, and must never be dropped into an
ordinary evidence ZIP.

## 5.7 What you can see, and what you cannot

You see the query, the roster, the timing, artifact sizes and, after release, the exact
aggregate. You do **not** see any provider's local count, source file, file hash or rows —
only opaque snapshot tokens.

The design does not hide the metadata above, and it does not claim to. What it prevents is
a coordinator obtaining the aggregate without every provider's participation.

Next: [Role: recipient](06-role-recipient.md).
