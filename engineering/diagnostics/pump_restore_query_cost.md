# Synthetic Pump restoration cost discriminator

Native source: `0c8e9beae8eed6e4579f4473c4f449f711fb5691`.
Helper: `operational/pump_restore_query_benchmark.py`, SHA-256 `acac8d72f1ed9c77d87cdd90af05bfdb267a99ca772d645137a822e7f8a30448`.

This is **SYNTHETIC_NATIVE_FIXTURE_ONLY_NOT_LIVE_CAPACITY**. It reads no AWS or production financial state, makes zero network requests, and changes no production implementation. It uses CPython 3.12.14, SQLite 3.53.1, the repository network guard and admitted Scratch scopes. AWS uses SQLite 3.45.1; absolute local timings are not AWS predictions. The helper reuses the existing native-frame fixture builder, actual source/consumer FULL delivery and ACK, actual native retirement/archive APIs, actual `CandidateHistory.events` and actual Pump runner restoration. The helper calls `ScopedRetirement.restore` to obtain TEXT hot bodies; it does not invent database schemas or update native source bodies directly.

The first attempt exceeded the existing 32-MiB fixture corpus guard at 128 candidates / 16 transaction frames each. Its disposable failure evidence remains at `/tmp/mm-engineering-dr431abl`. The corrected bounded run uses 16/32/64 candidates, yielding 512/1024/2048 economic references because the Create fixture emits multiple economic events. Successful scopes were checked and cleaned. Results were saved before successful cleanup.

Receipts:

- `/workspace/recovery-evidence/pump-restore-query-cost-0c8.json`, SHA-256 `5edfa342afad449aecb1770f9cddc3ce58a9dc13e20ec720c35228336612e1b6`.
- `/workspace/recovery-evidence/pump-cohort-path-cost-0c8.json`, SHA-256 `95f468ea5b445870438b120a57e9117b15b3c16dab58f1647f26ee5835ec6070`.

## Canonical lookup result

The exact production lookup is `SELECT body,hash,archive FROM canonical_evidence WHERE identity=?`. Its VM work is flat across all three populations: **33 steps for TEXT hot bodies, 46 for cold pointers**. A direct lookup in the fixture's native `rolling_economic_events` partition takes 15 steps and is checked to return the same tuple on these selected fixtures. The direct-partition query is an attribution comparator, **not a safe production replacement**: the canonical view's other branches and precedence remain required.

Selected warm lookup elapsed time is approximately 3.7–7.4 microseconds per call. The actual AWS partial metadata sample was 0.045068 s / 291 calls, approximately 155 microseconds per call, but includes different hardware/storage/concurrency and SQLite. No growing view scan is reproduced by this benchmark. The many UNION/subquery SEARCH operators in an EXPLAIN plan do not by themselves demonstrate population scaling or an unindexed query.

## Actual restoration results

Each cold archive holds 64 native records. Mixed means 75% TEXT and 25% cold in this fixture, not an estimate of the entire AWS retained population. Every mode within each population produces the same restored economic output hash, and all candidates restore. The operation API counters independently satisfy `fetch_calls - statement_calls = known materialized economic reference rows` for every case.

| Candidates / references | Body population | Restore wall s | Archive reads |
|---|---|---:|---:|
| 16 / 512 | All cold | 0.096723 | 8 |
| 16 / 512 | Mixed | 0.056510 | 2 |
| 16 / 512 | All TEXT | 0.046277 | 0 |
| 32 / 1024 | All cold | 0.189072 | 16 |
| 32 / 1024 | Mixed | 0.118421 | 4 |
| 32 / 1024 | All TEXT | 0.092187 | 0 |
| 64 / 2048 | All cold | 0.405395 | 32 |
| 64 / 2048 | Mixed | 0.355024 | 8 |
| 64 / 2048 | All TEXT | 0.187986 | 0 |

These are single timed passes with instrumentation, not stable capacity estimates. In the 2048-reference mixed pass, candidate-event calls use 0.336850 s CPU, including 0.038354 s selected SQL CPU. Ordinary scratch locators therefore leave 0.298496 s CPU outside the SQL boundaries. A separate CPU-profile pass is deliberately marked probe-inflated and is not used as throughput evidence. Its reached paths include path handling, deepcopy, JSON/digest and diagnostic instrumentation; replacing authentication with a cache is not justified by the profile alone.

The scalar microbenchmark decodes each actual reference JSON once and recomputes its hash; 2048 references take approximately 0.014–0.015 s CPU locally. For 256 actual TEXT canonical records totaling 275700 bytes, most JSON/decode/hash passes take approximately 0.004–0.0065 s CPU and a separate deepcopy takes approximately 0.006–0.0066 s CPU. A 0.0363 s decode/hash outlier is retained. Pump restoration supplies no `prepared` body to `_reference_body`; the existing prepared-ingest shortcut does not apply to these reads. No claim is made that these fixtures reproduce AWS payload sizes, variability, cache state, scheduling or concurrency.

## Authenticated legacy-cohort path result

The ordinary fixture does not exercise preserved legacy locator remapping. A second paired case builds and ACKs the real synthetic history under a temporary legacy `shared` layout, warms 75% of it through native restore, then renames that **intact** layout to a temporary AWS-cohort root. Original canonical references, manifest locators, body/hash checks and authentication predicates remain unchanged. Only the fixture's two root constants and its exact PAPER/cohort environment are relocated for the experiment. No real epoch is copied or read, no auth predicate is bypassed, and no returned payload is trusted without its original hash.

| Same 512 references / 16 candidates | Ordinary original locator | Authenticated relocation |
|---|---:|---:|
| Full restore CPU s | 0.098453 | 0.132915 |
| Candidate-event CPU s | 0.087975 | 0.129334 |
| Selected SQL CPU s | 0.016874 | 0.009793 |
| Candidate-event non-SQL CPU s | 0.071101 | 0.119541 |
| Archive reads / bytes | 2 / 12246 | 2 / 12246 |

Both passes produce the same economic output SHA-256 `778539750045469cb5aeec8298ed801410bf59838e51d4f3e063f3092e0063cf`. Non-SQL CPU rises **68.1%** in this single paired pass, while SQL CPU decreases. In the separate profile, `retained_reference_path` has 640 calls (512 canonical plus 128 cold-file resolutions) and 0.469239 s cumulative CPU out of 0.710415 s profiled total. These inclusive profile costs overlap callers and contain instrumentation overhead. They are not additive partitions or estimates of an AWS improvement.

This is evidence that the authenticated remap path can materially contribute to restoration CPU. It is consistent with four strict path resolves plus lstat on each legacy reference, despite reuse of the already-open canonical SQLite reader. It does not establish what fraction of all AWS references use this branch or that it explains the 311-second selected-SQL wall-minus-CPU difference. The actual AWS 0c8 rehearsal and its new diagnostics remain required before a production change.

## Safe contract choices before any implementation

Retain all existing authentication and cancellation checks while measuring the actual candidate. Do not replace the canonical view, skip body/hash checks, convert historical completion, or reuse decoded records across mutable authority boundaries.

A future narrowly scoped startup validation cache would need to bind the exact environment/cohort, configured source path and the **actual opened read-only SQLite file identity**. It must refuse replacement, source-parent symlink changes and foreign/reconfigured cohorts, and must never permit a new SQLite open without the full path proof. Existing-reader reuse must be shown to keep reading that authenticated file. A filename or pre-open stat alone cannot establish the identity of SQLite's opened file across a replacement race. Per-candidate versus per-reference ancestry validation is therefore a contract choice needing explicit replacement/race tests, not an assumed optimization.

Cold archives retain their own immutable source/manifest/stat fingerprints and original hash/decompression bounds. No cold-path shortcut follows from the canonical-reader finding. Every economic record retains independent payload/hash authentication, and stop/cancellation remains checked per record. Full-market processing and authoritative readiness remain unproven by this offline discriminator.
