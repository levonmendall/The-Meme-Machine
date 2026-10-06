# Workload efficiency successor

This is an independently reconstructed successor of baseline
`5c52b55208bfd6d8dc507eb89f2ad39402a67e3b`. The reported lost commit
`91ff8293147f4055e783589b711372117cfcf3bc` and tree were not recovered.
This work does not claim their identity or reuse their test results.

## Recovery checkpoint: local processing

Runtime imports were traced before editing. The active paths are the shared
Solana evidence worker, Robinhood candidate/evidence plane, and Ramses universe
collector installed through the existing lifecycle adapter. PAPER stayed stopped.

* Solana normalizes static and loaded keys once per frame and indexes relevant
  program membership. Pump codecs reuse successful base64 decoding within one
  transaction, with the original invocation-stack and discriminator checks.
  Prepared records share lossless compressed log chunks within that frame;
  canonical body hashes, record identities, ordering and availability are intact.
  Existing prepared IPC already omits duplicate raw payload trees; shared chunk
  objects also avoid redundant pickled chunk content.
* Pons reuses only immutable authenticated facts through a bounded 1,024-entry,
  16 MiB cache. SQLite data-version checks invalidate it on another writer's
  commits. Returned facts are independently decoded, so callers cannot mutate
  cached authority. Mutable state, generation fences, deadlines, reconsideration
  and Current/Survivor lifecycle decisions continue to read their original state.
* Ramses still authenticates/enumerates the complete factory and computes the
  existing exact timestamp window. A bounded 8 MiB public observation checkpoint
  reuses covered ranges only after checking the previous finalized anchor.
  Missing suffix coverage is fetched; newly discovered addresses receive the
  whole current window. Changed anchors/coverage regression use the original
  full-range reader. Expired events and decoded projections disappear exactly
  at the existing window boundary. Cached observations grant no trading authority.
* True unchanged evidence/checkpoints avoid commits; empty transactions roll
  back. Maintenance retains active/native/cohort pins and unconsumed results,
  narrows retirement queries with compatible indexes, avoids unchanged archive
  rewrites, and checks external-writer/age changes before skipping an idle sweep.
  The preserved bounded maintenance query repair is included without changing
  its existing 250,000-step limit, retirement semantics or maintenance fairness.

## Identical offline measurements

The measurement driver and raw results live in the durable external handoff.
Both variants consume identical checked-in transaction templates and synthetic
rolling-log evidence. These are operation counts, not a qualifying CAPACITY run.

| Measure | Baseline | Recovered successor |
| --- | ---: | ---: |
| Solana source bytes | 449,779 | 449,779 |
| Full transaction bodies received | 48 | 48 |
| Relevant transactions | 48 | 48 |
| Account-key normalizations | 2,649 | 549 |
| Base64 decodes | 71 | 35 |
| Compressions | 94 | 92 |
| Prepared IPC bytes | 205,318 | 201,935 |
| Canonical prepared bytes | 515,154 | 515,154 |
| Pons warm evidence SELECTs (1,000 reads) | 1,000 | 0 |
| Warm data-version probes | 0 | 1,000 |
| Duplicate immutable commits (200 deliveries) | 200 | 0 |
| Idle maintenance VM steps (20 sweeps, 1,000 candidates) | 583,180 | 140 |
| Idle maintenance writes / commits | 20 / 20 | 0 / 0 |
| Ramses steady log pages | 18 | 1 |
| Ramses additional anchor reads | 0 | 2 |
| Ramses repeated event decodes | 101 | 1 |

Canonical Solana record hashes, Ramses outcomes, and retired-history archive
hashes match the baseline. Single-invocation CPU timings are recorded externally;
they are not statistically meaningful CPU savings estimates. This checkpoint
demonstrates local processing and write reduction. **It does not demonstrate any
Solana upstream reduction or solve broad full-block overcollection.**

## Validation and boundaries

The focused recovery suite covers cache conflicts, external writes/eviction,
bounded memory, fresh mutable state, no-op transactions, active-position pins,
age boundaries, loaded addresses, prepared-byte/pickle parity, complete new-pool
catch-up, changed anchors, failed pagination, restart, duplicate outputs, empty
windows and disposable-cache corruption. It is included in OPERATIONAL.

Recovery checkpoint validation: focused **89 tests PASS** (65.699 seconds),
FAST **480 tests PASS** (30.993 seconds), OPERATIONAL **1,892 tests PASS**
(571.854 seconds), configured PAPER check **PASS**, and `git diff --check`
**PASS**. Full logs, commands, timestamps and hashes are in the external handoff.
The approved strategy audit compares all nine rules and all
44 Ramses economic modules. Those economic files and the Pons discovery/strategy
adapters are unchanged. Four runtime/capital families retain all six regimes.
Accounting, retention, recovery, finality and position-management tests are part
of the full suites; no new epoch or provider workload was started.

Solana source optimization, final publication, deployment/freeze and fresh
CAPACITY remain subsequent gates. No intermediate result authorizes them.
