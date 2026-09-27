# Run 381 runtime repair and exact-source continuation

## Preserved market incident

Run 381 is workflow `36283232551`, exact runtime
`510872d8cc5d2fde2ae7ef412b5b31e5e4c1cfbf`, runtime ref
`cert/single-market-510872d8-20260927`, native run
`62cc8db0-7dbb-4f31-8c44-f998a7ac0341`.

The exact-SHA full non-market certificate was `36282701124`, artifact
`10918964949`, SHA256
`7293c62f81a88ae5463f6e3fa683aff8185c5d39d7adb4e6b2c1bfef37b5a51e`.
That certificate did not establish a successful market smoke.

Preserved primary artifact `10920300257` (1,040,944,957 bytes), SHA256
`ff203674a69dcc013c6a6f93c0da6848275c7c65e92a38d3ab595360291be6d9`.
Compact artifact `10919463707`, SHA256
`c24973e06a39d7d74f9dc0e92a4f3920d83d5bdef0b2a86f05bd78abf7f7a29d`.
Terminal artifact `10920060788`, SHA256
`fea527e8ad38450a9a6034075b4f2ddf5fb4c46400d96d22a63ef9cf00100eaf`.
Read-only preserved review `36284212647` and storage/SQL profiles
`36284344514`, `36284492925`, `36284720001` required no new market run.

Pump exited after 376.03 seconds; four-lane overlap was 376.02 seconds. All four
books were flat and reconciled, with zero PAPER entries. This was a failed smoke,
not evidence of poor strategy economics. The campaign ended HALTED with native
exposure flat. Hourly was skipped; successor, continuation and retry were false.
The Run 376 phase-authority repair held.

The prior receive/dispatch repair held and initial source lag was 10–11 seconds.
The hot DB plus WAL then reached 2,147,671,936 bytes against the unchanged 2 GiB
guard. There were three capacity stops, 20 unresolved gaps, 11,041 archived
records and zero compacted records. Dense address indexes and interrupted
maintenance prevented durable cleanup. Pump had 47 incomplete/gap-blocked local
reads; Meteora reported 162 reconstruction-incomplete candidates and 158
service-unavailable outcomes. Shared capacity failure must classify this as
infrastructure censoring even when a consumer completed no local reads.

The Run 380 Meteora candidate-release repair held: 12 completed candidates released
their interests; independent position leases remain protected. Pons Survivor
completed 120 active admission steps; Pump Survivor reached 14 successful steps
before shared evidence service failure. Policies and shared-sleeve authority held.

Pons' isolated public eth_getLogs 429 had zero unrecovered ranges and its sequencer
had 6,579 messages without gaps. Ramses had one block-request 429. These observations
do not justify provider or strategy redesign. Preserve successful Pons WAL repair,
governor limits, candidate fail-closed handling and provider topology.

## Measured defects and bounded repairs

1. Retention DELETE transactions repeatedly rolled back under urgent control work.
   Commit bounded slices of at most 256 records, then yield. Preserve lifecycle/gap
   pins, durability and priority 0/1 precedence. Rotate the next scope after a
   committed slice so recurring urgent arrivals cannot starve later scopes.
2. Archive planning/serialization/compression consumed the serial SQLite owner.
   Snapshot bounded immutable encoded rows and chunks, at most 1,000 records,
   with 4 MiB target / 20 MiB hard encoded bounds. Prepare, hash and publish using
   the existing two-process pool. Admit exactly one archive future. Recheck pins
   when committing the durable archive; do not remove a newly pinned hot body.
3. Repeated inflation and full decoded bodies across process boundaries wasted
   work. Reuse immutable decoded log chunks with a bounded worker-local cache;
   verify canonical bodies and return compact commit identities. Use lossless
   gzip level 1, fixed mtime and content-addressed fsynced publication. Provenance
   and evidence hashes remain exact.
4. Large index maintenance was inefficient. Add the partial archive-selection
   index and cluster address references by record. Preserve address-window
   indexing. Existing databases migrate atomically with a bounded disk-capacity
   precheck; failure leaves the original schema and references intact.
5. Cleanup was coupled to one archive completion. A pending archive worker could
   leave already archived indexes untouched. Run bounded retention independently
   on the same priority owner, with one cleanup request outstanding, preserving
   scope fairness. This adds no unbounded queue.
6. SQLite can report SQLITE_INTERRUPT after BEGIN IMMEDIATE has opened a write
   transaction. BEGIN previously preceded the cleanup try block. Move BEGIN inside
   it and roll back only if a transaction remains open, preserving the original
   exception when SQLite has already aborted. Separately, explicitly close an
   interrupted archive snapshot cursor even if its traceback is retained.
7. Successful gap-repair pages accumulated exponential retry delay as if they
   were failures. Healthy page application resets the next lease to one second;
   only failed attempts contribute to backoff. Preserve 16-page/48-attempt limits,
   provider governance and final-exhaustion coverage semantics.
8. Readiness now rejects shared storage-capacity stops with unresolved gaps even
   if local reads are zero. Healthy zero-trade/zero-qualifier runs remain allowed.

The 64-frame / 96 MiB receive bounds, bounded ordered commit, 2 GiB hot guard,
180-second retention, freshness/finality requirements, source authority, shared
Pump/Meteora evidence plane, provider limits and PAPER-only boundary are unchanged.
Numeric stage telemetry separates archive planning, worker preparation/publication,
commit, retention and repair application. Failure frames are bounded and omit locals.

## Reproduction and rejected candidates

The pressure replay uses immutable preserved public Run 380 bodies with explicitly
synthetic envelopes, identity suffixes and event-clock retiming. It is production
path offline evidence, not a claim of fresh authenticated market observation.
The fixed source sends 2,223 approximately 4.082 MB frames at 0.27-second intervals
(600.21 seconds; 9,074,297,113 bytes), crosses the actual retention age, exercises
candidate-local reads in all three Solana scopes, verifies every archive body/hash
and provenance, and checks integrity, admitted-frame drain and resource bounds.

- `36285115423`: old implementation stopped at 1,330 frames; first storage
  repair stopped at 1,512. Both rejected for capacity failure.
- `36285730058`: snapshot candidate stopped at 891 frames with SQLITE_LOCKED.
  Retained lazy cursor reproduced deterministically and repaired.
- `36286622706`: 1,967 frames; archive throughput still insufficient. Rejected.
- `36287585070`: full source replay completed, but review found 107,858 archived
  index records awaiting cleanup. Not accepted for certification.
- `36288470041`: old scope-starvation assertion reproduced; setup lacked a
  declared pagination test. Restored the exact test before continuing.
- `36288580636`: 104 frames, checkpoint lock; preserved result lacked a traceback.
  Added bounded causal instrumentation, without guessing the failing statement.
- `36288953260`: full replay completed, but 74,624 Meteora archived index records
  remained. Scope fairness alone did not remove archive/cleanup coupling.
- `36289392521`: real SQLite interruption matrix reproduced four checkpoint locks
  caused by an interrupted BEGIN during maintenance health, not an active SELECT.
- `36289794729` and `36290205393`: test-generation syntax and stdin process-spawn
  setup defects. Neither is counted as runtime validation. Expected-failure
  checks now require exactly one assertion failure and no test errors.
- `36290247458`, source `388d58942213378e6f3abb85544ad43ddf68560f`:
  old BEGIN and coupled-cleanup implementations fail the intended assertions;
  repaired 15 focused tests pass. Real SQLite matrix: 260 cases, 189 interruptions,
  zero open transactions and zero checkpoint errors.
- `36290462085`, source `d3c110aa9879f5e65dde02f574a2a32f99c2f93e`:
  eight readiness/certificate tests pass; canonical preparation verifies all four
  exact source identities and frozen policy bindings.

The full machinery certificate now requires the complete 600-second pressure
replay on its own exact SHA, including a no-pin oldest-retained-record bound of
240 seconds. A fresh stream frontier or timely body archival cannot hide an
ever-growing index cleanup backlog. It also retains all current native,
supervisor, crash/restart, resource, accounting, deterministic lifecycle,
six-regime, preserved-evidence and authority gates.

## Strategy and integration identity

Use the latest user-approved promoted strategy base
`4ab66653a23475a72abe88bc96adf9f6e0b7fd9a`, certificate `36273166496`.
The runtime repair parent is the failed-smoke, fully certified
`510872d8cc5d2fde2ae7ef412b5b31e5e4c1cfbf`.
No strategy threshold, target market, lifecycle, allocation or risk gate changes.

Exactly four lanes and six active PAPER regimes remain:
Pump current + Pump Survivor, Pons current + Pons Survivor, Meteora and Ramses.
Both Survivors retain independent attribution/accounting and 25 bps target
allocation within their existing sleeves; no additional portfolio capital.
Authoritative hashes remain in sources.json and profitability_protocol.json.

Composed native diffs:
- Pump: `084b1b627101073f2f8ea0f93b761fb5da9a80cae54ebb16a28b2d4abdaec22f`
- Meteora: `c3bc023d66e9843ba17ee6a122bcb4b3c414423d62688a368e12bb449ce3a457`
- Pons unchanged: `f80a6965e7ae2b4a4ca3c7ebace88b0a6caf06920c8dc7c847bd703bf7e56bbd`
- Ramses unchanged: `255e286c4f2544127cbce9d3303eb4634da2c09aa48f4cc9396d3923fe597092`

The local execution workspace disconnected during this repair. Exact source,
regressions and artifacts were preserved and verified using provider-free GitHub
Actions. No credential, permission, signing or deployment boundary was changed.
A full exact-SHA certificate, one reviewed smoke, exact-SHA promotion and a
separate final live-market PAPER run are still required before completion.

## Stable mature-pressure result

Workflow `36290347538`, source `ff140989cb0982d930b29f86b512cd730cafb825`,
artifact `10921354151`, SHA256
`60e550f44b8eee35d921038c09c6590716250c64f39be21bc0bc37aa80ff87d8`.
Result JSON SHA256
`ff64c2cf7145d1fb9830e2e91f8a9732af0e949847772ac14f94b28e56b101a1`.

All 2,223 frames completed, 9,074,297,113 source bytes over 600.21 seconds.
Zero runtime disconnects, rejected frames, capacity stops or unresolved runtime
gaps; the three final gaps are explicit normal service-shutdown boundaries.
60 candidate-local checks completed across Pump, PumpSwap and Meteora.
All 2,224 admitted messages (including acknowledgment) drained durably.
Peak outstanding frames 7/64; dispatch bytes 28,574,035/100,663,296;
commit batch 16,328,020/16,777,216. Peak source lag 2.275 seconds.
Hot DB/WAL peak 980,405,984 bytes, below the unchanged 2 GiB guard.
Oldest hot body 183.50 seconds; oldest retained index record 183.75 seconds.
411,312 records archived, 410,963 compacted, only 349 awaiting compaction
(Meteora 128, Pump 51, PumpSwap 170). All 414,968 published archive records
verified canonical hashes and provenance; SQLite integrity was ok.
Total runtime including archive verification was 678.64 seconds.
This is the first reviewed mature replay to remove the observed cleanup debt.
It remains offline evidence and does not replace full exact-SHA certification
or a successful natural-market PAPER smoke.

Supporting standard CI `36290462108` passed 731 tests (12 skips), resource
checks and synthetic lifecycle. This is not the four-lane full certificate.

## Full-certificate archive throughput failure and measured follow-up

The candidate `7854901becf9af529c9a774f7350f271d2fd75ff` did **not** certify.
Full workflow `36290961701` passed 376 supervisor tests, all 1,694 native tests,
SIGKILL/restart, integrated acceptance and resource checks, then failed the mature
pressure gate. Artifact `10922502269` has SHA256
`c65a85bca388412ec37d27f89efd7daa20f98c5b26bd5d8a65d834c08423eca4`.
Digest-verified review `36291981425` preserves the causal result.
At 1,560 frames, oldest retained evidence exceeded 240 seconds. Archival lag grew
from roughly 180 to 239 seconds despite healthy source processing; hot storage
peaked at 1,279,760,912 bytes. There were no runtime gaps, capacity stops or lost
admitted frames. This is insufficient maintenance throughput, not strategy
rejection. The preceding standalone pass cannot override the failed full gate.

Bounded stage instrumentation in `fc2dd3d5d58f1e26b8ada9b66b56b61e1aff56bb`,
diagnostic workflow `36292139263`, measured roughly 94 seconds waiting for health
owner work over 459 seconds. Those waits serialized the same coroutine that
committed and submitted archives. CPU profile `36292392237` independently showed
that repeated JSON parsing/serialization consumed over half of archive-worker
CPU; fsync was a small share. These measurements motivate two narrow repairs:

- A separate health coroutine has at most one outstanding owner request and
  retains existing priorities, storage checks, failure propagation and cadence.
  Health scheduling cannot stall the single bounded archive pipeline.
- The archive worker reuses canonical hot-body/log bytes. Each raw log chunk is
  hash-verified and cached only within a 4 MiB snapshot-local bound. Only the two
  existing chunk-reference paths are eligible; ambiguous marker lookalikes fall
  back to ordinary decoding. Substitution is one pass, so inserted content is
  never reinterpreted. The complete reconstructed body hash is checked before
  credential scanning and durable publication. Archive bytes remain identical.

No queue, pressure, retention, freshness, authority, policy or allocation bound
changes. The source/decode pool remains two workers with one archive in flight.
Existing finality, gap pins, late lifecycle pin rechecks and idempotent commits
remain intact.

New regressions prove repeated health yields cannot starve archives and eliminate
full-body JSON churn on shared log chunks. Both fail the preserved implementation
with one behavioral assertion, rather than an import/setup error. Nineteen focused
cases pass, including exact archive bytes, Unicode/escaped content, legitimate
marker lookalikes, nested marker content, missing/corrupt chunks, full body hash
mismatch, bounded cache, partial worker budget, late pins, duplicate commits,
SQLite interruption cleanup, retention fairness and repair pagination.

The repair is under full 600-second provider-free pressure verification in
workflow `36293113748`, source `a77090e551efed37afc339dbe55e8233ae0deed2`.
This source is a diagnostic candidate, not a certificate or market authorization.
The integrated Pump native diff is
`e71882fe9f7dedb1a6fce15c0e1bf1e4f7c15e70b4c578c5adc73e591951c5f0`;
Meteora is
`973cf8f30efff6a1d63f062f703a9544bc87a00f37b59427e9289f5e38e95e80`.
Pons/Ramses diffs and all six regime policies remain unchanged.

### Follow-up sustained-pressure acceptance

Workflow `36293113748` completed successfully. Artifact `10923585351`, SHA256
`47705e33740ec44c070245c7b21bdf891a5d27dfbf50df1bd29056e8df32e59f`;
result SHA256 `742c7797c6476370fbc47e6505dd6df569b11f8a3b6072be1bd7e4c7ea537afa`.
All 2,223 frames / 9,074,297,113 bytes completed over 600.21 source seconds.
No runtime disconnect, rejected frame, capacity stop or unresolved runtime gap;
all 2,224 admitted messages drained. Final gaps were the three explicit normal
shutdown boundaries. Candidate evidence progressed in 59 three-scope checks.
Peak source lag 1.808 seconds; 3/64 outstanding frames; 12,246,015/100,663,296
queued bytes; 4,082,005/16,777,216 commit bytes. Hot DB/WAL peaked at
989,012,352 bytes. Oldest hot body was 183.54 seconds and oldest retained index
record 184.50 seconds; no growing archive or cleanup debt. 411,312 records
archived, 410,171 compacted, 1,141 in bounded pending cleanup at shutdown.
All 417,800 published archive records verified hashes and provenance; SQLite
integrity was ok. The artifact digest and runtime source hashes were independently
verified against this integrated candidate before selecting it for full certification.

Standard CI `36293113700` completed 734 tests (12 skips), resource and synthetic
lifecycle gates on the diagnostic tree. Canonical four-lane preparation, exact
native source integrity, protocol freeze, six-regime integration and eight
readiness/certificate regressions passed locally on the integrated tree.
This is still not a full certificate or a natural-market success claim.
