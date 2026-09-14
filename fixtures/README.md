# Synthetic fixtures only

`synthetic_cohorts.csv` is an independently invented 24-record table. It is not a sample, shuffle, perturbation or pseudonymized copy of the IOCN rows. Its final all-null canonical record is intentionally preserved because canonical CSV records have already been admitted.

`synthetic_expected.json` gives its own totals and 2/3-way modulo splits. These differ from clinical totals. `contract_examples.json` gives JSON structural examples with synthetic placeholder artifact hashes/sizes, not a valid OpenFHE transcript.

Tests create minimal synthetic OOXML packages in temporary directories for the narrow formula-cache reader. These test packages are not used as claims of general Excel compatibility. No patient workbook or private key is included.
