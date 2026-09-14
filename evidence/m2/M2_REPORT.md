# Implementation task — M2 process-separated crypto

Ticket / milestone: **M2 — process-separated crypto** (blueprint §7.1)
Owner / human reviewer: programmer implemented; **cryptography-reviewer approval of key
handling, aggregate verification and share handling still required** (§7.4)
Specification sections: §2.2–§2.8, §5.2, §5.3, §5.6, §7.1
Allowed files: `cpp/fhe-core/`, `services/common/protecmed_worker/`,
`tests/integration/`, `evidence/m2/`, `verification/milestones.json`

## What was implemented
`cpp/fhe-core/` — the isolated OpenFHE worker `protecmed-worker`, all nine subcommands
of §5.2, plus `services/common/protecmed_worker/` — the safe invocation client used by
both services (argv array, `shell=False`, fixed binary, timeout, minimal environment,
`cwd=/`, stderr reduced to one symbolic token).

| File | Responsibility |
|---|---|
| `src/main.cpp` | Strict argv parsing, per-command flag allowlist, dispatch, sanitized failure |
| `src/profile.cpp` | Reviewed profile construction and verification of the deserialized context |
| `src/artifact_io.cpp` | Size-limited reads, no symlink following, create-new + atomic rename, private-directory check |
| `src/commands.cpp` | The nine subcommands and their input validation |

## Security and arithmetic invariants
- The worker checks the **deserialized** context against compiled values: scheme,
  plaintext modulus 65537, `HEStd_128_classic`, `UNIFORM_TERNARY`,
  `NOISE_FLOODING_MULTIPARTY`, `FLEXIBLEAUTOEXT`, `BV`, digit size 10, threshold party
  count in {2,3}, ring dimension >= 8192, and no evaluation keys present.
- Key generation uses only the **public-key** `MultipartyKeyGen(pk, false, false)`
  overload. `ShareKeys`, `RecoverSharedKey` and the private-key-vector overload appear
  nowhere in the source. No combined secret is ever constructed.
- `0 <= count <= 10000` is enforced before encryption; the count arrives on stdin, is
  never placed in argv, and is never echoed to stdout or into an error.
- Aggregation is an ordered `EvalAdd` into a fresh result object. No re-randomization,
  multiplication, rotation, compression or added encrypted zero.
- Inputs must be fresh two-component ciphertexts with `PACKED_ENCODING`, level 0, the
  same key tag, and no duplicates. A partial (one component) cannot be fed to
  `add-counts`, and a partial cannot be used as the ciphertext of `partial-decrypt`.
- `verify-aggregate` recomputes the sum and compares the **cryptographic object** —
  components and their RNS parameters/values, encoding, key tag, level, scale metadata,
  slot metadata — via OpenFHE's `CiphertextImpl::operator==`. It never decrypts.
- `fuse` requires exactly `n` distinct partials, `n` equal to the context threshold, and
  a result in `0..n*10000`.
- Private shares are written 0600 into a directory the worker first checks is owner-only
  and owned by the running user; a group- or world-accessible destination is refused.
- Outputs are never overwritten: `OUTPUT_EXISTS` before any create-new + atomic rename.
- Reads refuse symlinks and non-regular files and cap at 64 MiB.
- Each invocation is one short-lived process handling one operation, so OpenFHE's global
  caches are never manipulated concurrently.

## Exact commands
```bash
cmake -S cpp/fhe-core -B build/worker -DCMAKE_PREFIX_PATH="$PWD/.local/openfhe"
cmake --build build/worker --parallel 2
python -m unittest discover -s tests -v
```
The integration tests locate the binary at `build/worker/protecmed-worker` and the
libraries at `.local/openfhe/lib`, overridable with `PROTECMED_WORKER` and
`PROTECMED_OPENFHE_LIB`. If the binary is absent they **skip** — they never pass silently.

## Tests actually run
**180 passed, 0 failed, 0 skipped** — 57 reference + 91 M1 unit + **32 new M2
integration** tests, all against the real worker in separate processes with per-party
owner-only directories. Full output: `evidence/m2/unittest-full.txt`.

Positive: 2/2 exact sum 11 (5+6); 3/3 exact sum 11 (3+2+6); all-zero; upper bound
(2/2 → 20000, 3/3 → 30000); shares owner-only in separate directories; `inspect-public`
describes context, ciphertext and partial without decrypting.

Negative: wrong key epoch with a pinned tag; mixed key tags; input under an intermediate
key; substituted input; candidate that is not the sum; wrong input count; duplicate
input; partial used as an input; missing partial; duplicate partial; party-count
mismatch; unknown role; count above the cap; non-numeric counts (`-1`, `5.0`, empty,
`abc`, `0x10`); `--secret` on `add-counts`; `--input` on `fuse`; repeated flag;
positional argument; existing output; symlinked input; group-readable share directory;
garbage artifact.

## Findings recorded during M2 (each has a test)
1. **A context does not identify an epoch.** Two `context-create` runs with the same
   profile serialize **byte-identically** on this build, and the worker accepts either
   for artifacts made under the other. A context hash pins the profile, not the epoch.
   Epoch identity must come from the signed plan, artifact hashes and the joint
   public-key tag — M3 work. Test:
   `test_a_same_profile_context_is_deterministic_and_interchangeable`.
   The determinism is also the good news §2.5 anticipated: a canonical context hash is
   usable as an additional cross-party check. It must be re-measured on amd64.
2. **Fusion with the wrong share can return a plausible, in-range integer.** Substituting
   one party's share from a different key chain produced **1419** where the true sum was
   **11** — no exception, inside the `0..20000` range check. `isValid` and the range check
   are decoding and sanity checks, never authorization. Test:
   `test_a_share_from_another_key_epoch_does_not_release_the_true_sum`.
3. **A roster with no lead is not reliably rejected by the library.** Two `main` partials
   and no `lead` failed the range check in the observed run, but that is luck, not
   enforcement. Test: `test_a_roster_without_a_lead_does_not_reliably_fail`.

Findings 2 and 3 are exactly what §2.6 predicts. They are the concrete reason the M3
application gate cannot be skipped, and they are why the worker's party-count check is
documented as a shape check.

## Measured artifact sizes (§5.6 limit calibration)
`evidence/m2/artifact-sizes.txt`, identical for n=2 and n=3:
context 675 B · final public key 525 651 B · private share 263 043 B · input ciphertext
525 999 B · aggregate 525 999 B · partial 263 399 B. Largest artifact 0.50 MiB, so the
provisional 16 MiB streaming limit in §5.6 is comfortable on this profile.

## Tests NOT run and why
- **No benchmark.** Worker invocations complete in well under a second here, but no
  timing methodology (§8.3) was applied and no performance number is claimed.
- **No amd64 or mixed-architecture exchange.** Everything is `linux/arm64`. Binary
  serialization portability and the context-determinism finding are untested across
  architectures, so no interoperability claim is made.
- **No service, HTTP, browser, container or signed-envelope behaviour.** Those are M3
  and M4. In particular, nothing here demonstrates that a partial requires human
  approval — the worker will produce one for anyone who can run it with a share.
- No clinical data. All counts in these tests are invented.

## Deviations and decisions
1. **`services/common/` is a new directory** not named in the §5.1 layout. The worker
   client is needed by both the coordinator and the party agent, and duplicating an
   invocation-hardening routine in two services would be worse. Flagged for review.
2. **The worker computes no SHA-256.** No OpenSSL development headers are available in
   this environment, and hand-rolling a hash into the cryptographic worker is the wrong
   trade. §5.6 already assigns artifact hashing to the services, which use `hashlib`.
   The worker therefore has no `--expect-hash` flag; it has `--expect-key-tag` instead.
3. **`inspect-public` requires an explicit `--type`** rather than guessing by trial
   deserialization, which would mean parsing an artifact repeatedly as different types.
4. `--expect-key-tag` was added to `add-counts` and `verify-aggregate` beyond the §5.2
   table so the service can pin the joint public-key tag from the signed epoch manifest.
   It is optional; omitting it still requires all inputs to agree on one tag.

## Evidence paths
- `evidence/m2/unittest-full.txt` — full verbose run, 180 tests
- `evidence/m2/artifact-sizes.txt` — measured serialized sizes
- `evidence/m2/M2_REPORT.md` — this report
- `cpp/fhe-core/README.md` — subcommand contract, exit codes and stated limitations

## Status
**PASSED (programmer evidence complete; cryptography-reviewer approval outstanding).**
Gate M2 is closed for implementation purposes on `linux/arm64`. M4 must not be accepted
until M3 also works against this real worker.

## Stop conditions / unresolved questions
- The three findings above are application obligations, not worker bugs. M3 must bind
  every artifact to a signed epoch and must never call `fuse` without the exact approved
  set of partials.
- Same-host separate directories are a **simulation** of institutional separation. One
  host administrator can read every party directory used by these tests.
