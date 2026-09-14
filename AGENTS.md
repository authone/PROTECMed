# PROTECMed v2 — mandatory coding-agent instructions

Normative document: IMPLEMENTATION_BLUEPRINT.md. Read the milestone ticket before editing.

Scope: local cohort filtering, exact BGV count encryption, coordinator EvalAdd, unanimous 2/2 or 3/3 decryption. No Kaplan–Meier, regression, machine learning, general SQL or arbitrary code execution.

Use only synthetic data. Clinical workbooks, actual rows, keys and raw clinical logs must be outside your accessible workspace, Git root and Docker build context. Ignore files are not access controls.

Pin OpenFHE v1.5.1. SetThresholdNumOfParties must equal the authenticated roster size. Preserve NOISE_FLOODING_MULTIPARTY and secure automatic parameter selection. No profile changes without human cryptography review.

Never construct/recover a combined secret key. Never use the private-key-vector debug overload, ShareKeys or RecoverSharedKey. Never lower the threshold after a provider disconnects.

Implement the application gate before calling fusion. isValid is not proof of consent or membership. Verify signed complete inputs, recompute the aggregate, bind the exact request, and require local authenticated approval before creating a partial.

No plaintext fallback, mock crypto in a production path, automatic remote approval or hidden bypass. Cache/resend immutable key-round/submission/partial artifacts; do not regenerate randomized results on retry.

Treat XOR/comparison/display tricks cautiously: SetLength(1) does not mask encrypted slots. Exact-count output leaks algebraic information; do not claim differential privacy.

Use the fixed query catalogue, strict missing-value rules and formula-cache policy. Never interpret string NO with bool(). Never treat missing formula results as false.

Run `python -m unittest discover -s tests -v` for delivered helper changes. Run the milestone's actual integration commands for production changes. Report passed, failed and not-run tests separately. Do not claim the reference Python suite tested OpenFHE, Docker, Windows/macOS or the complete service.

Stop and report an unsupported API, parameter failure or missing dependency. Do not invent a working version or a benchmark. Update contracts, docs and tests together; attach exact evidence paths to the ticket.
