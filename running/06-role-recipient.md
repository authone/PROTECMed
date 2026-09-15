# 6. Role: recipient

A named person or system authorized to receive the released aggregate. Recipients are
fixed in the run plan before key generation and are bound by hash into the decryption
request, so the list cannot change after the providers have reviewed it.

Recipients have a read-only API token. There is no recipient UI.

## 6.1 Read the result

```bash
COORD=http://127.0.0.1:8080/api/v2
curl -s "$COORD/runs/synthetic-run/result" -H "Authorization: Bearer <recipient token>"
```

Before release:

```json
{"run_id": "synthetic-run", "state": "APPROVAL_PENDING", "released": false}
```

After release:

```json
{"run_id": "synthetic-run", "state": "REVEALED", "released": true,
 "aggregate": 5, "fused_at": "2026-09-15T09:07:32Z"}
```

No value exists before every provider approves, and the route does not hint at one. A
**party** requesting this route is refused with `403` — providers contribute, they are not
automatically recipients.

## 6.2 Read the receipt

```bash
curl -s "$COORD/runs/synthetic-run/evidence" -H "Authorization: Bearer <recipient token>"
```

Object hashes, every party's signed decision with role and timestamp, and the released
aggregate. It deliberately excludes the partial-decryption binaries.

## 6.3 What the number means

It is the exact sum of one integer per provider, each counted locally against the same
approved query on a snapshot frozen before the run.

What it does **not** establish:

- **That any provider counted honestly.** The protocol proves the right parties approved
  the exact computation. It does not prove a provider's input was truthful; that would
  need a different design.
- **That the individual counts stay private.** With two providers, anyone who knows one
  local count derives the other by subtraction. With three, two colluding providers derive
  the third. This is arithmetic on an exact total, not a weakness in the encryption.
- **Any differential-privacy guarantee.** There is none. The output is an exact count.

If a record count is being read as a patient count, that needs the data owner's explicit
confirmation that one row is one patient with no duplicates within or across sites. This
prototype performs no record linkage — see [Configure §2.2](02-configure.md#22-the-queries).

Next: [Troubleshooting](07-troubleshooting.md).
