# Pump restore metadata acquisition

Base: `780f4015efd9fba528e97223f8e8e3b1a7322e12` (tree
`7646978bbfb2076aea90625c3c4a32cd4556491c`). This is a separate offline component.
It grants no funding, historical completion, deployment or normal-start authority.
The stopped read-context draft and unrelated Pons repairs are unchanged.

## Supported cause

AWS combined diagnostic `39085764934` stopped after 429.580 seconds with operation
recorder coverage lost. Retained forensic read `39086632466` identifies the same
installed source and a **partial**, cancelled Pump restoration: 8,096 candidate
calls, 247.948019 seconds wall / 45.123935 seconds CPU, with 110.618080 seconds in
selected statements and 103.480503 seconds in fetches. Its parent restore was
cancelled at 275.072 seconds. The captured stack reached the original scalar
fallback. It does not identify the fallback reason or a completed population.

The stopped eight-candidate sample contains 291 references: 227 TEXT, 64 cold,
no SEP1 and no missing record. That is not the live restore population. It has no
hot TEXT byte-size distribution. Current indexed scalar query plans do not prove
that the 128-key acquisition was cheap under the live writer and cache conditions.
No claim is made that this defect explains the whole restore or the source's
remaining capacity deficit.

The exact SQLite 3.45.1 discriminator shows a concrete avoidable read. Original
metadata selects `length(CAST(body AS BLOB)),hash,archive`. CAST prevents SQLite's
length-only column optimization. Merely changing to `octet_length(body)` still
walks rich-body overflow pages to reach trailing hash/archive columns. The safe
read decomposition is therefore:

1. Select only `identity,octet_length(body)` through the unchanged canonical view.
2. Admit unique hot identities under the original remaining encoded-byte budget;
   fetch their complete original body/hash/archive tuples.
3. For identities whose **first** canonical body is NULL, separately fetch their
   original hash/archive tuples and manifests, in the same SQL snapshot.

No index, schema, writer, persistent cache or cross-call authority is added.
Canonical precedence and first matching row remain unchanged. Every record still
passes the original reference, content hash and source/path checks. Cold archive
reuse retains all original per-reference manifest/stat/hash validation. Encoded,
prepared, reference and chunk budgets, original-order scalar fallback, cancellation,
FULL/ACK, and the cooperative 25 ms snapshot target remain unchanged. Snapshot
rollback still precedes decoding and cold-file I/O.

## Exact 3.45 measurements

The authenticated DSO is SQLite 3.45.1, SHA256
`e6b6daa1908cc4ebb2a2275fd771c26ef13a23ace38f4681e4fcf7bb09075b09`.
The first discriminator reproduces the exact source canonical view and four base
tables, with one 8 MiB BLOB and one 8 MiB Unicode TEXT, plus absent requested keys.
All branches use indexed SEARCH, with zero full-scan steps. Metadata values agree.

| Metadata arm | Thread logical read bytes | Read syscalls |
| --- | ---: | ---: |
| Original CAST + hash/archive | 16,821,546 | 4,110 |
| Direct octet_length + hash/archive | 16,814,209 | 4,108 |
| Identity + octet_length only | 20,609 | 8 |

The full acquisition probe executes the actual base `_source_rows` method and
its successor against the same 16,838,656-byte private fixture, with 128 references
to three unique identities (two rich bodies and one cold identity/manifest). It
compares complete typed body digests, hashes, archive metadata, first-match order,
fallback state, remaining budget and released snapshots. It does **not** decode
native economics or read the actual archive; genuine native FULL/ACK and codec
behavior are covered by the focused tests.

| Full acquisition, ABBA order | Logical read bytes | Read syscalls | Wall ms |
| --- | ---: | ---: | ---: |
| Before | 33,622,493 | 8,212 | 21.861 |
| After | 16,829,746 | 4,112 | 35.300 |
| After repeat | 16,829,747 | 4,112 | 16.758 |
| Before repeat | 33,622,495 | 8,212 | 18.054 |

All four output hashes are
`a6f3af68abb7e191c9bf2e626cf7b1c4712a8673240113dd0368924ea020b668`.
The full read reduction is approximately 50%; the mixed wall timings establish
**no wall-speed improvement**. Each arm uses a fresh read-only SQLite connection;
no OS-cache eviction is claimed. Physical reads are zero. Short VM executions
can exceed the cooperative 25 ms wall target without a callback, as before.
This probe does not reproduce the 25 GB AWS store, actual body geometry, concurrent
writer contention, actual fallback frequency or sustained market processing.

Retained evidence in `/workspace/recovery-evidence/`:

- `pump-restore-metadata-345-discriminator.json` preserves the failed octet-only
  optimization hypothesis; `pump-restore-length-only-345-discriminator.json`
  SHA256 `426d97905be9468be85ec5319f68ccdd617bc07108adf5adff184bca9e5fcb73`
  contains the length-only discriminator.
- `pump-length-only-complete-acquisition-345.json`, SHA256
  `27513e0cee64731e6323ce3c35183875fd1c7d333030e60ac690c8e1488b67dd`.
  Its fixed probe is `engineering/diagnostics/pump_restore_metadata_345_cost.py`.
- Initial test failures remain in `pump-length-only-initial-focused.log`
  (`/tmp/mm-engineering-kx5zl2tw`) and `pump-length-only-corrected-focused.log`
  (`/tmp/mm-engineering-yxozpnp0`): stale test insertion/query-count assertions
  and a writer fixture that updated the wrong canonical predecessor table.
- The first 181-case adjacency run in `pump-length-only-final-focused.log`
  (`/tmp/mm-engineering-1uz26qow`) passed 180 cases and exposed the old test's
  fixed two-name Pump diagnostic expectation. The replacement asserts the exact
  seven-name population and retains all unknown-name rejection checks.

## Fixed diagnostics

Existing opt-in operation costs add five fixed inner spans: metadata, hot bodies,
cold metadata, manifests and chunks. These perform no runnable/proc sampling.
Selected SQL now belongs to those innermost spans; parent operation wall totals
still overlap child totals. Parent SQL totals must not be compared alone with an
older source that attributed all this work to the parent.

A fixed numeric `restore_reference_counts` map is buffered per page and merged
once in the page's `finally`, through the same existing health snapshot. It counts
flushed started/completed pages, references, source groups, selected hot keys and
encoded bytes, selected cold keys, and actual scalar source reads. Selection is
admission, not a claim that the later SQL or decoding succeeded. First fallback
reason is counted once per reference: raw size, parse/hash, reference shape,
source snapshot expiry, source read/path error, encoded-byte budget, prepared
budget, preparation error, chunk shape, chunk snapshot expiry, chunk read error,
or chunk budget. A reason describes the reached code branch, not physical I/O,
locking, rich body class, full event readiness or a fabricated first source error.

No paths, arguments, payloads, candidates, hashes, exceptions, histograms or new
per-record process/provider queries are recorded. Diagnostic opt-out performs no
new timing/proc probes and keeps no page count dictionary. Empty count population
means UNEXERCISED. An active page is absent until it flushes; a killed process can
lose it. A completed page means the original iterator completed, not native
recovery or historical completion. Recorder validity and original failure stops
remain mandatory. Counters are diagnostic observations, never an admission gate.

## Remaining operational validation

A future exact-source rehearsal must measure actual completed restoration and
these page/fallback populations, complete source throughput/backlog, Pons behavior,
resources and genuine shutdown. Its original financial/native readiness and
source authentication remain required. The latest retained financial evidence
was sequence 16,391, cash $1,000 and flat, with funding closed and two unresolved
historical handler outcomes. This component never opens that financial state.
Full release suites and one-hour authoritative PAPER acceptance remain separate.

## Focused validation

`pump-length-only-frozen-focused.log` records **181 PASS in 14.382 seconds**, no
skips, through the original OPERATIONAL driver and network guard. Exact modules:
prepared evidence decode, restore reference pages, startup archive reuse, Pump
restore cost attribution, retained canonical reference, CandidateHistory, retained
reference path walk, run370 storage, operation costs, Pons operation costs,
operation-owner hooks and SQLite failure attribution. These exercise real native
FULL/ACK/cold restoration plus chunks, legacy Unicode, first-match duplicates,
NULL bodies, malformed payload/error order, stored-hash failures, byte admission,
source/reader ownership, WAL writer advancement, restart and cancellation.
The recorder assertions distinguish cancelled incomplete pages from fallback and
show fixed stage counters perform no scheduler sampling.

`pump-length-only-counterfactual.log` replaces only `_source_rows` with the exact
780 method under original Scratch/network guard: both selected regression cases
fail as expected (2 failures, 0 errors), preserving `/tmp/mm-engineering-9kdffd80`.
The actual I/O counterfactual is the independently recorded pinned-3.45 query and
complete acquisition A/B above; structural query assertions alone are not a disk
performance proof. No complete release suite, production state, provider, AWS
workflow or kernel profile was exercised by this component.
