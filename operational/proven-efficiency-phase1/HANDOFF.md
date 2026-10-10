# PR #129 final protective-capacity handoff

**BLOCKED_BY_SPECIFIC_PROVIDER_OR_RESOURCE_CONSTRAINT.** Software repairs are
implemented and focused regressions pass. The unchanged two-RPS configuration
still fails demonstrated twenty-owner partial-exit and sender/slow-response
workloads. Higher rates are tested only in disabled offline profiles. Required
containment acceptance needs an unavailable delegated environment. No PAPER
readiness or provider capacity is inferred from synthetic timing.

Continue the same draft [PR #129](https://github.com/levonmendall/The-Meme-Machine/pull/129),
branch `integration/pump-pons-efficiency-rc-20261009`. Frozen acceptance source:
**`ad77dc805cfd0c8261eeabd335f48445c0d63df1`**. Latest runtime is
`ad77dc805cfd0c8261eeabd335f48445c0d63df1`; the native Pons implementation remains `f9c82e40baddb1a80520023c0243e25d55f4d1e2`. Native quotes, risk, monetary commits
and Current controller files retain the earlier implementations; Survivor step
scheduling adds bounded offline phase reservation and prioritized pending cohorts. Later
publication commits contain handoff evidence only. `FINALIZATION.json` is the
single completion register; `TEST_RESULTS.json` retains exact-source receipts.

## Source reconciliation and repairs

Started from clean published `ed7b3c6616c59bfce21e96097d175ed3212214c2`, retaining
all PR129 ancestry and previous tested `2ec2fff2`/runtime `e454af49` work. Original
October 8 worktree `cbfcb4137f10474ffc7fe0e19f0b8772f25c1563` stays clean. Deployed
`/opt/meme-machine` stays at detached `b577cc1c67f4d64f887b430f5e933f376b607dc2`;
PAPER is inactive, disabled, PID 0. No resets, older branch replay or merge.
Pro's archive, 27-category ledger, 104-row comparison and reference tests were
not supplied or inspected. Owner-provided economic models remain hypotheses.

| Commit | Repair and source paths |
|---|---|
| `b77d037ca4ae3841bf0807501242e079a966e45b` | Native full/partial exit consolidation and bounded offline account profiles. `pons_quotes.py`, `pons_survivor_runtime.py`, `pons_selective_paper.py`, `pons_current_workers.py`, `provider_admission.py`, `provider_topology.py`, `runtime/survivor_commit.py`; affected tests and offline registry. |
| `8c0cb5bca844d14ab76dd3d164a56f630006cb56` | Existing `engineering/proven_efficiency/finalization.py` compares actual ed7 methods and preserved Current held sharing. |
| `fee79ea4` / `57b0e85c99f7f1e84c26505eb0eef749a661c7fa` | Retain overload rows, original pending-exit refusal/accounting and native execution-fault recovery evidence. No failed capacity case is recast as timely protection. |
| `0ca74509f2f19c1181518fc3b0445b20dbf24593` | Portable test-only root-owner fixture and exact wall-clock boundary. Production owner/resource guards unchanged. |
| `71711d28560d7be41292a5fd7f253a33547bc842` | Singleton Current exits retain original identity reuse with no extra provider elements; real-clock native queue/CPU/commit probes. |
| `3c21002102987dfda23551c2b3211cb0122c2965` | Shadow source-order test follows the extracted helper, retaining native-risk/scale-before-shadow and HOLD guards. |
| `020a347720d35cdc5cacf6f0d62a85dfba001279` | Disabled offline comparison rejects an individual oversize response as well as aggregate overflow; charged reservation remains recorded. |
| `9f5a51378112f6ce9380c9bc50e43045453f4af6` | Repair concurrent provider-ledger WAL initialization, preserve the original total busy budget and FULL durability, close failed connections. Five deterministic setup checks and forty repeated native two-owner reopen/exits pass. Worker errors retain their originating traceback. |
| `da090e6d080383f0309517a5eb39aa4ead3360e8` | Offline-only bounded protection-phase reservation in existing `provider_admission.py` and Survivor step; earlier/equal protective deadlines retain precedence, expiry/exception cleanup, zero token/spending grant. Generic ordered-proof invalidation remains unchanged. |
| `f9c82e40baddb1a80520023c0243e25d55f4d1e2` | Compatible already-due pending Survivor exits acquire together; ordinary owners acquire after pending native commits. Original unproved-resource/private fallback retained. Six native parity/recovery regressions in `test_pons_capacity_repair.py`. |
| `286626b6e7c5c9e53af94afb5e28eb608fac3715` | Strengthen existing pending-owner acquisition test with exact native predecessor parity and the demonstrated eight-to-six quiet transport reduction. |
| `4dc4c0fb95270924146ece290f1ea9f2a444ae3b` | Correct the staggered Current timing test scope; directly assert original risk deadline, persisted integer fill due and executable observation freshness, plus safe admission-expiry refusal. Test files only; runtime unchanged. |
| `ad77dc805cfd0c8261eeabd335f48445c0d63df1` | Consume accepted maintenance outcomes before shutdown can report success; keep original lease/native-record checks, cooperative yields and native timeout identity. `meme_machine/solana_evidence_service.py`, `tests/test_production_maintenance_arbiter.py`. |

Pons paths above are under `meme_machine/lanes/pons/`. Exact full identities and
all changed paths are in the completion register. No new provider, accounting
engine, database authority, polling schedule or permission system.

## Minimum native acquisition and deadline semantics

An active warm held turn requires:

1. Fresh target header and original acquisition clock.
2. Hash-pinned compatible state/gas/exact remaining-quantity simulations plus
   unioned incremental pool logs.
3. Unique missing receipt enrichment; transaction-body fallback when sender is
   absent. Required identity/status/log/block/sender evidence is never omitted.
4. **Ordered** numeric membership fence for target, event blocks and checkpoints,
   after dependent responses. Batch response ordering is not a temporal proof.

Quiet turns omit the receipt phase. Already-authenticated warm pending recovery
therefore needs three transports for full exits and five for partial exits. Full exits reuse the exact completed native
held simulation only for its original quantity, gas/frame and freshness scope.
Partial exits need another compatible state/gas batch containing each original
partial quantity and another ordered fence: six normal active transports,
seven with a missing-sender body. A changed head, quantity, source generation,
provider session or endpoint-wide activity forces original fresh fallback.
No quote timestamps are renewed. Partial/forked evidence is never published.

`survivor_history.Worker.tick` schedules Pons observations at
`Runtime.observation_interval_seconds=3`; an unfinished step prevents overlap.
Current yields its original five-second `monitor_wait`. Its existing PAPER exit
intent stores integer observation time and **due = that time + two seconds**.
Both the native execution time and executable quote `observed_at` must reach
that persisted due. Historical event time and SQLite commit completion are
different clocks; neither is relabeled to manufacture freshness. Fresh execution
evidence retains its original five-second validity. The tables retain
a conservative three-second *completed Survivor turn* check and separate Current
risk/intention and final fill times; a late response is never a timely turn.

The two old partial-exit purchases per position were consolidated. No wait enlarges
a cohort. A bounded noncommitting preview folds risks from one verified native
snapshot; final native risk, journal replay, accounting and atomic commits remain
independent and authoritative. All-full exits need no new execution purchase.
Endpoint-wide transport activity invalidates proof reuse across another native RPC
session. The optional offline phase reserves service for an already-due cohort for
at most three seconds. It grants no provider tokens, ignores no in-flight completion,
and does not renew evidence clocks. Earlier/equal protective deadlines can preempt;
unavailable phases proceed through ordinary admission without waiting. Expiry and
exception cleanup release the reservation. Default profile is zero seconds;
production admission creates no phase table and remains at two RPS. Lost/stale/incomplete facts preserve native recovery and pending intent.

## Capacity evidence

`CAPACITY_REPAIR_NATIVE.json` contains 72 Survivor, 54 coincident Current,
27 staggered Current, 24 mixed specimens and eight real-clock probes, with native
traces, methods/logical CU/throughput, mock bytes, waits, independent quantities,
deadlines and accounting. The original Survivor measurement source is `57b0e85c`; Current and real-clock
measurement source is `71711d28`. The native quote, risk, execution and Current controller implementations retain
those paths. The final Survivor scheduler also consolidates pending recovery
and tests disabled phase reservations; original matrix timings retain their sources. Final
exact-source suite rechecks are recorded separately. Inputs and source equivalence are identified explicitly. Prior
`FINALIZATION_NATIVE.json` and `CAPACITY.json` rows remain historical evidence.

| Survivor workload, 100-ms mock response | Starts | Completion | Evidence |
|---|---:|---:|---|
| One active HOLD / full exit, 2 RPS | 4 | 1.66 s | Virtual admission plus conservative local-work envelope |
| Two HOLDs / full exits, 2 RPS | 4 | 1.67 / 1.69 s | Same envelope |
| Twenty full exits, 2 RPS | 4 | 2.13 s | Same envelope; old six-start defect removed |
| One partial exit, 2 RPS | 6 | 2.623 s | Final frozen real clock: queue, responses, CPU, native commits |
| Two partial exits, 2 RPS | 6 | 2.644 s | Final frozen real clock: queue, responses, CPU, native commits |
| Twenty partial exits, 2 RPS | 48 | 23.663 s **— late** | Final frozen real clock: queue, responses, CPU, native commits |
| Twenty partial exits, disabled 3 RPS | 6 | 2.481 s | Final frozen real clock: queue, responses, CPU, native commits |
| Missing sender, one partial, 2 / 3 RPS | 7 / 7 | **3.18 s late** / 2.22 s | Conservative virtual-plus-local envelope |
| Twenty partial exits, 600-ms responses, 2 / 3 / 4 RPS | 126 | About **77 s — late** | Freshness fallback; six dependent responses alone cost 3.6 s |

A real-clock probe measures queue wait, admission, responses, validation, CPU,
SQLite commits and final native completion directly. Earlier conservative
virtual-clock totals add all local wall work, including work that may overlap
waiting; they are not substituted for real-clock results. Both forms use mock
responses. Neither is authenticated endpoint capacity or P95/P99 proof. The real-clock
rows above are the final frozen `ad77dc80` FAST recheck. The preserved
020a FAST used 54 starts/26.670 seconds and the earlier runtime checkpoint used
36 starts/17.672 seconds for twenty partial exits at two RPS. Interleaving and
local timing change fallback counts; all three runs fail that deadline.

The native fixtures mock periodic `compact_survivor` maintenance. Native risk,
journal replay, reconciliation and monetary commits remain active. Host capacity
acceptance must include actual compaction, backup, supervision and containment
overhead, plus the outer worker's bounded observation-only telemetry and dispatch.
`Worker.tick` measures its interval from the previous submission and permits no
overlapping step; a long step postpones the next observation. The measured native
`Runtime.step` envelope does not prove that outer production operating envelope.

| Real-clock mixed partial exits, 100-ms mock HTTP | Starts | Last Current risk observation | Survivor completed turn | Last Current fill |
|---|---:|---:|---:|---:|
| 2 Current + 2 Survivor, disabled 4 RPS | 16 | 1.924 s | 2.404 s | 5.327 s |
| 10 Current + 10 Survivor, disabled 8 RPS | 34 | 1.361 s | 1.622 s | 6.288 s |

Current fills include original independent intent/delay/execution clocks. They
are not mislabeled five-second risk decisions. Native books reconcile in both
probes; these synthetic books do not claim the original $500 can fund arbitrary
counts. Real interleaving loses some idealized seven-start execution sharing.

Coincident Current HOLDs use four transports; compatible coincident full/partial
exits use seven, with separate quantity simulations and native durable owners.
One/two/four/eight/twelve/twenty owners were tested at 2/3/4 RPS. Staggered
2/8/20-owner fixtures at 4/8/12 RPS have no virtual risk-window misses; physical
counts vary with already-due work and valid fallback. Mixed 2+2 and 10+10 fixtures
at 3/4/8/12 RPS expose Survivor deadline failures at lower rates. No global capacity
claim follows from these specimens, and cold recovery/entry/market bursts can add
necessary demand. Actual endpoint/account-wide Pump headroom remains unknown.


Real-clock **staggered** followups are separate from that coincident table. At
9f5a5137, ten Current plus ten Survivor partial exits used 88 starts and completed
Survivor protection in 11.317 seconds at eight RPS (four unavailable Current
risks), and 6.317 seconds at twelve RPS. Further unreserved 12/16/20/25-RPS
traces all failed the Survivor window. Native accounting reconciled; the failed
success-oriented fixture's `KeyError('action')` is retained, never a protection PASS.

The source repair preserves the shared Survivor execution proof by an opportunistic
bounded offline phase. Final frozen real-clock checks: 2+2 at three RPS, 20 starts,
Survivor 1.916 seconds; 10+10 at twelve RPS, 69 total starts, **6 Survivor starts**,
Survivor 1.313 seconds. Every Current original risk deadline and native accounting
passed. Eight RPS still missed Current deadlines in repeated checks; a lower
universal minimum is not established. These are 100-ms mock responses, not provider
measurements. Current still performs independent exact quantities and its two-second
PAPER fill delay; private acquisitions remain where owners genuinely stagger.

Pending recovery is now source-grounded rather than inferred from first-exit tests:

| Warm recovery after native refused execution | Original starts → repaired | Real-clock repaired completion at 2 RPS |
|---|---:|---:|
| Twenty pending full exits | 98 → 3 | 1.781 s |
| Twenty pending partial exits | 119 → 5 | 2.851 s |
| One pending partial plus nineteen ordinary owners | 62 → 8 | **4.288 s late**; urgent exit 2.118 s |

The original baseline for these rows is **da090e6d**, with the original failed-intent
warmup excluded from the recovery-turn counts. Exact position, quantity, basis,
realized money and native risk parity passed for one/two/four/eight/twelve/twenty
pending owners. Reorganization and unknown-capability fallback remain tested.
The real-clock warmup is a separate zero-RTT offline fault seed; the measured
recovery waits until the original next required boundary and uses actual pacing,
sleeping mock HTTP, validation, native journal/reconciliation and final completion.
No quote clocks are reset. Warm pending recovery is distinct from the still-failing
cold/active twenty-partial workload at default two RPS.

Final supplementary real-clock measurements on the same frozen source:

* One pending partial plus nineteen ordinary Survivor owners: eight starts at
  two/three/four RPS. Complete native turns took **4.288 s late**,
  **3.115 s late**, and **2.548 s passing**.
  The pending exit itself took 2.118/1.458/1.126 s.
  Prioritizing it does not prove every ordinary owner met its original schedule.
* Ten staggered Current plus ten Survivor partial exits with bounded phase:
  nine/ten/eleven RPS each used 66 total starts. Survivor completed in
  1.246/1.287/1.195 s;
  all original Current risk deadlines, ten Current exit commits, ten Survivor
  realizations and native money passed. Nine is the lowest observed passing
  specimen; eight has known misses and twelve retains both final-suite rechecks.
  No universal safe rate follows from one 100-ms fixture at each lower rate.
  The prepared 64-start comparison cannot execute these 66/69-start complete
  mixed loops; they need a distinct trace-sized authorization envelope.

The pending/ordinary path acquires each ordinary exact remaining quantity and
its canonical fence after pending execution preparation. Extending a previous
proof without validating its state, gas, quantity and time scope would weaken
native evidence. The four-RPS passing profile remains offline-only. All six
followups retain physical traces, original deadlines and native monetary states
in `CAPACITY_REPAIR_NATIVE.json`; they are not live measurements or new savings.

A rejected attempt to reuse partial simulation while separately refreshing head,
gas and fence did not improve overload; it was removed. Original counterexamples
and rejected 8-RPS capacity assumptions remain in the native evidence register.

The lowest tested real-clock passing rate for twenty warm partial Survivor exits
is **three RPS** in the 100-ms fixture. Warm already-pending recovery fits two
in its distinct twenty-owner specimen. One/two normal partial exits fit two. Missing-sender specimens
need three in the tested virtual envelope. Coincident mixed probes use four/eight; the bounded-phase staggered
2+2/10+10 final-suite probes use three/twelve; the latter also has single passing
nine/ten/eleven-RPS followups. Pending-plus-ordinary needs four in its tested
envelope. No universal minimum is established. Six-phase
600-ms latency cannot be repaired by start rate alone. Production stays at **two**.
`GOVERNOR_REPAIR_DISABLED.json` documents the explicit offline profiles: logical
256/s, throughput 2,000 CU/s, 50 elements/method/s, 50/request, response 2 MB,
two in flight/4 MB, protected reserves and modeled charged-failure spending.
Both native role pacer and account admission use the profile in tests; there is
**no environment/configuration production activation path**.

Native sessions do not automatically enable `shared_quote_resources`; the
resource descriptors in these measurements are fixture inputs. Authenticated
endpoint bounds and a reviewed production binding are still required. Absent
that proof, the complete original private acquisition path remains available.

## Retained strategy, history and accounting

Current still prepares authenticated 900-second history before fresh execution,
retains complete intervals and acquires missing delta/final tails. Earlier
25-event boundary: original full-window pass 43 mock starts/6,340 modeled CU;
missing prefix 25/5,500; retained unchanged pass 3/60; new block delta 4/140.
These prior savings exclude quotes/sizing and are not counted again here.
One add, first realization, 2x, fifteen-minute persistence, gross-high 15% proximity,
7.5% sleeve exposure, capital/liquidity and final native freshness stay intact.
Missing history blocks the add, never future reconsideration or protective exit.

Source/ABI/topic registry, risk-fold reuse, durable shared receipts and obligations,
conditional dense receipts, Pump known-slot/account-union preparation, PR126 fresh
held consolidation, PR127 asynchronous shadow, native continuation and portfolio
accounting remain. Full monetary replay reuse remains inactive. Previous local
benchmarks and source reconciliation are retained in the existing JSON artifacts.
The operative Survivor two-position veto remains removed; its descriptor survives
only for durable compatibility. Current has eight entry plus eight protected
workers with durable temporary deferral and filled-owner handoff, no position
count veto. It never fabricates an entry after its original deadline.

Original 5% allocation, realized-equity compounding, creator/concentration/liquidity,
first-profit/stop/trailing/right-tail, high water, position identity, independent
Current-to-Survivor decisions and native recovery remain. Event-only quote
suppression and exceptional-winner extensions stay inactive. The original 36/72-hour
strategy economics are unchanged; capacity/budget failure is exposed operationally
with native recovery/exit intent, not a new infrastructure liquidation rule.

## Offline acceptance

FAST: **1,437 tests, 0 failures, 3 errors, 0 skipped**, 1,959.155 seconds.
OPERATIONAL: **2,861 tests, 0 failures, 3 errors, 33 skipped**, 2,340.093 seconds.

Both are **COMPLETED_FAIL** because required containment errors remain; no full-suite PASS is claimed. `TEST_RESULTS.json` preserves actual receipts and unchanged before/after source fingerprints.

Preserved predecessor **9f5a5137** completed FAST 1,422 tests and OPERATIONAL
2,843 tests with zero failures and three containment errors each (33 OP skipped).
The intermediate da090e6d run was stopped for the independently demonstrated
pending-owner acquisition defect; it is an interruption, not acceptance.

The preserved `020a3477` receipts were FAST 1,417 tests (zero failures/three
errors) and OPERATIONAL 2,838 tests (one failure/three errors/33 skipped). The
OPERATIONAL failure exposed a real local provider-ledger WAL initialization race;
it was reproduced after 32 successful native two-owner iterations, repaired in
`9f5a5137`, and validated by five deterministic setup tests plus forty
successful repeated native two-owner exits. A 44-test adjacent development suite
passed. These are development receipts; final frozen suites are authoritative.

The preserved **286626b6** run completed FAST 1,436 tests with zero failures and
three containment errors; OPERATIONAL 2,857 tests had **one failure**, three errors
and 33 skipped. Its clock-monotonicity test also assumed that twenty staggered
Current exits always settle at four RPS. One actual native owner correctly refused
late execution and retained pending intent/recovery. Twelve subsequent native
replays do not erase that failed interleaving. The final test uses the existing
2-owner/4-RPS, 8-owner/8-RPS and 20-owner/12-RPS offline profiles, retains strict
successful fills and native accounting, and adds direct original risk/due/freshness
checks plus an explicit admission-expiry refusal regression. Runtime economics,
deadlines and production two RPS are unchanged. Rejected development assertions
that confused floating commit or historical event time with native integer due
are also retained in the test receipts; no source timestamp was changed.

The preserved **4dc4c0fb** run completed FAST 1,437 tests with zero failures/three
cgroup errors and OPERATIONAL 2,858 tests with one failure/three errors/33 skipped.
The OPERATIONAL queue-expiry assertion exposed a genuine shutdown race: an accepted
maintenance owner had failed, but its awaiting coroutine was still pending when
stop won. A deterministic replay returned no error and persisted phase `OFF`
despite `maintenance_owner_lease_exceeded`; native records were unchanged. The
successor consumes the accepted outcome before cancelling its waiter, preserving
native failure identity, the existing five-second owner-close bound and nonterminal
cooperative yields. No original assertion was removed. **53 affected tests ran: 47 passed and
six existing archived-model tests were skipped**; three new regressions cover the delayed
failure, cooperative yield and native timeout. Sixty passing isolated original
calls did not erase the full-suite failure or the deterministic counterexample.

Latest Current timing/ownership regression: **14 tests PASS**. Earlier affected
regression: **66 tests PASS**, including eight phase tests and six pending-recovery
tests. Development focused receipts include 73 acquisition/profile/native regressions,
12 final singleton/owner checks, two real-clock probes, 59 shadow/identity checks,
35 comparison/budget/package checks and 30 portable startup/storage checks.
These overlap and are not summed or substituted for the full suites.

The source-identity repair is preserved; original economics/nine-test pins remain.
GitHub exposed stale test-only root UID, floating exact-wall-boundary and extracted
shadow-location assumptions. Those fixtures were repaired without changing
production ownership/time/resource assertions. Earlier interrupted suite attempts
are retained as interruptions, not accepted runs.

Local containment still lacks delegated I/O and writable child controls. Existing
GitHub runners also lack enforcement and the required dedicated two-vCPU host.
No available suitable authorized environment was found. Original CPU/memory/I/O,
process-kill, escaped-descendant and write-accounting tests are unchanged.
`CGROUP_VALIDATION_ENVIRONMENT.json` gives exact errors and minimal Linux/cgroup-v2/
seccomp environment. No skip or simulated containment is accepted as PASS.

## Incremental purchasing economics

`FINALIZATION_COST.json` compares **ed7**, preserving previous held sharing and
excluding earlier PR124–128/L1 gains. Identical-evidence fixture decisions reconcile
within compatible sharing/resource scopes. These are synthetic purchase counts;
default two-RPS overload can force extra fallback, and Current quotation-component
counts do not replace the whole-controller traces above:

| Cohort | Starts before → after | Modeled billed CU avoided | USD per 1,000 cohorts at $0.525/million CU |
|---|---:|---:|---:|
| Survivor full exit, any tested count | 6 → 4 | 60 | $0.0315 |
| Two Survivor partial exits | 8 → 6 | 20 | $0.0105 |
| Twenty Survivor partial exits | 44 → 6 | 740 | $0.3885 |
| Two Current full/partial exits | 10 → 7 | 60 | $0.0315 |
| Twenty Current full/partial exits | 64 → 7 | 1,968 | $1.0332 |

HOLD and singleton Current purchases are unchanged. These are synthetic purchase
reductions when valid sharing succeeds, not bills. Do not add rate variants,
HOLD plus exit for the same turn or historical comparisons. Stale/private fallback
can spend more and miss deadlines. Monthly workload/action frequencies and actual
marginal tariff are unavailable; monthly net savings remain null. No blanket retry
multiplier or unattributed busy/extreme forecast is retained as an operating bill.
Additional warm recovery comparisons against da090e6d: twenty pending partials
avoid 114 starts/2,260 modeled CU ($1.1865 per 1,000 disjoint recovery cohorts);
twenty pending fulls avoid 95 starts/2,280 CU ($1.1970); pending-plus-ordinary
avoids 54 starts/1,034 CU ($0.54285). These do not add to cold exit, phase or prior
PR savings for the same physical purchase. CPU/local wall changes are recorded,
not assumed to reduce host spending. Actual external provider calls and realized
provider/host savings here are **zero**.

The retained Pons copy records 3,010 physical starts, 3,009 completions and 11,828
logical elements, estimated at 270,932 billed CU. Largest methods are `eth_call`
(188,552 CU) and `eth_getCode` (72,640). Its audit ring still has 1,413 unattributed
records/130,886 estimated CU; that ring overlaps lifetime totals. The separate
Pump completed-response window has 3,631 requests, 85,230 estimated CU and
95,059,577 delivered bytes; 1,748 purchases/35,350 CU remain unattributed. Legacy
consumer/evidence/deadline links and failures before response capture are unknown.
Equal arguments alone do not prove waste. Historical Ramses records remain
separate and cause no operational workload. No window is extrapolated to a bill.

Local replay batching serves noncommitting preview only; every native monetary
check remains. Twenty-partial unpaced CPU measured 0.5555 → 0.5987 s in this specimen;
no material local CPU/host-dollar reduction is claimed for this repair. Harness
RSS (about 88 / 76 MiB in the two reproduction runs) is not server sizing.
Physical purchases, reuse, failure, native deadline/decision links are recorded
where available; absent legacy evidence/bytes/consumer fields remain unknown.

Pons standard-RPC Chainstack equivalence is the smallest conditional provider move;
Alchemy Solana streams/enhanced history stay. `PROVIDER_COMPATIBILITY.md` records
current official prices, archive rules, whole-plan/fallback sensitivities and the
disabled comparison envelope. No subscription or credential is required by this
release. Net expected migration benefit cannot be established from missing monthly
distributions or included RU alone.

## Operational and authorization boundary

`FINALIZATION_SAFETY.json` verifies all seven native monetary files remain byte
identical, including the original $500 portfolio, epoch and canonical journal.
Deployed checkout/configuration/provider limits and service state are unchanged.
Meteora/Ramses remain paused. No trading/funding/signing, paid provider workload,
merge, deployment, host upgrade, service start/restart or new alert message.

| Existing requirement | Source status | Separate operating evidence |
|---|---|---|
| G01 | Volume/epoch/no-reseed controls retained | Actual current device/inception/permissions/startup |
| G02 | Coherent backup and isolated native recovery retained | Current off-host point and recovery with open owners |
| G03 | Independent monitor/owner attention retained | Fresh unattended monitor and alert delivery |
| G04 | Durable phase observations retained | Candidate CAPACITY/RECOVERY/AUTONOMY outcomes |
| G05 | Read-only dashboard transport/health retained | Snapshot freshness/replication/cutover |

Existing engineering was not rebuilt; prior receipts remain in
`operational/pump-pons-consolidation/HANDOFF.md` and bootstrap preparation.
Schema compatibility alone cannot justify rollback while positions are open:
a predecessor with insufficient protective capacity is not an automatic safe
rollback target. Retain original owners, journals and exit intent through failure.

Next external requirements, not executed or authorized here:

1. Existing authorized dedicated two-vCPU delegated cgroup-v2 environment; run
   unchanged containment tests and complete required acceptance there.
2. Confirm exact account tariff/allowance/archive/batch/failure treatment. Then
   separately authorize read-only Pons comparison: **60 s, 64 aggregate starts,
   256 elements, 16 MiB, 2 MB response/in flight, two RPS, zero retries**. Monetary
   ceiling stays null until independently verified; public $0.008064 arithmetic
   does not authenticate a $0.01 ceiling. Stop on any budget/evidence/timeout/failure.
   No subscription, trading authority or state change. No archive proof from an
   unsupported free endpoint.
3. Separately authorize higher-rate proof only with verified provider/account-wide
   headroom and spending. Start with the three-RPS warm partial specimen, retaining
   bounded starts/elements/bytes/throughput/in-flight/protection budgets. Mixed
   nine/twelve-RPS bounded-phase hypotheses and the four-RPS pending-plus-ordinary
   case need their own complete native deadlines, sender,
   slow-response, staggered, entry/recovery and actual RTT/payload evidence.
4. Only after capacity and required offline acceptance pass, separately authorize
   original-epoch bounded PAPER CAPACITY/RECOVERY/AUTONOMY and G01–G05 verification.
   Preserve native intent/owners on failure; no reseed or arbitrary forced exit.

Offline reproduction uses CPython 3.12.14, pinned requirements and the existing
network-guarded Scratch driver:

```sh
python -m operational.tests FAST --verbose
python -m operational.tests OPERATIONAL --verbose
python -m operational.tests FAST --modules tests.test_pons_capacity_repair tests.test_pons_current_exit_sharing tests.test_pons_rpc_equivalence_preparation --verbose
python -m engineering.proven_efficiency.finalization --capacity-repair --output /tmp/pr129-capacity.json
```

`--family current` replays changed Current paths without repeating byte-unchanged
Survivor specimens. Private logs/failed Scratch evidence are retained; no native
state or secret archive is committed. No further identified source defect remains
in these repaired paths; external capacity, containment and authorized PAPER
acceptance are the remaining readiness boundaries.
