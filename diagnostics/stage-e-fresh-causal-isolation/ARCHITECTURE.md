# Fresh Stage-E runtime reconstruction

PAPER ONLY. Stage E is RED; Stage F has not started. This is a diagnostic, not
a qualification candidate or a production repair.

## Authority and lineage

Runtime source: dc08f9064cf5e37b63f383f52aa709d0afc1723f.
Runtime tree: 68736cf664169dee665762019800bf87ca0f1f67.
The fresh diagnostic branch is a real descendant of that commit.
06f7a129eb9a1deab02af5f1f6bdfbaea89ea142 (tree
90839dfc47c1665e8d84eea62e6ba95e5e369efd) is a different, rejected historical
qualification identity. It is not needed or used as a parent.
5b8b749e3da8dfcb496b2ba3c1d242ab0cf7947f is a diagnostics-only paper record.
No lost Pro workspace, database, capture, traces, objects or scripts are inputs.

All references below are relative to the exact runtime commit above. CI compares
every preexisting blob and mode against it before executing any material variant.

## Canonical local workload

- certification/maintenance_qualification.py: PLAN_PATH and qualification()
  wire stagee24_qualification_plan.json, LifecycleObserver, durable-window-v4
  Interaction and strict hot/retained age acceptance into cleanup_recovery.
- certification/stagee24_qualification_plan.json: combined-1/2/3 have 2,223 frames;
  recovery-1 has 4,445 frames, 1,200.15 source-seconds; snapshots every five wall
  seconds; burst coordinates 216 and 378; 1,000-record envelope; 120-source-second
  recovery. This fresh diagnostic runs one derived profile, not that cohort.
- tests/test_run380_production_pressure.py:12-34, Wire: preserved public templates
  in certification/tests/fixtures/run380-production-templates.json.gz produce
  128 Meteora, 48 Pump, 80 PumpSwap and 256 failed filler transactions per frame.
  Unique synthetic signatures, slots and linked hashes are fixed by frame index.
  Source due time is start + frame_index * .27, before receive/backpressure.
  blockTime is integer due time. ACKs are transport barriers, not source frames.
- certification/run381_pressure.py: Wire retimes known binary event timestamp
  fields to blockTime; preserved economic bodies on disk are not edited.
- certification/cleanup_recovery.py:253-301: eight-second pauses at sent frame
  800/1,400 preserve cancellation-stable deadlines, then catch up to the original
  source clock. No reseeding, source clock refresh or source-rate relaxation.
- certification/run381_pressure.py: OWNER_SECONDS_PER_FRAME=.165,
  ARCHIVE_SECONDS_PER_THOUSAND=.36, COMMIT_LATENCY_SECONDS=.006 are reachable
  workload floors, derived there from earlier preserved hosted measurements.
  These are diagnostic load inputs, not production constants. The fresh baseline
  preserves them, measures their injected waits separately, and does not treat
  them as evidence of native SQLite cost.
- certification/combined_observer.py: Interaction holds a genuine reader for
  1.25 + .1 seconds when a mature multiframe batch arms it; delays a genuinely
  complete PASSIVE receipt by .75 seconds. Source/retirement overlap is checked
  from durable counters while the reader remains open. Urgent local ACKs run
  every second; the original driver's candidate read/ACK runs every ten seconds.

## Production source pipeline, owner and workers

meme_machine/solana_evidence_service.py:61-79, 790-870, 990-1190, 1330-1366:

- Source decode/preparation and archive preparation share one ProcessPoolExecutor
  with STREAM_DECODE_WORKERS=2. There is only ONE in-flight archive (ArchiveFlight),
  not one process in the pool. Large source frames (>=1 MiB) use process decode.
- Source reception, parallel decoding and ordered commits are independent bounded
  stages: <=64 outstanding frames, <=96 MiB dispatch; <=8 frames and <=16 MiB per
  durable source commit. ACKs remain barriers. Prepared-byte bounds remain native.
- source_batch calls _source_batch, one durable outer transaction with per-frame
  rollback boundaries. _source_locked reuses a filtered block across all three
  program scopes. FinalizedFence validates parent witnesses and seals coverage.
- Source admission is priority 3, urgent ACK/reservation work priority 0/1,
  maintenance priority 4, checkpoint handshakes priority 2.
- solana_evidence_control.py:29-143: one owner thread owns all writer SQLite access.
  When no urgent work is queued, nonurgent work shares FIFO sequence, including
  source and maintenance. Urgent SQL preemption and native retention boundary
  yields remain active. Capacity=64, eight reserved entries; no extra owner queue.
- Storage stage costs and work() queue/execution costs already exist separately.
  The diagnostic reuses these and adds bounded wall/thread-CPU aggregates.

## Eligibility, batching and durable progress

- solana_archive_snapshot.py:24-98: hot body, timestamp strictly older than
  wall_time-180; excludes lifecycle/address pins, account floors and unresolved
  gaps. Select <=1,000 records and normally <=4 MiB including shared chunks,
  lineage and coverage; a single snapshot can be <=20 MiB. Set reads use slices
  of 128. The archive worker receives <=16 MiB preparation budget.
- solana_evidence_plane.py:552-628: prepare hash-checked immutable bodies off-owner;
  gzip level 1, content-addressed durable publication. Owner rechecks identity,
  hash and pins before setting body=NULL. Triggers transfer synopsis hot counts
  to archived counts in the SAME transaction. Progress ledger commits with work.
- solana_evidence_service.py:698-744: commit slices are <=512 records. The last
  slice also prepares the next snapshot in that owner admission. Receipt retry
  after cooperative yield is idempotent; no duplicate publication/progress.
- solana_evidence_plane.py:641-751: retirement first derives per-scope safe floor
  from oldest hot slot, recent coverage, lifecycle/gap/account floors and durable
  prior floor. Only archived rows strictly below that floor can retire. Deletes
  of continuity, index fanout and bounded housekeeping also have native limits.
  ServiceState.retention uses max_records=1000, archive_first=False and no inline
  checkpoint; actual durable record progress is distinct from floor/housekeeping.
- solana_maintenance_state.py:19-350: transactional synopsis triggers, <=260
  scopes, <=4,096 cohorts per bounded query, <=250,000 observation VM steps.
  Native hot eligibility mirrors selector exclusions; retirement eligibility is
  archived synopsis debt below the freshly calculated safe floor. Continuity
  and housekeeping are bounded witnesses, not fabricated exact record debt.
  Source authority comes from durable finalized_frontier health, not deletable
  stream receipts. Unknown/capped observation fails closed.

## Readiness, deadlines, reservations and fairness

solana_maintenance_runtime.py: MaintenanceRuntime._demands, _episode and turn;
solana_maintenance_arbiter.py: ServiceLeases, ClockModel, choose and complete:

- Archive is ready with a pending worker receipt OR idle flight (plan initiation);
  an unfinished future is not ready. Retirement is ready. Worker wait does not
  renew service drought. Worker age lease is 15 seconds.
- Safety: oldest eligible hot/retirement timestamp +240; an unpinned archived row
  blocked behind hot evidence can tighten archive safety. Residence stays <240.
- Recovery: debt >1,000 latches source_frontier+120; debt <=1,000 resolves episode.
  Re-observation/restart does not gift a new deadline. ClockModel conservatively
  projects timestamps into monotonic time with three-second clock allowance.
  It does not equate source seconds with elapsed wall seconds.
- Owner admission and execution leases are each three seconds. Pair reserve =
  2*execution +2*owner +clock_error =15 seconds. Successful-service drought=45.
  Recovery, safety and service deadlines constrain each scope, then each side.
- A ready side must finish strictly BEFORE its own deadline. Its selection must
  also preserve opposite admission + execution: now+3+3+3 < opposite deadline.
  Unready work still constrains peer admissions. The terminal refusal is retained.
- Scores combine units/rate/safety headroom and excess/rate/recovery headroom.
  Rates are bounded measured record-service samples, used only to rank surplus;
  no rate enlarges a lease. Tie rules discourage the last side. Only positive,
  same-scope durable progress renews the relevant service clock; housekeeping
  does not claim record progress. Generation checks fence observations/receipts.

## WAL and checkpoints

ServiceState.__init__: FULL-synchronous WAL, automatic checkpoint disabled,
fixed 16 MiB owner cache, temp_store=MEMORY. Bounds and cache spill remain native.
serve.checkpoint: off-owner PASSIVE, one outstanding operation; incomplete reader
copy yields. Complete receipt attempts a generation-fenced owner reset.
solana_checkpoint.py: a stale completion uses a FIFO mutation-boundary handoff,
then off-owner fresh PASSIVE/TRUNCATE with busy_timeout=0. Mutation delay is real,
measured owner handoff time. Readers remain valid; cancellation joins accepted I/O.

## Fresh measurement contract

harness.py executes unchanged serve()/mutators/arbiter with the reachable local
Wire, Interaction and canonical load floors. It does not call a certification
entrypoint. Every five seconds it reads a short, coherent synopsis/counter
snapshot, copies existing native scheduling state and numeric wrapper aggregates.
There is no per-record SQL tracing or retained market body.

Eligibility arrivals are inferred as delta(eligible_hot)+delta(archived_records)
for each scope in this unpinned, gap-free workload. This includes aging and late
arrivals at the actual wall cutoff; it is not lifecycle.ingested treated as debt.
A nonzero pin/gap invalidates that inference. Native owner observations supply
actual readiness, deadlines and feasible-side arithmetic, including terminal
choose inputs. Measured transaction/stage/owner/worker intervals overlap and must
not be summed indiscriminately. Qualification observer work and extra diagnostic
observer/serialization/persistence/wrapper time are reported separately.
