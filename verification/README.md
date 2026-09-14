# Verification ledger

Read verification.json and python_reference_tests.txt. These are results of producing the documentation/reference package, not certification of the prototype.

57 local unit tests exercised only synthetic/reference Python logic, schema validation and minimal synthetic OOXML cache cases. The clinical cached-value counts were checked separately and match config/iocn_expected_counts.json; no patient rows are stored here. No cached-formula freshness or clinical semantic correctness was established.

C++, OpenFHE runtime, services, containers and Windows/Mac execution remain NOT RUN. Fill a new release-scoped acceptance report after the programmer actually completes those gates. Do not overwrite NOT RUN with PASS merely because the source looks plausible.
