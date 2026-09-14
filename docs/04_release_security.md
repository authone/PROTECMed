# 4. Release protocol and security requirements

## 4.1 What the system does not hide

The coordinator sees the query, roster, timing, artifact sizes and eventually the approved aggregate. The design does not hide those metadata. Each provider knows its own records and its local count.

An exact two-provider total reveals the other provider's count to a recipient who knows one local count: `cB = total − cA`. In 3/3, two colluding providers can similarly infer the third count from the released total. This is mathematical output leakage, not a break of threshold encryption. Do not claim that local counts remain secret from every provider or from a coordinator colluding with enough informed recipients after release.

A fixed catalogue and fresh keys do not eliminate repeated-query differencing. Small-cohort suppression in the coordinator UI does not hide the number from the coordinator after fusion. The MVP therefore uses an explicit `exact-count-restricted-demo-v1` disclosure policy and a locally approved study-wide release ledger. Any formal differential privacy, encrypted suppression or protection against all inferred local counts is future work. On clinical data, IOCN must approve the recipient list and the specific small aggregate being released before the demo.

## 4.2 Immutable identities, plan and epoch

Provision the party identities locally. Each endpoint generates its own Ed25519 key; the coordinator must never generate all party identity private keys. Fingerprints are checked out of band by the operators before the roster is locked. A central registration page alone is not proof that independent institutions control the listed keys.

The signed `run_plan` binds `study_id`, fresh `run_id`, n, threshold=n, ordered roster, lead, identity-key fingerprints, each opaque snapshot token, query hash, mapping hash, profile ID, public row caps and exact recipient list. All parties accept this plan before key generation. Unknown or changed identity keys require a new enrollment and run.

The `epoch_manifest` binds the run-plan hash, context hash, final public-key hash and the ordered key-round transcript hash. All n parties sign the identical epoch-manifest hash. The coordinator makes all confirmations available to all providers. No input ciphertext is accepted before all epoch confirmations are present.

The coordinator's own Ed25519 identity signs its plans and evaluation requests. It is a separate orchestration identity, not an additional FHE share. These signatures provide message integrity and attribution to provisioned agents; they are not qualified electronic signatures or proof of medical consent.

## 4.3 Signed envelopes and canonical bytes

Each signed object uses this envelope:

```json
{
  "signer_id": "party-a",
  "purpose": "partial",
  "payload": {"...": "fields from the corresponding contract"},
  "signature_b64": "base64 of the Ed25519 signature"
}
```

Sign `b"PROTECMed/v2/" + canonical_bytes({signer_id, purpose, payload})`. The signature field is excluded. Verify against the signer pinned in the roster, not a key supplied by the message. Enforce the expected purpose at every endpoint; a valid submission signature is not a valid approval.

For v2 use the included **restricted canonical JSON profile**: ASCII strings and keys only, null/booleans/integers with absolute value at most 2^53−1, arrays and objects; object keys sorted, no insignificant whitespace and no floats. Reject duplicate keys while parsing raw request bytes. Human-readable Romanian labels are rendered locally and are not substituted for the signed query definition. Mapping files are hashed as exact release bytes. This restricted format is intentionally not advertised as a general RFC 8785 implementation; full Unicode/JCS support is a versioned extension [S16].

SHA-256 hashes are lowercase 64-character hex. Hash signed payloads where the contract says `*_sha256`; hash raw binary bytes for ciphertext artifacts. Arrays retain their defined order. Never hash a UI string, Python dictionary representation, client filename or a JSON object containing its own signature/hash field.

## 4.4 Input set and decryption request

An `encrypted_count` submission contains the run ID, epoch-manifest hash, party ID, query hash, snapshot token, raw ciphertext SHA-256 and size, final key tag and format ID. It contains no local count, admitted-row number or patient identifier. Authenticate and store exactly one contribution per roster party.

The input-set manifest lists each provider's signed submission payload hash and ciphertext hash in roster order. Its hash commits to the entire exact input set. The coordinator creates an immutable request binding the run, epoch, query, input-set hash, aggregate-ciphertext hash, recipient-list hash, required parties, lead, nonce and UTC expiry. There is one request per epoch. The readable query is rendered from the approved catalogue, not trusted as a free-text description from the coordinator.

Before the approval button becomes active, the party service must:

1. Verify the coordinator signature, schema, purpose, expiration and locally pinned run/epoch.
2. Verify the exact query and mapping hashes, fixed roster, lead and recipients against local records.
3. Download every signed input manifest and its ciphertext; verify signatures, hashes, sizes and epoch/query bindings, plus its own stored submission byte-for-byte.
4. Confirm one input per required party, no omissions/duplicates/extras and the exact ordered input-set hash.
5. Invoke local `verify-aggregate` on these inputs and the candidate result. Reject an individual site's ciphertext, a subset sum, substituted input, extra constant or re-randomized result.
6. Confirm the local key share belongs to this epoch, no prior partial was emitted, and the local study-wide disclosure ledger permits this query/snapshot/recipient combination.
7. Show the query, parties, recipients, verification status and the irreversible-release warning. Require an authenticated local operator action.

A signature over an opaque aggregate hash alone does not demonstrate that the approved operation was performed. Steps 3–5 close that gap for this simple deterministic addition circuit. They do not prove that a dishonest provider computed its count honestly.

## 4.5 Approval, partial and all-party gate

An approval creates a signed `partial` payload binding the exact request-payload hash, aggregate hash, epoch hash, party ID, role, decision `APPROVE`, UTC approval time and partial-binary hash/size. A signed rejection creates no partial. The identity signature covers both the approved request and the resulting partial artifact. FHE secret-share bytes are never part of the payload.

On the coordinator, fusion is permitted only if all of the following hold:

- the epoch was confirmed by the whole roster and has not been closed, rejected or put on integrity hold;
- the immutable request and input set still match the frozen run;
- the set of verified partial signers is **exactly** the expected roster, with one lead and n−1 mains;
- every partial has the same request hash, epoch hash and aggregate hash, with correct signer/party/role;
- every approval was created and accepted under the request policy; binary hashes and structural checks pass;
- no conflicting partial, rejection, change of recipient or query has been accepted;
- the operation is serialized under an exclusive run lock and no prior fusion receipt exists.

Only then call `MultipartyDecryptFusion`. Return a stored receipt for idempotent retries; do not re-fuse on every poll. API callers cannot bypass the gate by supplying `expected_parties=2` for a 3-party run. The trusted local run manifest, not a client argument, determines n.

## 4.6 Irreversibility, expiry and revocation

**Once a participant's partial has left that participant, it cannot be recalled cryptographically.** Once all required partials are available, a recipient possessing them can run fusion outside the application. An expiry timestamp, closed database state or deleted web page cannot make those bytes undecryptable.

The honest application enforces expiry before producing/uploading a partial and before completing its release transaction. It refuses new work after expiry. The UI must say that approving authorizes this disclosure and cannot revoke an already emitted contribution. A user who has not contributed can withhold or reject; a user who has already contributed cannot be promised retroactive revocation. Keep request lifetimes short but sufficient for the demo, and create a new epoch after an expired incomplete run.

Do not put all partial-decryption binaries into an ordinary evidence ZIP. Such a ZIP is a decryption-capable package, not harmless metadata. The default evidence export contains hashes, signed decisions and reviewed aggregate results. A restricted protocol-debug archive containing all partials requires explicit approval and must be labelled accordingly.

## 4.7 State machines and crash handling

A study persists the fixed policy/roster and disclosure history; each new analytical run has its own FHE epoch.

```text
DRAFT -> PLAN_ACCEPTED -> CONTEXT_READY -> KEYGEN
      -> EPOCH_CONFIRMED -> COLLECTING -> INPUTS_LOCKED
      -> EVALUATED -> APPROVAL_PENDING -> PARTIALS_IN_PROGRESS
      -> REVEALED -> CLOSED

Terminal alternatives: REJECTED, EXPIRED, ABORTED, INTEGRITY_HOLD
```

Local provider state includes `IMPORTED`, `PLAN_ACCEPTED`, `SHARE_CREATED`, `EPOCH_CONFIRMED`, `SUBMITTED`, `REQUEST_VERIFIED`, `PARTIAL_RESERVED`, `PARTIAL_COMMITTED`, `PARTIAL_SENT`, `CLOSED`. Saving a key-round result or encrypted submission must also be idempotent: a network retry resends it rather than generating a new secret share or input ciphertext.

A forged/unauthenticated request or bad upload is rejected without globally aborting a run. Otherwise any network user could trivially cause an integrity abort. Authenticated conflicting messages cause an integrity hold and operator review. Byte-identical retried messages return their existing receipt. Use unique database constraints on `(run_id, party_id, artifact_kind)` and on request IDs, plus transactional compare-and-set transitions.

A coordinator restart may resume from durable public/encrypted state. A party-container restart loses its ephemeral keys; unfinished runs must be aborted. Local study disclosure history survives a container restart and is not reset by creating a new epoch. Recovery must not reset query budgets or re-emit a partial under an old key.

## 4.8 Minimum application hardening

Use authenticated local sessions, exact Host/Origin checks, CSRF tokens for state-changing requests, HttpOnly cookies and SameSite=Strict. Use distinct cookie names for the different local agents: cookies do not isolate applications by port. Disable CORS, development debuggers, public API documentation and stack traces in the clinical validation profile. No state-changing GET requests.

Bind published local ports to `127.0.0.1`, with separate ports for A/B/C. Inside a container the service may listen on `0.0.0.0`; it is the host port mapping that must be loopback-only. Do not confuse a loopback bind inside the container with a working host-accessible UI. Providers poll the coordinator over authenticated HTTPS in multi-machine mode. Pin the private CA and agent identities; no `verify=False`.

Restrict subprocess arguments, filesystem paths, upload sizes, concurrent jobs and CPU/memory time. The worker takes counts via stdin or a protected descriptor, not a process-list-visible `--count` argument. Never log request bodies, decrypted local data, FHE secret material or raw exceptions containing cell values. Server-generated identifiers determine all storage paths.

Clinical files and keys must be outside the AI coding-agent workspace, Git root, Docker build context, cloud-sync folders and public CI. An AI “ignore” file is not an access-control boundary. Develop on synthetic fixtures and run clinical acceptance with an authorized human in a separate local environment.
