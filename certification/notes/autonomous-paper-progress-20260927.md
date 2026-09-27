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


## Resumption at 6feea40 — checkpoint-owner causal candidate

2026-09-27 refresh: remote continuation head is still
`6feea40bffb74053f8e90ad01d17b3922f0c0f35`; CI `36303678377` passed,
durability diagnostic `36303678366` failed, and no newer Actions run exists.
Run 381 remains the latest market run. Recovered uncommitted stage-3 candidate
changes were preserved and reviewed; no strategy/source manifest changed.

Artifact `10925884118` independently matches SHA256
`57ce5ace61528fcb9ea6422e4310134af46cce1ac6a1de8ccc6692f035fd62d5`.
Legacy and atomic-health variants both hit 45-second source lag. Atomic health
reduced health stage time (20.41s to 7.19s), but SQLite COMMIT still consumed
177.99 wall seconds / 9.21 CPU seconds; injected delay was only 11.19 seconds.
That isolates remaining investigation to real durable commit work.

Causal candidate: service source/metadata commits implicitly run SQLite's
1,000-page automatic checkpoints in addition to retention's explicit PASSIVE
checkpoints. Keep FULL synchronous WAL commits, move checkpoint initiation to
the already bounded retention path, and publish periodic health atomically.
A production-writer microprobe (five batches / 640 records) measured source-path
writes of 24,904,680 versus 14,025,640 bytes; main DB growth during source commits
was 10,702,848 versus zero. Both independent readers saw all 640 durable rows;
retention copied the same 13,385,728 DB bytes, with integrity OK. This proves
redundant source-path copying; sustained sufficiency remains unproven.
The checkpoint regression fails the restored old 1,000-page policy and passes
the candidate. Health regressions preserve all fields, require six-to-one commit
reduction, and prove rollback of an interrupted publication.

Next hosted verification hypothesis: eliminating implicit source checkpoints
and health commit amplification restores owner headroom under measured slow
durability. Discriminator: unchanged 2,223-frame / 600.21-second replay with
0.165s/frame owner floor, 0.36s/1,000-record archive floor and 6ms extra per changed
commit. PASS establishes sustained candidate capacity only if lag, 240s retained
age, 2GiB storage, archive/cleanup, local reads, gaps and integrity gates all pass.
FAIL disproves repair sufficiency and requires stage evidence review before any
new run. Run candidate once; do not repeat the already failed legacy 600s replay.
The final certificate must repeat this durability profile independently.


Candidate `a7bba25b7be05db390293fe00040cfbb6926d500` is pushed on the
continuation branch. Hosted durability verification `36325689034` and ordinary
CI `36325689045` are running. Local focused/instrumentation/acceptance checks:
16 passed; affected archive/retention/atomic-frame/storage checks: 40 passed.

Read-only B/C gap mapping during hosted verification: existing native Survivor
commit/monitor, frozen risk boundaries, shared-sleeve concurrency and restart
accounting tests are reusable. Normal successor dispatch is explicitly disabled
by the current single-campaign policy; extend durable orchestration under this
task's explicit autonomous authority, preserving standalone single-run semantics.
A short production Pump Runtime.step reproduction filled History capacity (one
candidate) with an expired candidate and offered a new graduation: result was
`survivor_candidate_capacity`, old candidate remained `graduated`, and retirement
did not progress. Existing positions run before discovery, so this reproduction
establishes candidate-progress starvation only. Add a focused regression and
bounded scheduling repair in B/D; do not claim wider lifecycle failure from it.

Ordinary CI `36325689045` passed for `a7bba25`; pressure still running at this
checkpoint. The same full-capacity Runtime.step retirement stall reproduced in
Pons Survivor. The final source composition must refresh only engineering overlay
file/diff identities for Pump/Meteora after the service repair; leave all approved
strategy versions, policy hashes, source/execution commits and allocations intact.
B/C audit must explicitly check transfer of unfilled Survivor candidate history
across normal campaign windows: their six-hour minimum age exceeds an hourly
window, and the current normal workflow prepares fresh worktrees. No conclusion
of working long-horizon Survivor acquisition is justified by within-window tests.


Hosted checkpoint candidate `36325689034` FAILED at the unchanged 240s retained
age gate (240.334s; source lag 42.334s; 1,200,610,440-byte hot peak). Verified
artifact `10934002779`, SHA256
`19d067642564f9eb2884331ec0df78109e9bc7ccd34aed43101f1a3118945d7b`.
Moving checkpoints did remove measured commit amplification: COMMIT wall time
14.89s versus prior atomic-health 177.99s, despite more processed frames.
However retention still consumed 97.38 wall / 61.34 CPU seconds; explicit
checkpoints consumed 23.56s, and process write requests reached 77.27GB for
6.07GB of admitted source. The repair is useful but NOT sufficient. No rerun.
Next cheap discriminator: fixed mature-store maintenance slices measuring write
amplification with unchanged transaction sizes, comparing SQLite spill behavior
and a bounded page-cache working set. Do not relax any pressure/resource gate.
Uncommitted B candidate-progress patches/tests are parked; both old native
runtimes failed the regression and both scheduling prototypes pass, but they are
not composed/promoted and Phase A remains the only active completion gate.

Bounded mature-store probes isolate remaining retention amplification to record
deletion's temporary statement journals and address-index page-cache churn. With
24,000 records / 384,000 address refs, one unchanged 1,000-record retention slice
requested ~126MB writes / 73MB reads using default disk temp / 2MiB cache;
memory temp / fixed 16MiB cache needed ~34MB writes / 20MB reads. Factor probes
independently reduce writes with memory temp and reads with the bounded cache.
Bulk delete was rejected: fewer write requests but more actual durable bytes.
Disabling cache spill added little; retain normal spill and transaction bounds.

Accepted candidate configures only ServiceState's owner connection with memory
temporary work and a fixed 16MiB page cache. FULL WAL, 256-record retention
transactions, source bounds, pins, provenance and all acceptance limits remain.
New production-retention regression fails old behavior at 125,901,768 requested
write bytes. Candidate passes; injected trigger abort restores rows, lineage and
address refs, then reopening/retrying produces correct durable deletion and
integrity. Twelve 1,000-record cycles on a 100,000-record store stabilized at
37,052–37,056KiB RSS, eight FDs, and decreasing hot bytes after initial WAL reuse.
Focused checks: 11 passed. Affected storage/archive/atomic/crash/acceptance checks:
66 passed. No market/provider access occurred.

Next hosted verification hypothesis: removing temporary-journal write
amplification and page-cache churn restores sustained owner capacity after the
already measured checkpoint repair. Discriminator remains the full 2,223-frame /
600.21-second replay with the same source/archive floors and 6ms changed-commit
delay. PASS requires all existing lag, age, storage, archive/cleanup, local-read,
gap and integrity gates. FAIL disproves sufficiency and requires reviewing stage
evidence before any further hosted run. No limit or source load is relaxed.

Working-set candidate `e33adc5f5ec013e9169e7ce64d80638b912f5d97` is pushed;
offline durability run `36327089863` is executing. While waiting, 38 reusable
canonical native conformance/Survivor/accounting/continuity tests passed. Draft
six-regime gap matrix is `autonomous-production-coverage-20260927.md`.
Meteora's existing production lifecycle test already simulates its full 24-hour
hold; retain it rather than duplicate it.

Material B finding: both frozen Survivor policies approve 14,400-second minimum
age, but both native Runtime.step schedulers still hard-code 21,600. New native
boundary regression fails both at the approved minimum. Earlier notes describing
a six-hour policy minimum were incorrect: that is the stale runtime gate, not
frozen strategy authority. Bind runtime age scheduling to the existing policy
values in Phase B; do not modify either policy or its hash.
The same audit found Pons Survivor runtime turnover sizing still divides by 40,
while its approved frozen policy divides by 30. The existing promotion patch
changed the policy but left both runtime capacity sites unchanged. Native
`turnover_cap` regression reproduces 30 units instead of policy-authorized 40 for
1,200 units turnover. Bind both sites to the frozen policy in B; no allocation or
policy change. These B regressions are deliberately uncommitted while A runs.
Parked B prototypes now pass four focused native regressions: saturated-history
retirement, both approved age boundaries, Pons native reconstruction/qualification
and sizing, and Pump native reconstruction/qualification including actual oracle
and concentration checks. Reconstruction cases reopen History and verify that a
recorded continuity gap still prevents entry. Native acquisition/discovery-to-
history and normal cross-window handoff remain explicit audit gaps. Ordinary CI
`36327089807` passed for the independent Phase-A candidate.

## Phase A complete — 2026-09-27

Exact candidate `e33adc5f5ec013e9169e7ce64d80638b912f5d97` PASSED hosted
durability run `36327089863`. Artifact `10934422845` independently verified as
SHA256 `d7facd425993e78a66804e05d7dac59858d8d074051f66351fc2e127aa37a4ba`;
all five recorded production source hashes match that checkout. Full 2,223 frames
/ 600.21 source seconds, 6ms changed-commit latency (5,025 injected waits),
0.165s/frame owner and 0.36s/1,000-record archive floors remained unchanged.
Peak lag 3.068s; hot age 184.726s; all-retained age 186.223s; hot bytes
1,054,211,840. Fifty-nine candidate-local reads passed; 410,384 archive records
hash/provenance verified; 409,384 archived and 407,336 compacted. Remaining 2,048
archived index rows are bounded backlog, not lost evidence. Receive/dispatch peaks
9 frames / 36,738,045 bytes; admitted/committed messages both 2,224 including end
marker. No runtime gaps/disconnects/capacity stops; three shutdown gaps are the
intentional terminal discontinuity. SQLite integrity OK. Zero provider calls.

Causal explanation: serial owner throughput was consumed by redundant implicit
checkpoints and amplified record-deletion I/O (file-backed temporary statement
journals plus a cache too small for the bounded address-index working set).
Atomic health alone and checkpoint ownership alone were independently insufficient.
Service-only explicit retention checkpoint ownership, atomic health publication,
memory temporary rollback work and a fixed 16MiB cache retain FULL WAL durability
and every acceptance bound. Full candidate write requests were 43.38GB across
2,223 frames versus 77.27GB across 1,487 on the checkpoint-only failure; cancelled
temporary writes fell from 4.56GB to 0.00026GB. Sustained source lag stayed low.
Deterministic old-fail/new-pass I/O and checkpoint regressions plus rollback/reopen
proof justify the repair. No second standalone 600s run: final full certification
will supply the required independent sustained proof. Phase B is now active.

Phase B first repair batch: declared Pump/Pons scheduling overlays bind approved
age/turnover fields and let full candidate sets progress to retirement. Fresh
preparation from all four frozen execution SHAs applies every declared patch;
source-integrity verification passes. Forty focused native conformance, worker
policy, Survivor and shared-accounting tests pass. Refresh only engineering
composed/diff identities in sources/protocol; all approved policy hashes,
strategy versions, source/execution SHAs and task-manifest bytes stay unchanged.
Remaining coverage gaps are tracked in the matrix; no full certification or
market workflow has been started.

First B batch pushed as `b52018b552d668ebbd916f0ce978df0746765ab6`.
Next reproduced defect: current Pons native run_lifecycle was interrupted directly
after its real partial PAPER exit committed. Journal preserved reserve, entry,
mark, exit intent and exit; 667 of 1,000 original tokens remained. No durable
controller context preserved high-water/streak/partial/graduation state, and no
current-strategy resume entrypoint exists. Existing restart_safety explicitly
proves only a fail-closed guard. Reproduction is a virtual-time native lifecycle
with transport fixtures, not a policy-only test. Repair must checkpoint controller
state atomically with native journal actions and reuse the same production monitor
on restart; no new entry or reconstructed profitability authority.

B recovery prototype now atomically binds current-Pons controller context to the
native position journal: original hold clock, partial quantities, high-water and
confirmation counters, graduation state and pending action. Exact buyer sets are
normalized with journal-bound digests; recovery reuses the existing production
monitor and has no entry authority. Six real native crash cuts (before entry,
after entry, mark, exit intent, partial fill and final fill) now resume with one
entry, one partial and one final exit; duplicate settlement acknowledgement is
idempotent and provider-free. Concurrent controllers and corrupted buyer sets
fail closed. Integration into cohort/continuation still pending; do not mark the
restart matrix complete. Eighty-seven affected native tests passed before the
expanded crash matrix; focused recovery/accounting/provider checks now pass.

Ordinary CI `36328163432` failed one short pressure shutdown assertion (received
41, committed 40). A new deterministic scheduling regression reproduces the cause:
a subscription task observes stop before the dedicated stop waiter is scheduled;
old shutdown treats this as structural completion and cancels admitted work
(1/33 committed). Production now branches on the actual stop flag and drains
33/33. All five persistence/stop tests pass, including the original dense workload.
No pressure load, retention bound or durability setting changed. This is a newly
reproduced shutdown defect, separate from the closed Phase-A throughput cause.

Expanded current-Pons regression passes nine lifecycle crash cuts, including
native graduation commit, post-graduation admission mark and V4 runner mark.
An injected SQLite abort proves buyer-set inserts, controller projection and
native journal roll back together. Ninety-one affected native tests pass. The
recovery entrypoint is protected by an OS-released nonblocking controller lock;
restart cannot authorize a second simultaneous manager or any new entry.
Declared recovery overlay now preserves this work in repository source composition.
Cohort startup and full workflow continuation remain the next integration work.

Pushed recovery foundation `44cee91b4f0eae30cebc078e82f498ef942e1a36`;
fresh composed lanes pass source integrity, 91 affected native tests and 38
canonical checks. Startup integration now invokes the same bounded native
recovery before fresh discovery. Recovery receipts coalesce by verified lifecycle
identity, preserving the append-only archive without duplicate economic counts.
A separate actual V4 pending-partial/max-hold regression exposed false terminal
reporting: old loop said settled with 667 tokens still open. Repair preserves the
pending partial, then exits the remainder on fresh evidence before final settlement.
The expanded native recovery tests pass. Workflow continuation integration is
still in progress; no new certificate or market run was launched.

Ordinary CI `36329901006` passed for `44cee91`. The next recovery batch passes
96 affected native tests plus 14 canonical continuation/terminal/accounting tests.
Actual position-continuation code now resumes current Pons alongside Survivor
management under the same sleeve, reports one newly settled native position,
and grants no discovery/entry authority. Read-only handoff proof verifies the
controller journal without modifying the native DB; bounded slices retain the
original hold clock and partial state. Real GitHub dispatch availability remains
unproven until the final-SHA control-plane gate.
A related exit regression reproduces both curve/V4 helpers returning an unfilled
pending position after the ledger rejects a wrong-market quote. Helpers now
propagate that native rejection instead of allowing callers to report completion.
The original intent, quantities and capital remain held; no evidence check changed.

Continuation batch stable locally: 97 affected native tests and 20 canonical
conformance/terminal/continuation tests pass. Its declared overlay also applies
cleanly to a separately prepared foundation Pons lane; all four composed source
identities verify. Existing frozen policy/base-source identities are unchanged.
Next audit work: current Pump workflow continuation, both Survivor acquisition
composition and cross-window unfilled histories, durable rolling controller,
then the missing multi-day/crash/provider matrix. No Phase-B–G gate is yet closed.

Pons continuation batch pushed as `4c4b22e5275960b25933a707306d9edf3a421f31`;
ordinary CI `36330743539` passed. Current Pump already had exact native strategy
replay but lacked workflow continuation. Reusing its production restore/monitor
exposed a shared-sleeve defect: after a recovered native settlement, 255,569,215
fixture lamports remained held because replay never reattached its allocation.
A startup binding now verifies and attaches only the existing reservation; it
cannot reserve again or recreate a missing sleeve. Read-only terminal replay
explicitly omits that operational binding. The production monitor regression
uses finalized local history, performs a real native partial, reopens, preserves
the original clock/partial/high-water context, stops and settles once, and releases
exact shared-sleeve P&L. Missing allocation fails without creating a database.
Twenty-two affected native Pump tests pass; policies and capital remain unchanged.

Pump continuation batch `6f66880552e29d3651e4ae97a9c4e4d8fb10381f` passed
ordinary CI `36331425729`. Phase A remains closed; no new pressure or market run.

Survivor acquisition audit reproduced Pons history starvation with an offline
five-block/second clock: after 24 five-second production steps, the bounded
64-candidate hot set has maximum lag 600 blocks. Discovery also admits only ten
blocks per step. This is scheduling throughput, not a strategy rejection.
Prototype shares authenticated transport across separate pool identities and
advances all history cursors in the existing 40-block work slice; each provider
log query remains at most ten blocks. The same probe now stays current. Captured
Pons graduation bytes traverse actual discovery/ABI/receipt/lineage/history code;
missing initialization fails closed. Two-market swaps, wrong-pool/receipt/reorg
rejection, interruption recovery and reopen/idempotence pass. Policy unchanged.

The required native Pons suite ran 433 tests: two fixture errors require adding
the new batch transport interface to its old discovery stub. Four other failures
match the already documented workspace PID/proc namespace mismatch: direct
`alive(process_identity())` is false here. Keep production liveness fences intact;
the final hosted certificate must pass those concurrency tests. No retry is being
used as evidence. Acquisition composition and source-identity recording pending.

Composed Pump discovery regression now reproduces a separate BROKEN binding:
the shared `program_decoders()` path replaces the old lane overlay and omits
authenticated migration events. Raw migration parsing passes in isolation but
the real finalized census/read path produces zero Survivor candidates. Repair
moves the existing migration codec into the neutral shared decoder, invokes it
alongside trade/create parsing, and makes the lane helper reuse it. No parsing,
lineage, native-quote or strategy gate is relaxed. Full composed regression is
being verified, including unsealed evidence, non-native quote and gap rejection.

Survivor acquisition batch passes 59 canonical/transport/finality tests, 25 native
Pump tests and 30 affected native Pons tests. Pump composed discovery now admits
one authenticated SOL migration only after its linked finalized census, excludes
non-native quote, survives reopen and rejects an unresolved gap. Pons uses the
same receipt/ABI/sender authentication for each pool in shared transport; the
64-candidate probe and independent discovery keep pace without widening a single
ten-block log query or the 40-block history slice. Thirty-two-event graduation
and 256-event per-pool limits remain. Frozen policies and allocation unchanged.
Declared overlays/source identities are being recorded. Next: cross-window
candidate history, bounded long-horizon storage, and durable controller gates.

Acquisition batch pushed as `48e7cd03121d9a2337038658071717b9db4f3e72`.
Independent prepared checkouts have identical source identities for all lanes.
Normal-window audit reproduced Ramses rejecting its existing capital directory
on a second production campaign invocation. Prototype verifies the original
pinned screen, manifest, exact asset/book set and each native genesis, then
reopens existing journals before discovery. Missing books or changed screen/policy
fail without writes; no re-funding. Eight native campaign tests pass, including
an open position across reopen, loss preservation and two production campaign
windows with one original genesis and four distinct settlements. Old production
startup fails that same second-window regression. Workflow transfer remains pending.

Ordinary CI `36332509437` passed the acquisition batch. Ramses recovery composes
identically in both prepared checkouts. Its complete native suite ran 365 tests:
362 pass and three fail at the previously established workspace PID/proc liveness
boundary (two immutable-RPC, one candidate-plane); no production fence weakened.
Final hosted certification remains mandatory. Five new state-capsule tests pass:
exact SHA/policy/campaign/authorization lock, corruption/collision rejection,
interrupted installation before receipt publication, and real Survivor history,
partial/native ledger and sleeve transfer without creating capital. This module
does not yet dispatch or authorize a successor; runtime/controller wiring is next.

Ramses/state transfer batch pushed as `65d11fdf739623c35d6933f9ca8cc48e8754b12f`;
ordinary CI `36333697273` passes. No market or pressure dispatch.

Cross-window bridge now preserves a separate native book identity while each
supervisor window keeps its own run ID. Native Pons completed checkpoints still
reject ordinary reruns; an exact verified successor can restore one only when
campaign, authorization, predecessor index/run and copied checkpoint agree.
Nine capsule/native-checkpoint tests pass, including refusal to hide native open
exposure behind a flat controller claim. Pons bounded-history rollover and full
six-regime cross-window integration remain unfinished.

New controller prototype reuses the actual Git StateStore and global contention
inventory; the old single-campaign policy remains unchanged. Eight deterministic
tests pass using a Git API model with real non-fast-forward enforcement and the
actual workflow bytes: smoke review barrier, two normal successors, position-only
authority/identity, competing workflow rejection, CAS collisions, lost dispatch
response, and crash after durable intent before POST. A pending intent is never
retried. Workflow checks require both active registration and exact-ref content.
New autonomous workflow/adapter are uncommitted and still being wired; these are
not control-plane certification or market evidence. The same workflow will run
bounded native continuation before allowing new entry when positions remain.

Ramses terminal audit currently proves capital conservation but omits a durable
handoff proof for its sidecar/controller. The new state capsule correctly rejects
such open exposure. Next repair must read-only bind original entry clock, native
position/book/geometry and recoverable write-ahead intent to the existing sidecar;
do not weaken the capsule gate or infer flatness from an absent sidecar.

Ramses read-only handoff now binds the original native reservation clock, book,
asset, position, geometry and sidecar, including recoverable intents on both sides
of native commit. Missing/mismatched state retains open exposure and provides no
handoff authority. Native regression proves no writes during audit. Supervisor
clears stale report handoff flags when authoritative native proof is false.

The rolling workflow adapter now claims before provider access, reuses exact
certification and existing endpoint preflights, verifies preserved artifact/state
digests, restores the original book namespace, runs existing native windows, and
requires native review before successor intent. Position windows reuse the actual
continuation runners with a shared Solana owner and no discovery/entry authority.
Inspection exposed whole-artifact directional journal scans mixing Pump/Pons
schemas; each continuation audit now reads only its own native lane. Regression
demonstrates the old mixed count and the corrected separate identities. A capsule
also retains the last discovery window across intermediate position-only slices,
so Pons can bind its original discovery checkpoint after positions settle.

Ninety-four focused authority/runtime/continuity/accounting tests pass, including
workflow command claim/export, source-artifact corruption rejection and native
checkpoint transfer. Workflow YAML parses with seven dispatch inputs. No full
certificate, pressure rerun or market dispatch occurred. Remaining before Phase C
closure: execute the workflow adapters offline through all six actual native
states and position paths (not only controller transitions), verify failure
artifact/drain behavior, then query final-SHA registered dispatch availability.
Phase B restart/replay and Phase D long-horizon/steady-state gaps remain open.

Wiring batch pushed as `b2ca5fa2920dd41a8f69310a087c5661131e262e`;
ordinary CI `36335523112` passes and registration-only workflow `36335523146`
passes. Prepared source identities remain unchanged. The connected GitHub tool
has no dispatch operation and rejects direct workflow-registration GET endpoints.
Reuse the repository's external launch-request architecture: a separate request
branch checks out the exact runtime, verifies real workflow availability, consumes
a durable one-use launch intent, then calls workflow_dispatch. Four tests pass,
including read-only contract checks, malformed requests, exact certificate SHA,
ambiguous POST and duplicate rejection. No launcher has been executed yet.

Control-path audit found the engineering gate still recognized only Survivor-v1
handoffs, while current Pump/Pons terminal recovery produces controller-v2.
Added a strict v2 binding to the actual native proof, current controller schema,
unique position identities, no-entry authority and exact combined position count.
Both-lane tests now pass; mismatched/stale/native-missing/duplicate proofs fail.
Nineteen affected control/smoke-continuation/launch tests pass. This repairs gate
binding, not strategy or exposure policy. Full adapter and long-horizon proofs
remain pending; no market run or new pressure dispatch.

Two bounded long-horizon probes identify real remaining work. Actual Pump Survivor
evaluation at 263/514/1,012 points takes 0.0342/0.1191/0.4918 seconds, while retaining
the same qualified fixture decision. Its six-hour slope recomputes both exact
means inside every summand: quadratic work. Precomputing those two Fraction means
can preserve every arithmetic result; prove equality and linear operation count.
The unchanged History default also rejects 100,001 one-second observations at
age 100,000 seconds, well inside the approved 604,800-second candidate horizon.
The transaction rolls back and leaves the watermark at zero in this single-batch
causal probe. Do not raise the point limit: a durable archived boundary and exact
bounded feature-history representation are required. No repair to these two
findings has been implemented yet.

Launch/v2 handoff gate batch pushed as `a8f626f1dc8accad2eab06c1e2b3ca9f53cd46dc`;
ordinary CI pending refresh. Prototype exact-mean optimization now passes all 16
native Pump Survivor tests, including an independent pairwise covariance identity
and a deterministic linear addition-count bound. Complete old/new decisions match
at 263/514/1,012 points; new times are 0.0030/0.0078/0.0119 seconds. A dense full
six-hour 21,602-point evaluation completes in 0.245 seconds and qualifies; the
quadratic old full-density case was deliberately not rerun. Policy hash unchanged.
Prototype remains unstaged in the primary prepared Pump tree, exported to
`patches/autonomous-pump-survivor-history.patch`; it is not yet declared/composed
in source manifests. Batch it with the pending bounded-history repair. The
100,000-point/seven-day history defect remains open, as do full adapter execution
proof and multi-day steady-state/crash/provider matrices.

Do not close discovery/lifecycle decoupling with the current conservative rolling
prototype: it routes any open book to a position-only window before fresh entry.
This safely preserves positions but could suspend unrelated lane discovery for a
long Ramses hold. Normal successor admission must also support verified existing
positions once every native startup can resume its controller concurrently with
discovery. Pump and Meteora already have native restore paths; audit Ramses
async-manager restoration and Pons startup's synchronous recovery batch. Retain
the separate no-entry continuation route for contexts without fresh-entry
authority. This is pending engineering, not an accepted final orchestration design.

Ordinary CI `36336215318` passes on `a8f626f`; branch refresh confirms no newer
remote descendant. No market/certificate/pressure dispatch in this batch.
Normal-window audit reproduced synchronous recovered Meteora/Pons management and
missing Ramses recovered async ownership. Meteora now schedules its original
native restored lifecycle on the existing worker; no second reserve/entry or
nested worker. Native interrupted-mark regression preserves elapsed 300→600 and
holds exposure through a transient observation boundary while discovery returns.
A separate accelerated native 288-segment/24-hour run settled the same original
entry once with economic replay. Pons startup submits verified original trials
to the existing eight-worker pool before warmup; original curve exclusion and
shared reservations stay authoritative. Recovery receipts coalesce by native
identity while append-only receipts remain preserved. Seventeen native current
recovery/campaign tests pass; source overlay is declared and composed.

Ramses startup now reopens the funded campaign and starts its existing continuation
core only after exact restored-window/position/native-handoff validation. Discovery
can observe occupied capital without writing over the controller sidecar. A real
native book/worker regression proves no new genesis/entry, duplicate-owner rejection,
original clock preservation and durable handoff after a bounded provider-429 hold.
This exposed a missing write-ahead bridge on continuation provider-hold checkpoints;
those journal versions now commit matching sidecar state. Eleven affected canonical
lifecycle/recovery tests pass. Normal successors retain entry authority with verified
existing positions; no-entry position slices remain after the authorized normal
window budget. Twenty-two controller/state/adapter tests pass, including two normal
windows with retained positions followed by a no-entry continuation. Full native
workflow adapter, bounded-history, multi-day/crash/provider matrices still pending;
these focused results do not close Phases B–D.

Normal-discovery recovery batch is `2a61717b81ddcb5053e13b2a39019572cdba39f7`.
Ordinary CI `36337682834` ran 798 tests and found one failure:
`frozen_lane_drift:pons`. The new Pons composed-source digest was updated in
sources.json but omitted from profitability_protocol.json. Corrected only that
implementation-identity binding in the following history batch; frozen policies,
cohort acceptance rules and task manifest remain unchanged. Focused protocol
freeze verification passes. No unchanged CI retry was requested.

Survivor history repair now retains the original graduation anchor, exact last
24 hours and one boundary witness. Before removing any older point, runtime
requires a verified restored predecessor capsule, preserved artifact digest and
exact original history-file checksum. The raw observations remain in that native
artifact; each prefix records the removed-data hash and prior-prefix hash.
Pump carries the exact running reset scan/selected-reset low; Pons retains all
inputs its longest feature window needs. Archived price rewrites and past-window
queries fail closed. Both normal and no-entry position windows use their own
validated claim. Constructor no longer rewrites an unchanged policy row, allowing
an interrupted prune to roll back to the exact archived file identity.

Dense regression preserves the original 100,001-point capacity rejection and
rollback, then advances three archived/restarted windows beyond it: 86,402 points
after prune, 90,002 after each hour; hot DB growth stays within 1 MiB across these
windows and integrity passes. Independent old reset-scan arithmetic agrees with
incremental prefix reduction; complete native Pump and Pons decisions agree before
and after compaction, including Pons seven-day candidate age. Pump exact-mean
optimization is now declared in the composed overlay. Seventeen Pump and fourteen
Pons native Survivor tests pass; thirty-six affected canonical tests plus the
interrupted-compaction rollback regression pass. All four prepared source-integrity checks pass. The
full multi-day integration proof remains pending. Remaining
steady-state risks include retired identities, accumulated native journals/receipts,
Pons enrollment metadata, provider/crash matrices and full workflow adapters.

History batch pushed as `d493c28625dc9dbee5d6530f7e0b31ce7c33dabc`; prepared
Pump/Pons composed identities are `594150374d3137f3994082b7fce7485d2a93bab0fe221bc67544e98ac9c5ae1d`
and `7f7df98287b655e333e5b52fc7cf63db351c2a07df9858b9c5414ed627a8840f`.
Ordinary CI pending refresh. Phase-D native Ramses integration now runs actual
qualification, controller, geometry requalification, cost/P&L decomposition,
write-ahead checkpointing and ledger settlement with virtual provider evidence.
It crosses compound/recenter, three-day hold and original seven-day exit; restores
both sides of rebalance commit; discards a 211-second stale recenter and re-decides;
repeated final replay does not settle twice. This exposed only a terminal-reason
loss: the continuation settled correctly but overwrote the frozen controller's
maximum-hold reason with a generic flat-quote reason. Preserve the native reason.
Seven affected lifecycle tests pass; this repair/test batch remains uncommitted.


Ordinary CI `36338490587` passes at `d493c28625dc9dbee5d6530f7e0b31ce7c33dabc`.
Meteora crash-boundary audit found the existing deterministic restart guard
permanently halted on a journal-proven reserved-but-unfilled intent. A native
BEGIN IMMEDIATE recovery transaction now appends cancellation only for those
unfilled intents, before providers/workers start. Committed open/unresolved
positions remain occupied; an entry racing after cancellation fails its existing
state-machine guard. Regression covers idempotent reopen, mixed filled/unfilled
state, interrupted multi-cancel rollback and the actual run_live startup boundary.
This is PAPER execution recovery; no evidence or economic policy changed.

Pons had a second crash cut between cohort reservation and native reservation:
resume required one native position, so the original capital stayed held forever.
The cohort now atomically records its exact native reservation intent; recovery
under the existing exclusive lifecycle lock replays that missing intent and
immediately uses native cancellation. No provider or entry runs; original cohort
and shared-sleeve amounts release once. Eighteen affected native recovery,
cohort-capital and shared-sleeve tests pass, including the new actual startup cut.

Ramses first funding now uses one unpublished directory and durable original
funding intent. All original books must exist and be empty before atomic directory
publication; restart finishes the same budgets/run identity after interrupted
initialization. Already-published missing books still fail closed. Four cuts
(before/after first genesis, before/after publication) and nine campaign tests pass.
Meteora's eight accounting/recovery tests pass. Nine canonical long-horizon,
continuity, concurrent discovery/recovery and frozen-policy contract tests pass.
All four composed source checks and protocol freeze pass. Updated the directional
contract gate to recognize only the declared recovery files/overlays while keeping
approved strategy, policy, source and target-scope identities checked; mutation
regressions reject policy, strategy-file, target and unreviewed-overlay drift.

Focused six-regime directional acceptance passes all eleven gates on the composed crash-recovery candidate. No market work or full certification was dispatched.

Crash-boundary batch is `8f8952476d772bf9e0c0c0b138b16db84ddad387`.
Ordinary CI `36339852293` ran 805 tests; the two new policy-contract tests failed
because generic CI intentionally uses a shallow checkout without the historical
Git objects. Preserve the exact two baseline source rows as checksum-bound test
fixtures (with source SHA/path provenance), eliminating that test-only history
dependency. The production directional gate still compares the original refs.
Also corrected market-assurance scope text from stale six-hour Survivor age to
the already-approved four-hour age; no executable thresholds changed.

Six-regime capsule integration now uses actual current Pump fill, current Pons
post-graduation partial/controller state, both Survivor partials, a Meteora native
mark and a Ramses native position. Actual archive snapshot, digest-bound ZIP
extraction, original-worker deletion and relocated normal restore reconcile all
six without capital or journal changes. Extending this to the native Ramses book
constructor reproduced `native_position_projection_conflict`: identical native
positions carried different absolute worker-root locators in the shared evidence
projection. Fixed only known native trial/asset locators to lane-relative paths;
position/version/candidate/policy/book identity still compare exactly. Historical
projection bytes remain untouched on idempotent reads. Added conflict regressions
for changed quantities, policy and book identity. Position-only transport and
four-hour Survivor history advancement are included in the same native fixture.

Thirty-five focused workflow/controller/capsule/native-handoff/policy/projection
tests pass. The actual Ramses constructor now reopens against restored shared
projection state in both normal and position-only modes. Six native positions
retain accounting and journal prefixes; Survivor history crosses four hours.
The Phase-B matrix is now all PROVEN using this integration plus existing actual
native continuation tests. This is not final certification or market validation.
Three unchanged local Plane ownership tests retain the established PID/proc
namespace limitation; hosted gates still require them unchanged. Phase-C real
final-ref availability and Phase-D steady-state/provider soak remain pending.

Next measured storage discriminator: Solana retention removes completed archive
manifests from the hot DB, but campaign capsules copy the entire local cold archive
directory. Repeated windows can therefore recopy evidence already preserved in
native artifacts. Probe bounded archive-reference transport before changing it;
preserve all referenced chunks and every raw file in the preceding artifact.

Native-handoff batch pushed as `900a8349d0932550f9a39642d49dcca31e45a454`;
ordinary CI pending refresh. Archive probe reproduced 3 files recopied into a
successor with only 1 live DB reference (2 completed cold chunks duplicated).
Candidate repair filters only continuation capsules, after verifying the complete
native artifact snapshot. All referenced archive hashes/files and exact pinned/gap
DB state remain; no source/native-artifact file is deleted. The capsule binds the
full inventory and preserved snapshot hashes and reports transferred/externalized
counts/bytes. Both normal and position-only workflow adapters pass the verified
artifact to sealing. Referenced-copy and corrupted-preservation regressions pass;
this does not yet close the complete accelerated multi-day resource gate.

Ordinary CI `36340575811` passes at `900a8349d0932550f9a39642d49dcca31e45a454`.
The archive-handoff component now passes 168 virtual hourly windows (seven days)
through actual ServiceState archive/retention and capsule snapshot/restore. Every
restart first exposes an unavailable interval, then authoritative fixture repair
restores local reads; stale reinsertion remains rejected. One hot record remains
per boundary, one local cold chunk is preserved per window and zero completed cold
chunks transfer to successors. Inactive interests stay <=3, SQLite integrity stays
OK, hot files stay within a 1-MiB band after warmup, FD growth <=2, threads unchanged,
no temporary publication files remain. This is a bounded component soak; full
cross-lifecycle/provider/resource coverage remains pending. Missing/modified live
archive files and corrupt preserved snapshots fail closed.

Twenty-seven affected archive/capsule/native-adapter tests pass. Seven-day archive component hot footprint is exactly 546,624 bytes after warmup in this fixture; 168 distinct cold chunks remain preserved, with no cold duplication across the restored boundaries.

Archive-handoff batch pushed as `ed2a55708a59b682eb40216c16af14077537645e`.
Long-lived pin audit found a previously untested Pump Survivor IPC seam: after
fill, `_increment` passed lifecycle `position`, but the real evidence service
accepts only `open` for that state. The authoritative raw-migration regression
now promotes a held row through the real RuntimeEvidence/FinalizedFence path and
reproduces `invalid_interest`. The smallest native correction uses `open`, priority
0, preserving owner/address and all lifecycle pin semantics. Reopen the affected
Phase-B monitoring cell until this repair is composed and verified. Existing
native ledger and capsule continuity proofs remain valid.

Ordinary CI `36341134079` passes at `ed2a55708a59b682eb40216c16af14077537645e`.
A six-cycle real writer/consumer probe reproduces retained-index accumulation:
200 unrelated archived records per cycle grow from 201 to 1,201 total records
while the active owner remains pinned at slot 10 despite requested bounds through
slot 1,218. Conservative interest MIN semantics silently ignore consumed progress.
The measured repair is an explicit same-owner durable checkpoint acknowledgement,
issued only after native replay state commits; ordinary interests, other owners,
unresolved gaps, source authority and resource limits remain unchanged. Regressions
must distinguish pre-commit crash, lost acknowledgement, duplicate/conflicting or
foreign acknowledgement, restart and sustained retention before composition.

Checkpoint implementation passes same-owner monotonic/idempotent acknowledgement,
foreign/conflicting/future rejection, atomic rollback and retained gap/other-owner
pins. Pump persists consumed scope/slot/content hash in the same History transaction;
retry reuses the original checkpoint instead of deriving a different overlap bound.
Meteora acknowledges only committed native tapes and recovered replay state. Actual
native pre-mark/post-mark/post-ack cuts reopen and settle exactly once. This also
exposed terminal pin leaks after cancelled fills/writeoffs and in position-only
settlement: release now checks the native terminal state, retaining unresolved risk.

An additional deterministic account probe showed all five old account values still
pinned after consumed progress. Checkpoint-aware account retention now preserves
the latest boundary witness and all later values; any unacknowledged owner retains
all original history. The probe keeps slots 25/30 at bound 28, then the unchanged
slot-30 value at bound 40. Raw older observations archive with hashes/provenance.
The held-owner seven-day resource fixture includes account changes as well as
program records; no resource or evidence acceptance limits changed.

The composed repair passes 48 focused canonical/native-boundary/retention tests
and 48 native Meteora strategy/recovery/campaign tests. The extended 168-hour held
program/account fixture peaks at two hot records and 1,785,592 hot bytes (8,192-byte
warm-state band), preserves 168 raw archive chunks, and retains one checkpoint.
The existing 168-window capsule/archive component also passes (558,912-byte plateau).
Meteora startup reconciles same-book orphan/terminal pins after abrupt pre-reserve
or post-terminal cuts; unresolved and foreign-book pins remain. Both independently
prepared source trees compose identically. Phase-B monitoring returns to PROVEN;
the complete Phase-D joined resource/provider proof remains pending.

Evidence checkpoint batch pushed as `1f9573756ce1f03f4103f2b25c045013e8471507`;
ordinary CI `36342478094` PASS. Protocol freeze and all four composed
source identities pass. No market or full certification was dispatched.

Next causal reproduction: current Pons' actual campaign loop with 20,000 preserved
predecessor observations dispatches zero new lifecycle work because it applies the
per-window cap to cumulative history. A verified normal successor now records a
durable observation offset; the unchanged 20,000 cap counts only that window's
observations. Cumulative sequence/trial IDs, qualifiers, re-entry vectors, native
books and sleeve remain intact. The same actual scheduling fixture now progresses;
real capsule recovery and mid-window restart keep the exact offset. This fixes
capacity starvation, not the still-pending raw-history storage compaction problem.

The Pons window-capacity repair passes 13 capsule/native-handoff/capacity tests and six native campaign regressions. The new observation counter resets only under verified successor authority; mid-window restart retains it. No threshold, trial ID, re-entry rule or allocation changed.

Pons window-capacity batch pushed as `9389d72c705cced0d77d9877ac491d494db43b59`.
A fixed-hot-set resource probe (one market, one held Survivor position, one sleeve
candidate; six batches of 200 updates) measures persistent growth despite WAL
checkpointing: Survivor journal 202→1,202 rows, DB 167,936→851,968 bytes; sleeve
journal 200→1,200, DB 122,880→577,536 bytes; Robinhood observations/transitions/cache
each 200→1,200, DB 139,264→434,176 bytes. This is a remaining Phase-D failure.
Investigate preserved-prefix checkpoints, starting with the shared sleeve; exact
native balances/identities/generations and duplicate-settlement checks must survive.
Raw predecessor bytes must remain in verified native artifacts, with no limit change.

Ordinary CI `36342939773` passes at `9389d72c705cced0d77d9877ac491d494db43b59`.
Shared-sleeve preserved-prefix implementation now replaces only a predecessor
journal prefix whose exact SQLite snapshot is bound by the verified controller
receipt and native artifact. Newer hot journal rows stay. A transactional anchor
retains every position, candidate generation, capital/P&L, reservation and original
journal hash; regular append-only guards remain, including after rollback. Native
artifact chains retain the raw old rows. Automatic normal-window restore is tested;
missing preservation identity fails closed. Duplicate reservations/settlements,
wrong prefix, changed snapshot and pre-commit interruption all preserve authority.

Twenty-one affected controller/capsule/sleeve/accounting/native-handoff tests pass.
The fixed-hot-set sleeve component passes 168 hourly cycles / 33,600 candidate
updates with exactly 126,976 hot bytes after warmup and 168 distinct preserved
snapshots. This proves journal-prefix boundedness only. Candidate/position churn,
Survivor native journals, Robinhood raw histories/cache and the joined multi-day
resource/provider proof remain unresolved; no complete Phase-D claim is made.

Shared-sleeve batch `eb6fb8b46968ff4da9fa490a8ef3447cb614c5cd` passes ordinary CI
`36343459928`. The component's virtual observation clocks now span 168 actual
hourly boundaries; its 126,976-byte plateau is unchanged.

Survivor prefix checkpoints address the measured 202→1,202-row fixed-position
journal growth. Only exact predecessor snapshots already preserved in the verified
native artifact may compact. The anchor preserves native cash/positions/hash chain,
actual risk replay (including partial/high-water/trailing state), committed execution
costs and exact action counts. Newer hot rows remain. Campaign review proves an
archived prefix against the preceding report's event hashes; wrong prefixes,
eventless state changes and skipped historical proof fail closed. Raw old journal
rows remain in predecessor artifacts. No strategy/risk/exit policy changed.

Both frozen Survivor policies pass actual partial→restart→stop→settlement with
checkpoint cuts before/after partial. Automatic constructors in the real six-native
capsule handoff also compact and retain exact reconciliation/continuity. Thirty-five
affected tests pass; the 168-checkpoint storage component preserves 33,600 marks and
168 distinct raw snapshots with exactly 200,704 hot bytes after warmup. This is a
fixed-position storage proof, not a policy-horizon or full Phase-D completion claim.
Candidate/settled-position churn and Robinhood/Pons cumulative histories remain
pending. No market or full certification was dispatched.
