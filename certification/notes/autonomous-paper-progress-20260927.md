# Autonomous PAPER runtime task — current evidence

Starting integration: `repair/run377-runtime-six-regime-20260926`,
`075f1e5cc6fc3e809e30682041461aa97c75c334`. Remote refresh confirmed the
handoff. Latest full certificate `36297528197` failed retention pressure;
standard CI `36297528132` passed. Latest successful full certificate before
these repairs: `36282701124`, source `510872d8cc5d2fde2ae7ef412b5b31e5e4c1cfbf`.
Latest market-connected workflow remains Run 381 / `36283232551` at that SHA.
No queued or running workflow existed when this task began.

## Frozen strategy authority

`certification/autonomous_paper_task_manifest.json` records all four lanes and
six regimes. The promoted ref was refreshed at
`4ab66653a23475a72abe88bc96adf9f6e0b7fd9a`; successful strategy certificate
`36273166496` independently confirmed. Current frozen strategy hashes,
directional sleeve allocations and portfolio construction exactly match that
approved generation. The exit audit did not establish a subsequently approved
and promoted policy change. No policy or allocation changes are authorized here.

## Phase A observations — no causal conclusion yet

Original successful standalone artifact `10924736061` has SHA256
`8299d7ae2224dbb10254b844323dc4644455445b3dbc89036e99b2d934bff9b1`.
Failed full-certificate artifact `10925051726` has SHA256
`d62ef9426113a5f9906b5a2cafd9af9334296ff6e3a3e665ce51c49a7143d890`.
Local preserved ZIPs matched both independently retrieved artifact digests.
Five production runtime file hashes and the pressure harness/fixture/IPC harness
bytes are identical across the compared sources. Hosted runner image and Python
versions match, but the jobs ran on distinct hosts in distinct Azure regions.

Failure starts when archival becomes mature, around source second 180.
Decoding was faster in the failed run (182 versus 241 ms/message). Retention
averaged 238 versus 110 ms/call. Archive commit/plan execution averaged 145
versus 56 ms, with owner queue waits averaging 733 versus 170 ms. Existing
process snapshots show no obvious surviving busy child from preceding suites.
Those measurements narrow the issue but do not establish the cause.

Diagnostic commit `6467c9290bddf9707f564062e4d2f7c1d2b45667` adds bounded
SQL wall/thread-CPU timing and process I/O/memory/filesystem measurements only.
Standard CI `36300927068` passed. Focused diagnostic `36300927115` compares
600-second measured-contention pressure before and after the preceding resource
workload on the same hosted runner. No full-certificate retry or market launch.
Production runtime bytes, source cadence, contention floors, retention, storage,
freshness and finality acceptance bounds are unchanged.

The retained-age observer currently scans the full payload-bearing records
table on every poll. An independent 12,000-row diagnostic returned the same
minimum timestamp via the existing scope/time index while requesting 2.56 MB
instead of 39.42 MB from SQLite's file reads, including null timestamp fallback.
This is a hypothesis about unnecessary observer I/O, not yet a demonstrated
explanation of the full-certificate failure.

Local baseline replay passed all 2,223 frames / 600.21 source seconds with the
same five runtime hashes as both original artifacts: 3.091-second peak lag,
972,034,248-byte hot peak, 182.800-second oldest hot age, 184.018-second oldest
retained age, 59 candidate checks, 411,520 archive records hash-verified, and
2,224/2,224 admitted/committed messages. Elapsed including verification: 698.47s.
This is a source-hash diagnostic replay, not an exact-SHA certificate: the local
checkout advanced from the starting source to the diagnostic commit while the
already-loaded original harness ran. The hosted comparison remains the required
controlled diagnostic, and Phase A remains open.

The controlled hosted comparison reproduced failure on the fresh runner before
the resource prelude (06:43:28–06:51:15Z). Prior-suite residue is not necessary
for that instrumented failure. The post-prelude comparison remains in progress.

A candidate observer-only fix explicitly reads the existing scope/time index.
The exact MIN(COALESCE(market_time,first_seen)) expression still includes hot,
archived and null-clock rows. No production index/schema/cache/limit changed.
The new behavioral I/O regression fails the old query at 39,415,945 requested
bytes against an 8,122,368-byte bound and passes the repaired observer. Empty,
mixed-hot/archived and null-clock semantic checks pass. This candidate does not
yet establish the hosted failure's causal attribution or close Phase A.

The controlled diagnostic completed as failure. Artifact `10925412135`, SHA256
`8a46e30db806ca5d6d1a34515714c4072163ff8bc64ad291466e1e364665230b`,
was downloaded and verified. Before: archive-age failure at 466.2 seconds;
after: source-clock failure at 454.7 seconds. Memory was available (roughly
14 GiB), physical input stayed near zero, and preceding resource workload
did not cause a material difference. This does not support cold-read pressure
or leaked prior-suite processes as the explanation.

The old observer alone used 83–85 wall seconds / 81–83 CPU seconds. By source
second 362 the process requested about 200 GB of reads. However this diagnostic
also timed over six million individual SQL statements. A local replay with
the indexed observer but that detailed profiler showed lag after maturation,
where the uninstrumented local baseline passed. Those instrumented failures
cannot independently establish native runtime capacity. Stage-level v2 removes
per-record clocks/counter updates and retains only source/maintenance stages,
commits/checkpoints and the age observer. A deterministic regression requires
one timed call for a thousand record INSERTs plus their COMMIT.

The next controlled comparison uses stage-level v2 on one runner, indexed first
and legacy second, both at all 2,223 frames / 600.21 source seconds with identical
contention floors and unchanged runtime. It makes no market/certification claim.

The stage-level v2 comparison `36302144874` on exact SHA
`d6a7645639b6abed245887191ae5f2404367f359` passed BOTH variants. Artifact
`10925634877` was verified against SHA256
`28cbe79ab678fa804786e81f77d71af5119f7aa625e7a5271a4436ef891d1534`.
Indexed versus legacy: observer CPU 18.94 versus 87.90 seconds; requested reads
141.25 versus 405.62 GB; peak lag 1.69 versus 1.95 seconds; retained age 183.37
versus 183.47 seconds. Both processed 2,223 frames and verified 411,840 archive
records. This disproves the observer query as a sufficient causal explanation.
The observer repair is preserved, but Phase A is NOT closed from this pass.

Canonical, uninstrumented local pressure on that same exact clean SHA passed:
2,223 frames / 600.21 seconds, peak lag 3.288 seconds, hot peak 973,230,112 bytes,
retained peak 184.183 seconds, 59 candidate checks, 411,840 verified archive
records, 2,224 admitted/committed messages, integrity OK, zero provider calls.
Result SHA256: `1923a0df9f0cb057f75758fd481ec288219c85732a2db563878544a3abf3d465`.
Standard CI `36302144866` passed all 748 tests, resource and synthetic lifecycle.
Four prepared lane worktrees passed exact source-integrity comparison.

The remaining measured difference is durable owner latency, not decode speed.
Original full-certificate health publication averaged 37.84 ms; the new paired
runner averaged 2.82 ms. Real production health publication performs SIX changed
outer commits. A focused production-method probe at 7.5 ms additional commit
latency measured 46.36 ms per publication versus 7.94 ms when enclosed in one
outer transaction (same fields, no source change). The next diagnostic adds a
bounded 6 ms latency per changed commit, derived from (37.84 - 2.82) / 6, and
compares existing health against that atomic-publication prototype at full
600-second pressure. This is an offline causal experiment, not certification.
No-op reads and rolled-back writes incur no injected delay. Five focused probe,
observer and instrumentation checks pass. Production runtime remains unchanged.

## Recovered lineage and mandatory later control-plane proof

Preserve Run 377's repaired process/provider/bounds issues, Run 378's preflight
repair, Run 379's source conformance/Survivor graduation repairs, and Run 380's
serial persistence corrections. Run 378 stopped before meaningful market work.
Run 381 exposed storage/archival/retention pressure after earlier phase-authority
and transport repairs held. Do not reopen these without a regression.

Prior accepted campaign `35949285193` automatically launched continuation
`35956802640`. Reuse proven continuation and native ledger machinery. A separate
later failure showed that correct POSITION_CONTINUATION state is insufficient
when GitHub cannot dispatch `position-continuation.yml` from its registered
workflow surface.

Phases C/G must therefore verify both normal campaign successors and actual
position-only continuation dispatch on the final SHA. Carry SHA, policy manifest,
authorization, campaign, lane and position identity; reject duplicate, stale,
wrong-SHA and wrong-campaign requests. Recover durable intent across a restart
between terminal handoff and dispatch. A position-only continuation may monitor,
recenter, partially realize, stop, exit and settle existing positions, but grants
no discovery/qualification/new-entry authority. Do not equate state-machine
tests or historical success with current real control-plane validation.

Phase A remains in progress. Phases B–G have not yet been executed for this task.
PAPER ONLY; no signing, submission, live money, deployment or Render interaction.
