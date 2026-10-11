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
reservation: 48 MiB for Yellowstone and 64 MiB for WebSockets. The installed
512-MiB native in-flight/diagnostic boundaries are unchanged. This reduces
duplicate durable-writer work; it does not eliminate delivered-byte charges or
claim provider equivalence before another authenticated observation. Frame,
failure, queue and canonical requirements remain unchanged.

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
