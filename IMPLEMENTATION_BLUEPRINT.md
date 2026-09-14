---
title: "PROTECMed"
subtitle: "OpenFHE cohort-count prototype
Developer implementation blueprint"
date: "Version 2.0 · 5 September 2026"
lang: en-GB
---

**Architecture · cryptographic protocol · data contract · implementation gates**

A count-only prototype for two or three data providers. Local cohort filtering, exact BGV aggregation and unanimous 2/2 or 3/3 decryption. A simple browser interface on provider-controlled Windows/macOS endpoints.

**Delivery status:** a development specification plus reference helpers. 57 synthetic/reference Python tests passed; the six IOCN plaintext queries were independently rechecked. The C++ source has not been compiled here, and no completed web service, Docker image or installer is included.

The clinical regression appendix contains restricted aggregate information, not patient rows. Do not publish it automatically. See the execution ledger in `verification/verification.json`.

# Contents and starting point

[1. Product, scope and architecture](#sec1)

[2. OpenFHE profile and cryptographic protocol](#sec2)

[3. IOCN adapter, queries and test data](#sec3)

[4. Release protocol and security requirements](#sec4)

[5. Repository, CLI and API contracts](#sec5)

[6. Build, installation and operator deployment](#sec6)

[7. Implementation plan and acceptance gates](#sec7)

[8. Test plan, measurements and TRL evidence](#sec8)

[9. Instructions for AI-assisted development](#sec9)

[10. Extension points without scope creep](#sec10)

[11. Sources, provenance and verification boundaries](#sec11)

[Appendix A. Changes from v1](#changes)

**First session:** read Sections 1–4 and `AGENTS.md`; run the Python reference tests; then complete M0, the real OpenFHE build gate. Do not implement a web interface around an unverified cryptographic core.

**Using this package:** the assembled Markdown and this Word document contain the same technical chapters. The `docs/` directory splits them for focused coding-agent tasks. Companion JSON, C++, Python and templates are in the ZIP. “Required” means an implementation obligation, not an assertion that the feature already exists.

# 1. Product, scope and architecture {#sec1}

## 1.1 PROTECMed in one paragraph

PROTECMed is a platform for privacy-preserving collaboration on medical research data. Its original proposal combines an analytics SDK, a web platform and an interactive release process requiring the data providers' participation [P1]. This prototype implements a deliberately smaller slice: two or three providers count records matching the same approved cohort definition locally, encrypt their respective counts under one jointly generated public key, and let a coordinator add those ciphertexts. The exact aggregate is released only after every provider approves the particular computation and produces its own partial decryption. No Kaplan–Meier, regression or machine learning is included.

**The deliverable is a development specification and reference kit, not a finished or certified clinical system.** The verification ledger distinguishes checks executed during this revision from tests that the programmer must still run. No OpenFHE runtime, Docker image, Windows installation or macOS installation was executed during preparation of this revision.

## 1.2 The MVP contract

The baseline is `cohort-count-local-v2` on profile `bgv-count-nofn-v2`. It performs the predicate in plaintext inside the provider, not at the coordinator. Only one exact integer per provider is encrypted. It demonstrates federated filtering, homomorphic aggregation and unanimous decryption; it does not demonstrate general encrypted database search or fully encrypted patient-level analytics.

| Mandatory | Explicitly deferred |
|---|---|
| 2/2 and 3/3, fixed roster per run | 2/3, dropout recovery, dynamic membership |
| Exact integer counts, BGV, `EvalAdd` | CKKS, multiplication, rotations, bootstrapping |
| One query and one aggregate per fresh key epoch | Repeated decryption oracle under long-lived FHE keys |
| Local XLSX/strict canonical CSV import | EHR, FHIR/OMOP, hospital SSO, native installers |
| Signed artifacts; each provider verifies the aggregate | Proofs that a provider's input is truthful; malicious-secure DKG |
| Minimal local and coordinator browser pages | SPA, dashboards, arbitrary SQL, plug-ins uploaded by users |
| Synthetic tests; restricted IOCN acceptance | Public release of clinical fixtures or query results |

No implementation may silently replace this contract with a centrally generated secret key. `ShareKeys`, `RecoverSharedKey`, the `MultipartyKeyGen(vector<PrivateKey>)` debugging overload and any reconstruction of the complete secret are forbidden in the integrated prototype.

## 1.3 Architecture and trust boundaries

![PROTECMed v2 architecture](assets/architecture.png)

The coordinator is not a data provider and receives no FHE secret share. Party A is the *algorithmic lead* solely because one partial must include the first ciphertext component. A has no additional approval rights. Each provider has one vote and one indispensable secret share.

| Component | Responsibilities | Must not receive or export |
|---|---|---|
| Local party service | Import; validation; approved filtering; local count; human approval; signed protocol messages | No upload of patient rows, local count, local file hash or FHE secret share |
| Local C++ worker | Pinned OpenFHE operations; binary serialization; aggregate recomputation | No network access; no arbitrary cipher operations exposed to users |
| Coordinator service | Freeze run plan; relay public key rounds; verify submissions; add ciphertexts; collect signed partials; fuse approved result | No XLSX/CSV data endpoint; no party data/key mounts |
| Browser | Local provider UI or coordinator status/result UI | No OpenFHE keys or patient tables stored in JavaScript/browser storage |
| Local audit store | State, approvals, immutable outbox and public artifact hashes | No patient rows or counts in central logs |

Party traffic is outbound to the coordinator. The coordinator never calls a network-facing provider decryption API. Providers poll for work, download immutable public/encrypted artifacts and upload signed responses. A poll can announce a request but cannot approve it. The provider's browser calls only its own loopback service.

## 1.4 Data flow

1. A local operator selects a workbook from a preconfigured read-only directory, validates the five-column projection and accepts any cached-formula policy. The agent assigns an opaque local `snapshot_token`; the actual source hash and mapping report stay local.
2. The coordinator prepares a run plan containing the fixed roster, threshold, query hash, mapping hash, snapshot tokens, profile, recipient list and output policy. Every provider checks the same plan and independently pinned identity fingerprints.
3. The coordinator generates the public context; A, B and optionally C extend the public-key chain sequentially. Each creates a private share locally. All providers confirm the identical final epoch manifest before anyone encrypts.
4. Each provider evaluates the frozen query on its frozen local snapshot and submits exactly one signed encrypted count.
5. The coordinator verifies all submissions and computes a deterministic ordered sum. It publishes the exact inputs, their signed manifests and the aggregate in a decryption request.
6. Each provider verifies the signatures, roster and inputs; recomputes the same sum locally; and verifies equality with the requested aggregate. The local operator then chooses Approve or Reject.
7. An approval generates one partial decryption, saves it in a local immutable outbox and uploads the same bytes on retries. The coordinator fuses only after the exact set of n signed, distinct, matching partials is present.
8. The authorized aggregate and an audit receipt are shown to the named recipients. The epoch is closed. A new query requires a new run and new FHE shares.

## 1.5 What “local” and “unanimous” mean

Local means the provider-controlled execution environment, not merely another Docker container under the coordinator's administrator. Three containers on one laptop are useful for a reproducible simulation, but the host administrator can inspect all three. Separate machines and operators are required to demonstrate institutional separation. Container isolation does not defeat a privileged host administrator [S15].

Unanimity is a combination of distributed keys and local policy checks. OpenFHE does not know which hospital signed an approval. The application authenticates parties and verifies the expected roster; the library performs the arithmetic. A missing participant blocks an authorized release. A lost key share requires a fresh epoch, not an administrator bypass.

The baseline trusts providers to run honest key generation and local counting, and trusts their own endpoints and operators. It protects against a curious coordinator under this model and adds concrete integrity checks against accidental or substituted artifacts. It does **not** establish a malicious-secure multiparty protocol.

## 1.6 Reading and implementation order

Read Sections 1–4 before writing application code. Implement milestones M0–M3 before the web UI. Sections 5–7 define the CLI, APIs and deployment contract; Section 8 defines acceptance tests and evidence. Section 9 is the AI-agent workflow. Section 10 is optional extension guidance and must not delay the MVP.

`IMPLEMENTATION_BLUEPRINT.md` is the assembled normative text. The numbered files under `docs/` are the same text split for focused agent tasks. `config/` and `contracts/` provide machine-readable companion artifacts. A disagreement between these files is a release-blocking defect, not permission for an AI agent to choose a convenient interpretation.


# 2. OpenFHE profile and cryptographic protocol {#sec2}

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


# 3. IOCN adapter, queries and test data {#sec3}

## 3.1 Source inspection and limits of the inspection

The attached workbook `Date - craniospinal irradiation - salvarea ultima 4 decembrie.xlsx` was re-inspected for this revision [P3]. Its main sheet is `Date - craniospinal irradiation`, range A1:MG52: one header row, 51 data rows and 345 columns. `Sheet2` is empty. The five required headers are unique after trimming. These are observations about this file, not assumptions to impose on every future export.

| Canonical field | Exact source header | Column in this sample | Canonical type |
|---|---|---|---|
| `diagnosis` | `Diagnostic` | I | enum or null |
| `rt_technique` | `Tehnica RT2` | Q | enum or null |
| `toxicity_wbc_ge2` | `Toxicity >=2 WBC` | LY | boolean or null |
| `age_at_rt` | `Varsta radioterapie ` (trailing space) | H | integer 0–120 or null |
| `surgery_type` | `Tip chirurgie` | M | enum or null |

Locate columns by normalized header, not hardcoded Excel letters. Letters above are for inspection and regression only. Match Unicode-normalized, trimmed headers; reject ambiguous required matches. Never infer the closest similarly named column. A mapping version change changes its hash and requires a new run.

No patient identifiers or patient-level rows are included in this package. Aggregate regression values are still restricted research information: do not automatically publish the clinical appendix, logs or reports to a public repository.

## 3.2 Important correction: WBC flags are formula cells

All **51 cells in the selected WBC toxicity column contain formulas** in the supplied workbook. The other four selected columns contain no formulas in this sample. The observed Yes/No values are saved formula results, not necessarily literal cell values. A library such as openpyxl can return those saved results with `data_only=True`; that option does not recalculate formulas or prove freshness [S12].

The production adapter must have two explicit modes:

- `literal-only`: default for new imports. Reject formulas in selected clinical cells. A values-only export prepared and verified locally by IOCN is acceptable.
- `reviewed-cached-values`: permit formula cells only after the local operator confirms that IOCN has recalculated/reviewed and saved the workbook. Require a non-error, nonempty cached result for every selected formula cell. Record the acknowledgement, local source hash and formula count locally. Show a warning that cache freshness cannot be established from the workbook alone.

For the supplied workbook, the second mode is needed to reproduce the recorded Q004 baseline unless IOCN provides a values-only copy. Do not treat a missing cache as null, false, zero or a reason to quietly exclude the row. Fail the import with `FORMULA_CACHE_MISSING`. The supplied workbook also has one external-link part. Its presence is not a request to refresh it: use only the reviewed cached cells and never follow external targets. Do not evaluate Excel formulas using `eval`, enable macros, refresh external links, or expand the clinical allowlist to recalculate toxicity from laboratory measurements. That would change the approved data processing.

Open the workbook read-only. A normal implementation may use two openpyxl views (`data_only=False` for formula detection and `data_only=True` for saved values), selecting only required columns for the canonical table. The parser may internally load shared strings or XML for the local file; the truthful boundary is that disallowed values are never materialized into the canonical table, emitted, logged or uploaded. Do not promise that the XLSX parser never touches their bytes.

The included `reference/python/iocn_audit.py` is a narrow offline OOXML inspection/reference utility for this sample-shaped XLSX. It is not the production web-upload parser. It calculates only aggregate counts and formula statistics and emits no patient rows. Its restricted format and size checks are documented in its module header.

## 3.3 Normalization and row semantics

Use a positive allowlist. Never create a full patient DataFrame and then delete a few identifier columns. Do not copy names, NIDs, dates, notes or free text into canonical rows or fixtures. Restrict XLSX to the approved sheet and reject encrypted workbooks, macros and external-link workflows. Validate actual file structure and resource limits, not only the filename extension.

Normalize clinical strings by trimming and uppercasing. Missing tokens are empty cells, empty strings, `NA`, `N/A` and `NULL`, case-insensitive. For diagnosis, allow `MBL`, `PNET`, `GLIOMA`, `HAEMA`, `ICGCT`, `PINEAL TUMOR`, `EPD`; for radiotherapy, `3DCRT`, `IMRT`; for surgery, `GTR`, `STR`, `INOP`, `BIOPSIE`. Unknown nonmissing tokens cause a local validation error, not a guessed category.

Boolean normalization accepts actual booleans, numeric 0/1, or exact strings `YES/DA/TRUE/1` and `NO/NU/FALSE/0`. Never use `bool(cell)` on a string: `bool("NO")` is true in Python. Reject numeric values other than 0/1 and distinguish missing from false. Age accepts integer-valued numeric cells or decimal integer strings within 0–120; reject fractions and do not truncate. In query JSON, require an actual integer for age and an actual boolean for toxicity; Python's `bool` subtype must not accidentally pass an integer validator.

Freeze the validated canonical snapshot locally before accepting a run plan. Keep its local source/version digest and mapping version in the party registry. Re-importing a changed source creates a new snapshot token and invalidates unfinished runs that depended on the old selection; it must not silently alter an already-submitted count. Only opaque tokens leave the provider.

A record is *admitted* when at least one of the five raw selected fields is nonblank. A record containing `NA` is still a record; its missing fields affect only queries that use those fields. Skip rows whose five selected raw cells are all blank, and show their number locally. Retain admitted-row order. Assign an internal zero-based admitted-row index only in memory/local metadata; it is not an identity or a deduplication mechanism.

Q001 counts admitted records. Calling these unique patients requires IOCN's explicit confirmation that one row corresponds to one patient and there are no duplicate patients locally or across institutions. This prototype does not implement private record linkage or cross-site deduplication. Without that confirmation, label the result “matching records”, not “unique patients”.

For each query, a row missing any field required by that query is excluded; fields not used by the query do not affect eligibility. A local validation report shows admitted rows, skipped blank rows, missing/invalid values per field, and eligible/excluded rows per query. These diagnostics and local counts are not sent to the coordinator.

## 3.4 Fixed query catalogue

The catalogue is immutable within a release. Its canonical JSON is in `config/query-catalog.json`. The engine supports a bounded AND-list of typed predicates, but the MVP UI offers only these six catalogue entries. Matching a JSON schema alone is insufficient: the query must exactly match its allowlisted catalogue entry and hash.

| ID | Query | IOCN total | IOCN 2-provider split | IOCN 3-provider split |
|---|---|---:|---|---|
| Q001 | All admitted records | 51 | 26 + 25 | 17 + 17 + 17 |
| Q002 | Diagnosis = MBL | 29 | 14 + 15 | 8 + 11 + 10 |
| Q003 | MBL AND IMRT | 13 | 6 + 7 | 3 + 4 + 6 |
| Q004 | MBL AND IMRT AND WBC toxicity >=2 = true | 11 | 5 + 6 | 3 + 2 + 6 |
| Q005 | Age at radiotherapy <12 AND MBL | 21 | 8 + 13 | 5 + 7 + 9 |
| Q006 | Surgery = GTR AND IMRT | 9 | 4 + 5 | 3 + 3 + 3 |

These values were recalculated in this revision and agree with v1. They are plaintext import/query regression values, **not OpenFHE benchmark results**. They depend on this workbook and its saved formula results. A changed export, row order or clinical correction may change the expected totals or shard values; do not adjust code to force the number 11.

The primary restricted acceptance query is Q004. Its literal clinical meaning is the stored toxicity flag, not a new medical interpretation of raw WBC measurements.

```json
{
  "schema_version": "2.0",
  "query_id": "Q004",
  "query_version": 1,
  "logic": "AND",
  "filters": [
    {"field": "diagnosis", "operator": "eq", "value": "MBL"},
    {"field": "rt_technique", "operator": "eq", "value": "IMRT"},
    {"field": "toxicity_wbc_ge2", "operator": "eq", "value": true}
  ],
  "missing_value_policy": "exclude_required_missing"
}
```

Use explicit typed comparisons; no SQL text, Python expressions, regex predicates, `eval`, `exec` or `pandas.query`. Empty filters are allowed only for Q001. Unknown IDs, fields, operators, values, extra keys, excessive nesting or more than five filters fail before any patient data is evaluated.

## 3.5 Demo splitting and independent synthetic fixtures

The local splitter first creates the validated canonical projection, then assigns admitted row index j to provider `j % n`. It outputs only the five canonical fields, in fixed order. There is no need to include an ID column in transmitted shards. Retain the original order within each shard. Prove disjointness and coverage by local index checks before writing files; do not report those indices centrally.

Split only on an authorized local machine, never at the coordinator. In a real deployment, institutions already possess their own distinct datasets; the artificial split must be labelled a simulation. Do not give the full workbook to each party and rely on a runtime modulo filter to simulate separate ownership.

The package includes a **fully synthetic** 24-row CSV generated independently of patient rows, with its own expected counts in `fixtures/synthetic_expected.json`. It intentionally has different totals from the IOCN file. CI uses this fixture only. Local IOCN acceptance uses `config/iocn_expected_counts.json` and the original private workbook. Never copy clinical rows into tests or an AI prompt to fix a failed test.

## 3.6 Formula-cache and import acceptance tests

Required tests include a formula with a valid saved result, a formula with no cache, an Excel error result, a changed formula-cache acknowledgement, extra source columns, missing/duplicate required headers, lower/upper case, blanks, `NA`, string `NO`, boolean `false`, invalid age 11.5, a wholly blank selected row and a row whose selected values are all explicit missing tokens. The implementation must fail closed where specified and preserve the stated record semantics.

The local source file and canonical snapshot are frozen for a run. An operator changing the file after encryption does not change the frozen contribution. Any intended data correction, query change or mapping change starts a fresh run. The source file SHA-256 stays local; the coordinator receives an opaque snapshot token, not a content hash of clinical data.


# 4. Release protocol and security requirements {#sec4}

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


# 5. Repository, CLI and API contracts {#sec5}

## 5.1 Repository layout

The ZIP is a specification/reference kit. Directories `services/`, `cpp/fhe-core/` and production deployment scripts below describe the **repository to implement**, not software already present in this delivery.

```text
protecmed/
  README.md, AGENTS.md, SECURITY.md
  docs/                         # versioned normative specification
  config/                       # profiles, mappings, query catalogue
  contracts/                    # JSON schemas plus semantic validators
  cpp/fhe-core/                 # isolated OpenFHE CLI to implement
  services/coordinator/         # FastAPI, SQLite, server-rendered pages
  services/party-agent/         # local import, consent, outbox, polling
  reference/                    # small examples, never an auth bypass
  tests/{unit,integration,e2e}/
  fixtures/                     # synthetic only
  deployment/                   # images, Compose, scripts to implement
  evidence/                     # sanitized release artifacts
```

The supplied package already contains `config/`, `contracts/`, synthetic fixtures, Python reference helpers, C++ smoke source, build template, task cards and test/evidence templates. `verification/verification.json` is the exact execution ledger. A template or compile command is not evidence that the corresponding software exists or passed.

## 5.2 C++ worker commands to implement

The service owns policy, authentication, signatures, immutable state and authorization. The worker validates cryptographic inputs and performs only these subcommands. It must never be exposed directly over HTTP.

| Subcommand | Inputs | Output and preconditions |
|---|---|---|
| `context-create` | Reviewed profile; trusted n | Context binary; effective-parameter JSON; n in {2,3} |
| `keygen-first` | Context; local epoch slot | Private share in local tmpfs; first public key |
| `keygen-next` | Context; verified preceding public key | New local share; extended public key; fresh=false |
| `encrypt-count` | Context; final key; count on stdin | Ciphertext; enforce 0..10000 |
| `add-counts` | Context; ordered n verified inputs | Deterministic sum; no secret files |
| `verify-aggregate` | Same ordered inputs; candidate result | Equal/not equal; no decryption |
| `partial-decrypt` | Context; local share; verified result; trusted role | One partial after local authorization gate |
| `fuse` | Context; ordered approved partials; trusted run n | Aggregate JSON after coordinator gate |
| `inspect-public` | Approved context/key/ciphertext artifact | Sanitized type, effective parameters, tag, dimensions |

Specify input/output paths through a per-job directory generated by the service. Counts and secret bytes never appear in shell arguments. Pass an argv array with `shell=False`, a fixed worker binary, timeout and minimal environment. Check exit code and output schema. Do not forward the worker's stderr verbatim to the browser.

The worker's `--parties` argument is supplied by the authenticated service's stored plan. A developer can of course run a local binary outside policy; neither argv flags nor an API wrapper constitute tamper-proof cryptographic enforcement.

## 5.3 Example target CLI workflow

**These are the target commands to implement in M2, not commands supplied by the Python helper kit.** Paths `A`, `B` and `C` below represent separate machines/private namespaces. In the same-host synthetic test they may be separate directories, explicitly labelled as a simulation.

```text
Coordinator: context-create --parties 3 --out public/context.bin
A: keygen-first --context context.bin --secret-out private/share.bin
   --public-out public/pk-a.bin
B: keygen-next --context context.bin --incoming public/pk-a.bin
   --secret-out private/share.bin --public-out public/pk-ab.bin
C: keygen-next --context context.bin --incoming public/pk-ab.bin
   --secret-out private/share.bin --public-out public/pk-abc.bin

Each party, after epoch confirmation:
  encrypt-count --context context.bin --public pk-abc.bin
  --count-stdin --out public/input.bin

Coordinator:
  add-counts --context context.bin --input a.bin --input b.bin
  --input c.bin --out aggregate.bin

Each party before the local human approval:
  verify-aggregate --context context.bin --input a.bin
  --input b.bin --input c.bin --candidate aggregate.bin

Each party after approval:
  partial-decrypt --context context.bin --secret private/share.bin
  --ciphertext aggregate.bin --role lead-or-main --out partial.bin

Coordinator after verifying all signed records:
  fuse --context context.bin --parties 3 --partial da.bin
  --partial db.bin --partial dc.bin
```

`lead-or-main` is explanatory, not a literal accepted role. The service sets `lead` for A and `main` for B/C. An `encrypt-count` unit test can use shell input with synthetic integers; integration must pass the local result through a protected pipe and never log it.

Suggested exit-code registry: 10 invalid command/schema; 11 profile mismatch; 12 serialization failure; 13 context/key/shape mismatch; 14 crypto failure; 15 missing/duplicate/incorrect role; 16 input/output range; 17 aggregate mismatch; 20 filesystem failure; 21 timeout/resource limit. The reference smoke program is separate and uses ordinary success/failure exit codes.

## 5.4 Coordinator routes to implement

Use `/api/v2/` consistently. Every POST requires authenticated identity, purpose-specific authorization and an idempotency key. A service API is not the same as a UI route. Tables describe the contract; FastAPI OpenAPI output should be generated from the implementation and tested against it.

| Method and route | Actor / purpose |
|---|---|
| `POST /studies` | Authorized coordinator operator; create fixed study |
| `POST /studies/{study}/runs` | Operator; freeze run plan and snapshots |
| `GET /runs/{run}` | Run members; sanitized state |
| `POST /runs/{run}/plan-acceptances` | Party; acknowledge exact plan |
| `POST /runs/{run}/key-rounds` | Correct roster party for next round |
| `POST /runs/{run}/epoch-confirmations` | Party; confirm final key/transcript |
| `POST /runs/{run}/submissions` | Party; one encrypted count |
| `POST /runs/{run}/evaluate` | Operator; complete inputs required |
| `POST /runs/{run}/decryption-request` | Operator; one immutable request |
| `POST /runs/{run}/partials` | Party; signed approval and partial |
| `POST /runs/{run}/rejections` | Party; rejection, no partial |
| `POST /runs/{run}/fuse` | Authorized operator/service; all-party gate |
| `GET /runs/{run}/result` | Named recipients only; no value before release |
| `GET /runs/{run}/evidence` | Authorized reviewer; sanitized export |
| `GET /runs/{run}/artifacts/{sha256}` | Authorized member; run-scoped retrieval |

No coordinator route accepts a clinical XLSX or CSV. The artifact route must verify run membership even for a known content hash; content-addressed storage does not make clinical ciphertexts public. Do not allow arbitrary filesystem paths or URLs in any payload.

## 5.5 Local provider routes and UI

Local routes use `/local/v2/` and are reachable only through the loopback UI with authentication and CSRF checks. Required actions are `import`, `validate`, `accept-plan`, `key-round`, `confirm-epoch`, `prepare-count`, `encrypt-submit`, `review-request`, `approve`, `reject` and `status`. The service's poller handles transport, not approval.

Use a configured read-only import directory. The UI lists files in that directory and submits an opaque selection token, not an arbitrary path. Reject symlinks and path escapes. A browser cannot safely supply a general host path; avoid pretending that a remote coordinator file picker selects data on the provider. A local upload endpoint can be added later with separate multipart/temp-file tests, but is not needed for the first IOCN demonstration.

Three local screens are sufficient: (1) Import and mapping status; (2) Run/key/submission status; (3) Verified decryption request with Approve/Reject. Show local counts only on the provider's authenticated screen. Never show patient rows. Coordinator screens show run progress, one line per provider, and an authorized result only after fusion.

Use simple server-rendered HTML forms, a small local stylesheet and periodic status refresh. HTMX is optional and must be vendored, not fetched from a CDN. No React, analytics trackers or external assets are required. Translate clinical display labels into Romanian without changing signed canonical query data.

## 5.6 Transport, database and envelope details

Use multipart for a signed JSON envelope plus its binary artifact; JSON does not carry base64 ciphertext. Bound the JSON part (for example 64 KiB) and streaming binary part (provisional 16 MiB, checked against measured artifacts at M0). These are engineering starting limits, not claims about expected OpenFHE sizes. Hash while streaming into a quarantine file, authenticate before deserialization, then atomically promote it. Reject unknown multipart fields.

SQLite is sufficient per service for the MVP. Enable foreign keys, transactions and a tested locking strategy. Store run plans, epoch records, submission metadata, requests, approvals, outbox receipts and audit events; store binaries in restricted content-addressed files. Do not put clinical rows into the coordinator DB. No distributed database is needed.

The schema set in `contracts/` checks structure; semantic validators must also check equal n/threshold, exact roster, all signatures, identity pinning, chronological validity, same hashes, correct state and immutable input snapshots. JSON Schema alone cannot prove these relationships. Use one canonical contract version across Python and C++ metadata.


# 6. Build, installation and operator deployment {#sec6}

## 6.1 What is provided versus what is to be built

This delivery includes a C++ smoke source and a CMake template. It does not include OpenFHE binaries, container images, an application installer or completed services. The programmer produces and tests those in M0–M6. Do not hand the documentation ZIP to IOCN as though it were an installable application.

The recommended implementation is a C++17 OpenFHE CLI, Python FastAPI services, SQLite and server-rendered HTML. A separate minimal Linux image for each role keeps operations reproducible. No GPU is required by the specified additive circuit. Resource requests are measured during the first build/run; start builds with two parallel jobs on memory-constrained laptops rather than an unbounded `--parallel`.

## 6.2 Pinned upstream build gate

Run on a Linux developer environment or inside the build image with network access:

```bash
git clone --branch v1.5.1 --depth 1 --recurse-submodules \
  https://github.com/openfheorg/openfhe-development.git vendor/openfhe

git -C vendor/openfhe rev-parse HEAD
git -C vendor/openfhe submodule status --recursive

cmake -S vendor/openfhe -B build/openfhe \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PWD/.local/openfhe" \
  -DBUILD_EXAMPLES=ON -DBUILD_UNITTESTS=OFF \
  -DBUILD_BENCHMARKS=OFF -DWITH_OPENMP=OFF -DNATIVE_SIZE=64
cmake --build build/openfhe --parallel 2
cmake --install build/openfhe

cmake -S reference/cpp -B build/smoke \
  -DCMAKE_PREFIX_PATH="$PWD/.local/openfhe"
cmake --build build/smoke --parallel 2
ctest --test-dir build/smoke --output-on-failure
```

These are source-informed build instructions; they were not executed in this environment because the OpenFHE checkout was unavailable. M0 must reject missing submodules, version mismatch or unsupported flags rather than continuing silently. Store the resolved full commit, CMake cache, compiler version and build log. Check that CMake actually reports 64-bit native arithmetic. Re-enable OpenMP only as a separately benchmarked build change.

Link using the variables/exported libraries from the pinned OpenFHE CMake package and preserve its compile flags. The supplied CMake template follows the upstream user-project pattern [S13]. Do not guess imported target names or omit required library/ABI flags. Run the official BGV threshold and serialization examples before the project smoke tests; locate their generated executable paths in the build output.

The smoke program is intentionally an **in-process mathematical test using invented counts**. It holds separate party keys in one process to test API sequencing, not to demonstrate security isolation. It must not be packaged into the coordinator service or used with clinical data.

## 6.3 Two deployment profiles

**D1 — synthetic single-host demonstration.** Compose starts coordinator, A, B and optional C. Use separate role-specific volumes, local ports 8080/8081/8082/8083 and one private Docker network. Host-published ports are `127.0.0.1:<port>:<container-port>`. HTTP is acceptable only for this local simulation. Do not claim independent institutional trust boundaries.

**D2 — restricted IOCN validation.** Coordinator runs on an approved machine/VM; A, B and optionally C run on distinct provider-controlled Windows/macOS computers. Each party has its own local data directory, tmpfs keys, credentials and local UI. Only the coordinator HTTPS endpoint is reachable over the approved network. Providers use the correct network hostname, not `localhost`, to contact it. The coordinator is not allowed to mount provider data/key directories.

For a minimum 3/3 distributed validation, three distinct provider endpoints can participate while the coordinator shares a machine with a disclosed trusted operator if that topology is explicitly accepted. The strongest separation places the coordinator on its own host. Report actual machines and administrators rather than counting processes as independent hospitals.

## 6.4 Container requirements

Build from a pinned base-image digest, pin Python dependencies in a reviewed lock file, verify source commits and include an SBOM and license notices. Use non-root runtime users, no Docker socket mounts, no privileged containers, no writable host-root mounts, no cloud telemetry and no debug mode. Mount data read-only and tmpfs keys owner-only. Log only allowlisted fields.

The ephemeral-key profile must ensure that the service and its worker run under compatible UIDs and can read their own tmpfs, but not another provider's directory. A chmod instruction applied to a host bind mount is not a complete Windows/macOS permission model; test the container view. Store local audit/outbox state separately from ephemeral secrets.

Produce `linux/amd64` and `linux/arm64` images. They share the source/profile release but have different platform-specific digests. A run must use the approved platform digest from that release; requiring byte-identical image digests across architectures would be wrong. Test serialization round trips and a mixed-architecture 2/2 or 3/3 run before calling the release interoperable.

No prebuilt image is included here. The application build should fail when required source files, version locks or runtime permissions are missing, rather than run a mock/no-crypto fallback.

## 6.5 Windows and Mac preparation

The operator should not compile C++ on an IOCN laptop. IT installs a supported container runtime and the programmer supplies tested role images plus short start/stop scripts. Docker Desktop on Windows requires its documented virtualization/WSL or supported backend prerequisites; on Mac choose the correct Apple Silicon or Intel installation. Check current support and institutional licensing before deployment; do not assume every existing machine or every institutional use qualifies [S14a, S14b].

A practical starting machine has enough memory for its assigned service(s) and container VM; the release report must record measured RAM rather than convert a guess into a mandatory hardware specification. Avoid putting three simulated providers and a native build into the same memory budget during clinical validation.

The programmer supplies `start-demo.ps1`, `start-demo.command`, `stop-demo` equivalents and a D2 per-party starter. Each starter checks the runtime, architecture, image checksums, expected services, free disk, port conflicts, required config and read-only mounts. It opens the local UI and shows an explicit “synthetic demo” or “restricted IOCN validation” banner. A restart warning explains that unfinished ephemeral-key epochs cannot be resumed.

## 6.6 Offline bundle and credentials

The offline application bundle produced in M6 contains architecture-specific image archives, Compose files, scripts, a release manifest, SHA-256 checksums and a Romanian operator guide. Dependency installation and image pulling must not occur during an offline clinical demonstration. Offline image loading does not install or license Docker Desktop itself.

Generate all private keys and local operator credentials on the target endpoint at runtime, never embed them in the image/archive. The baseline may use an ephemeral random local operator token shown through a local-only provisioning command, exchanged for an authenticated session. Keep tokens out of coordinator logs, URLs, screenshots and shared `.env` files. Clear local sessions when the agent restarts.

For D2, configure an IT-approved private CA and HTTPS at the coordinator. Distribute only the CA certificate and correct public identity fingerprints; never distribute the coordinator's private TLS key or all party credentials. Plaintext patient files stay in IOCN-approved storage and are not copied into the software bundle.

## 6.7 Operator path to demonstrate unanimity

1. Start the approved release; confirm the mode, roster and fingerprints locally.
2. Select the local shard/approved data file. Accept the reviewed formula-cache mode only when justified. Confirm mapping and validation status.
3. Accept Q004 and the recipients. Complete the local key step and final epoch confirmation.
4. Compute the local count and encrypt/submit it. The coordinator shows a received status, never this count.
5. Review the verified aggregate request on each provider screen. In 3/3 approve A and B only; show the coordinator's blocked state and no result value.
6. Disconnect C and verify that the state remains blocked. Reconnect C without restarting its key-holding container, or start a fresh epoch if keys were lost.
7. C approves the same verified request. The correct aggregate appears. Export the sanitized evidence bundle.

Distinguish network disconnection from container restart: the first can preserve the ephemeral key; the second intentionally cannot. Use synthetic data for training. Restricted IOCN Q004 should produce 11 only for the verified source and splitting rule.


# 7. Implementation plan and acceptance gates {#sec7}

## 7.1 Work in vertical increments

One engineer can follow these milestones sequentially. AI agents may work on independent fixtures, UI layout and documentation, but a human owns the cryptographic boundary and merges one reviewed change at a time. Do not start by generating an entire application from a single prompt. There is no calendar promise: close a gate only when its evidence exists.

| Gate | Implement | Required evidence before proceeding |
|---|---|---|
| M0 — reproducible upstream build | Pin source/submodules, build OpenFHE and the supplied smoke source; capture effective 2/2 and 3/3 profiles | Build log, full commits, compiler/CMake flags, successful exact sums, no forced insecure parameters |
| M1 — reference data semantics | Port the fixed catalogue and strict import rules; keep the clinical file outside the development environment | Synthetic tests; formula-cache tests; separately authorized IOCN plaintext regression |
| M2 — process-separated crypto | Implement the nine worker commands, serialization, private directories and deterministic recomputation | Distinct processes; positive 2/2 and 3/3 flows; wrong epoch/input/aggregate rejected |
| M3 — signed immutable protocol | Implement plans, key rounds, epoch confirmations, submissions, requests, local approvals and exact partial set | Signed contract fixtures and negative tests; no fusion call when a share or signature is missing |
| M4 — services and minimal UI | Add coordinator, party poller, local import selector, approval forms, transactions and immutable outbox | Browser/API end-to-end tests, CSRF/auth tests, rejection/offline/retry scenarios |
| M5 — packaging | Build pinned amd64 and arm64 images, same-host synthetic Compose and separate-host profiles | Image IDs, installation scripts, secret/data mount inspection, offline install rehearsal |
| M6 — relevant-environment pilot | Test two and three endpoints, including intended IOCN Windows/macOS hardware | Operator acceptance, mixed-platform artifact exchange, clinical comparison, failure/recovery evidence |
| M7 — handover | Freeze release, export sanitized evidence, document limitations and operator recovery | Signed acceptance report, reproducible test instructions, retained risk register |

M1 can proceed in parallel with M0. M3 may use a fake worker for state-machine unit tests, but those tests must be labelled as such; they do not validate threshold encryption. M4 cannot be accepted until M2 and M3 work with the real worker. M5 is not a substitute for M6.

## 7.2 First engineer session

Read `README_START_AICI.md`, this blueprint's Sections 1–4, and `AGENTS.md`. Run the delivered Python unit tests on synthetic data. Review the verification ledger before treating any file as executable product code. Then perform M0: acquire the pinned upstream source in an environment with network access, build it, build `reference/cpp/count_smoke.cpp`, and record the results. Do not change the cryptographic scheme merely because compilation or serialization needs a small fix.

The C++ smoke source deliberately holds all separate shares in one test process. That makes it an API/correctness smoke test only. It must never become the coordinator implementation or receive patient data. M2 replaces this arrangement with independent private namespaces and processes.

## 7.3 Task card template

Each implementation ticket must contain: requirement IDs or section numbers; files allowed to change; input/output contracts; threat-model assumptions; positive and negative tests; exact commands to run; evidence paths; and an explicit stop condition. Use `templates/task_card.md`.

A completed ticket includes the patch, test output, remaining failures and a short explanation of any changed assumption. “It should work” is not an acceptance result. A coding agent must not mark skipped tests as passed, fabricate benchmarks, or weaken validation to make a test green.

## 7.4 Human review responsibilities

The programmer owns implementation and reproducibility. A cryptography reviewer approves effective parameters, key generation, aggregate verification, share handling and extension designs. IOCN confirms the mapping, formula-value provenance, record/patient semantics and output recipients. A local IT/security reviewer approves deployment, identity enrolment, network access and clinical-data handling. These are roles to assign, not assertions that approvals have already been obtained.

Before merging, answer four questions: does any new path expose a local count or secret; can a remote request cause a partial without local approval; can a run mix keys, snapshots or ciphertexts; and does the test evidence support the exact claim made in the documentation?


# 8. Test plan, measurements and TRL evidence {#sec8}

## 8.1 Separate verification layers

The delivered Python helpers test data semantics, canonicalization and a narrow signed-partial gate. They do not implement the production service, OpenFHE serialization, malicious-secure distributed key generation or a complete consent system. `verification/verification.json` records what was actually executed for this revision. Tests below are requirements for the future prototype unless explicitly marked as executed there.

| ID | Scenario | Required outcome |
|---|---|---|
| D01 | Synthetic CSV and Q001–Q006 | Exact expected totals and 2/3-way shards |
| D02 | Supplied IOCN export, locally authorized | Totals 51, 29, 13, 11, 21, 9; matching shard table |
| D03 | WBC formula with valid saved result | Literal-only rejects; reviewed-cache mode accepts |
| D04 | Missing/error formula cache | Whole import fails; no false/zero substitution |
| D05 | Missing or duplicate required header | Fail before any canonical dataset is admitted |
| D06 | `NO`, false, 0, blanks and NA | False and missing remain different |
| D07 | Age 11.5, bool-as-age, unknown diagnosis | Reject, not truncate or guess |
| D08 | Blank selected row; explicit-NA row | Blank skipped; NA row retained for Q001 |
| D09 | Extra identifier/free-text columns | Not present in projection, logs, fixtures or uploads |
| D10 | 10,001 admitted rows | Reject before encryption |
| C01 | 2/2 counts 5 and 6 | Exact 11 under final joint key |
| C02 | 3/3 counts 3, 2 and 6 | Exact 11 under final joint key |
| C03 | Zero and boundary counts | 0, 20,000 or 30,000 as applicable; no wrap |
| C04 | Parameter inspection | Correct n, mode, modulus and secure automatic ring |
| C05 | All operations in separate processes | Same exact result after binary serialization |
| C06 | Intermediate key, wrong context or epoch | Reject before evaluation/partial decryption |
| C07 | Replaced aggregate or omitted/doubled input | Local recomputation rejects before approval |
| C08 | Nonzero unexpected output slots | Flag regression; no silent data leakage |
| C09 | Missing, duplicate or wrong-role partial | Application denies; fusion call count stays zero |
| C10 | Malformed or oversized binary object | Bounded failure in isolated worker; no key/log leak |
| C11 | amd64 ↔ arm64 exchange | Key/ciphertext/partial round trips; exact result |
| P01 | Tampered envelope/hash/signature | Deny before deserialization or use |
| P02 | Unknown signing key or changed roster | Deny; do not trust a key embedded in the message |
| P03 | Expired, replayed or different request | Deny; no new partial generated |
| P04 | Changed query/snapshot/recipient | Deny or create a new approved run; never mutate |
| P05 | One provider rejects | Run remains undecryptable through the honest application |
| P06 | Network disconnect and retry | Pending state; retransmit identical immutable bytes |
| P07 | Crash during partial generation | Recover exact cached artifact or abort; do not regenerate |
| P08 | Party container restart/key loss | Abort epoch and explicitly re-enrol/rekey as needed |
| P09 | Two concurrent approval requests | At most one generated partial; transactional gate |
| P10 | Fresh key for another query | Does not reset study-wide disclosure ledger |
| U01 | Coordinator tries local approve route | Unreachable or unauthorized; no partial |
| U02 | CSRF, untrusted Origin and unauthenticated UI | Deny state-changing actions |
| U03 | Localhost ports share browser cookies | Distinct cookie names/scopes; no credential collision |
| U04 | Import path escape, symlink or remote URL | Deny; read configured import root only |
| U05 | Evidence export | No raw rows, source paths, secrets or full partial set |
| U06 | Separate-host mount/network audit | Coordinator cannot mount provider data or key tmpfs |

Cryptographic negative tests are not proofs of security. In particular, do not infer security from a few wrong numbers obtained with incomplete partials. The protocol's assumptions, upstream design and application controls must all be stated.

## 8.2 Minimal live demonstration script

Use synthetic data first. Start coordinator and two providers. Enrol fingerprints, select Q004, pin the plan, generate the joint key, confirm the epoch, and submit encrypted local counts. Show that the coordinator has no plaintext count and cannot import a spreadsheet. Request the sum. Approve at A only: the result must remain unavailable. Reject at B: the run terminates without a result. Start a **new run with fresh keys**, obtain both approvals, and compare the exact final result with the independent plaintext oracle.

Repeat with three providers. Approve A and B while C is disconnected: no fusion. Reconnect C without destroying its runtime keys, inspect the identical request and approve it: the exact total becomes available. Demonstrate a tampered aggregate and a wrong-epoch partial being rejected. Demonstrate a container restart separately: key loss aborts the epoch, unlike a temporary network interruption.

For clinical acceptance, repeat Q004 on the locally prepared IOCN shards. The expected plaintext total is 11. A permitted test can inspect local 5+6 or 3+2+6 on the provider screens; the coordinator receives only the final result. Explain that splitting one institution's file across laptops is a distributed-processing simulation, not proof of data governance across independent hospitals.

## 8.3 Benchmark methodology

Use synthetic datasets with 100, 1,000 and 10,000 admitted rows **per provider**, and n = 2 and 3. Record dataset generator version and query selectivity. The encrypted payload contains one scalar irrespective of the local row count; local filtering scales with rows, while the baseline FHE operation count depends primarily on n. Do not present a scalar aggregation as server-side encrypted filtering of 30,000 rows.

Measure import, normalization/filtering, context generation, each key-generation round, encryption, serialization, input upload, `EvalAdd`, aggregate verification, each partial, fusion and output serialization separately. Record ciphertext/key/partial byte sizes, peak resident memory, CPU, operating system, architecture, container limits, OpenFHE commit/submodules, effective parameters, compiler and thread settings. Use a monotonic timer; explicitly include or exclude network time.

After a warm-up, collect at least 20 samples per reported configuration. Use fresh keys for each complete run and one partial generation per provider per epoch. Report median and nearest-rank P95 (sorted element at index `ceil(0.95*N)-1`), with N. Human approval time is a separate measure, not cryptographic latency. Failed runs and retries are counted and reported. Do not reuse the same partial-generation call hundreds of times on clinical data for a benchmark.

No measured speed, RAM requirement or latency target is asserted in this document. Set acceptance budgets after M0/M2 measurements and record the rationale. A slow but correct baseline is preferable to silently lowering security or removing unanimous approval.

## 8.4 Evidence package and maturity claims

Create a release-scoped evidence index with build identifiers, test logs, parameter dumps, benchmark CSV, architecture, threat model, installation procedure, sanitized screenshots, observed defects, operator acceptance and the exact capabilities demonstrated. `templates/acceptance_report.md` and `templates/benchmark.csv` provide a starting structure.

Laboratory validation can support a TRL4 argument for the **cohort-count component** when the integrated system works and its tests are documented. Relevant-environment validation at IOCN, on representative machines and workflows with the appropriate authorizations, can support a TRL5 argument. Neither this specification nor a successful in-process smoke test establishes those levels automatically. Do not extend a count-only maturity claim to a future statistical SDK or to the entire platform promised in a funding application.

The default evidence export contains artifact hashes and signed consent metadata, not private shares or a reusable complete set of partial-decryption binaries. A stored aggregate plus all partials remains decryption-capable. Clinical output values and local diagnostics require their own access and retention rules. Use synthetic screenshots for public demonstrations.


# 9. Instructions for AI-assisted development {#sec9}

## 9.1 Rules for every agent

Treat this blueprint as the normative specification. `AGENTS.md` is its compact enforcement checklist. Read the relevant upstream pinned files before introducing an OpenFHE API. Work only on synthetic fixtures. Do not send the IOCN workbook, rows, raw logs, clinical screenshots or secrets to an external model. Keep clinical testing physically outside the agent's accessible workspace.

Do not create a central private key, reconstruct shares, use a debug key-generation overload, bypass an approval gate, decrease the threshold after a failure, or “temporarily” fall back to plaintext. Do not generate new randomness on an idempotent retry. Do not silently substitute CKKS for exact counts, turn off noise flooding, force a small ring, or allow arbitrary query expressions.

Do not claim a function is malicious-secure merely because it checks signatures. Keep source-supported library behavior, application policy and unproven assumptions separate. Missing source or a test failure is a reason to stop and report, not to invent an API or an expected benchmark.

## 9.2 Reusable task prompt

```text
Task: implement [MILESTONE / TICKET] for PROTECMed v2.
Read AGENTS.md, IMPLEMENTATION_BLUEPRINT.md sections [X],
and the pinned upstream files listed in this ticket.

Scope: cohort-count-local-v2, BGV exact integers,
2/2 and 3/3 unanimous decryption. No other statistical module.
Allowed files: [PATHS]. Contracts: [SCHEMA NAMES / VERSIONS].
Use only fixtures/synthetic_cohorts.csv or generated synthetic data.

First state the input/output invariants and the negative tests.
Implement the smallest vertical change that satisfies the ticket.
Never construct a full secret key or bypass local human consent.
Preserve immutable run/epoch/query/input/recipient bindings.

Run [EXACT TEST COMMANDS]. Report separately:
1. files changed and why;
2. tests actually run, environment and evidence paths;
3. tests skipped or blocked, with reason;
4. unresolved security or compatibility questions.
Do not claim completion while required tests are skipped.
Stop for human review before any cryptographic-profile change.
```

## 9.3 Safe parallelism and review

A data-adapter agent can implement schema/normalization tests while a crypto agent completes M0/M2. An API agent can draft state-machine tests against a fake worker, clearly labelled. A UI agent may implement only the approved local forms. The lead engineer reconciles the contracts before integration; agents must not independently invent competing query JSON or role names.

Every merge must preserve one source of truth for the catalogue, schema version, crypto profile and release policy. Update documentation and tests together. If an implementation deviates from v2, record an architectural decision and version the changed contract rather than leaving incompatible examples in the repository.


# 10. Extension points without scope creep {#sec10}

## 10.1 Stable module boundary

Implement a local `CountModule` with four operations: validate a canonical query against the release catalogue; declare required fields; count matching rows with a local eligibility report; and return the single bounded integer for encryption. Keep this code independent of XLSX parsing, networking and OpenFHE. A new data adapter must produce the same typed canonical rows rather than changing query semantics.

A future module definition must declare its input/output shape, missing-value policy, arithmetic bounds, encoding, security profile, circuit, permitted output, required evaluation keys, reference oracle, leakage assumptions and test suite. The run plan binds the module version and its hash. New code is not executable through a user-provided string or plugin upload.

## 10.2 Adding a new cohort predicate

First add a reviewed canonical field or allowed value to a versioned mapping if needed. Write synthetic normalization and missing-value tests. Add the exact typed query to a new catalogue version and document its clinical meaning. Review its relationship to already released counts: a harmless-looking additional query may reveal a small difference. Create a new run and keys, but retain the same study-wide disclosure ledger.

This extension still filters locally and encrypts a scalar. It does not need ciphertext multiplication, key-switching keys or CKKS. Do not add those components simply because OpenFHE supports them.

## 10.3 Optional future encrypted-feature counting

A separately approved experiment could encrypt zero/one indicator vectors at each provider, evaluate predicate intersections on ciphertexts, sum slots and finally aggregate provider results. Keep it a **different module and crypto profile**. The v2 MVP does not implement or validate this flow.

For example, an AND of three indicators uses multiplication and has positive multiplicative depth. Choose BGV or BFV only after a measured design review; the v1 document's BFV extension was a proposal, not a requirement to switch the baseline. A packed-slot implementation also needs a correct multiparty evaluation-key ceremony and, for slot sums, appropriate rotation/summation keys. The upstream five-party example illustrates these additional API families, but is not a drop-in production protocol [S17].

The release object must contain only authorized output. **`Plaintext::SetLength(1)` merely truncates the displayed/returned vector; it does not remove information from a ciphertext.** If extra slots retain per-record indicators or intermediate sums, a recipient can decode them. Homomorphically mask non-output slots before approval, or prove that every surviving slot carries only the same permitted aggregate. Test the entire decoded slot vector, not just slot zero. Adjust depth and bounds for the masking operation.

Also specify chunking, padding, cross-chunk sums, absence of overlapping patient records, completeness of submitted chunks, and leakage of row counts/chunk counts. The original local scalar module avoids these extra dependencies. Do not delay a count-only TRL demonstration to implement them.

## 10.4 Deferred capabilities

Kaplan–Meier, regression, general statistical tests, private record linkage, differential privacy, malicious-secure input proofs, dropout-tolerant thresholds and FHIR/OMOP integrations remain outside this implementation baseline. They may be designed later, but must not appear as completed or as dependencies of the cohort-count acceptance test.


# 11. Sources, provenance and verification boundaries {#sec11}

## 11.1 Project inputs

[P1] `Cerere de finantare_PROTECMed_FINAL.pdf`, especially Objective O2 on page 3: web collaboration and interactive decryption with the agreement of all data providers. This is the project intent, not evidence that the system is implemented.

[P2] `PROTECMed_OpenFHE_Prototype_Implementation_Blueprint.md` and its earlier DOCX/ZIP: starting specification. Version 2 preserves the count-only local-filtering architecture, unanimous thresholds and small web deployment, while the change register identifies corrections and clarifications.

[P3] `Date - craniospinal irradiation - salvarea ultima 4 decembrie.xlsx`: local structural inspection, formula-cache audit and independent recalculation of the six aggregate queries. No patient rows are redistributed. Agreement with v1 is an import/query result, not a clinical interpretation or an FHE execution result.

The user's later count-only instruction supersedes broader functions discussed in the funding proposal and earlier planning response. New security controls, caps, request formats and packaging choices in this blueprint are engineering decisions for the prototype, not quotations or implied requirements from the funding authority.

## 11.2 Primary technical references

The following sources were checked on **5 September 2026**. OpenFHE code links are pinned to v1.5.1 rather than a moving main branch. Each source supports only the indicated library/documentation facts; the application design remains this specification's responsibility.

**[S1] [OpenFHE releases](https://github.com/openfheorg/openfhe-development/releases).** Version pin and documented multiparty fixes.

**[S2] [threshold-fhe.cpp](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/examples/threshold-fhe.cpp).** BGV additive API sequence; use the public-key chain, not the debug joint-secret example.

**[S3] [gen-cryptocontext-params.h](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/include/scheme/gen-cryptocontext-params.h).** Parameter setters including SetThresholdNumOfParties.

**[S4] [gen-cryptocontext-params-defaults.h](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/include/scheme/gen-cryptocontext-params-defaults.h).** Defaults; a roster size in the application does not alter a library default.

**[S5] [bgvrns-parametergeneration.cpp](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/lib/scheme/bgvrns/bgvrns-parametergeneration.cpp).** Joint-secret bound and multiparty parameter generation.

**[S6] [Threshold_FHE.md](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/docs/static_docs/Threshold_FHE.md).** Supported threshold schemes and BGV/BFV noise-flooding modes.

**[S7] [rns-multiparty.cpp](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/lib/schemerns/rns-multiparty.cpp).** Lead/main partial computation and scheme-specific flooding behavior.

**[S8] [base-multiparty.cpp](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/lib/schemebase/base-multiparty.cpp).** Sequential public-key accumulation and the debug private-key overload.

**[S9] [cryptocontext.h](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/include/cryptocontext.h).** Public API signatures and context/key validation.

**[S10] [cryptocontext.cpp](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/lib/cryptocontext.cpp).** Fusion wrapper and decoding checks; not an institutional roster check.

**[S11] [simple-integers-serial.cpp](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/examples/simple-integers-serial.cpp).** Serialization pattern. For BGV also include scheme/bgvrns/bgvrns-ser.h.

**[S12] [openpyxl load_workbook documentation](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html).** data_only selects saved values, not formula recalculation.

**[S13] [CMakeLists.User.txt](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/CMakeLists.User.txt).** Official exported-variable build/link pattern.

**[S14a] [Docker Desktop Windows installation](https://docs.docker.com/desktop/setup/install/windows-install/).** Check current runtime prerequisites and institutional licensing.

**[S14b] [Docker Desktop Mac installation](https://docs.docker.com/desktop/setup/install/mac-install/).** Separate Apple Silicon/Intel installation instructions.

**[S15] [Docker Engine security](https://docs.docker.com/engine/security/).** Container/host security boundary; one host is not independent ownership.

**[S16] [RFC 8785: JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785).** Context for canonical JSON; this kit uses a narrower explicitly defined profile.

**[S17] [threshold-fhe-5p.cpp](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/examples/threshold-fhe-5p.cpp).** Multiparty evaluation-key families for a deferred feature-count experiment.

**[S18] [bgvrns-ser.h](https://github.com/openfheorg/openfhe-development/blob/v1.5.1/src/pke/include/scheme/bgvrns/bgvrns-ser.h).** Required BGV serialization registrations.

## 11.3 Exact status of this delivery

Executed locally: synthetic/reference Python unit tests; JSON Schema validation; independent IOCN saved-value aggregation; package consistency checks; and DOCX rendering/layout review. Detailed counts and status are in `verification/verification.json` and the accompanying logs.

Not executed here: compilation or runtime execution of the supplied C++ source, OpenFHE process-separated integration, Docker image builds, browser/service testing, Windows/macOS installation, mixed-architecture interoperability, clinical deployment, penetration testing and TRL assessment. The authoring environment had no installed OpenFHE and its attempted network checkout failed. Those are mandatory implementation gates, not results to infer from a code listing.

No GPU performance, security audit certificate, clinical approval or maturity level has been established by producing this package. Record the subsequent real evidence against the exact release before making those claims.


# Appendix A. Changes from v1 {#changes}

Date: 5 September 2026. This register distinguishes corrections from deliberate tightening of the prototype contract.

| Area | Correction or clarification | Consequence |
|---|---|---|
| OpenFHE party parameter | SetThresholdNumOfParties(n) is explicit; application roster alone is insufficient | Check effective profile for both n values |
| Fusion | Library fusion does not authenticate the roster or human consent | Exact signed-party/role gate before library call |
| Aggregate approval | Verify all signed inputs and recompute ordered EvalAdd, not merely sign an opaque hash | Reject substituted ciphertexts and subset sums |
| Key generation | Public-key overload; fresh=false; no debug combined-secret overload | Independent shares remain at endpoints |
| Key tags | Do not equate private-share tags with institutional identities | Bind to signed epoch and local key registry |
| Arithmetic bounds | 10,000 admitted rows per provider; <=30,000 total | Prevent modular wrap under honest input bounds |
| WBC import | 51 formula cells; reviewed saved values or verified values-only export | Missing/error caches fail rather than becoming false |
| External links | Supplied XLSX has one external-link part | Never refresh/follow external links during import |
| Row semantics | Admitted records are not automatically unique patients | Local and cross-site uniqueness must be confirmed |
| Canonical shards | Preserve all-null already-admitted records | Do not repeat the raw-XLSX blank-row admission filter |
| Output privacy | Exact 2-party sum can disclose the other local count to an informed party | Explicit disclosure warning and study-wide ledger |
| Consent | An emitted partial cannot be cryptographically recalled | Honest expiry checks; no promise of retroactive revocation |
| Evidence | All partial binaries plus aggregate form a decryption-capable archive | Default export contains hashes/decisions, not full partial set |
| Retry | One immutable output per fresh epoch; resend identical partial bytes | Crash/uncertain emission aborts; no blind regeneration |
| Secret lifetime | Shared local tmpfs across CLI calls, not transient process memory alone | Container restart loses keys; network loss need not |
| Cross-platform | Separate platform image digests and measured serialization compatibility | No untested Windows/Mac portability claim |
| Local web UI | Authenticated local approval, CSRF/Origin checks, distinct cookies | Coordinator cannot invoke an approval automatically |
| Extension safety | Display truncation does not erase extra encrypted slots | Homomorphic masking or proof of output-only slots |
| Verification | Source review separated from compilation/runtime | C++/Docker/services explicitly NOT RUN here |
| Usability | Modular docs, task gates, schemas, independent synthetic fixtures and tests | Start with README, AGENTS and M0, not a single monolithic AI prompt |

The six IOCN plaintext totals and their 2/3-way splits were rechecked and retained. They are not newly measured OpenFHE timings or cryptographic benchmarks.
