# 11. Sources, provenance and verification boundaries

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
