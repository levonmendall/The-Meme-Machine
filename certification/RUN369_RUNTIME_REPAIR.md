# Run 369 runtime repair (paper only)

Base: `d1fc161401869522db9abbf50e3f6073e80a4374`, branch
`cert/single-market-evidence-planes-v1-20260925`.
Repair branch: `repair/run369-solana-runtime-20260925`.

## Evidence and causes

Run 36200179045, concurrent-smoke job 108284978734, artifact 10891513582
(`four-lane-certification-36200179045-1`, archive SHA256
`02e04c9d93ba3aafffe89f16af2e265ef27602a8c67d9c1197a8a4be9501c665`)
contains the consumer timeout and service-side disconnected response failure.
The 250ms client deadline raced synchronous command handling on the ingestion
event loop; Meteora's initial interest was outside its classified failure boundary.
Changing the deadline alone cannot resolve command ownership after a lost reply.

A second defect explains the false gaps and capacity collapse. The retained
database has identical initial census counts (1241) for all three programs.
Of 9859 bodies stored under Meteora, only 916 mention Meteora in static or loaded
account keys. The stored body bytes are 69,888,720 versus 14,276,184 for scoped
transactions. A block subscription filter selected whole blocks; it did not
filter transactions inside those blocks. Unrelated signatures could never be
satisfied by Pump program logs. The retained DB/WAL reached 286,726,232 bytes,
above the previous 256MiB cap. Blocking ingestion/maintenance aggravated IPC
latency, but repairing IPC alone would leave false gaps and storage pressure.

Pump intentionally completed its native 600-second discovery while flat. The
supervisor required it to remain alive until every lane's enclosing deadline and
required lane HTTP activity despite local evidence authority. Run 369 also had
unusable evidence: its original result must still fail the new health contract.

## Repair contract

* One bounded priority owner thread holds SQLite. Socket read/write handling stays
  on the event loop. Queue capacity is 64, including eight reserved lifecycle
  slots; at most 32 socket consumers wait. Lifecycle commands precede foreground
  decisions, source triggers, diagnostic/prefetch work, and background repair.
  Background SQL yields and rolls back when higher-priority work arrives.
* Every mutating IPC request carries consumer, request ID and expiry. Mutation and
  receipt commit atomically. Interest, release, ack and counter retries return the
  original receipt; changed content under the same ID is rejected. Receipts have
  a bounded count (8192) and expiry retention. Expired identities cannot be newly
  applied after receipt collection. Consumer authority remains the same whitelist.
* Client acknowledgement has a three-second total budget, six bounded attempts,
  and the same envelope throughout. Server read, pending response and drain budgets
  are 500/400/200ms. Disconnects never cancel accepted work. Exhaustion is explicitly
  unacknowledged (with the original envelope), never a claim of non-application.
  Rejections, pending replies, retries, overload and disconnects have telemetry.
* One authenticated finalized full-block feed is reused across all program scopes.
  Static and loaded keys determine each program census and stored bodies/events.
  Empty scoped blocks retain parent witnesses; signature-only censuses cannot grant
  coverage. Public discovery and Alchemy/governor authority are preserved.
* The hot store has a fixed 2GiB cap and a bounded three-minute archive tail,
  preserving explicit lifecycle/account pins. Address-specific pins do not retain
  unrelated program bodies; finite gaps do not pin all subsequent history. Archive
  work uses 64-record slices and rechecks pins after off-owner compression. Repair
  uses one background governor request at a time, bounded pages/attempts and backoff.
* Health distinguishes WARMING, USABLE, DEGRADED, DRAINING and FAILED using the
  source phase, 15-second heartbeat/receipt bounds, 60-second finalized lag,
  linked-parent coverage and storage pressure. Admission fails closed. Pump watches
  both Pump and PumpSwap authority. Unusable startup is classified within 90 seconds;
  a previously usable service gets a 30-second degraded bound. Failures latch.
  Position monitoring and pending-entry safety execute before new admissions.
* Pump's exact flat completion receipt requires its discovery deadline, flat native
  accounting, zero restarts, exit zero, and usable evidence without a latched failure.
  Generic exit zero, premature death and stale evidence remain failures. Actual
  overlap is preserved in telemetry. No strategy threshold or economic gate changes.

## Deterministic verification

Before changing the base, two regression fixtures produced one error and one
failure: a 350ms command raised `evidence_service_unavailable`, and an unrelated
transaction was retained as Meteora evidence. The repaired fixtures pass.

`tests/test_run369_runtime.py` covers scoped ingestion, loaded keys, all four
durable mutations/restart/conflicting IDs, receipt and queue capacity, background
SQL interruption/rollback, pin scope/recheck, health states, slow admission,
disconnected response/retry, and continued service health.
`certification/tests/test_run369_lifecycle.py` covers exact completion, premature
death and stale authority. Incremental lane overlays include real Pump-loop
completion/stall tests and a real Meteora admission-boundary test with persisted
infrastructure classification and no economic screening.

Local Unix bind is unavailable in the executor. The local transport fixture runs
the production server callback; the dedicated Actions workflow additionally sets
`MM_REAL_IPC_TESTS=1` and runs real Unix socket checks. Its four component suites
forbid external socket connections. The workflow also runs retained reconstruction,
frozen policies, provider topology, supervisor/accounting, resource checks, native
crash/restart matrices and integrated deterministic acceptance. It contains no
provider credentials, provider probes or market launch step.

Prospective throughput/authority validation remains outside deterministic proof
and requires separate market authorization. No market run is authorized here.
