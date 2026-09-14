# 2. OpenFHE profile and cryptographic protocol

## 2.1 Version and upstream evidence

Use OpenFHE **v1.5.1**. Its release page was checked on 5 September 2026 and identifies it as the latest release, with short commit `1306d14`. The release includes fixes for multiparty BGV/BFV parameter sizing and BFV multiparty decryption [S1]. Resolve and store the full commit and recursive submodule commits during M0; do not invent a full hash from the short identifier. An upgrade requires an explicit review, new profile/version, regression tests and new keys.

The baseline follows the API sequence in the upstream BGV additive example, with an explicit party-count parameter and application-specific bounds added [S2–S5]. Code fragments and the C++ smoke source in this package have been checked against the published APIs, but have **not been compiled or executed here**. Their first acceptance gate is M0. This is not a claim that upstream OpenFHE is untested; it is a statement about this package's own verification status.

## 2.2 Parameter profile

| Parameter | Required baseline value |
|---|---|
| Scheme / encoding | BGVRNS / packed exact integers |
| Plaintext modulus | 65537 |
| Multiplicative depth | 0 |
| Party count | `SetThresholdNumOfParties(n)`, n = 2 or 3 |
| Security level | `HEStd_128_classic`; no forced small ring |
| Multiparty mode | `NOISE_FLOODING_MULTIPARTY` |
| Key switching / digit size | BV / 10; no evaluation keys generated |
| Scaling technique | `FLEXIBLEAUTOEXT`, explicitly pinned |
| Secret distribution | `UNIFORM_TERNARY`, explicitly pinned |
| Addition budget / key-switch budget | 5 / 0; actual baseline sum uses n−1 additions |
| Payload | `[local_count]`, with remaining slots zero-padded by encoding |
| Local admitted-record limit | 10,000 per provider |
| Maximum aggregate | 20,000 for 2/2; 30,000 for 3/3 |
| Decryption policy | One immutable aggregate per fresh FHE epoch |

The party-count setter sizes the joint-secret bound; it does **not** enforce the approval threshold. The defaults use one party, and the BGV parameter-generation source uses this field in its secret bound [S3–S5]. Do not omit it because the application roster already says three parties.

```cpp
CryptoContext<DCRTPoly> MakeCountContext(std::uint32_t n) {
    if (n != 2 && n != 3)
        throw std::invalid_argument("expected 2 or 3 parties");
    CCParams<CryptoContextBGVRNS> p;
    p.SetPlaintextModulus(65537);
    p.SetMultiplicativeDepth(0);
    p.SetThresholdNumOfParties(n);
    p.SetSecurityLevel(HEStd_128_classic);
    p.SetSecretKeyDist(UNIFORM_TERNARY);
    p.SetMultipartyMode(NOISE_FLOODING_MULTIPARTY);
    p.SetScalingTechnique(FLEXIBLEAUTOEXT);
    p.SetKeySwitchTechnique(BV);
    p.SetDigitSize(10);
    p.SetEvalAddCount(5);
    p.SetKeySwitchCount(0);
    auto cc = GenCryptoContext(p);
    cc->Enable(PKE);
    cc->Enable(KEYSWITCH);
    cc->Enable(LEVELEDSHE);
    cc->Enable(ADVANCEDSHE);
    cc->Enable(MULTIPARTY);
    return cc;
}
```

Use the upstream automatically generated ring and RNS moduli; record the ring dimension, modulus list, tower count and effective profile. BGV/BFV threshold noise flooding and CKKS decryption-noise configuration are different APIs. Do not copy `SetDecryptionNoiseMode` from a CKKS example into BGV, or claim that a CKKS query-budget setting automatically proves security for this profile [S6–S7]. A one-output epoch is an application safety rule, not a new proof or differential-privacy mechanism.

The worker checks the *deserialized* context against the locally compiled profile, not only the sidecar. At M0 record every available getter and test the checks. Some high-level generation settings may not survive serialization as independent fields; bind those through the signed plan, compiled profile and recorded effective parameters instead of inventing getters.

## 2.3 Integer correctness and overflow prevention

Each provider checks `0 <= local_count <= admitted_rows <= 10000` before encryption. The public caps guarantee `sum(local_count) <= n * 10000 <= 30000 < 65537/2` when providers follow the protocol. This prevents wraparound and ambiguity in centered integer decoding. The coordinator checks the final result against `n * 10000` as an additional sanity check.

Checking only the decrypted result is insufficient: an oversized sum can wrap modulo 65537 and look plausible. Checking each input against 30000 is also insufficient for three parties. The hard input-row cap is therefore part of the baseline, including its tests and benchmarks. Do not silently apply modulo reduction, clipping, signed-to-unsigned conversion or float rounding.

These are honest-provider input bounds, not cryptographic range proofs. A malicious provider can encrypt a false or out-of-range value. Detecting that requires a separate design; it is not established by a signed manifest.

## 2.4 Sequential distributed key generation

Freeze the ordered roster `party-a, party-b[, party-c]`. Publish the public context and its signed metadata. Each party verifies it before using it. Each round stores its newly generated secret share only in that provider's private tmpfs.

```cpp
// A: no previous public key.
auto kpA = cc->KeyGen();
// B: load A's authenticated public-key artifact, not A's secret.
auto kpB = cc->MultipartyKeyGen(pkA, false, false);
// C, only for 3/3: load the authenticated AB public-key artifact.
auto kpC = cc->MultipartyKeyGen(pkAB, false, false);
```

Check `kp.good()` after every call. In 2/2 the final encryption key is `pkAB`; in 3/3 it is `pkABC`. No data may be encrypted under an intermediate key. The `fresh=false` argument preserves accumulation into the preceding joint public key; do not switch it to true [S8].

The signed key-round record binds the run-plan hash, context hash, round index, party ID, incoming-public-key hash and outgoing-public-key hash. The first incoming hash is null. Providers verify the complete chain, including their own contribution. Every provider signs a final epoch confirmation covering the identical final key and transcript. Encryption waits for all confirmations.

**Key tags are not identities.** Intermediate key pairs may have different tags. Do not require each original private share's tag to equal the final public-key tag, and do not rewrite tags merely to silence a validation failure. Bind private shares to the epoch in the local key registry. Input ciphertexts must carry the final joint-public-key tag; verify context and public-key fingerprints independently. For partials, authenticate the party by its signed sidecar, not by interpreting an OpenFHE key tag as a hospital identity [S2, S8–S9].

## 2.5 Local encryption and deterministic aggregation

Encode an `int64_t` count with `MakePackedPlaintext(std::vector<int64_t>{count})`, then call `Encrypt(finalPublicKey, pt)`. Encryption randomness comes from OpenFHE. Never seed a deterministic generator for clinical data or expect two encryptions of the same count to have identical bytes.

Aggregate the authenticated input ciphertexts in roster order, always with a fresh result object:

```cpp
auto aggregate = cc->EvalAdd(ctA, ctB);
if (partyCount == 3)
    aggregate = cc->EvalAdd(aggregate, ctC);
```

No re-randomization, multiplication, rotation, modulus reduction, compression or additional encrypted zero is allowed in this profile. Reject ciphertexts with the wrong scheme, context, encoding, final key tag, element count or level/tower structure. Fresh baseline ciphertexts have two components; a partial has one. Do not feed a partial to `EvalAdd` as if it were an input count.

The worker provides `verify-aggregate`: load the same immutable inputs, perform the same ordered `EvalAdd` operations, and compare the resulting **cryptographic object** with the supplied aggregate. Check all components and their RNS parameters/values plus encoding, key tag, level, scale metadata and slot metadata. Serialization hashes bind transport bytes; they are not a substitute for verifying the computation. If serialization is proven deterministic in the pinned build, a canonical reserialization hash can be an additional check, not the only untested assumption.

## 2.6 Partial decryption and fusion

Immediately before partial decryption the local service must pass every check in Section 4, including human approval and aggregate recomputation. It invokes exactly one of:

```cpp
auto dA = cc->MultipartyDecryptLead({aggregate}, skA);
auto dB = cc->MultipartyDecryptMain({aggregate}, skB);
// Same Main call for C, if present.
```

Each returned vector must contain exactly one non-null ciphertext. The lead includes `c0`; the main contributions do not. Exactly one lead and n−1 main contributions are required; do not designate every provider as a lead [S7].

After the application verifies n distinct signed partial records for the exact request:

```cpp
Plaintext plaintext;
auto status = cc->MultipartyDecryptFusion(orderedPartials, &plaintext);
if (!status.isValid || !plaintext)
    throw std::runtime_error("fusion failed");
plaintext->SetLength(1);
const auto values = plaintext->GetPackedValue();
if (values.size() != 1 || values[0] < 0 ||
    values[0] > static_cast<int64_t>(partyCount) * 10000)
    throw std::runtime_error("invalid aggregate range");
```

The full policy gate precedes this code. `isValid` is a decoding check, **not** evidence that the roster participated or that shares are authentic. The upstream fusion routine takes a vector; it does not consult an institutional roster [S9–S10]. Missing-share tests must verify that the application never invokes fusion, not assume the library must throw or can never accidentally decode a plausible integer.

## 2.7 Serialization and worker isolation

Use `SerType::BINARY` and include `openfhe.h`, `cryptocontext-ser.h`, `ciphertext-ser.h`, `key/key-ser.h` and `scheme/bgvrns/bgvrns-ser.h`. Load the approved context before other objects [S11, S18]. Re-enable the required features after loading if necessary in the tested build. Use one short-lived process per operation and only one epoch per process; this avoids concurrent manipulation of OpenFHE's global context/key caches.

Hash raw incoming bytes before deserialization. Verify authenticated size and type, then deserialize in a resource-limited worker with no network, no coordinator credentials and access only to that operation's files. An authenticated binary object is not necessarily safe or mathematically well-formed. Enforce maximum bytes, timeout and memory limits; catch exceptions and return sanitized error codes.

Use server-generated paths, create-new semantics, no symlink following, restricted directories and atomic rename. Never clear library-global caches while another worker thread is evaluating. Persist public/encrypted artifacts by content hash. Treat the binary format as release-bound, and test amd64/arm64 exchange before claiming portability.

## 2.8 Secret lifetime and retry semantics

The MVP uses an **ephemeral local tmpfs directory**, not “memory inside a CLI process.” Separate CLI invocations need a common local place to retain the share. Mount `/run/protecmed-keys` as tmpfs with owner-only access in each party container; never mount it into the coordinator. A container/VM restart destroys these keys and invalidates unfinished epochs. A worker-process restart need not destroy the tmpfs. Disable core dumps; avoid swap where practical; document that tmpfs is not hardware-backed protection against the host owner.

Each epoch has exactly one request and one partial generation per provider. Atomically reserve the request before computation, write the resulting partial to an immutable local outbox, commit its hash and then upload. Retries resend the **same bytes**, not a newly randomized partial. If a crash leaves it uncertain whether a different partial was emitted, abort the epoch rather than generate another. A lost response is recovered by fetching the stored receipt, not by redoing the cryptographic operation.

Persistent FHE key storage, OS keystores, Argon2id envelopes and HSMs are optional later work, not dependencies of this baseline. No full secret may be constructed even for backup or recovery.
