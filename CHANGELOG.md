# Changes from v1 — PROTECMed programmer package v2

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
