# `protecmed-worker` — isolated OpenFHE worker (M2)

The nine subcommands of blueprint §5.2. The worker performs pinned OpenFHE operations
and validates cryptographic inputs. It owns no policy: authentication, signatures,
immutable state, human approval and the all-party gate all live in the services.

**It must never be exposed over HTTP**, given network access, handed coordinator
credentials, or run against clinical data outside an authorized provider endpoint.

## Build

```bash
cmake -S cpp/fhe-core -B build/worker -DCMAKE_PREFIX_PATH="$PWD/.local/openfhe"
cmake --build build/worker --parallel 2
```

The CMake file aborts unless the pinned package reports OpenFHE 1.5.1 and native size 64.

## Subcommands

| Subcommand | Flags |
|---|---|
| `context-create` | `--parties 2\|3 --out` |
| `keygen-first` | `--context --secret-out --public-out` |
| `keygen-next` | `--context --incoming --secret-out --public-out` |
| `encrypt-count` | `--context --public --count-stdin --out` |
| `add-counts` | `--context --input ... --out [--expect-key-tag]` |
| `verify-aggregate` | `--context --input ... --candidate [--expect-key-tag]` |
| `partial-decrypt` | `--context --secret --ciphertext --role lead\|main --out` |
| `fuse` | `--context --parties 2\|3 --partial ...` |
| `inspect-public` | `--type context\|public-key\|ciphertext\|partial --artifact [--context]` |

Each flag is allowed only for the command that needs it: `--secret` on `add-counts`,
`verify-aggregate` or `fuse` is rejected as an invalid command, not ignored. The local
count arrives on stdin and never appears in argv, stdout or an error message.

## Exit codes (blueprint §5.3)

`0` ok · `10` invalid command/schema · `11` profile mismatch · `12` serialization
failure · `13` context/key/shape mismatch · `14` crypto failure · `15`
missing/duplicate/incorrect role · `16` input/output range · `17` aggregate mismatch ·
`20` filesystem failure · `21` timeout/resource limit.

stderr carries exactly one uppercase symbolic token. OpenFHE messages and filesystem
paths are never forwarded.

## What this worker does NOT do

- It does not hash artifacts or verify signatures — the services do (§5.6).
- It does not know which hospital holds a share. `--role` is a shape argument, not an
  identity, and the party count is a shape check, not proof that a roster approved
  anything.
- **A context object does not identify an epoch.** Two `context-create` runs with the
  same profile serialize byte-identically in this build, so a context hash pins the
  profile only. Epoch identity comes from the signed plan, artifact hashes and the joint
  public-key tag.
- **Fusion with the wrong shares can return a plausible in-range integer.** Measured
  during M2: substituting one party's share from a different key chain produced `1419`
  for a true sum of `11`, with no library error. `isValid` and the range check are not
  authorization. The application must guarantee the exact approved set of partials.

## One epoch per process

Each invocation is short-lived and handles one operation, so OpenFHE's global context and
key caches are never manipulated concurrently (§2.7). Private shares are written into an
owner-only directory the worker checks before writing; a group- or world-accessible
destination is refused.
