# Ramses target-coverage observation windows

This reporting candidate is based on certified runtime
`c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66`. The active prospective cohort and hourly
campaign remain on that revision. This candidate has not replaced their runtime
or received a full exact-revision certificate.

The initial v5 smoke, workflow 35935431384, completed successfully and passed its
native artifact review. Its Ramses scans observed four strategy-target pools at
frontier 70908459 and three at frontier 70915843. Two pools were shared, giving
five distinct target pools across the block. The original report divided that
union by the latest scan's three-pool census and incorrectly reported 5/3 coverage.

The reporting change reads the frontier identities already preserved in native
pipeline discovery records. It uses the latest complete target census as an
aggregate denominator only when every observed candidate belongs to that same
frontier. Multiple frontiers, missing provenance or a different frontier leave
aggregate coverage unknown. The latest census count remains separately visible
with its scan scope. Broad factory inventory still never becomes observed target
market. No provider calls, native writes, strategy changes or admission changes
are introduced.

Validation completed locally:

- All 10 focused market-assurance tests passed, with no skips. Regressions cover
  overlapping scans, equal counts across different scans, missing frontier
  provenance and a latest census that differs from the observed frontier.
- Reprocessing the preserved smoke returned five observed target pools and an
  unknown aggregate denominator/coverage. Its native accounting proof, zero
  natural entries and empty admission-failure list were unchanged.
- `git diff --check` passed.

The captured smoke artifact is 10783726415, SHA-256
`fb1631395f78645fcdeff2c7cdf4383aed12d4d8d36ed3adb790a921ac24f8c0`.
The independent corrected audit is preserved on the cohort state branch at
`certification/results/target-market-audit-35935431384.json`. All 75 manifest
files were checksum-verified; the original artifact remains untouched.

This candidate requires the normal full exact-revision certificate before any
runtime adoption. Continue the existing certified cohort without interrupting its
native work or resetting positions for this reporting correction.
