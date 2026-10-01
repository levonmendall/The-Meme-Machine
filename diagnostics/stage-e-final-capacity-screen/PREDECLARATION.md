# Final Stage-E capacity screen — immutable predeclaration

PAPER ONLY. ASTRA_DECISION: AUTHORIZE_FINAL_CAPACITY_SCREEN.
Stage E: RED. Stage F: NOT_STARTED. Non-certifying diagnostic only.

New capacity budget: **0/2 consumed before execution**. Separate budget ID:
`stage-e-final-capacity-screen-20261001-v1`. Historical exploratory budget remains
**6/6 consumed, unchanged**. Exactly CONTROL then TREATMENT, one attempt each.
Every start consumes its execution, including interruption/crash/instrumentation
failure/early stop. No retry, third arm, replacement or formal observer benchmark.

## Exact bound identities

| Arm | Commit | Tree | Assembly SHA-256 |
| --- | --- | --- | --- |
| CONTROL | 19b4244d6c09eeebab37319784109b876c94a0d4 | dda7f9df08fa258d9856b5521ada10a7cb8e8b25 | 61bf11629765f7251767a1e868002ad7f099a51d0112ff88eb490e90ac26f7f9 |
| TREATMENT | 7a516a6a92be9347661ac0e7f560971c171a0931 | 9da7d1e1625ba04c1437c63606c90f5e293bdba7 | 08d5a491975345c859941c01cbde6ee3ef8b56a85026209fd497c14daa047659 |

Treatment is exactly reviewed S/T/assembly, reconstructed without byte changes.
CONTROL is a diagnostic derivative of S with exactly one production callsite
replacement: `offer=await admission.rendezvous(source_state)` -> `offer=None`.
All other tracked blobs and modes match S. [CONTROL.diff](CONTROL.diff) and
[CONTROL.patch](CONTROL.patch) are the same full-index binary-capable exact diff.
Patch SHA-256: `6e05436dce786c9c1f7d8f9dbbee1c708be4e771408f7cbc3bd7826c11219344`. Only changed path:
`meme_machine/solana_evidence_service.py`. [STATIC_CONTROL_PROOF.json](STATIC_CONTROL_PROOF.json)
proves the single replacement by bytes and AST, preserves all remaining service
AST, and binds constant M1, housekeeping, arbiter, owner, retention and checkpoint
files. Qualification-v2 bytes and original input manifest are unchanged; this
control derivative receives no formal qualification input-verifier credit.
Assembly manifests are published for both arms.

## Driver, workload and environment

[PREDECLARATION.json](PREDECLARATION.json) is the complete machine-readable
binding, including all driver/workload SHA-256 values and full environment hashes.
Screen driver SHA-256: `d5992be6cc70fa60875284a28949485ee7cdadc2e94e7195035e028c0b2a2902`.
The driver derives from the reviewed `d4068d4fa177225daf8780ee7c9765977f4b8793`
`diagnostics/housekeeping-ordering/harness.py` and uses the existing preserved
Run380 production templates, Run381 retiming and durable-window-v4 Interaction.
The historical harness is preserved as text, with its exact digest and all
adaptations disclosed. Only diagnostic provenance, start guards and bounded
capture are extended, with **full canonical urgent controls restored**.

Fixed workload: 512 transactions/frame (Meteora 128, Pump 48, PumpSwap 80, failed
filler 256); cadence .27 seconds. Source charge remains
`max(0, .165 * actual_frame_count - native_source_elapsed)`. Archive worker charge
remains `max(0, .36 * records / 1000 - native_archive_elapsed)` and additional
outer commit latency remains .006 seconds. Actual native and injected charge are
reported separately. Source batching stays at 8 frames/16 MiB, archive snapshot
1000 records and archive commit slice 512 records. The same existing two spawned
workers serve source decode/archive. Pending bounds stay 64 frames/96 MiB.

The original 8-second source pauses remain at frames 800/1400 (source 216/378 s).
The second pause is outside this fixed prefix. The existing actual multiframe
batch arms the original held reader (1.25 + .1 s) and .75-second complete-PASSIVE
tail delay. No maintenance/checkpoint/housekeeping input is changed. Canonical
ACKs use unchanged local IPC every 1 s after ten source frames, plus the original
candidate ACK/read every 10 s. There is no reduced-ACK shortcut.

Both arms run sequentially on this same managed physical executor. Python
3.12.14, SQLite 3.53.1 and websockets 17.1 match the reviewed environment exactly,
including interpreter SHA-256, standard-library digest and dependency file hashes.
[ENVIRONMENT.json](ENVIRONMENT.json) binds the full environment, host, CPU affinity,
quota, memory and process resource limits. This exact reviewed environment is why
this managed runner is used instead of introducing a different hosted CI runner.
Each arm gets a fresh process group, database, archive/temp directory, state,
worker processes and observation output. The child environment is sanitized.

## Fixed horizon and mature interval

The screen ends at **1,334 durably committed source frames**, representing 360.18
frame-count source seconds and a last payload offset of 359.91 s. This preserves
the reviewed first-burst recovery window [216,336], followed by 23.91 source
seconds. Full urgent behavior changes legal scheduling only. The horizon never
changes based on results. Active wall backup: 600 s; controller/teardown guard:
660 s. No horizon extension is permitted.

The mature interval is identical for both arms: offered-source offsets
**[190.08,349.92] seconds**, corresponding to frame-count coordinates [704,1296].
It starts after initialization and retention maturity, includes sustained pressure
and the original first-burst recovery window, and ends while source continues to
1,334 frames. Two scheduled, read-only live snapshots bind these exact boundaries.
The source clock is the immutable `Wire.start + offset`; no rebase is allowed.
Acquisition gaps are measured; gaps >1 s invalidate instrumentation. Periodic
snapshot cadence is 5 s; live sample gaps >10 s invalidate capture.

A native relevant CONTROL capacity stop within this interval explicitly censors
the remaining suffix. The interval is never moved. CONTROL reproduction is
measured from the fixed start to the live pre-stop snapshot within that interval,
with censored exposure labeled. TREATMENT green requires the complete original
interval, both boundary snapshots and the complete fixed source horizon. Neither
arm receives capacity credit from shutdown drainage. Whole-arm totals are
reported separately.

## Recovery deadlines, pressure reproduction and success

Native recovery window stays 120 source seconds with a 1,000-record pipeline
slack. The first native episode's `wall_started` and `source_now + 120` are the
original anchors; existing ClockModel uncertainty is unchanged. Capture every
scope/side, opening excess, original start/deadline, progress, resolution and
headroom. Episodes latched at/before source offset 240 require original-deadline
observation. Later episodes are still listed; unresolved episodes at mature end
block green. Only resolution before the original deadline is PASS. Otherwise
report OPEN, CENSORED or FAILED; an unobserved deadline is never PASS. Re-enrollment,
rebasing, origin refresh and replacement episodes cannot create credit.

CONTROL reproduces only when **all three** hold within its declared mature
exposure: durable archive drain < measured eligible arrivals; archive debt grows
or positive recovery excess fails to discharge; and captured native
`maintenance_cannot_reserve_both_sides` / `maintenance_service_deadline_exhausted`
shows the relevant maintenance-capacity mechanism, or required original-deadline
excess remains unresolved. A random fixture/source/disconnect/corruption/worker/
instrumentation/unrelated-timeout failure cannot count. Static lease-validation
failure cannot count. Treatment is preauthorized and predeclared to continue
unchanged regardless of the control result.

TREATMENT green requires all of the following:

- Full mature archive drain strictly exceeds eligible arrivals, positive rate
  surplus, ending hot debt < starting debt and a negative debt slope.
- For every active scope (Pump, PumpSwap, Meteora and any additional native scope),
  retirement service >= newly archived work; ending archived-pending debt <=
  starting debt; retirement excess declines/resolves or stays zero; no starvation.
- Every required original deadline passes; no unresolved mature-end recovery
  episode and no pass credit from censored/open/failed episodes.
- The offered workload is unchanged; 1,334 data frames are offered/admitted/
  committed on contract, with .165 charge exact, source lag <45 s, no silent loss,
  unrepaired gap, disconnect or upstream accumulation masking improvement.
- Urgent priority, nonurgent FIFO after admission, cross-scope fairness, continuity/
  floors, checkpoint completion, all leases, two-sided reservations, generation
  fencing and transaction/frame/byte bounds remain exact. No new failure replaces
  the historical one. Hot and retained ages are each **strictly <240 s**.
- Per-scope conservation holds: ingested = hot + archived-pending + durable retired;
  eligible arrivals = eligible hot + archived-pending + durable retired. Hot debt
  reduction cannot simply export debt to retirement or another backlog.
- Integrity is `ok`; no abandoned transaction, unresolved accepted owner future,
  leaked worker/process group, provider call or provider attempt. DB+WAL <2 GiB.

## Identical bounded instrumentation and observation cost

The machine binding enumerates every SOURCE, ARCHIVE, RETIREMENT, HOUSEKEEPING,
ARBITRATION, A2, OWNER, RESOURCE/SAFETY and PROVENANCE field. Durable counters,
cohort census and progress come from the same short read snapshot. The arrival
census directly counts eligible cohorts plus durable retired records; it does
not use a historical rate. Source queue depths are captured from suspended
native coroutine locals without modifying them. Full owner/A2/native-turn events
are independently retained despite the runtime's ordinary rolling-ring evictions.
All caps are bound in JSON; drops/errors are reported and invalidate capture.

Record actual periodic observer, serialization, persistence, wrapper, queue and
boundary elapsed time, sample drops/errors and acquisition/measurement gaps.
Some timers overlap; report that explicitly. **Never subtract observation cost**
from runtime results. No <1% benchmark is run. Different instrumentation bytes,
configuration, unexplained drops/errors, missing direct measurements, conservation
mismatch or material asymmetric measurement gaps produces
INCONCLUSIVE_INSTRUMENTATION. Expected CONTROL suffix censoring caused by the
predeclared capacity stop is reported separately.

CONTROL A2 opportunity count must equal zero. TREATMENT reports offers, acceptance,
timeouts/bypasses, affected frames and actual maintenance-before-source owner
placements. Correlate actual placements with durable native progress, debt and
original-deadline headroom. Claim only what this matched pair measures.

## Firewall, receipts, artifacts, budget and stop

Parent and spawned workers block Internet connect/connect_ex, DNS,
create_connection and urllib before a packet. Local Unix IPC remains native.
Child attempt records are retained and summed with parent attempts. Provider
calls = 0 and attempts = 0 are required; no credential/wallet enters the child
environment.

Attempt 1 only, exclusive arm directories and durable STARTED.json before Popen.
An uncertain/failed start cannot be replaced. Before each arm, commit/publish a
non-certifying receipt with exact identity, remaining budget and no tuning. After
each arm, immediately preserve raw logs/telemetry/worker receipts and full-file
SHA-256 inventories, then commit/publish consumption 1/2 and 2/2 respectively
before interpretation. Arm 1 is saved before arm 2 starts. Fixed artifact names:
CONTROL_RAW_EVIDENCE.tar.gz and TREATMENT_RAW_EVIDENCE.tar.gz; local run identity:
`final-capacity-screen-20261001-v1/{control,treatment}/attempt-1`. No state transfer.

AGENTS.md requires runtime DBs to stay out of Git/logs. Full runtime databases and
payload archives remain outside Git, with exact SHA-256 inventories published.
All raw read-only telemetry, logs and worker/firewall receipts are published.

Stop on the fixed source horizon, native failure/refusal, candidate/control
failure, source lag >45 s, either residence >=240 s, the declared wall guards or
user cancellation. Preserve root failure and cascades without turning them into
capacity reproduction. Apply exactly one classification using the JSON's fixed
precedence: EXECUTION_INTERRUPTED; INCONCLUSIVE_INVALID_CONTROL_FAILURE;
INCONCLUSIVE_INSTRUMENTATION; INCONCLUSIVE_CONTROL_DID_NOT_REPRODUCE;
CONTROL_FAILS_TREATMENT_RECOVERS; MECHANISM_WORKS_CAPACITY_INSUFFICIENT;
NO_BENEFIT_OR_NEW_FAILURE. The two final mechanism categories use directly useful
A2 placements/progress/debt/headroom evidence, never a mere scheduling offer.

Only CONTROL_FAILS_TREATMENT_RECOVERS is capacity-screen green. Stage E remains
RED and Stage F NOT_STARTED regardless. After both executions: **STOP FOR ASTRA**.
No retry, third arm, observer benchmark, full fixed cohort, canonical Stage E,
promotion, candidate freeze, treatment tuning or Stage F is authorized.
