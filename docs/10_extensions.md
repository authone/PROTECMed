# 10. Extension points without scope creep

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
