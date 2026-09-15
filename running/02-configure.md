# 2. Configure

## 2.1 The three configuration files

These live in `config/` and are part of the release. Changing any of them changes a hash
that the protocol binds, which invalidates in-flight runs — that is deliberate.

| File | What it fixes |
|---|---|
| `config/crypto-profile.json` | The reviewed BGV profile `bgv-count-nofn-v2`. **Do not edit without cryptography review.** |
| `config/query-catalog.json` | The six allowed queries, Q001–Q006. A query outside this catalogue is refused before any data is read. |
| `config/iocn-mapping.json` | Source-header mapping, approved sheet name, default formula mode, local row cap. |

The worker checks the deserialized context against the profile **compiled into it**, not
against a sidecar file, so editing `crypto-profile.json` alone cannot weaken a run — it
will simply stop matching.

### Query and mapping hashes

The coordinator needs these when it freezes a run:

```bash
.venv/bin/python - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "services/common")
from protecmed_protocol.canonical import payload_hash, sha256_hex
for query in json.loads(pathlib.Path("config/query-catalog.json").read_text())["queries"]:
    print(f'{query["query_id"]}  {payload_hash(query)}')
print(f'mapping  {sha256_hex(pathlib.Path("config/iocn-mapping.json").read_bytes())}')
PY
```

For the files in this release:

```
Q001  524e16a8d8288e4f997f14cec8d6754c23585346f26dead9e385a933822ac854
Q002  81b26fbcfdcf8e45cf6892d7cab82d06c93ce3cfd81fd39b4008fc0480382f23
Q003  0237e987741750dff8f70ed89b3e3e776b6b925346088f207b1eb86222dc2fa8
Q004  59544300891e03b9002cb74a8fa708797a8fae2d770e6f44446b1628269c054f
Q005  313e61b3c0072b4fda7dd43ccf0f5f8a2142dd547c02cd81a69c2f6c058ad2a0
Q006  6e67c540d3d230eada677e85c9ed02aa3c9794397270d280a7d6122f41afa7dc
mapping  9ce1b019263bb9501742ab1a40aedffde79fca00f576ddfe6d92313a564bf1c9
```

If your output differs, your config files differ. Find out why before running anything.

## 2.2 The queries

| ID | Cohort |
|---|---|
| Q001 | All admitted records |
| Q002 | Diagnosis = MBL |
| Q003 | MBL and IMRT |
| Q004 | MBL and IMRT and WBC toxicity ≥ 2 |
| Q005 | Age at radiotherapy < 12 and MBL |
| Q006 | Surgery = GTR and IMRT |

Q001 counts **matching records**. Calling them unique patients requires an explicit
confirmation from the data owner that one row is one patient with no duplicates within or
across sites. This prototype does no record linkage.

## 2.3 Identities and enrolment

Every endpoint generates its own Ed25519 identity key **on that endpoint, at first
start**, and stores it as `identity.key` (mode 0600) in its private directory. The
coordinator never generates a party's identity key and never holds an FHE share.

Enrolment is deliberately a two-step human process:

1. Each provider starts its agent and reads its **fingerprint** (printed by the launcher;
   it is the SHA-256 of the raw public key).
2. The operators compare fingerprints **out of band** — a phone call, a signed document,
   anything that is not the coordinator — and only then is the key registered and the
   roster locked.

A registration page alone is not proof that independent institutions control the listed
keys. If a fingerprint changes, that is a new enrolment and a new run, never a silent
accept.

## 2.4 Where data lives

Each provider agent owns a private directory, created with mode 0700:

| Path | Contents |
|---|---|
| `identity.key` | Ed25519 identity, 0600 |
| `share.bin` | The FHE secret share for the current epoch |
| `outbox/` | Write-once submission and partial artifacts, plus receipts |
| `disclosure.jsonl` | Study-wide record of what this provider has helped release |
| `registry/` | Frozen canonical snapshots |
| `jobs/` | Per-operation worker input and output files |
| `import/` | The read-only directory the UI lists |

The coordinator owns `coordinator.db` (SQLite), `artifacts/` (content-addressed binaries)
and its own `identity.key`.

**Rules that are not negotiable:**

- Clinical files and keys stay outside any AI coding-agent workspace, outside the Git
  root, outside a Docker build context, outside cloud-sync folders and outside public CI.
  An ignore file is not an access control. The snapshot registry refuses to be created
  inside a Git work tree for exactly this reason.
- The coordinator database never receives a clinical row, a local count or a source file
  hash. It receives an **opaque snapshot token**.
- In the intended deployment the share directory is an ephemeral tmpfs. A restart destroys
  the keys and unfinished runs must be abandoned — that is the design, not a fault.

## 2.5 Formula mode

XLSX import has two explicit modes:

- **`literal-only`** (default) — a formula in a selected clinical cell is rejected. Use a
  values-only export prepared and verified by the data owner.
- **`reviewed-cached-values`** — saved formula results are accepted only when the local
  operator confirms the file was recalculated and saved, and only when every selected
  formula cell has a non-error, non-empty saved result.

Cache freshness **cannot** be established from the workbook. The report always records
`cache_freshness_verified: false` and the UI shows a warning. A missing cached result is
never read as null, false or zero; the import fails.

## 2.6 Ports and network

The demo binds `127.0.0.1` only:

| Service | Port |
|---|---|
| Coordinator API | 8080 |
| party-a UI | 8081 |
| party-b UI | 8082 |
| party-c UI | 8083 |

There is **no TLS**. That is acceptable only for a single-host synthetic demonstration.
The multi-machine profile — HTTPS at the coordinator, an IT-approved private CA, pinned
certificates — is not implemented.

Each agent uses a distinct session cookie name (`protecmed_session_party_a`) because
cookies do not isolate applications by port.

Next: [Run the demo](03-run-the-demo.md).
