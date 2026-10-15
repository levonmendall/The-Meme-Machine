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

The recovery checkpoint was committed as
`368acfa5546238074a711fcb02c7709f0e432369`, tree
`9434a6c2813f3ca6ee5569c581a1e91078f39412`, parent the baseline above.
A full-ancestry Git bundle was independently cloned and its commit, tree and
parent verified before the source work began. The bundle and diagnostics were
also copied to the persistent volume and their hashes read back. This is an
honestly identified successor; the lost commit was not reconstructed by identity.

## Final Solana intake boundary

The owner requested a bounded test of minimal finalized block notifications
plus the existing address-specific census, followed by a local intake fallback
if complete content delivery could not be established. No paid gRPC capability,
new provider, subscription or service tier was selected.

The configured program-filtered full notifications delivered the same whole
block for Pump, PumpSwap and Meteora. On captured slot 453933561 each notification
contained 1,207 transactions and 5,429,488 JSON bytes. Static and loaded keys
identified a union of 389 relevant transactions and 818 unrelated transactions.
The accounts-only representation also retained the whole transaction population.
The runtime continues using its existing single broad finalized block stream;
it does not subscribe to three duplicate broad full-block feeds.

The bounded minimal probe received `transactionDetails=signatures` and `none`
for the same finalized slot 453941925: 104,352 bytes / 1,145 signatures and
362 bytes / no signatures, respectively. Neither contained transaction bodies.
Three finalized `getTransactionsForAddress` calls then compared the existing
address index with the captured full-block census at slot 453933561. Pump's
239 returned signature identities matched the observed set, but the response
still had a pagination token and different ordering. PumpSwap and Meteora
returned empty terminal pages despite 143 and 51 known relevant transactions.
These observations do not establish complete near-tip indexed content coverage.
Silence, subscription ACKs, block headers and terminal index pages therefore
cannot authorize an empty relevant interval. The minimal stream/index combination
was not installed as the hot evidence source.

The implemented local fallback uses pinned `pysimdjson==7.0.2` to validate the
bounded provider JSON into a native tape. Python visits static and loaded account
membership and the identity needed for retained evidence. It immediately discards
unrelated transactions before canonical decode, canonical hashing, compression,
decoder IPC, SQLite storage or strategy processing. The entire JSON still requires
native syntax scanning; provider bytes and provider billing are unchanged.

Only retained evidence crosses the process-pool boundary. Pump/PumpSwap-only
transactions become compact signature/account/err/log projections matching their
existing canonical decoder inputs. Meteora and cross-program transactions retain
their full exact body because the existing tape consumes instructions and
balances. The normalized account list and membership index are reused after IPC.
Native parser proxies never cross that boundary. Duplicate routing/membership
keys and malformed input fail closed; no ambiguous input can hide relevant content.
Native object projection iterates key names before reading values, so excluded
transaction subtrees are never recursively materialized as a side effect.

The finalized block metadata, original receive time, relevant signature census,
canonical identities, event contents and ordering remain the original contract.
The existing gap detection, bounded repair, reconnect, persisted coverage and
restart paths are unchanged. Discovery breadth, migration, later Survivor
eligibility and open-position inputs consume the same canonical evidence.

## Measured residual source and local cost

The comparison below uses the exact same saved finalized block, not a live
benchmark or a CAPACITY attempt. The pre-intake implementation is the recovered
checkpoint. Twelve CPU samples per variant ran in isolated Python processes;
host contention and the small sample limit extrapolation. Worker serialization
measures arguments exactly, excluding process-pool protocol overhead.

| Measure | Recovered broad intake | Final selective local intake |
| --- | ---: | ---: |
| Provider JSON bytes | 5,429,488 | 5,429,488 |
| Full transaction bodies received from provider | 1,207 | 1,207 |
| Transactions checked for account membership | 1,207 | 1,207 |
| Full Python transaction bodies materialized | 1,207 | 51 |
| Compact Pump/PumpSwap log projections | 0 | 338 |
| Unrelated full bodies transferred to decoder processes | 818 | 0 |
| Python body JSON-equivalent bytes | 5,429,164 | 2,143,929 |
| Serialized decoder arguments, bytes | 5,429,728 | 2,240,283 |
| Serialized prepared result, bytes | 682,257 | 682,437 |
| Median CPU per frame, milliseconds | 335.982 | 256.078 |
| Intake / canonical median CPU, milliseconds | not separated | 58.888 / 195.497 |
| Peak process RSS, KiB | 66,124 | 73,548 |
| Canonical retained records | 147 | 147 |
| Canonical prepared bytes | 1,505,515 | 1,505,515 |

Source/upstream reduction is **zero**. The remaining source cost is the existing
whole-block delivery and bounded native syntax scan, plus account membership for
all transactions. That is a documented provider limitation under the owner's
revised local-fallback instruction. Local Python body creation, canonical worker
input and measured CPU fall. Peak RSS rises modestly because of the native tape;
the measurements do not demonstrate lower process memory. Canonical storage is
unchanged. The recovery-phase no-op writes, cache and archive reductions above
are separate storage improvements, not upstream savings.

The fixture SHA-256 is
`c58f12471e032a865467333567cc2a02fecd13664094f0835636902aa20a1dab`.
Both implementations produce canonical prepared facts SHA-256
`9220b1b01a755652f7a6e7a9e077fe82610b0b7e29c6803d4651d75277850a1f`.
The slight result-IPC increase carries bounded intake counters. Runtime
observations expose inspected/discarded/full/projected counts and intake CPU;
they do not perform additional JSON serialization or monetary work.

## Final verification and continuation

Fresh final validation, using CPython 3.12.14, SQLite 3.45.1, websockets 17.1
and pysimdjson 7.0.2: focused **236 tests PASS** (85.932 seconds),
FAST **480 tests PASS** (30.486 seconds), OPERATIONAL **1,910 tests PASS**
(603.266 seconds). The full suites include the 18 new intake tests as well as
gap/repair, reconnect/restart, duplicate delivery, finalized coverage, loaded
addresses, Current/Survivor independence, portfolio Decimal accounting and
retention/recovery regressions. An actual asynchronous worker/process-pool test
verifies unrelated bodies are absent from submitted work. The earlier final
validation was explicitly interrupted for a measured native-projection CPU
defect; its logs remain preserved and it supplies no final qualifying result.
The configured PAPER check and `git diff --check` passed. Read-only replay of
the preserved authoritative epoch reconciled at sequence 1,807, with $500.00
inception and marked equity, zero realized P&L, zero open positions/reservations
and zero pending deliveries. All 17 existing SQLite databases passed
`PRAGMA quick_check`; the authoritative portfolio file was unchanged. The 199
strategy/valuation/accounting files and the nine-rule audit were reverified.

The final source must be committed, independently recovered from its verified
full-ancestry bundle, published and read back from GitHub, then deployed and frozen
before a new 3,600-second CAPACITY phase. Existing economic state and the $500
inception remain authoritative. The configured Alchemy endpoint must satisfy the
owner's no-spend constraint before continuous provider traffic resumes. No
profitability, hour-long capacity or upstream bandwidth saving is inferred from
these offline results. Exact commit/tree, bundle hashes, deployment identity and
subsequent gate results are recorded in the external operational handoff.
