# `protecmed_protocol` — signed immutable protocol (M3)

The application layer that makes a release *unanimous*. OpenFHE performs the arithmetic;
everything that authenticates parties, freezes the computation and requires a human
decision lives here.

| Module | Responsibility |
|---|---|
| `canonical.py` | Restricted canonical JSON, hash recipes, UTC parsing |
| `identity.py` | Ed25519 identities, the pinned roster, signed envelopes |
| `contracts.py` | `contracts/*.schema.json` and the purpose-to-schema binding |
| `objects.py` | Payload builders and the semantic rules no schema can express |
| `state.py` | Run and local-party state machines |
| `store.py` | Immutable outbox and the study-wide disclosure ledger |
| `party.py` | The local provider gate: verify, approve, partial, reject |
| `coordinator.py` | Plan, key rounds, input set, request, all-party fusion gate |

## The two gates

**Local (`party.verify_request` + `party.approve`)** implements blueprint §4.4 steps 1–7:
coordinator signature and purpose, pinned run/epoch, unexpired request, exact query,
roster, lead and recipients, every signed submission and ciphertext verified including
this party's own bytes, exactly one input per required party in roster order matching the
input-set hash, a local `verify-aggregate` recomputation over exactly those inputs, the
local share bound to this epoch, no prior partial, and the disclosure ledger's consent.
Only then may an authenticated local operator action produce a partial.

**Coordinator (`coordinator.authorize_fusion`)** implements §4.5: full roster epoch
confirmation, no rejection, request and input set still matching the frozen run,
unexpired request, the set of partial signers **exactly** the roster with one lead and
n−1 mains, every partial bound to the same request/epoch/aggregate hash with the correct
signer and role, verified artifact hashes and sizes, an exclusive run lock and no prior
fusion receipt. `n` comes from the frozen run plan; `fuse()` takes no party-count
argument, so no API caller can lower it.

## What this closes from M2

M2 measured that a context does not identify an epoch and that fusion with a wrong share
can return a plausible in-range integer. Both are closed at this layer: the epoch
manifest binds the run-plan hash, context hash, final public-key hash and the ordered
key-round transcript, every submission and partial carries that epoch hash, and fusion is
unreachable without the exact set of signed partials for that exact request.

## What it still does not do

- It does not prove a provider counted honestly, or that a provider used its correct
  share. The baseline trusts providers for that (§1.5).
- Signatures give message integrity and attribution to provisioned agents. They are not
  qualified electronic signatures and not proof of medical consent (§4.2).
- **An emitted partial cannot be recalled.** Expiry, a closed state or a deleted page
  cannot make those bytes undecryptable (§4.6). A party that has not contributed can
  withhold or reject; a party that has contributed cannot be promised revocation.
- The disclosure ledger answers each (study, query, snapshot, recipients) combination
  once. That is a local policy under `exact-count-restricted-demo-v1`, not differential
  privacy and not a formal query budget.
- An exact two-provider total reveals the other provider's count to anyone who knows one
  of them (§4.1). Nothing here hides that.

## Canonical bytes

Sign `b"PROTECMed/v2/" + canonical_bytes({signer_id, purpose, payload})`. ASCII only,
sorted keys, no floats, integers within ±(2^53−1), duplicate keys rejected at parse time.
Deliberately not a general RFC 8785 implementation; full Unicode/JCS would be a versioned
extension.
