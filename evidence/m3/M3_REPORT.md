# Implementation task — M3 signed immutable protocol

Ticket / milestone: **M3 — signed immutable protocol** (blueprint §7.1)
Owner / human reviewer: programmer implemented; **cryptography-reviewer approval of the
approval gate and aggregate verification still required** (§7.4)
Specification sections: §4.1–§4.8, §5.6, §7.1
Allowed files: `services/common/protecmed_protocol/`, `tests/unit/test_protocol_*.py`,
`tests/integration/test_protocol_flows.py`, `tests/integration/protocol_harness.py`,
`evidence/m3/`, `verification/milestones.json`, plus one corrective change in
`services/party-agent/protecmed_party/snapshot.py` (below)

## What was implemented
`services/common/protecmed_protocol/` — nine modules: canonical bytes, Ed25519 identities
and envelopes, contract validation, payload objects, state machines, immutable outbox and
disclosure ledger, the local provider gate and the coordinator fusion gate. See
`services/common/protecmed_protocol/README.md` for the module table.

Unlike the reference helper, this is not a narrow structural guard: it is the full §4.4
and §4.5 flow, driven end-to-end against the **real** M2 worker.

## Security invariants
- Every signature is verified against the key **pinned in the roster**, never a key
  supplied by the message. Envelope purpose is enforced at every endpoint: a valid
  submission signature is not a valid approval, and re-labelling an envelope breaks the
  signature.
- Identity fingerprints are SHA-256 over the raw 32-byte public key, not a PEM text form.
  A changed identity key fails pinning rather than being silently accepted.
- Canonical bytes are ASCII-only, sorted-key, float-free, with integers bounded by
  ±(2^53−1), depth-limited and duplicate-key-rejecting at parse time.
- The run plan binds threshold == party_count == len(roster), unique parties, snapshots
  and identities, and lead == first roster entry. The epoch manifest binds the run-plan
  hash, context hash, final public-key hash and the ordered key-round transcript hash.
- Each party verifies the whole key-round chain including its own contribution; the chain
  must link (`incoming[i] == outgoing[i-1]`), start with a null incoming hash and follow
  roster order. Key tags are not treated as identities.
- Submissions carry no local count, admitted-row number or patient identifier.
- The local gate refuses to produce a partial unless all of §4.4 steps 1–6 pass **and**
  `operator_approved is True`. A truthy non-boolean (`1`, `"yes"`, `[1]`) does not count.
- `fuse()` has no party-count parameter. `n` comes from the frozen plan.
- The outbox is reserve → compute → commit → send. A retry resends the same bytes; a
  reservation with no commit aborts the epoch rather than emitting a second partial.
- Authenticated conflicting messages raise an integrity hold; forged messages are
  rejected at signature verification, so a network user cannot trivially abort a run.

## Tests actually run
**274 passed, 0 failed, 0 skipped** — `python -m unittest discover -s tests -v`
(57 reference + 151 unit + 66 integration). Full output: `evidence/m3/unittest-full.txt`.
M3 adds 60 unit tests and 34 end-to-end tests.

M3 integration tests run the **real worker**, not a fake. §7.1 permits a fake worker for
state-machine unit tests provided they are labelled; that allowance was not needed.

### The central negative evidence: no fusion call
Six tests assert the coordinator's `fuse` subcommand was invoked **zero** times:
2-of-3 approvals, a rejection present, an operator who declines, a forged request
signature, a substituted aggregate, and an expired request holding every partial. Two
further tests assert `partial-decrypt` was never invoked when the operator declined or
the request had expired. These check what the application did, not what the library
might have done.

### Positive
2/2 and 3/3 full releases (both exact sum 11); correct role split — the coordinator never
runs `keygen-*` or `partial-decrypt` and each party runs `verify-aggregate` **before**
`partial-decrypt`, never `fuse`; local states advance to `PARTIAL_SENT`.

### Negative
Unsigned and party-signed requests; unpinned signer; purpose replay; reordered input set;
input set not matching the request; changed query hash, recipient list or epoch hash;
substituted aggregate; **subset sum** (hash consistent but not the sum of the exact input
set — caught by local recomputation, worker exit 17); submission from outside the roster;
conflicting submission → integrity hold; byte-identical retry is a no-op; inputs locked
before every party submits; ciphertext offered before every epoch confirmation; expired
request; re-verification after a partial exists; second release of the same combination.

## Findings and design notes
1. **Re-verification after a partial exists is refused** (`PARTIAL_ALREADY_EMITTED`),
   because §4.4 step 6 requires that no prior partial was emitted. That makes
   re-verification the wrong recovery path for a lost upload, so `stored_partial()` was
   added: it returns the stored bytes from the outbox without any cryptographic
   operation, which is exactly what §2.8 prescribes.
2. **The M1 snapshot token format did not satisfy the `run-plan` contract.** The token
   was 32 hex characters, but the contract pattern is `^[a-z][a-z0-9-]{0,63}$` and hex can
   begin with a digit. Tokens are now `snap-` plus 28 hex characters (112 bits of
   randomness), which matches the contract. Caught by building M3 on top of M1 rather
   than by inspection.
3. **The gate proves the right parties approved, not that they computed honestly.** A
   provider that deliberately used the wrong share would still pass every check here and
   produce a partial that fuses to a wrong number. That is inside the stated
   honest-provider trust model (§1.5), not a defect of this layer.

## Tests NOT run and why
- No HTTP, browser, CSRF, session, cookie or TLS behaviour — that is §4.8 and M4. This
  layer has no network code at all; the transport is simulated by passing envelopes
  between objects in one process.
- No SQLite persistence or durable transaction. The coordinator holds run state in memory
  plus a file-backed outbox for the fusion receipt; §5.6's database and unique-constraint
  work is M4.
- No crash-recovery test that actually kills a process. The uncertain-emission path is
  tested by constructing the reservation-without-commit state directly.
- No benchmark, no Docker, no Windows/macOS, no clinical data.
- Multi-machine transport, expiry under clock skew between hosts, and operator UI flows
  are M4/M6.

## Deviations
1. The protocol package lives in `services/common/`, the same directory flagged in M2 and
   still not named in the §5.1 layout. Both services need it.
2. `LocalParty.approve` takes `operator_approved: bool` rather than owning a UI. The
   authenticated local session and CSRF-protected form that supply it are M4 (§4.8); this
   layer refuses to proceed without an explicit `True`.
3. `stored_partial()` is an addition beyond the §4.4/§4.5 text, justified by §2.8's
   "fetch the stored receipt, do not redo the cryptographic operation".

## Evidence paths
- `evidence/m3/unittest-full.txt` — full verbose run, 274 tests
- `evidence/m3/M3_REPORT.md` — this report
- `services/common/protecmed_protocol/README.md` — gate contents and stated limits

## Status
**PASSED (programmer evidence complete; cryptography-reviewer approval outstanding).**
M0–M3 are now closed for implementation purposes on `linux/arm64`, which is the point the
blueprint sets before any web interface work begins (§1.6, §7.1).

## Stop conditions / unresolved questions
- §4.6 irreversibility must be stated in the M4 UI: approving authorizes this disclosure
  and cannot revoke an already emitted contribution.
- The default evidence export must not contain the full set of partial binaries — that
  bundle is decryption-capable (§4.6). No such export exists yet.
- The disclosure policy implemented here (one release per study/query/snapshot/recipient
  combination) is a reviewable choice, not a blueprint constant. It needs IOCN and
  cryptography-reviewer sign-off before clinical use.
