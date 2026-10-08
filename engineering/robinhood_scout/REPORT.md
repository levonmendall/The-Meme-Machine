Robinhood scout-first implementation and operational handoff
===========================================================

Implemented on `engineering/robinhood-scout-first-20261008`, based on
`63ec2352`, which descends from the owner's Pons reference
`b1f215edd3dc079b623401c7e09e9c91a380e6a0`. This branch is PAPER engineering
work. It is not deployed and does not certify autonomous production operation.
The owner's updated 10M CU objective is **aspirational**, with no acceptance gate
or production CU budget. Complete strategy behavior, preserved opportunities,
original deadlines, position safety and sustainable throughput take priority.
The modeled continuous-history subtotals below exceed the aspiration; this is
cost information, not a failed acceptance condition. Actual Robinhood billed
usage and genuine combined provider latency remain unmeasured. No production
state, service, provider plan or subscription
was changed. The `$500` inception and epoch `paper-1791089005190643467` remain
unchanged. Meteora and Ramses remain paused.

The starting workspace was empty. The adjacent engineering checkout had
uncommitted forward-Survivor work. This task used a separate Git worktree, then
imported only the forward startup/readiness changes and associated tests. The
source checkout was not edited, reset or merged with unrelated branches. Its
reviewed patch is preserved outside Git as `../forward-survivor-reviewed.patch`,
SHA256 `d9c6319aeb9e30b4326f767c8dbbf6c47e138c224a007d58022a54692afca4ac`.
The imported `test_forward_survivor.py` source hash was
`b3d23a980435fd486d145239a9a62a2459f989fcd61d2c84bbfd58db940440a9`.
This provenance does not assert that the adjacent work is already deployed.
While validation was running, that work was published as `ca2c1fb3` followed by
`d0c67bee09cb58f4b60627c6fdec1ecfee299caf`. The latter's recovered-nomination
and separate-checkpoint scheduling repairs were reconciled into this branch,
including the three migration/recovery/scheduling regressions. Its paused-family IPC fixture repair was also
retained for operational validation. No unrelated branch was merged.
The subsequent `481bd11e918cda9c5de624a619f44688dc97fefb` was inspected as well;
it publishes forward-operation evidence and handoff documents only. Those
artifacts are referenced at their existing commit and were not copied here.

**Baseline audit, before edits.** The original code already had the right
authorities: Nitro sequencer ordering, public observation, canonical Alchemy,
shared admission, immutable RPC reuse, the Candidate/Evidence Plane, native
Pons History, and independent strategy/position controllers. They are retained.

| Production path | Reference acquisition | Implemented acquisition |
| --- | --- | --- |
| Current broad discovery | Public CurveBuy/Sell filters, up to four ten-block ranges per batch | The same cohort loop batches a topic-OR of TokenLaunched, PoolGraduated and both curve events; the pinned factory validates factory scope |
| Survivor discovery | Independent canonical factory range polling; ordinary historical readiness could depend on a seven-day census | Shared public graduation journal; exact canonical nomination/lineage authentication; inclusive forward enrollment |
| Graduated observation | Canonical economic reconstruction for all retained rows | Shared exact-Pons pool public event journal; early weak/unknown rows stay cheap; improving rows promote; mature candidates still receive required canonical history |
| V4 economic transport | Separate evidence contexts for log/header/receipt/transaction phases | One bounded evidence context; canonical receipt pins; receipt `from` supplies transaction sender, with the original transaction-body fallback |
| Weak mature qualification | Executable ladder before market gates | Original market gates first; the unchanged ladder only when nonexecution gates pass |
| ABI event decode | Rehash immutable signatures for every event | A bounded 256-signature immutable hash cache; exact decoder and values unchanged |
| Positions | Native authenticated quotes, flow, risk exits and reconciliation | The same native controllers and priority-zero admission |

The pinned diagnostic schedule is `meme_machine/runtime/alchemy-cu-schedule.json`:
getLogs 60, receipt/header/transaction/code 20, eth_call 26, gasPrice 20, chainId
0. These are method-weight estimates, never a billing receipt. Physical HTTP
attempts are counted independently of batch members.

**Final architecture.** `pons_selective_cohort.py` owns the one shared broad
observer. `MarketScout` is a journal projection inside the existing Plane, not
another provider, candidate registry, process or history service. The public
market filter serves both strategies. Current nominations are enqueued with
their original five-second clock before deferred pool observation. Duplicate
delivery cannot renew deadlines. Survivor consumes the same durable graduation
identities independently of Current decisions and cash availability.

Factory identity is the pinned Pons V2 factory
`0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e`. Event hashes come from the checked
ABI, including exact CurveBuy/CurveSell signatures. Dynamic curve addresses
require the existing topic-filtered market request; only exact-factory launch
and graduation logs become factory nominations. Graduated pool filters use
the pinned V4 PoolManager and canonically proved Pons pool IDs, with Swap,
ModifyLiquidity, Donate and ProtocolFeeUpdated topics. They do not enroll
unrelated V4/Ramses pools. Every getLogs element stays at ten blocks or fewer.
Four contiguous elements share one supported batch. Response saturation is
subdivided; single-block saturation or an unknown page envelope leaves an
explicit gap and cannot certify completeness.

Robinhood's official documentation exposes HTTP RPC and a Nitro sequencer
feed, and says its public RPC is rate limited. It does not document a public
decoded-contract-event WebSocket subscription for this task. This branch uses
the repository's existing public filtered HTTP path and uses the sequencer
only for ordering/liveness. It does not assume that feed bytes are authenticated
decoded economic events. Public completeness/sustainability at production
traffic is still an operational measurement requirement.
[Robinhood connection documentation](https://docs.robinhood.com/chain/connecting/)

The three evidence levels use the existing authorities:

* **A, market scout:** retain raw event identity/payload, chronology, pool
  mapping, cursors, gaps and provisional price activity. Buyer independence is
  UNKNOWN. No quote ladder or economic decision uses public values.
* **B, deep watch:** native Preparation authenticates exact graduation,
  receipt/header, source bytecode, factory record, launch and pool lineage.
  Native Pons History hydrates exact swaps and buyer/price windows with fair
  bounded cohorts. Public improvement promotes early; UNKNOWN before four
  hours can wait for public catchup. Mature candidates and canonical recovery
  remain due. No negative public signal permanently rejects a candidate.
* **C, qualification/positions:** fresh canonical state, original reducers and
  executable quotes remain authoritative. Funded safety work outranks final
  qualification, canonical authentication, public continuity and deferred
  hydration. Existing scheduling ages deferred tickets, preserving continuity.

Current and Survivor share the observation journal, exact immutable RPC cache
domain, receipt/header evidence and provider admission. Matching authenticated
receipt pins enable reuse across acquisition phases and consumers. Mutable
state and quotes still follow their original freshness and canonical-boundary
checks. The native transaction-level buyer evidence is preserved; Swap.sender
is not substituted for transaction sender. Missing standard receipt sender
uses the original eth_getTransactionByHash path.

There is no retained-identity top-N or count cap. Limits of 64 pool/work rows,
256 intake records per consumption turn, four log filters per batch and
40-block economic turns are bounded work cohorts that rotate durably. Original
candidate expiry stays graduation plus seven days, inclusive at the boundary.
The first Survivor age stays four hours. Weak and capital-denied candidates
reactivate on new activity, timed feature boundaries and recovery probes.
Fair qualification also prioritizes candidates at their original expiry, with
the original ordinary tie-breaks preserved. Both canonical and public pool
acquisition claim only overlapping checkpoints, so an old recovery cannot
consume a newer candidate's work credit without advancing its coverage.

Raw public launch/graduation identities remain durable. Curve economic payloads
are compacted only beyond eight days; graduated pool payloads only beyond the
candidate horizon plus recovery overlap. Pending identities and unknown pool
relationships are not pruned. Maintenance is capped at 4,096 expired raw rows
per minute with a digest checkpoint; sustained traffic beyond that removal
rate needs an operational storage measurement. Funded positions retain their
separate native canonical history and are not retired by the scout horizon.

Public failures do not advance coverage. Market and per-pool gap identities
survive restarts. A public boundary reorg rewinds the same prospective enrollment
and pool cursors, retains fork witnesses and resumes native canonical recovery.
An authenticated header/receipt can disprove a public nomination; its witness
is retained as INVALID_OBSERVATION without declaring the token ineligible or
blocking a later canonical witness. Delayed/missing evidence remains pending.

Ordinary startup does not invoke global seven-day reconstruction, warmup or
readiness. Existing explicit historical research/recovery machinery remains
available, but is not an operational prerequisite. Candidates are complete
only for their own proved interval. Pre-enrollment opportunities are reported
UNOBSERVED, never backdated into prospective recall.

**Offline economic and acquisition evidence.** CPython 3.12.14 and pinned
dependencies were used. Market I/O is blocked by the operational test driver.
`replay.py` loads the reference collector directly from the named Git commit;
`decisions.py` also loads the frozen Runtime. The same chronological synthetic
RPC replies exercise actual collectors, receipt/ABI verification, native
History, state/quote decoding, qualification, step orchestration and accounting.
They are explicitly synthetic inputs, not fabricated market-acceptance evidence.

`collector-comparison.json` preserves exact normalized canonical tapes and
100% candidate recall in all three workloads:

| Identical workload | Physical HTTP attempts | Logical RPC elements | Diagnostic CU | Response bytes | Collector CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 markets / 20 blocks | 12 → 6 | 290 → 155 | 5,800 → 3,160 | 344,527 → 303,229 | 2.059 → 0.486 |
| 32 markets / 40 blocks | 48 → 24 | 1,626 → 834 | 32,400 → 16,720 | 2,027,045 → 1,781,835 | 11.970 → 2.567 |
| 64 markets / 40 blocks | 50 → 25 | 1,698 → 870 | 33,840 → 17,440 | 2,119,691 → 1,863,222 | 13.285 → 3.132 |

Thus physical attempts fall 50%, diagnostic CU 45.5–48.5%, payload bytes
12.0–12.2%, and collector CPU 76.4–78.6%. CPU includes the in-memory reply fixture;
the reference restores uncached ABI hashing. Offline maximum RSS is 35.5–52.0
MB, approximately unchanged. These results do not certify a two-vCPU/eight-GiB
mixed production workload, provider scheduling wait or network latency. Cache
hits are deliberately excluded from this cold HTTP comparison; separate native
cache regressions verify exact hash-pinned reuse and invalidation.

`decision-comparison.json` records an accelerating-buyer winner, a concentrated
buyer rejection, and a quiet token that rejects at four hours then qualifies
at five. All nonexecution features, exact transaction/buyer history, price,
momentum/reset windows and complete eligible decisions match the frozen runtime.
Weak evaluations acquire zero quote sizes versus seven in the reference;
eligible evaluations acquire the same seven exact sizes. Avoided weak quote
work is 3 transports / 18 elements / 450 diagnostic CU per measured ladder.
Missing execution is explicitly PENDING_EVIDENCE, not an economic verdict.
Intentionally unhydrated negative evaluations have missing execution fields
that differ from the full reference. This is a recorded acquisition-status
difference; exact decision equality is claimed for complete eligible evidence,
not for those deliberately pending execution fields. The original nonexecution
economic rejection predicates remain unchanged.

The native funded `step(admit=False)` is also profiled: with an unchanged head
and no new economic events it uses 3 physical attempts / 7 elements / 152
diagnostic CU / 1,136 response bytes. A real turn with swaps, an exit, scaling
or recovery adds work. Shared Plane and optimized History logical SQLite page
stocks are 168–188 KB and 160–172 KB in these small tapes, versus 86–98 KB for
the already-authenticated reference History. The optimized stock includes the
durable public journal and canonical nomination/lineage witnesses. Neither
page stock includes cumulative writes, WAL stock or a monthly storage forecast.

The native replay preserves qualification before capital admission, denial then
retry when cash returns, original expiry, one native position and identical
authenticated position quotes. Five Current vectors also match the frozen
qualification code. The source-pin regression keeps the economic policy files,
nine-change directive, Pump source, right-tail and continuation logic unchanged;
it separately pins unchanged Pons price/buyer/sizing/quote expressions.

Production-path regressions cover startup graduation, 301 simultaneous nominees,
Current rejection/Survivor independence, fairness among competing candidates,
public loss, delayed canonical receipt, reorg/replacement, interrupted hydration,
restart, authentic buyer flow, saturation subdivision, hash-cache invalidation,
position precedence, native money/reconciliation and paused-family isolation.
FAST passed 956 tests. Full OPERATIONAL ran 2,377 tests successfully, with 33
existing Model A characterization cases skipped. The final 70-test delta covers
the published migration/checkpoint repairs, public pool fairness and original
qualification tie-breaks after the broad run. The focused 48-test production-path run
also covers the final campaign/recovery/cache/provider source. No broad run is
relabeled as a rerun of subsequently added cases. `validation.json` records
the precise source scope, final counts, statuses and local evidence hashes.

The offline host has two CPUs and 8,132,488 KiB of reported memory. The full
operational run used 682.23 user CPU seconds and 78.82 system CPU seconds over
993.78 seconds, with 241,908 KiB peak RSS and no swaps. This finite suite fits
the host envelope; it is not a certificate of sustained mixed market throughput.

The bounded tapes arrive before their original decision boundaries. Real-network
evidence arrival during a late breakout, large sustained bursts, outage recovery
or combined funded-position contention is **not certified**. A deferred candidate
can require many ten-block canonical reads before its history catches up. That
is a real remaining capacity limit, not hidden economic rejection. The existing
`combined_position_and_candidate_provider_latency_not_certified` guard remains.

**Cost and capacity.** `cost-projection.json` is generated from the measured
offline method profiles and the previously retained canonical header pair,
which gives 9.897436 blocks/second. Economic event, promotion and funded-position
rates are not live measurements from this task. The three sparse lower bounds
assume 1 / 1 / 2 continuously hydrated cohorts and mean Survivor funded-position
occupancy 0.05 / 0.25 / 1, respectively. They include canonical range reads and
native warm funded turns; all omitted Current work, authentication, receipts,
qualification, candidate/acquisition head probes and recovery add cost. Position
head probes are included in the measured warm funded turn. Both comparison
architectures use the same three-second forward-worker funded workload. The
original `b1f215ed` Worker ran at five seconds; the imported approved forward
work adopts three to let bounded acquisition follow the retained block rate.
This comparison does not assign savings to a change in safety cadence.

| 30-day modeled required-work subtotal | Reference | Optimized |
| --- | ---: | ---: |
| Normal conditional workload | 314.42M diagnostic CU | 160.49M diagnostic CU |
| Busy conditional workload | 340.68M | 186.76M |
| Stress conditional workload | 593.10M | 439.18M |

The removed routine independent Alchemy factory census alone projects to
153.92M diagnostic CU per 30 days at that retained block rate. The removed
one-time seven-day global factory scan projects to 35.92M; it is not added to
recurring monthly savings. One continuously authenticated ten-block pool-range
stream still costs approximately 153.92M per month before receipts or quotes.
One continuously funded Survivor exit-quote stream at the adopted three-second
cadence costs 114.05M; the measured no-delta native turn including its head probe
costs 131.33M before new swaps or conditional safety work. This implementation preserves those required
canonical and safety requirements rather than imposing a CU budget.

The JSON also normalizes the identical dense collector traces for 30 days:
reference 7.594 / 20.934 / 21.857 billion diagnostic CU, optimized 4.053 / 10.723 /
11.185 billion. Those are synthetic sustained-density stress projections, not
representative live forecasts. Optimized physical demand is 2.97 / 5.94 / 6.19
HTTP attempts/second, exceeding the unchanged 2-RPS Alchemy ceiling even before
Current and positions. They provide reproducible failure bounds rather than
fabricated sustainable throughput. Substitute genuine prospective rates into
the recorded coefficients before any operational cost commitment.

The shared public market plus one active pool cohort costs three physical
batches per forty blocks: approximately 0.742 HTTP attempts/second at the retained
rate, versus independent discovery consumers and unbatched requests. Logical
getLogs elements remain separately counted. Public throttling, response bytes
and activity-heavy subdivision can change this rate; sustainment is unverified.

A realistic complete-system monthly minimum is **not established** for normal,
busy or stress operation. These are conditional required-work subtotals and
dense synthetic profiles, not measured representative full-system forecasts.
Current final qualification/positions, genuine activity, promotion incidence,
funded occupancy and recovery are explicit **unmeasured additive terms**, not
assumed to cost zero. `cost-projection.json` retains those missing terms and
the measured cold graduation-authentication and execution coefficients so
genuine rates can replace the assumptions without another runtime refactor.
Principal remaining drivers are
canonical ten-block coverage, exact swap receipts/headers, funded quotes,
candidate head checks and recovery backlog. Complete operation at dense tested
rates is incompatible with the present admission ceiling; no limits were raised.

Alchemy's account throughput and the repository's 2 physical requests/second
are different constraints. Official documentation specifies account-wide
weighted CU/s evaluated across a ten-second window, including other apps; the
documented Free and PAYG base rates are 300 and 10,000 CU/s respectively. Batch
members still consume their method weights. Those published rates are not an
account-specific capacity certification. This branch keeps the application
ceiling and tested ten-block boundary unchanged.
[Alchemy throughput](https://www.alchemy.com/docs/reference/throughput),
[pricing plans](https://www.alchemy.com/docs/reference/pricing-plans),
[method and subscription weights](https://www.alchemy.com/docs/reference/compute-unit-costs)

The dense collector alone requires at least **3 / 6 / 7 physical RPS** for the
normal/busy/stress fixtures, respectively, plus roughly **1,566 / 4,145 / 4,323
throughput CU/s** before Current, authentication, final qualification, funded
maintenance, recovery and deadline headroom. Exact values are in the generated
JSON. Increasing only monthly allowance would not fix the physical bottleneck;
raising only physical pacing would not fix an account CU/s constraint. A full
system ceiling cannot be chosen honestly from these incomplete combined rates.
The smallest justified next action is bounded combined measurement, not a
provider purchase. The published PAYG CU/s rate exceeds this isolated collector
demand, but its suitability for complete operation, cost and burst safety is
unproved. No plan selection or spending authorization follows from this report.

A narrow further option is a supported authenticated exact-Pons logs
subscription, feeding the same journal with unchanged receipt/lineage and
canonical recovery. It could avoid empty canonical range polling. At the
published 0.04 diagnostic CU/delivered byte, one continuous ten-block range
stream breaks even at about **1,485 delivered bytes/second**, excluding
establishment, receipts, headers, recovery and every quote. Dense receipt work
remains a driver. Alchemy documents Robinhood `eth_subscribe(logs)` and topic
filters. Actual filter behavior, completeness, delivery bytes and
recovery need a separately authorized bounded capability test before such a
change. It is investigated, not implemented or claimed proven. Existing
completed optimizations are preserved; no new ingestion framework or broad
numerical-target refactor was introduced.
[Robinhood subscription method](https://www.alchemy.com/docs/chains/robinhood-chain/robinhood-chain-api-endpoints/eth-subscribe)

`billing-availability.json` records an independent administrative read. The
matching Robinhood app exists, but the app/method breakdown request returned
403 because it requires a paid plan. The permitted account-wide 24-hour query
returned no usage rows. This is **no usable billed sample**, not zero billed CU,
and cannot attribute costs to this offline branch. No market RPC validation
was performed by those metadata reads.

**Modules changed.** Runtime changes are in `pons_natural_observation`,
`pons_selective_cohort`, `pons_survivor_runtime`, `pons_historical`, `pons_history`,
`pons_selective_v4`, `provider_topology`, `provider_admission`, `provider`,
`sequencer_feed`, Pons `abi`, Robinhood `provider_usage`, and the imported shared
`survivor_history` forward-readiness change. Offline tooling changes are
`operational/tests.py`, the bounded capability accounting wrapper and the
`engineering/robinhood_scout` replay/projection package. New and adjusted tests
are listed by Git on this branch. `runtime/robinhood/pons.py`, `plane.py`, the
economic policies, position controllers, capital rules and Pump strategy files
were inspected and reused without another authority or economic rewrite.

**Operational acceptance and next validation.** Implementation and finite
offline equivalence are ready for integration review. Deployment, public coverage
verification, genuine four-strategy combined latency/capacity and a defensible
full-workload billing forecast remain outstanding. The 10M aspiration does
not block acceptance. A global seven-day seed is no longer a blocker.
The old published proof plan is retained as historical evidence; this branch's
next-test specification supersedes its obsolete startup-seed prerequisite only.

`NEXT_VALIDATION.json` specifies a separately authorized, maximum 300-second
isolated PAPER observation test, with no signing, production service restart,
production epoch write, provider upgrade or automatic retry/extension. It starts
forward, retains every prospective identity and records public/canonical byte,
attempt, method, latency, queue, throttle and gap counters. No mature four-hour
candidate is required to be manufactured during five minutes. A restored,
individually complete authentic candidate and existing funded PAPER controllers
may supply combined qualification/position samples in isolated state if their
provenance and copy admission are checked. Otherwise the result is
INSUFFICIENT_SAMPLE for those criteria and the existing certification guard stays.

No live test was executed. The next test's executor must first be reviewed
offline against the branch and hard stop contract; authorization is a separate
user decision. No further infrastructure is proposed.

Reproduce locally with CPython 3.12.14 and pinned requirements:

```bash
python -m operational.tests FAST
python -m operational.tests OPERATIONAL
python -m engineering.robinhood_scout.replay --output engineering/robinhood_scout/collector-comparison.json
python -m engineering.robinhood_scout.decisions --output engineering/robinhood_scout/decision-comparison.json
python -m engineering.robinhood_scout.projection
```

An initial test environment accidentally linked the 3.12.14 executable to the
system's 3.12.3 shared library, producing reproducible asyncio crashes. The
isolated virtualenv now has the correct library path; it did not modify system
Python or the adjacent checkout. Failed and superseded evidence is retained
outside Git with explicit disposition in `validation.json`. Final passing
results, rather than earlier interrupted runs, determine this handoff's status.
