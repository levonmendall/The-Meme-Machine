# Pump restoration reference acquisition

This component is based on application `54dc2fa1e61c09c3c84749d550a4d06305561b54`.
It reduces repeated canonical-source acquisition during the existing cancellable
Pump startup pass. It does not prove AWS throughput, reconcile historical work,
create coverage, acknowledge callbacks, or authorize PAPER operation. All work
here used disposable offline state; no financial database was opened.

## Observed cause and scope

Protected profile `39070080581` describes AWS rehearsal `39067324778`, exact
application `99a9d8faca4d75e9e1de7c03cbe221f95312359f`: restoration took
550.719s; its 14,309 events calls took 540.521s wall / 162.797s CPU.
Selected statements/fetches consumed 413.259s wall / 34.892s CPU, with 3.803GB
physical reads. Subtracting the two per-candidate queries leaves 380,201 combined
canonical/manifest/chunk lookups, not a count of unique references. There were
about 93 statement/fetch API calls per candidate. The retained profile does not
identify the actual hot/cold/chunk distribution or establish lock waiting.

Normal CandidateHistory already retains one source connection per path. This
change addresses repeated point acquisition, not fictional reconnection.
The earlier transaction-only prototype did not demonstrate a wall improvement
and was not landed. Different AWS restoration populations are not an A/B pair.

## Read ownership and invariants

`candidate_restore_reads.RestoreReferenceReader` is explicit, thread-owned, and
limited to one Pump startup pass. The runner binds one cancellation callable and
one existing cold-archive dictionary; `events` checks those exact owners. Normal
`events` calls retain the existing scalar path. Existing normal source readers,
progress handlers, and caller-owned transactions are never borrowed.

The new reader uses one private read-only source connection at a time. A bounded
SQL snapshot reads canonical byte lengths, selected bodies, and matching cold
manifests through the unchanged canonical view. It rolls back before parsing or
cold-file I/O. A second short snapshot reads only chunks named by the actual
SEP1 marker paths, with byte admission before fetching their BLOBs. Canonical
and chunk content hashes provide the immutable seam between those snapshots;
there is no data-version retry or freshness/coverage authority. Missing retained
chunks still fail. Source garbage collection between phases can expose that
genuine failure; it never becomes an empty result or a fabricated chunk.

Every reference still performs its original strict source/path and expected-hash
checks. Cold reads retain per-reference manifest/path/stat/hash validation, the
existing one-archive reuse slot, and lazy ordered first-match selection. Bulk
view reads keep the original first matching row, not dictionary last-wins.
The original candidate query order and final economic-event sort are unchanged.

Acquisition admits at most 128 references, 32MiB combined encoded source/chunk
bytes, 4MiB raw reference JSON, 4MiB successful prepared outer JSON, and 4MiB raw
decoded-log cache bytes per page. These are encoded/raw byte budgets, not exact
RSS bounds: Python object overhead, one lookahead row, an individually oversized
scalar unit, returned event ownership, and the original archive slot remain.
Large valid units use the original scalar path rather than a new rejection cap.
The 25ms SQL cutoff is cooperative at the SQLite VM progress callback; it is not
a hard wall bound for short statements, copying, busy/open waits, or Python work.

Failed speculative parsing/acquisition drops rich exceptions and partial buffers,
then reproduces the scalar result/error at that reference's original turn.
This preserves error order without retaining inflated JSON exception documents.
Each prepared outer is parsed once per reference and consumed once. Completed
lookups detach their prepared/buffer ownership before yielding. Only exact flat
string log lists are cached, with independent list copies on store/load. Other
valid JSON chunk shapes remain uncached. The ordinary decoder keeps its existing
TEXT/scalar/literal-marker behavior and 16MiB compressed-inflate limit.

The codec is a changed transitive dependency, not a byte-identical old blob.
Exact-source approval must review its prepare/finish factoring and the new reader
alongside CandidateHistory/runner; this component changes no approval allowlist.

## Fixed native workload and results

`pump_restore_reference_cost.py` creates native decoded Pump frames, publishes
candidate references through actual FULL delivery/ACK, retires them, restores
twelve of sixteen candidates hot, and relocates the retained source to a private
AWS-style root. Every measured pass restores the same 1,024 references while an
independent native writer commits exactly 64 FULL control updates and executes
eight PASSIVE checkpoints. Writes occur before every sixteenth reference's body
validation, after bulk acquisition for its page; this does not claim a writer was
scheduled inside every brief SQL acquisition. Network and foreign database/file
writes are refused. The main native corpus has no hot chunks; chunk equivalence
is covered by the focused real-SQLite cases, not a representative chunk benchmark.

Final benchmark generation:
`40e94022fdea0ea11b94418a95322ca2a722efe67cae7fbe3c54ddddbce457bb`.
Corpus hash:
`0079a11deb00ea0d7bcde5fcf10be5356d9d6ead8a31a8bbba75195ed449fa1f`.
Every final pass produced output hash
`d5170c613844af90ae66a03703578069fec9e798907d7b95d264eb8295ea0eb1`.
Both versions kept consumer tables unchanged, with 384 FULL commits / 48
checkpoints across six passes and zero checkpoint busy/backlog counters.

Final receipts under `/workspace/recovery-evidence/` are
`pump-reference-batch54-owned-before.json` and
`pump-reference-batch54-owned-after.json`.

| Per-pass median | Original | Final bounded reader |
| --- | ---: | ---: |
| Wall seconds | 0.260698 | 0.260720 |
| Process CPU seconds | 0.258598 | 0.257940 |
| Main-thread logical read bytes | 7,828,064 | 3,736,160 |
| Main-thread read syscalls | 1,985 | 986 |
| Canonical source queries | 1,024 | 28 |
| Cold-manifest queries | 256 | 4 |
| Selected statements | 1,312 | 64 |
| Selected fetch calls | 2,336 | 1,860 |
| Selected statement wall microseconds | 16,584 | 5,744.5 |
| Physical read bytes | 0 | 0 |

The query/read reduction is repeatable; end-to-end wall improvement is not
established. Warm-cache physical reads were zero, unlike the actual AWS workload.
Earlier paired receipts showed both improvement and regression and are retained:
`pump-reference-batch54-before/after.json` and
`pump-reference-batch54-final-before/after.json`. One observation-only ABBA
discriminator (`pump-reference-batch54-gc-A1/B1/B2/A2.json`) kept GC enabled and
found pooled medians 0.257086s versus 0.259467s. It also exposed avoidable
copy-heavy allocation: B had 83.878ms aggregate GC wall across twelve passes,
versus A's 9.464ms. The final one-shot-outer correction reduced the six-pass B
GC total to 9.147ms (A 3.175ms). Other timing variation remains unexplained;
no favorable subset is substituted for the final neutral-wall result. AWS benefit
requires a separate exact-source rehearsal after the concurrent Pons repair.

## Validation and remaining release work

The supported OPERATIONAL driver ran 104 affected reader/history/storage cases,
all passing in 9.677s. Exact modules:

```
tests.test_prepared_evidence_decode
tests.test_restore_reference_pages
tests.test_startup_archive_read_reuse
tests.test_pump_restore_cost_attribution
tests.test_retained_canonical_reference
tests.test_candidate_history
tests.test_retained_reference_path_walk
tests.test_run370_storage
```

The retained receipt is `pump-reference-batch54-final2-owned-focused.log`.
Cases include actual FULL/ACK cold/hot parity, duplicate first-match semantics,
missing/corrupt chunks, error order, metadata/encoded/prepared scalar fallbacks,
rich-exception release, nested valid JSON, between-yield mutation isolation,
large uncached chunks, per-reference cold-file changes, cancellation/rollback,
foreign-owner/transaction refusal, restart, flush, and commit rollback.

An expanded 209-case run also encountered 44 subtest errors in the unchanged
retirement hot-byte forced-index query (`no query solution`, SQLite 3.53.1) and
one unchanged candidate-publication FIFO assertion. Both exact representative
cases reproduced on untouched 54dc. Those failures remain unresolved; they were
not repaired or silently excluded from the expanded receipt. Evidence:
`pump-reference-batch54-focused.log`, failure scratch
`/tmp/mm-engineering-k1_6nm1f`; baseline comparison
`pump-reference-batch54-baseline-failures.log`, scratch
`/tmp/mm-engineering-uvxuoze6`. Earlier fixture failures and intermediate positive
receipts remain preserved as well.

Independent read-only review covered the reader/history/runner ownership,
authentication, error order, memory admission, and snapshot cleanup. The codec
author did not independently approve their own codec slice. Full release suites,
source approval, AWS deployment and capacity acceptance have not been performed
for this local component.
