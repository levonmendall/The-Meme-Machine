# Continuous Pump and Pons PAPER successor

This successor continues `df6274e270bcf40b818428a359b30e88ceb21ffb`. It does not
replace the frozen release, reinitialize capital, redesign the dashboard, or
grant provider-test dispatch authority. The intended final configuration contains
Pump Current, Pump Survivor, Pons Current and Pons Survivor. Meteora and Ramses
remain paused. Exact published/tested/deployed identities belong in the execution
receipt; the source file hashes in `CONTINUOUS_VALIDATION.json` identify the code
tested before publication.

## Repairs and operational changes

The last authorized Pump retry at `df6274e...` delivered 119 scouts but no
canonical program checkpoint or economic publication. Its retained journal
reported `reconnect_cursor_regression`: an authenticated overlapping control
block preceded a later open outage gap, and the fence tried to use that earlier
block as the gap's reconnection boundary. This is a reproducible local defect.
The fence now retains that later gap open until a qualifying authenticated
boundary arrives. Earlier receipt authentication, hash conflicts, strict writer
ordering and the requirement to actually repair gaps remain intact.

Control reconnects now refresh the finalized tip and clamp their request to the
existing conservative 6,000-slot replay window. A stale checkpoint outside that
window remains unavailable history; current streaming does not invent coverage
for it. The earlier Alchemy `INTERNAL` / `RST_STREAM ... error code 2` observations
remain preserved. The failed `df6274e...` retry established the local regression,
not a new provider INTERNAL diagnosis. Provider success after this repair still
requires authenticated evidence.

The subsequent authenticated canonical-worker diagnostic received native data
but published no economic events or program checkpoints. It retained 15 physical
starts, seven logical RPC elements / 140 CU, and 330,695,967 accounted native
bytes, below the unchanged 512-MiB diagnostic boundary. No native INTERNAL was
recorded in that attempt. A separate first-failure diagnostic reproduced INTERNAL
on the sliced Pump account scout. These are failures, not protection passes.

For a checkpoint already outside the supported replay window, control now starts
the current 256-slot linked tail rather than purchasing 6,000 old slots that
cannot repair the earlier outage. The original gap, coverage and candidate/held
history obligations remain unavailable until their own actual repair. New bounded
join-state/close observations retain missing log, metadata and finality facts.
Fixed candidate failure reasons survive the safe process diagnostic. Rolling
retries back off to eight seconds and reset only after real durable publication.

The authenticated Pons route diagnostic read six authenticated hook-free direct
WNATIVE/USDG pools at canonical block 85,988,696. Every getSwapOut response returned
the whole 10^15-wei input unspent and zero output. The existing oracle round/code
acquisition alone cannot convert ETH to USD. Native USD route readiness therefore
fails closed; no fixed rate or historical snapshot replaces it. This diagnostic
used ten physical starts, 34 logical elements / 780 CU, 129,156 response bytes,
and a public-price modeled $0.0004095. It establishes the specific tested route
failure, not the nonexistence of every possible on-chain route.

A local FULL-durability SQLite journal benchmark did not show a WAL advantage;
no speculative journal/commit change was made. The 67 affected regressions and
their exact file hashes/log are retained in CONTINUOUS_JOIN_REPAIR_VALIDATION.json.

The subsequent `75288fec...` diagnostic advanced the current control tail, but
the economic stream remained in its replay prefix. Per-frame durable native
metering averaged 27.8 ms and ended with a five-second SQLite operation failure.
Its original exception code was not retained; a successor diagnostic records only
validated SQLite names/codes, never arbitrary exception text. The failed run and
all counters remain in AUTHENTICATED_PUMP_METER_FAILURE_752.json.

Native intake now groups only immediately ready SDK frames, in FIFO order, up to
32 frames / 16 MiB, with no positive batch timer. The exact group byte total is
durably committed before any content is returned to an economic consumer.
Cancellation waits for an accounting transaction already started. One look-ahead
frame and the existing SDK buffers are covered by a larger conservative per-open
reservation: 64 MiB for Yellowstone and 80 MiB for WebSockets. The installed
512-MiB native in-flight/diagnostic boundaries are unchanged. This reduces
duplicate durable-writer work; it does not eliminate delivered-byte charges or
claim provider equivalence before another authenticated observation. Frame,
failure, queue and canonical requirements remain unchanged.

The `96ae082d...` retry published two linked initial program intervals but no
normalized economic records, then filled the 32-MiB log join while native status
delivery lagged. Zero-wait polling still allowed roughly one SDK read per durable
meter commit. The reader now continues into a bounded ready group during a
durable write; both charged and ready groups and one look-ahead frame are covered
by the conservative reservation above. No batch timer, late-log discard or
coverage shortcut is introduced. A ready group commits before any content is
returned. Actual provider equivalence remains unproved.

The same run exposed an optional candidate archive failure terminating the whole
collector. Optional failures now remain on their existing acquisition job: a
retryable failure has a durable exponential backoff up to 30 seconds, without
resetting its cursor or original deadline. Nonretryable/expired failures remain
unavailable and retained. A mandatory or concurrently upgraded protective job
cannot borrow this deferral. Safe fixed method/status/cause fields are retained
for RPC failures; arbitrary exception messages and credentials are excluded.

The previously declared two-RPS validation envelope was not the actual hybrid
governor setting: enabling the Solana plane selected a 50-ms interval. The
successor makes operational pacing explicit and seals bounded-test pacing in the
existing usage ledger before dispatch. The default operating and Pump validation
profiles use 500 ms. A changed diagnostic pacing file refuses dispatch without
resetting counters. Existing protected request priority and method backoff remain.

Continuous PAPER uses the existing `Budget` database, supervisor and native
managers. It has no cumulative dollar, CU, request, byte, stream-opening or
reconnection allowance. Actual in-flight HTTP/native reservations, frame and
response bounds, shared pacing, queue and host resource checks remain. Eight
native failures within 60 seconds open a durable 30-second reconnect backoff;
the lifetime count is telemetry, not a permanent eight-opening lockout. This
does not confer evidence freshness or mark degraded positions protected.

The same usage database records lifetime counters and UTC hourly aggregates;
daily/monthly reports sum those aggregates. Public-price estimates, hourly/daily/
monthly warning thresholds and a threefold recent-usage trend warning are exposed
to the existing monitoring path. They never trigger liquidation or healthy
protection shutdown. Diagnostic ledgers and all their failed usage remain retained;
they are not converted into fresh experiment allowances. An installed continuous
scope change preserves its counters, clocks and history, records the configuration
change, and requires fresh readiness.

Normal admission evaluates current selected-regime readiness instead of the
unconditional `combined_position_and_candidate_provider_latency_not_certified`
prohibition. Startup may acquire read-only evidence while funding remains closed.
Live funding requires the exact selected profile/epoch-local ledger, a live
supervisor process identity, recent readiness, canonical progression and native
recovery/exit wiring. Native qualification, exact executable quantity, USD
validity and the shared authority still gate each actual reservation/execution.
An unpublished old checkpoint cannot borrow a newer program block's market time.
No source flag substitutes for the missing authenticated protection trial.

Normal worker discovery loops have no bootstrap clock. Repeated positions and
settlements use the original cash/exposure/capacity rules. The runtime run ID and
usage history survive restart; each actual process registration receives a new
idempotent command identity rather than replaying the first PID/time. Funding
closure and canonical worker recovery do not discard or stop native owners.

## Restriction inventory

| Restriction and source | Origin / effect | Disposition and current replacement |
|---|---|---|
| Unconditional Solana production prohibition; `solana_selective_source.py` | Development certification pending; refused all ordinary PAPER irrespective of live facts | REMOVE. `operational/admission.py:require_normal` checks selected live readiness and native risk gates. |
| 600-second readiness cutoff; supervisor `bootstrap_tick` | First-owner bounded experiment cutoff | TEST ONLY. `normal_tick` can warm/recover indefinitely; 60 seconds of genuine progressing coverage is still required before reopening risk. |
| 1,200-second funding / 1,800-second bootstrap; admission and continuation | Limited initial experiment | TEST ONLY. NORMAL/AUTONOMY carry neither funding nor stop timestamp. |
| One lifecycle, $25 gross allowance, initial/addition fee ceiling records | Historical first-position diagnostic guard | TEST ONLY. Continuous reservations use the approved shared realized-equity policy, not that gross allowance. |
| One-time bootstrap claim and finite recovery/continuation envelopes | Prevented replenishment of finite authorized experiments | TEST ONLY. Those experiments remain nonrenewing; continuous operation has a separate explicit capacity profile. |
| Lifetime CU, logical/physical calls, bytes, dollars and openings; `bounded_provider.py` | Diagnostic monetary/resource envelope | TEST ONLY. Continuous totals are durable telemetry; current in-flight bytes remain admission constraints. |
| Boot/wall expiry in the provider ledger | Bounded test identity and timer | TEST ONLY. Continuous restarts retain history without exhausting an allowance. |
| Native reconnects | Originally limited an experiment's total openings | REPLACE. Durable rolling failure backoff, source recovery and current evidence health; no lifetime reconnect lockout. |
| Historical 50-ms hybrid Solana default | Engineering throughput profile; contradicted authorized observation pacing | REPLACE. Explicit sealed operational/diagnostic endpoint pacing. Historical offline probes keep their own fixtures. |
| Pons two-RPS shared admission plus two-RPS local pacer | Conservative development aggregate limit | REPLACE. Both read the same explicit installed operating pace. Baseline remains two RPS; four-RPS alternative is prepared, inactive and requires real validation. |
| Pons shared endpoint cooldown / deadline / priority queue | Provider failure and physical contention | KEEP. Protected work outranks optional discovery; latency and cooldown cannot extend quote validity. |
| Temporary Pump discovery/follow-up and Pons campaign end timestamps | Engineering campaign lengths | TEST ONLY. Continuous campaign loops do not expire; native shutdown and health controls remain. |
| Robinhood startup dependency during Pump-only observation | Two-family bootstrap default | REGIME SPECIFIC. Only selected/obligated families require their own credentials and economics. The final four-regime profile requires both. |
| Seven-day Pons historical preparation | Explicit historical research/recovery | REGIME SPECIFIC. Existing forward acquisition remains ordinary startup; each candidate still requires its actual strategy history. No new removal was necessary. |
| Candidate eligibility ages / lookbacks / economic freshness | Original strategy rules, distinct from holding age | KEEP. Do not treat them as administrative holding limits. |
| Holding-age sale or profit-multiple ceiling | Earlier owner-approved removals | REMOVE already integrated. This successor does not change economic exit helpers, tail bridge or high-water decisions. |
| Physical native entry/owner worker pools and bounded candidate queues | CPU, memory and response capacity | KEEP. These are reusable work slots, not permanent position-count vetoes; occupied entry work defers rather than erases eligibility. |
| Per-operation RPC sessions, batch size and recovery page limits | Prevent malformed or runaway work within an acquisition | KEEP. Existing session rotation/checkpoints permit ongoing work; no lifetime operating quota is derived from them. |
| Canonical membership, explicit gaps, sender/receipt obligations and stream completeness | Trading evidence correctness | KEEP. Scouts, quiet streams and cached values never confer qualification or protective authority. |
| Exact native quote, token/pool/hook authentication, gas and fees | Executable economics | KEEP. No quote suppression or stale-cache promotion is enabled. |
| Pons USDG oracle / native route and five-second boundaries; `runtime/usd_valuation.py` | Financial correctness | KEEP. Prior verified oracle evidence is historical, not a current route-capability pass. |
| Pump and Pons protective observation intervals / native timing | Strategy and exit protection | KEEP. Pons Survivor three seconds, Current five seconds; no deadline is relaxed. |
| Cash, reservations, asset/aggregate/family/regime exposures and additions | Approved $1,000 capital policy | KEEP. 5% initial, eligible 2.5% addition, 7.5% cumulative asset reference, 10% marked admission reference, 75%/45%/30% exposure references and original cash/drawdown controls. |
| Single writer, process ownership, idempotent delivery and no reseed | Capital/recovery integrity | KEEP. Missing previously selected continuous usage history requires restoration, not a fresh database. |
| Persistent volume identity, disk guards, memory/CPU and resource verification | Physical operating capacity | KEEP. Root warning cleanup does not waive storage checks. |
| PAPER-only environment, read-only provider allowlist and no signing/submission | No real-money authority | KEEP. Unpriced/writing calls fail before dispatch; no wallet funding or on-chain orders. |
| Exact same-source CAPACITY → RECOVERY → 36-hour AUTONOMY sequence | Evidence for sustained unattended claims | KEEP for those claims. NORMAL's first protected admission does not require completion of a future 36-hour observation. |
| Meteora/Ramses pause and historical account isolation | Owner-directed scope and accounting | KEEP. No workers, funding or active dashboard cards for these families. |

## Prepared configuration, activation and remaining proof

`deployment/paper-continuous.pump-first.json` independently selects Pump Current
and Survivor. `paper-continuous.four-regime.json` selects all four at the conservative
two-RPS baseline. `paper-continuous.four-regime.4rps-unvalidated.json` retains Pump
at two RPS and proposes Robinhood at four RPS. It is **not installed or certified**.
Profiles specify physical resources and warning thresholds, not capital grants.
`paper-continuous.conf` targets the existing service and isolated $1,000 state root;
it must replace the validation drop-in coherently. Acceptance must use the same
private environment/profile/usage path. No historical environment-file precedence
may select the $500 database.

A source-level seven-start Pons active specimen already demonstrates why two RPS
cannot establish three-second completion before the final response. A four-RPS
profile changes only physical pacing; it cannot prove endpoint latency, USD route
availability, complete history or four-regime capacity. Wider logs, compatible
sharing and receipt reuse from the integrated release remain unchanged. Do not
activate a higher rate merely because the dashboard advertises 10,000 CU/s.

Before funding either family, authenticated observation must establish its actual
canonical coverage, complete genuine candidate qualification, fresh native and
USD economics, response/queue latency and concurrent protection. Unobserved
adverse events use retained valid offline replays with that scope explicitly
labelled. No forced trade establishes a lifecycle pass. Full completion also
requires the real combined CAPACITY, RECOVERY and sustained AUTONOMY milestones,
with all four regimes enabled and protected. Pump may pass independently first;
Pons remains part of this assignment until its own requirements pass.

The already initialized epoch is `paper-shared-1000-20261011T071207Z`, inception
SHA256 `aea262d34d976cddeddf83f57045508cf09f3c8e28cf8a2c73ae49d38cc261b1`.
Its approved risk-policy SHA256 is
`b91e83300994b6c02fe5e6bdbeb031cc391e6c8caa97af9fa6df1ecbc4aa979c`.
Do not initialize it again. The historical $500 portfolio remains independent.
The dashboard stays at its restored appearance and authentic new-epoch snapshot;
only its accepted runtime source pin changes when a tested source is installed.

Provider charges in these records are conservative public-price estimates, not
authenticated invoices. Normal operation has no expiring engineering budget.
The latest owner directive authorizes essential targeted authenticated checks
in the repair/deploy/observe loop. Each diagnostic keeps an explicit technical
envelope and a durable new run identity; the consumed prior retry is never reused.
This does not waive external tool controls or authorize unsafe funding.

The immediate acceptance milestone is 60 consecutive real elapsed minutes with
both families and all four regimes funding-ready on the reconciled $1,000 epoch.
The clock starts only after authenticated coverage and native protection pass;
meaningful coverage, readiness, worker or protective interruptions reset it.
Separate healthy intervals cannot be combined. A passing hour leaves the service
running and does not constitute an unobserved trade lifecycle or the separate
36-hour sustained-autonomy proof.

`CAPACITY` now checks all four selected regimes' current live funding readiness
at every sample and fails the interval immediately on a meaningful interruption.
Its separate recovered run must complete the entire hour. Existing longer
self-recovery observation remains labelled separately. Admission uses the
existing query-only authority reader on acceptance's read-only epoch mount,
without constructing a schema/WAL writer.

The first successor's FAST failure is retained. The correction preserves
bootstrap's all-regime eligibility observations and selected-scope reservation
guards, supplies the reconnect fixture's newly mandatory tip acquisition, and
replaces assertions of the obsolete unconditional prohibition with assertions
of current protection refusal. Economic, freshness and capital assertions
remain intact. Authenticated Pons USD route availability is still unresolved;
its failed diagnostic is not a native protection pass.
### 2026-10-11 18:50 UTC checkpoint

Published source `00f1327a010eaadd8c987379a348fecf4a16b993` passed required
FAST CI: 1,620 tests in 1,450.386 seconds. The authenticated read-only intake
published Pump and PumpSwap economic records, but failed sustained coverage:
22.81-second market-to-publication lag, candidate log-buffer pressure and the
diagnostic's accounted-native stop. The 512-MiB boundary was preserved, as were
all historical gaps and usage counters. This is not a position-protection pass.

The next narrow repair batches already available scout locator facts on the
existing canonical owner. It retains priority 5, FIFO order, original times,
durable lifecycle wakeups and rollback; no batch timer or economic authority is
introduced. A 64-fact queue holds at most 128 KiB serialized, not native frames.
One available 64-scout burst uses one writer admission and one durable commit.
Focused locator/intake/closure/startup regression: 58 tests passed in 28.043s.
Live latency improvement remains unproven until the repaired source is measured.

Pons has five usable WNATIVE first hops among 87 authenticated hookless pools in
the maintained inventory, but no validated complete USDG route yet. One unknown
pool clone is excluded with its code hash retained. These read-only capability
observations grant no financial or funding authority. Both families remain
funding-disabled; the 60-minute continuous acceptance clock has not started.
### 2026-10-11 19:15 UTC continuation

The scout-batch follow-up reduced measured priority-2 peak queue wait from
2,668,479 to 220,687 microseconds in distinct diagnostic runs. This is a queue
observation, not a controlled billing or protective-equivalence claim. It still
failed: native statuses stayed in the pre-floor replay prefix while live logs
filled their 32-MiB guard. Preserve the exact failed receipt and all counters.

The next correction permits 256 already available small messages per durable
usage group instead of 32. Both group and lookahead remain limited to 16 MiB;
the original SDK, frame, reserved-memory, response, deadline and 512-MiB
diagnostic limits are unchanged. No timed batching or content-before-accounting
is introduced. Offline 1,024-message FIFO proof uses 4 ledger commits instead of
32; provider starts, logical CU and delivered bytes are unchanged. This is a
local durable-write reduction, not verified Alchemy savings.

Scout reconnects also refresh the actual provider tip and retain an explicit
locator gap if the original boundary has fallen outside the supported 6,000-slot
replay window. Such a gap grants no canonical membership or candidate admission.
The source no longer retries a permanently obsolete locator replay boundary.

Affected intake, physical-budget, locator and shared-capacity regressions:
65 tests passed in 5.196 seconds; startup/intake subset 51 passed in 8.360 seconds.
One initial offline assertion incorrectly counted the packet already held by
the blocked durable writer as still in lookahead; corrected accounting leaves
every packet and original byte/rollback assertion intact. Failed log retained.

Pons current-block two-hop investigation found two positive quote paths through
r33/RAM using authenticated hookless pool identities. Bridge-token transfer
behavior has not been proved, so neither route is active for financial decisions.
The diagnostic used 10 starts, 78 elements, 1,834 conservative CU and 139,362 HTTP
bytes; public-rate estimate $0.00096285, not authenticated invoice charges.
### 2026-10-11 19:25 UTC ordering defect

The 256-message intake passed its bounded authenticated follow-up's first
canonical program interval (58 slots; 723 Pump and 3,741 PumpSwap rolling records)
but did not pass admission or continuous protection. Control was still replaying
previous diagnostic history about 3,000 slots behind the new live join. Its
missing corresponding headers prevented external market-time publication; live
logs again reached their original 32-MiB guard. The diagnostic stopped within
512 MiB, and all earlier counters, records and gaps remain intact.

The narrowly scoped correction waits for the existing canonical control owner
to durably reach the sampled startup tip before opening rolling live log joins.
It changes acquisition order only. It does not substitute a cached block number
for canonical membership, skip historical replay or grant candidate admission.
Source cancellation remains bounded. Affected regressions: 83 passed in 14.841s.

### 2026-10-11 19:48 UTC retained failure and deterministic timing

The control-first bounded diagnostic authenticated a current control frontier
(455766953) beyond the program join (455766914), but still failed sustained
economic coverage. It published 654 Pump and 994 PumpSwap rolling facts; its
32-MiB log guard and 512-MiB accounted native boundary remained intact. Six
openings, 49 HTTP starts, 43 logical elements and 3,900 conservative CU are
retained. The public upper is $0.056665675605, including uncertain unread buffers;
this is not an authenticated invoice or full protection pass.

FAST on `6d64f93e39fb6eeb54245386671b035e75a4714c` failed one research timeline
assertion: it required an ordinary 20-owner replay to take over three seconds;
the runner measured 2.959457262 seconds. This is not a production deadline
relaxation. All ordinary traces remain; an explicit 600-ms provider-RTT stress
now establishes the intended deadline miss independently of runner CPU speed.
The affected exact native timing test passed in 8.507 seconds. Genuine
protective deadline, accounting and economic assertions remain unchanged.

The remaining Pump bottleneck needs attribution between native intake, join
processing, normalized publication and optional cold work before another
correctness trial. Further measurement is diagnostic, never a funding gate
pass. Both families remain disabled; the continuous acceptance clock is zero.

### 2026-10-11 20:00 UTC accounting-path repair

A separate sixty-second instrumented diagnostic reached only control/scout
replay, not complete program coverage. Its durable native groups had median
210 bytes and mean commit latency 13.103 ms. It ended at its wall guard with
2 openings, 3 physical starts, 20 CU and 1,760,646 known native bytes; unread
reserved buffers remain conservatively attributed. Public upper $0.01428820722.
The profiler adds overhead and its asynchronous call timings are diagnostic,
not a protective-capacity measurement.

The existing usage ledger rewrote every immutable/unchanged run key on each
small delivery and created rollback DELETE journals. New ledgers now use WAL
with synchronous FULL, and each transaction updates only changed keys. Usage
deltas, hourly accounting, original counters, reservations and failure reasons
remain atomic; content cannot reach consumers before its durable commit. No
old run ledger is migrated or reset. No stream/response/memory limit changes.
SQLite's FULL WAL durability is documented at
https://www.sqlite.org/pragma.html#pragma_synchronous.

Focused native intake, explicit limits, continuous days/restarts, continuation,
ungraceful worker exit and aborted-write regression: 75 passed in 11.020s.
The retained first run exposed a cutoff fixture's SimpleNamespace lacking the
new real control-order barrier; the fixture now uses the actual source object.
All control frontier, timeout, economic and capital assertions are preserved.
For 64 native frames, the ledger issues 64 changed-key UPDATEs rather than
rewriting every run key, with exact legacy counter/reason/configuration parity.
This is local write reduction, not lower provider request/CU billing.

### Stream-scoped WAL handle correction

The first WAL diagnostic still failed sustained joins. Short-lived accounting
connections were repeatedly the last WAL connection, forcing checkpoint/unlink
work before the next group. Each already bounded native stream now retains one
read-only ledger handle until it closes. The handle holds no read transaction,
permits checkpoints, writes no counters and grants no evidence. Every group
still completes its FULL commit before data delivery. No old ledger is changed.
Native, failure, restart, days-of-usage and continuation regression: 77 passed
in 11.132s, including ordinary checkpoints during the live handle and refusal
of writes through it. Authenticated throughput remains to be established.

Pons bridge code is now independently retained: two canonical `eth_getCode`
reads matched the existing Sourcify compiler-input/runtime verification path
for non-proxy R33OftSatellite and RamsesOftSatellite. They inherit stock OFT and
OpenZeppelin ERC20 local transfers; remote mint/burn and peer control must not
be mistaken for immutable pool prices. Four starts/five elements/80 CU/47,299
HTTP bytes cost public-modeled $0.000042, not invoice evidence. No financial
route or trading regime has been enabled by this identity check.

### Retained failure-time maintenance repair and bounded Pons route extension

The 60-second WAL-handle observation remained in control replay and did not
open live economic intake. Its usage was three physical starts, one logical
element, 20 CU and 135,914,764 accounted native bytes; public-modeled $0.01428155022.
The original 300-second follow-up stopped on a real local
`maintenance_observation_vm_bound` before current-control catch-up. Eight thousand
coverage intervals caused an empty-prefix witness query to scan later protected
intervals. Frozen failure-time read-only replay reproduced 251,000 steps against
the unchanged 250,000-step guard. Supplying the native interval's necessary
`lo < floor` index bound yields the same observation at 219,000 steps. It deletes
no history and changes neither floor, evidence, debt nor the observation budget.
A 25,000-interval regression preserves all future coverage and still sees actual
older coverage/repaired-gap debt. All failed run counters remain retained.

The existing Pons valuation reader now has an explicitly disabled fallback for
the two compiler-verified R33/RAM bridge routes. It uses the same pinned-block,
USDG oracle, canonical fence and five-second validity. Every refresh authenticates
current bridge code, both factory memberships, exact pool clone token/step
identities, zero hooks and full-input first/second-hop quotes. The second input is
the exact first output. Unknown bridges and pools are excluded by the bounded
reviewed identities. Ramses trading stays paused. `MM_PONS_USD_BRIDGE_ROUTES` is
unset in the service; only `verified_two_hop_v1` can select this diagnostic
extension. No source identity alone enables funding.

Maintenance and valuation focused acceptance: 59 passed in 10.346 seconds,
including original direct-route behavior, disabled no-acquisition behavior,
source transfer semantics, hook/membership/quantity/fee refusals, depeg composition,
expiry, reorganization and pending-accounting recovery. Actual shared native
financial/protective latency and continuous economic coverage remain unproved.

The next maintained-prefix observation exposed repeated fresh-minimum scans
inside each old closed-gap range. Exact second failure-time replay exhausted
251,000 steps. Reusing the minimum within the same single-owner readonly command
reduces that identical observation to 53,000 steps; no cross-command cache or
authoritative-state change is involved. Forty-two focused maintenance/retention
tests passed in 10.523 seconds (one existing optional-capability skip), preserving
25,000 fresh intervals, all unresolved gaps and actual older retirement debt.

The disabled Pons two-hop reader passed an authenticated cold and warm native
USD component on 3d89e5f19772c92ad761fdca19a24d77c0765664. Cold acquisition took
3.369708 seconds and warm refresh 2.131293 seconds with distinct current canonical
blocks and the original five-second validity. It used 23 starts, 92 logical
elements, 2,162 CU and 239,353 HTTP bytes: public-modeled $0.00113505. This is not
invoice evidence or full Current/Survivor protective capacity. The feature remains
unset in the service pending coincident native quote/USD/deadline proof.


Operational checkpoint — 2026-10-11 21:03 UTC

Authenticated source 3659ffd59fe5e35e08b0a8b0ec620f56b5d0751e published 3,926 additional Pump/PumpSwap economic records during the owner-attribution diagnostic. Sustained coverage still failed: status ingestion lagged live logs, which reached the unchanged 32-MiB join bound, then conservative unread-buffer charges closed the unchanged 512-MiB engineering envelope. All failed counters and gaps remain. No funding, orders, component rerun or PAPER service start occurred. The receipt records 39 starts, 33 logical elements, 2,900 CU, 7,812,072 HTTP bytes and 520,141,108 accounted native bytes; the public-model upper is $0.05613731634, not an invoice.

Owner attribution identified duplicate development/publication work across eight archive consumers and unnecessary Pump retention scans. The successor coalesces global development housekeeping at the existing 100-ms poll cadence while every job is still independently planned, retains each original deadline and in-flight exclusion, and lets the existing ordered publisher publish in batched mode. Nonbatched acquisition retains its original inline publication path. Paused Meteora checkpoint requirements are not polled in Pump operation. Retirement no longer computes the Meteora-only hot-history pin rule for Pump; all actual consumer, position, unresolved-gap and unacknowledged-receipt pins remain intact, as do lossless cold restoration and future Survivor histories.

Focused supported FAST: 106 tests passed in 34.463 seconds across shared capacity, rolling prewarm, closure and startup. New regressions prove eight distinct jobs, original deadlines, immediate priority-zero planning between housekeeping polls, no fabricated coverage, no paused-family work, and unchanged Pump history after retirement. Remote predecessor CI 38173187232 passed for 3659ffd; the new successor still requires its own full FAST before normal deployment. This is not a protective-capacity or uninterrupted-operation pass.

Pons authenticated native USD bridge remains PASS_NATIVE_USD_COMPONENT_ONLY. No family funding is enabled. Combined quote/history/USD deadlines and four-regime capacity remain required. The normal deployed source remains df6274e270bcf40b818428a359b30e88ceb21ffb; the $1,000 epoch is unchanged, with zero positions. The 60-minute acceptance clock has not started.


Operational checkpoint — 2026-10-11 21:10 UTC

Published source 8a1a5e8d3cba8f5075dae5ea87dd5eadd4944f8b encountered an additional aged-history maintenance admission failure before any native stream opened (one finalized-slot HTTP read, 20 CU). Its exact failure-time readonly replay exhausted 251,000 VM steps. The successor first tests whether an initial between-gap range contains any actually removable row; overlap fencing only shrinks that range, so an empty initial range cannot acquire work. Exact overlap predicates remain intact. Existing SQLite gains a coverage hi/lo index, with same-command fresh-minimum selection of the appropriate index. Suffix debt checks also supply both lo bounds. No observation limit or retention obligation changes.

The same canonical database and frozen failure time replay now require 2,000 VM steps under the unchanged 250,000 limit, with all 21 control gaps retained and zero fabricated coverage. Focused OPERATIONAL: 42 tests passed in 10.213 seconds. The new 25,000-row regression covers aged protected history, empty disjoint ranges, real later retirement debt, and whole overlapping witnesses that must fence that debt. Two failed intermediate offline attempts remain in /tmp/maintenance-aged-empty-suffix-focused.log and /tmp/maintenance-aged-empty-suffix-focused-corrected.log; genuine assertions were preserved and the query selection was corrected.

Native stream/protection acceptance remains pending. No service activation, capital mutation, historical-counter reset or Render reconfiguration occurred.


Operational checkpoint — 2026-10-11 21:19 UTC

Authenticated 88a0ea0dcf7758f098dbeafb5fbd9784d1795746 got past aged maintenance and published another 3,366 economic records. Archive poll execution fell to 2.624 seconds across 10,663 callbacks; observed source-owner waits were below one second rather than the prior ten-second peak. The run still failed the unchanged log join bound and stopped at that first failure, without repeated subscriptions. Receipt: seven physical starts, three logical elements/60 CU, 129 HTTP bytes, four openings, 90,111,562 known plus 285,212,672 uncertain native bytes. No full-protection claim or funding.

Control publication consumed 53.348 owner execution seconds across 3,472 commands. A same-input disposable replay showed FinalizedFence.seal's unchanged query scanning retained sealed/currently irrelevant historical receipts: 151,000 VM steps versus fewer than 1,000 with a partial (scope,session,slot) index for sealed=0. The query and canonical parent/child, census, session and consumer guarantees remain unchanged. The successor adds that single existing-SQLite index. Focused FAST: 56 tests passed in 11.682 seconds; focused OPERATIONAL fence suite: nine tests passed in 0.639 seconds. The 25,000-retained-header regression also proves the genuine current parent is sealed, its child remains unsealed and old evidence is preserved.

Native provider coverage, qualification and combined protection still require a passing authenticated run. The prepared Pons follow-up tests a historical verified V4 key's exact buy, full and quarter quantities with coincident USD refresh; it cannot establish a newly qualified opportunity or a complete four-regime lifecycle. No PAPER activation or epoch change.


At 21:33 UTC the published control-index successor `969dc905c2a454ea800f8572e525d7dbca0262e3`
was measured through the actual existing filtered source with a fresh explicit
300-second engineering envelope. It stopped at the first `candidate_log_buffer_pressure`
after 167.863 seconds; its zero process exit is **not** a passing protection result.
It published 857 new Pump and 3,953 PumpSwap economic events and reached the
startup STEADY_STATE publication barrier, but retained logs through slot
455800207 while native publication stopped at 455800111. Old historical gaps
and missing program checkpoints remain obligations, not fabricated coverage.
The retained receipt records 19 physical starts, 15 logical elements, 1,260 CU,
3,152,134 HTTP bytes, four native openings, 71,940,448 known native bytes and
285,212,672 conservatively accounted uncertain bytes. Public modeled upper
$0.0381625776 is not authenticated invoicing. No funding or orders occurred.
An 11.659-second development housekeeping operation delayed required source work;
first-10,000 native groups separately averaged 6.291 ms and are a truncated
sample, not the whole-run average.

The narrow follow-up repair commits rolling-boundary and publication-wait
state changes together with their diagnostics using the existing sole writer's
FULL transaction. Previously each UPDATE/diagnostic INSERT outside a transaction
could fsync independently, including hundreds of expired waits. Original
obligations, deadlines and proof checks are unchanged. A rollback retains the
original pending obligation. The focused 82-test receipt proves durability,
rollback, missing-evidence and unchanged deadline behavior; a 400-wait backlog
uses two commits rather than independent per-row autocommits. This is offline
proof, not an authenticated timing pass. No buffer, deadline or VM limit changed.

Pons's exact-quantity combined native/USD diagnostic passed on source `969dc905`
using the inactive verified-two-hop USD flag and an explicit four-starts/second
Robinhood profile. Fresh USD plus full sell took 2.867752 seconds against the
unchanged three-second Survivor deadline; a new quarter-quantity sell took
0.756068 seconds, and the buy quote took 0.775714 seconds. It consumed 32
physical starts, 110 logical elements, 2,558 CU and 291,182 HTTP bytes with no
stream, funding or order; modeled public upper $0.00134295. This verifies only
the measured quote/USD combination for an authentic historical V4 pool, not
candidate qualification, discovery contention, native protective-controller
behavior or four-regime capacity. Its 132-ms headroom must not be extrapolated
as a sustained protection guarantee. The first helper attempt's exact-arithmetic
`Inexact` failure and its original 1,212-CU expenditure are retained separately;
integer ratio arithmetic corrected the diagnostic quantity without altering the
production exact-money rules. The previous USD component was not repeated as
an isolated reassurance test.


At 21:40 UTC source `595816300f80f5fbb621d7a9331d399fa0587869` finished
its next fresh explicit engineering run with `candidate_log_buffer_pressure`
after 81.327 seconds. Publication reached startup STEADY_STATE and added 1,180
Pump and 1,757 PumpSwap economic events. This remains a failed canonical-intake
trial, not a full protection pass. Owner development execution peaked at 2.016
seconds versus 11.659 in the previous run; different market periods cannot be
used as a controlled overall capacity comparison. This run retained 42 physical
starts, 38 logical elements, 3,560 CU, 8,589,942 HTTP bytes, four native openings,
62,848,907 known and 285,212,672 conservatively accounted uncertain native bytes;
public modeled upper $0.038415465795. Every failed ledger remains intact.

The next exact retained-state lookup replay identified an independent publication
bottleneck: the existing program unconsumed-content fence used its family/address
index to scan historical consumed rows. Over 100 executions of the same query,
it used 111,079,400 VM steps and 2.706 seconds. A partial index of the exact
canonical/unconsumed subset returned the identical result in 1,400 VM steps and
0.000412 seconds. A canonical binding index likewise changed an exact all-binding
scan from 2,248,300 to 9,900 VM steps; a scope/bounds index reduces gap lookup.
These are disposable-copy query measurements, not provider response latency.
The SQL predicates, historical rows, canonical decisions, freshness and proof
requirements are unchanged. Focused 117 tests include a 30,000-consumed-receipt
regression, current missing content preventing checkpoint, and restored pending
content still blocking after restart. No lifetime usage counter or historical
evidence was removed. Full remote FAST passed for `969dc905`; successor CI is
pending. Normal deployment and PAPER funding remain off pending genuine protection.

The exact `1308c9d2` run still failed canonical intake with
`candidate_log_buffer_pressure` after 102.48 seconds, despite 3,314 additional
canonical Pump/PumpSwap events. It retained 52 physical starts, 48 logical
elements, 4,560 CU, 15,854,188 HTTP bytes, four native openings, 72,012,767 known
and 285,212,672 uncertain native bytes; public modeled upper $0.039902671095,
not an authenticated invoice. Exit code zero after diagnostic stop is not PASS.
Full remote FAST passed for `1308c9d2`; earlier failed evidence is preserved.

The next narrowly scoped repair reuses the original eight-frame writer batching
for candidate frames. FIFO identity/content joins remain unchanged. At most eight
frames and 32 MiB, including the owner-held batch, can queue; a quiet ready frame
commits immediately. One atomic owner transaction retains the original economics
and proofs, while failed batches roll back and durably record their unavailable
interval. Stream accounting is still committed before content delivery.

Replay now starts its current session receipt at the actual received replay block,
even when it precedes the previous session's last receipt. Only its subsequent
linked child republishes that interval. A repeated authenticated native proof
repairs a disconnect gap without changing original content availability. Existing
historical checkpoints remain untouched; cached bytes alone cannot repair a gap.

Normal readiness reads current, durably published program frontiers rather than
requiring a market-wide historical checkpoint to bridge unrelated old gaps. It
requires the released startup identity, both real native feeds, actual linked
child membership matching a sealed control header, acknowledged canonical content,
and no unresolved gap since the current startup boundary. Five-second receipt
and fifteen-second market freshness and the existing sixty-second progressing
readiness requirement remain. Historical candidate lookback gaps still prevent
qualification. No fictitious checkpoint is written.

The Pons supervisor now explicitly forwards the validated USD-route selector
only to a non-offline Pons worker. The route remains inactive in the installed
service. Unknown selectors refuse startup, and Pump cannot inherit this flag.
Focused 95 FAST and 20 OPERATIONAL tests passed; full new source CI and genuine
combined provider protection remain prerequisites to normal funding. Trading is
still off, and the real sixty-minute acceptance clock has not started.
