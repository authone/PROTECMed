# OpenFHE smoke source — first implementation gate

**Status: source-reviewed, NOT COMPILED and NOT RUN in the authoring environment.**

Use Section 6.2 of the blueprint to acquire/build OpenFHE v1.5.1 and build this source. The authoring container had no installed OpenFHE and its direct network checkout failed. Do not turn this into an unqualified claim of successful C++ verification.

The smoke covers two/three-party sequential public-key generation, exact scalar encryption, addition, one lead plus main partials, fusion, zeros, boundary values and unexpected extra slots. It intentionally keeps all separate party keys in one process. It tests API sequencing, not distributed trust, serialization, request integrity, consent, or platform interoperability.

No combined secret key is constructed. The executable takes only the argument 2 or 3 and uses invented counts, not a clinical file. The programmer must implement the isolated workers and the signed application gate separately in M2/M3.

Do not fix a failure by weakening the cryptographic settings. Capture the actual compiler/runtime error and effective parameters for the cryptography reviewer. Confirm exported CMake variables against the installed pinned package if a build-system difference appears.
