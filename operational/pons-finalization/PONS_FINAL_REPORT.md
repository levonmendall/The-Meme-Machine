PONS_FINALIZATION: NOT_READY

**D — PONS_NOT_READY.** Pons machinery repairs are implemented and pass the offline regressions. The retained archive cannot establish complete market recall, historical winner capture, a chronological executable portfolio, actual provider deadlines or monthly Pons provider cost. These missing proofs prevent a freeze. They do not establish that the frozen economic strategy needs a change.

The branch is `engineering/pons-finalization-20261007`, based directly on operational commit `5bd1a8bfb58b0a9e3df2b0a5194c6b11e0328bd0`, tree `65c2f85f1c67676372ab2b449499d76a17bb224f`. The containing commit/tree are reported after committing these artifacts. PR #121 was inspected read-only and remains independent; its architecture was not used. No merge, deployment, live trading change or acceptance campaign was performed.

The final read-only remote check found that operational advanced during this work to `9f08f0db68fd3161c84bb955800db9a200a70f77` through an independent Ramses pause commit. Its five changed files are operational acceptance/supervisor, an owner-decision note, test registration and pause tests; no Pons source or economics changed. This Pons branch retains the head observed at branch creation and its exact tested baseline. No rebase or integration of the later commit was performed. PR #121 remains OPEN/unmerged, now at head `daad4640a6dab35ffcabca4e17ba9b3e3ae6c927`; it was not incorporated.

The machine-readable evidence is [PONS_HISTORICAL_AUDIT.json](PONS_HISTORICAL_AUDIT.json), [PONS_CURRENT_WINNER_RECALL.json](PONS_CURRENT_WINNER_RECALL.json), [PONS_VERIFICATION.json](PONS_VERIFICATION.json) and [PONS_EVIDENCE_LIFECYCLE_MAP.json](PONS_EVIDENCE_LIFECYCLE_MAP.json). The [human lifecycle map](PONS_EVIDENCE_LIFECYCLE_MAP.md) identifies 17 Current stages, 14 Survivor stages, active and preserved alternate entrypoints, exact source symbols, provider authority, required windows and every identified bound. [PONS_CHANGED_FILES.json](PONS_CHANGED_FILES.json) lists the final files and content hashes.

## Frozen strategy and target market

Current version: `pons-selective-continuation-v1`.

Current revision: `profitability-v1-profit-protection-v2-execution-capacity-v1-moderate-admission-v1-operational-nine-v1`.

Current policy hash: `888904d0e58865f1a701560a5be8386f57d88f66a0c25d7094c994cafa7f448f`.

Survivor version: `pons-postgrad-survivor-momentum-v1`.

Survivor policy hash: `ed17402a75470801fda47877b6b1f3b1266793b7e0750b7a7cd821f327541e5f`.

Both retain the 5% applicable realized-equity target; unrealized marks do not expand it. Current retains -8%, +18%/25%, 12% ordinary trail, 1.20x adverse flow and its structural/safety exits. The common >=2x tail permits 40% giveback of **peak profit**. The bridge retains its original-open 36-hour deadline and native basis/HWM. The one-add gate, 15-minute persistence, 15% HWM proximity, full fresh requalification, 2.5%/half-original-basis/cash/capacity minimum and 7.5% exposure ceiling are unchanged. Survivor retains its own -10%, +20%/25%, normal/tighter trail and 72-hour hold.

The pure Current module's AST matches the operational source after removing only the accidental `len(events)>512` acquisition veto. Its economic expressions and policy tables are unchanged. Survivor policy, common continuation/risk, sizing, execution-capacity and native-accounting sources are byte unchanged. All 33 reconstructed whole vectors match the operational source. The stale 0.25% comment was corrected to the existing 5% value; no threshold changed.

The intended market is Robinhood Chain 4663, exact authenticated compiled Pons V2 native-quote curves from factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e` and deployer `0x3711ceA4feaDE896C913C68F01Eda97Cb06D1A42`. Current cheap discovery nominates every address emitting the Pons CurveBuy/CurveSell topics, then canonical identity/code/factory/state establishes membership. Its strategy domain is progress 45–88%, age 90–900 seconds and graduation ETA 15–120 seconds, with the remaining coded gates. Every legitimate Current qualifier requires positive recent independent buying, so a complete Buy log census would nominate it. The retained archive cannot prove that census or cold-start coverage of previously active curves.

Survivor independently discovers all canonical Pons V2 `PoolGraduated` transitions to the registered native Uniswap V4 pool under manager `0x8366a39CC670B4001A1121B8F6A443A643e40951` and Pons hook `0xE5e702641Ea86F4ae6cC3cDaeD2B886f976Be044`. Its fixed domain is 4 hours through 7 days after graduation. Current decisions and native exits are absent from Survivor qualification inputs. Same-asset reservation conflicts remain explicit execution constraints after qualification.

Official public RPC supplies nominations; the sequencer supplies the block clock. Canonical Alchemy RPC supplies authoritative facts. Public observations never substitute for canonical qualification evidence. No market provider was contacted for this audit.

## Engineering repairs and their limits

| Defect | Repair | Evidence |
|---|---|---|
| Survivor discovery stopped at population 64 and truncated graduation bursts | Pons-owned unlimited identity retention; complete raw intake and hashed discovery cursor commit together; one authentication per turn | 4,096 cheap identities; 1,025-event burst survives restart |
| Failed/lowest-block candidates could monopolize history and qualification | Durable fair attempt sequence rotates before provider work; <=64 candidates and <=40 blocks per history slice; one fair qualification per turn | All 1,025 candidates advance after a failed first batch and restart; 1,025 qualification turns cover every identity |
| Survivor qualification depended on allocatable/funding cash | Reconstruct against realized equity and strategy turnover cap; commit full decision before funding/max-position checks | Whole Current and Survivor vectors identical under four cash states; real quote acquisition identical under full, zero and partial funding budgets |
| Fixed Survivor quote ladder omitted exact turnover/funding sizes | Acquire exact requested and 2x probes on demand with bounded batched native V4 calls | Exact turnover-capped and arbitrary partial-size probes; no interpolated executable size; cache repeat buys no new calls |
| Public Current tape could omit required creator/flow evidence | Complete selected-curve canonical 60-second log ranges; receipt/header authentication of every member | Omitted public creator sale is reconstructed and rejected by the unchanged gate; missing/conflicting/future/removed members fail closed |
| Arbitrary evidence/population slices could veto a busy valid opportunity | Remove Current 512-event veto, 2,048 source-tail slice, Pons public 1,000 count cap and V4 256-per-pool cap; retain all events within strategy windows | 1,025-trade Current reduction; inclusive same-second boundary and deterministic canonical ordering |
| Dense Survivor price history could hit the generic 100,000-point veto | Fold only price observations older than the active 24-hour strategy window, retaining original anchor/boundary and sealed proof prefix | 100,001 dense price points produce the identical frozen vector before/after safe compaction |
| Current hot add path reconstructed an urgent large window | Persist normal authenticated 60-second windows into rolling 900-second Pons history; consume small deltas | Exact 900-second accumulation and restart; a gap/reorg invalidates authority and defers add until enough history reaccumulates |
| History observations and block watermark could commit separately | Pons-owned atomic observations plus block/hash checkpoint | Exact watermark after reopen and actual child-process `os._exit` after commit |
| Immutable numeric aliases could hide a fork | Fresh numeric canonical-membership witnesses; invalidate mutable aliases while preserving by-hash audit facts; bounded Survivor replay | Current forward reorg, durable cache fork, Survivor candidate reorg, orphan graduation and later canonical reactivation tests |
| Quote completion/reuse could restart freshness | State/quote/qualification retain the original five-second monotonic clock; batched V4 state/cost includes fresh numeric boundary; commit/exit revalidate membership | Cached stale quote is an operational deadline failure; a quote-time fork cannot authorize exit; no reset after completed reads |
| Full candidate provider queue could refuse position work | Priority-zero admission bypasses only candidate queue-cap refusal; original aggregate 0.5-second interval and burst fairness remain | 256 candidate tickets plus an imminent position: depth 257, position wait 0, all 256 candidate tickets retained; 26 shared-governor regressions pass |
| First position/provider startup failure could suppress other positions/recovery | Funded positions first, per-position error isolation; restored native work before observation startup; exact saved cursor retained | First position failure does not skip second; observation 429 continues native maintenance; invalid saved cursor fails closed |
| Untrusted conflicting public variants could create a sticky Current tombstone | Pons observation key includes raw digest; legacy public conflict returns only to unqualified canonical work | Conflict/restart/new canonical generation reactivation; no fabricated qualification |
| Current retries depended on another buy, even after provider recovery or the age gate opening | Durable Current watch alternates fair fresh-head probes with raw nomination work; complete canonical window, real receipt and all mutable facts are reacquired with a separately bound five-second deadline | Actual receipt decoder and fixed qualification move from age87 reject to age90 pass with no new trade; 1,025 quiet identities receive a probe under continuous new-buy pressure; stale service estimate cannot permanently suppress a probe |
| An aged projection or pre-submit restart could lose Current reactivation | Watch preserves original nominee/first time, highest generation and latest real Buy/Sell ordering; restart repairs an observation/watch commit gap and releases only orphan confirmation guards after native reconciliation | Projection retirement/reopen does not erase the watch; active controllers, live native reservations and unconsumed decisions stay protected; only authenticated chain-age expiry stops Current probing and leaves Survivor intact |
| Operational failures were indistinguishable from strategy rejects | Append-only idempotent Pons attempt journal; explicit evidence/deadline/provider/capacity/funding/supersession/horizon categories | Durable decision precedes funding; duplicate replay does not duplicate disposition; audit retirement protects pending/unconsumed/native work |
| Campaign attempt limit and blocking warmup could stop opportunity observation | Remove operational campaign 20,000 attempt stop and 65-second startup warmup; canonical Current coverage replaces warmup | Existing bounded research modes remain separate; operational discovery retains restart range |

Transport work remains bounded. Identity retention has no population eviction. This does not prove timely complete evidence at every conceivable population: 2 physical requests/second, the five-second evidence deadline and the 8,192-block trajectory lookup still require real throughput/coverage evidence. Provider pressure records a recoverable explicit failure and preserves identity. A quiet candidate is now reevaluated from fresh canonical evidence; another public buy is not required to recover from a failed provider or a too-young age screen. Timely recall of a brief historical opportunity cannot be inferred from identity retention alone.

The Current timer does not renew old evidence. Its durable watch keeps the original raw buy, first observed time and latest real-event ordering. Each probe observes a new canonical head, verifies numeric membership, finds a real canonical buy in the complete current60-second census and reads every mutable value at that head. The actual buy receipt/log keeps its original block/hash; the strategy state/window uses the separately recorded fresh head. Canonical receipt pins replace orphan/public hints before cache lookup. A future head, changed membership, absent canonical buy or incomplete range fails closed. The new observation retains its own original five-second deadline throughout acquisition, qualification and entry. Native positions retain their basis/HWM; no timer grants funding authority.

Current rolling flow history is observation authority, never basis/HWM authority. Survivor replay after a fork preserves its native controller/book; an orphan graduation remains ineligible until a new canonical transition proves reactivation. Software interpretation changes can fail closed on older native interpretation metadata; cross-version production migration was not accepted or started.

## Temporary weakness and failure dispositions

| Condition | Treatment |
|---|---|
| Wrong compiled lineage, non-native pair or noncanonical graduation | Structural for that proven identity; a disagreement or missing proof remains incomplete evidence, not a proven structural fact |
| Momentum/acceleration, buyers, flow, concentration or executable depth below the fixed gate | Economic reject for that observation; recoverable on fresh evidence while the strategy horizon remains open |
| Creator sale within the active window, or mutable tax/snipe state failing the gate | Fixed strategy reject for that observed state; observation continues; an already-triggered native safety exit remains irreversible |
| Provider unavailable, incomplete range/receipt/header, quote failure, history lag or fork | Recoverable explicit provider/evidence/capacity/deadline disposition; no permanent candidate tombstone |
| Candidate younger than its domain | Retained and reevaluated from fresh canonical state without requiring another buy; age87 to age90 regression passes |
| Capital/sleeve unavailable | Durable qualification remains true; funding outcome differs only afterward |
| Current age >900 seconds | Explicit Current horizon expiration; does not expire independent Survivor history |
| Survivor >7 days after graduation | Actual Survivor eligibility expiration; retirement never follows population count |

The attempt journal implements all ten requested failure categories, plus successful `QUALIFIED`. `OTHER_EXPLICIT_REASON` retains its concrete reason, including Current same-curve lifecycle/reentry authorization blocks and the unchanged Survivor maximum-open-position execution block. An actual offline Current cohort regression qualifies twice while a prior same-curve lifecycle is active: both durable decisions remain `QUALIFIED`, and the second funding disposition is `OTHER_EXPLICIT_REASON: same_curve_lifecycle_active`, with no second entry. The existing reentry-regime predicate is unchanged, including its application after an entry-failed prior lifecycle; this audit does not remove that coded authorization gate. Tested repeated identical attempts are idempotent. Seven-day audit-prefix folding preserves native accounting authority and protects pending, unconsumed, qualified-unfunded and open-position work.

## Historical evidence and clean-room replay

The only historical authority used is the user-pinned repository archive `d1fc161401869522db9abbf50e3f6073e80a4374`, primary fixture `certification/evidence/robinhood-runs-355-368.json.gz`, SHA-256 `1be70cb9f53bfc9bce039f6913813a6d2a0a21dde39b6b10bf95b9123f47597f`. The archived replay implementation `certification/robinhood/replay.py` was read for fixture semantics. Its old decisions were not used as truth. The separately pinned archived strategy baseline is `strategy/pons-opportunity-preservation-v2-20260925` at `3de3d376847531ccb90e260cfcc96c37587ccb23`; that policy predates the active operational policy. Both are independently reconstructed where complete inputs exist.

Eight retained runs contain 15,051 decision rows. They identify 1,312 curves; 4,798 rows lack a curve identity. Only 33 complete normalized market input vectors across 19 curves can be independently replayed. Six of fourteen requested runs are unavailable or have no retained market-candidate trace. This is a partial evidence cohort, not a representative continuous market/portfolio backtest.

The active Current policy produces eight qualifying evaluations across five distinct curves, sixteen strategy-reject dispositions, seven execution-capacity-unavailable dispositions and two deadline-missed dispositions. All 33 complete reconstructed vectors equal the original operational vectors. Timestamp checks find no future snapshot/event input in these normalized windows. The archive does not retain the complete raw log/header/receipt census needed to prove same-second canonical membership or absence of omitted trades independently. The supplied nominal sizing base is 10^18 quote units; no historical realized-equity journal proves compounding chronology.

| Rejecting gate in reconstructed vectors | Evaluations containing gate |
|---|---:|
| `top3_buyer_concentration` | 19 |
| `largest_buyer_concentration` | 14 |
| `flow_deceleration` | 8 |
| `position_size_zero` | 7 |
| `roundtrip_cost_unavailable` | 7 |
| `independent_breadth` | 5 |
| `buyer_growth` | 2 |
| `stale_state_after_evidence` | 2 |

Gate counts overlap; do not sum them as lost opportunities. Capacity-zero and stale evidence outcomes are explicitly separated from the sixteen economic rejections. This table does not establish that any rejected curve became a major winner.

`PONS_CURRENT_WINNER_RECALL` is retained in the machine audit with curve/token/asof/vector and explicit missing fields. First market observability, first complete evidence, earliest strategy eligibility, winner multiple, eligible/qualified before the large move, strategy-missed winners, machinery-missed winners, provider/evidence lateness and outside-universe winner counts are **UNMEASURABLE**. The archive lacks continuous independent winner paths and the recall denominator. No unverified symbol/multiple was promoted into a historical winner label.

Seven recorded legacy lifecycle attempts all ended `entry_failed`, with no retained fills. That is a description of old observations, not evidence that this fixed strategy has zero entries or zero P&L. Current/Survivor entries, Survivor qualifiers, qualified-but-unfunded opportunities, wins/losses, realized/marked P&L, profit factor, win rate, median hold, drawdown, utilization, peak deployment and historical tail/add/bridge contribution remain **UNMEASURABLE**. No missing history was generated and no live data was used to fill these gaps.

## Right-tail, add and bridge mechanics

The frozen mechanics can convert a surviving exponential underlying path into an outsized sleeve winner. Historical conversion is unproved. The following conditional calculation uses Current's actual frozen `runner_action`, a $100,000 initial sleeve, $5,000 original basis, an entry reference of 1, a 25% first sale at 1.18 ($1,475 proceeds), and exit exactly at `1 + 0.6 * (peak_multiple - 1)` for the remaining $3,750 entry-price quantity. It assumes executable frictionless fills, fresh independent demand, valid continuation/bridge gates when required and no intervening stop, trail, flow, structural or safety exit. It is neither a real market path nor a performance forecast.

| Underlying peak | Peak remaining position value | Tail exit price | Remaining exit value | Realized P&L | Position basis return | Initial sleeve contribution |
|---|---:|---:|---:|---:|---:|---:|
| 2x | $7,500 | 1.6 | $6,000 | $2,475 | 49.5% | 2.475% |
| 5x | $18,750 | 3.4 | $12,750 | $9,225 | 184.5% | 9.225% |
| 10x | $37,500 | 6.4 | $24,000 | $20,475 | 409.5% | 20.475% |
| 25x | $93,750 | 15.4 | $57,750 | $54,225 | 1,084.5% | 54.225% |
| 50x | $187,500 | 30.4 | $114,000 | $110,475 | 2,209.5% | 110.475% |

The $1,475 first realization is separate from the remaining exit value. Peak values exclude that realized cash. The modeled 50x case is not an observed 50x winner. Sleeve contribution is relative to initial sleeve equity; the share of a larger portfolio cannot be calculated without its sleeve allocation.

In the conditional add variant, first 2x occurs at 60 seconds, an add occurs at 960 seconds with all fresh gates/cash/capacity/reservations satisfied, and the peak/exit occur at 1,200/1,201 seconds. `scale_budget` permits $2,500: half the original basis is the binding ceiling; $225 already-realized harvest profit increases durable sizing equity to $100,225. The add buys $2,500 at price 2 without rebasing risk. Incremental add P&L for 2x/5x/10x/25x/50x peaks is -$500/$1,750/$5,500/$16,750/$35,500, or -0.5%/1.75%/5.5%/16.75%/35.5% of initial sleeve equity. The 2x retracement illustrates add risk. Historical trigger frequency, incremental P&L and maximum drawdown remain missing.

`bridge_state` is exercised at 181 seconds with the existing gates and preserves the original 129,600-second deadline. Native tests reopen after first realization, right-tail activation, bridge and one add, preserving original basis/HWM, lifecycle identity and exactly one add; a second add is refused. Independent Survivor qualification remains possible while same-asset funding is blocked. No sell/rebuy, artificial realization, basis/HWM reset or second reservation is introduced. Historical bridge invocation count and economic contribution remain missing.

Existing mechanics that can suppress a later underlying winner are the pre-2x ordinary 12% trail, stop/flow/structural/safety exits, the approved 36-hour Current bridge/72-hour Survivor hold, fresh add qualification/capacity and reservation availability. A synthetic 1 -> 1.6 -> 1.4 path exits before any later 25x move. A separate 1 -> 1.18 -> 2.1 -> 1.82 -> later peak path shows the common tail holding through a post-2x pullback that a perpetual 12% ordinary trail would exit. The wider common tail can realize less than a tight trail on a monotonic peak-to-exit path; its incremental value depends on path shape. No economic mechanic was changed, and no historical strategy-change proposal is supported by this archive.

## Execution and provider evidence

Current sizing uses the coded curve execution math, fee/tax/snipe/gas, ordinary loss and exact 2x stress test, not a quoted mark as executable size. Survivor uses exact V4 buy and sell probes with conservative gas, the 30x turnover cap, 450/650-bps ordinary/stress limits and fixed capacity search. Funding reacquires fresh state, full qualification and exact executable size. Quotes pin a proved hash-capable call to `requireCanonical`; otherwise an uncached numeric membership boundary fences fresh state. Cached bytes never prove current canonical membership. The archive cannot independently prove delayed entry/exit fills or average actual executable round-trip loss.

| Provider measure | Retained Pons report value | Qualification |
|---|---:|---|
| Physical HTTP requests | 45,678 | Sum of retained Pons report counters; not an independently deduplicated daily total |
| Logical wire RPC calls | 233,035 | Multiple logical members can share one physical batch |
| Report-estimated CU | 4,563,656 | Estimate retained as reported; not verified canonical billed CU |
| Transport-cache hit fraction | 0.795860% | Hits/(hits+misses); excludes session/coalescing and cannot separate provider roles |
| Maximum reported candidate queue depth | 21 | Historical report telemetry, not a stress test of repaired runtime |
| Queue-enqueued / processed report sums | 17,582 / 15,051 | Report counts; do not interpret as unique opportunities |
| Deadline-insufficient / expired-before-evidence report sums | 1,910 / 617 | Overlapping with other classifications; not winner-loss labels |
| Consumer-deadline / stale-before / stale-during report sums | 128 / 2,527 / 165 | Historical classifications, not independently authenticated candidate outcomes |
| Reported provider-failed class sum | 46 | Role/member attribution is incomplete |

Attribution inputs are the four user-pinned files under `certification/results`: `hourly-35578433187-pons-rpc-attribution.json`, `hourly-35589047835-provider-attribution.json`, `smoke-35578433187-pons-rpc-attribution.json`, `smoke-35589047835-provider-attribution.json`. Exact archive paths and hashes are recorded. The Pons-specific hourly/smoke files retain four/five exception-only failures; the shared-provider files do not supply missing response-member blame. Empty fields remain missing.

Daily requests, daily batches, daily canonical CU, provider bytes, monthly Alchemy cost, official/public vs sequencer vs canonical vs immutable reuse vs position role costs, wait distributions, oldest-pending age, deadline slack and actual retries/429 rates are **UNMEASURABLE** from these reports. No Solana or Ramses cost is allocated to Pons; shared endpoint totals are not added to the Pons counters. No Alchemy pricing assumption is used to turn estimated CU into a bill.

Repair tests demonstrate durable immutable header/receipt reuse, fresh canonical boundary checks, no extra call for cached exact quote lookup, and small normal-history deltas. Actual before/after cache efficiency and operational cost savings require retained comparable provider measurements and are unproved here. The focused offline test process used 35.25s user CPU, 3.01s system CPU, 43.91s wall time and 174,416 KiB maximum RSS; those are test-process measurements, not production lane utilization or provider fairness evidence.

## All requested phases

| Phase | Delivered result | Remaining acceptance proof |
|---|---|---|
| 1 — exact system | Machine/human map with files/classes/functions, authority and generic runtime | None for source mapping |
| 2 — target completeness | Exact coded universe; all-address Current nominations; independent bounded seven-day graduation scan; bounds A–E | Independent all-market census and cold-start completeness |
| 3 — retention stress | 4,096 cheap identities in each strategy; 1,025 history/qualification/burst tests | No claim of timely throughput at arbitrary population |
| 4 — capital independence | Whole Current/Survivor vectors identical across four actual sleeve states; exact quote budget independence | Historical portfolio chronology missing |
| 5 — Current facts | Code-derived vector, canonical complete range/ordering/creator evidence and explicit incomplete failures | Raw archive authority census and real five-second coverage |
| 6 — winner recall | 33 independent vectors/19 curves; named missing fields in PONS_CURRENT_WINNER_RECALL | Independent winner paths and first-observable/eligible times |
| 7 — Current to Survivor | Rejection/exit/capital/provider/restart/retirement independence tests | Real longitudinal cohort trace unavailable |
| 8 — Survivor history | Atomic fair bounded incremental advancement, reorg reconstruction and dense safe compaction | Complete historical Survivor coverage and real catch-up timing |
| 9 — reactivation | Quiet timer and new-nomination reactivation; fresh canonical-head/receipt/state proof; 1,025 fair probe turns; authenticated horizon expiry | Actual longitudinal recall rate |
| 10 — fairness | Governed queue/priority tests and shared-provider regressions; retained pressure telemetry | Simultaneous real latency/queue/deadline measurements |
| 11 — reuse | Durable hash facts, fresh membership, exact lazy quotes, batched state/cost | Comparable before/after operational reuse rate |
| 12 — incremental architecture | Robinhood-native Current rolling history plus Survivor incremental history | Real cost/latency benefit unavailable |
| 13 — positions | Native safety/right-tail/bridge/add tests, restored-first work and 257-depth priority test | Zero real deadline starvation not established |
| 14 — right-tail | Actual frozen mechanics and conditional 2x–50x conversion | Historical execution/capture paths missing |
| 15 — add | Fresh exact requalification/capacity; one-add continuity; conditional budget/contribution | Historical trigger count/P&L/drawdown missing |
| 16 — bridge | Original position/basis/HWM/deadline continuity and restart | Historical invocation/contribution missing |
| 17 — execution | Exact existing curve math and pinned V4 ordinary/stress/funding probes | Historical/live executable delayed fills absent; no live probe authorized |
| 18 — categories | Durable ten-category failure journal and QUALIFIED success | Operational failure-rate measurement absent |
| 19 — recovery | Reopen, child-process death, checkpoint, unfunded/native/harvest/tail/bridge/add continuity tests | Full real restart/deadline acceptance not performed |
| 20 — clean-room study | Chronological point-in-time normalized-vector reconstruction, no decision labels | Representative continuous fixed-strategy portfolio impossible from archive |
| 21 — provider cost | Preserved Pons counters/method/cache/pressure and attribution | Durations, role allocation, bytes and billing missing |
| 22 — repairs | Implemented Pons machinery changes; frozen economics/protected-source checks | No known unimplemented repair claimed as passed |
| 23 — tests | Focused, full Pons, FAST, affected OPERATIONAL, exact baseline parity | One pre-existing unrelated baseline assertion remains |

## Freeze criteria

`PASS_OFFLINE` describes the stated engineering test domain and never substitutes for an unproved end-to-end criterion.

| Required criterion | Result |
|---|---|
| PONS_TARGET_MARKET_RECALL | NOT_PROVEN — no independent complete market denominator |
| PONS_NON_LOSSY_RETENTION | PASS_OFFLINE — 4,096 identities per strategy, 1,025 active fair-work/restart tests |
| PONS_CAPITAL_INDEPENDENT_QUALIFICATION | PASS_OFFLINE — whole vectors equal; exact quote budget independence |
| PONS_CURRENT_EVIDENCE_COMPLETENESS | NOT_PROVEN end-to-end — complete ranges/order/fail-closed regressions pass |
| PONS_SURVIVOR_EVIDENCE_COMPLETENESS | NOT_PROVEN end-to-end — fair incremental/reorg/dense-history regressions pass |
| PONS_CURRENT_TO_SURVIVOR_PRESERVATION | PASS_OFFLINE — no Current decision/exit/capital/provider/retirement veto |
| PONS_REACTIVATION | PASS_OFFLINE — quiet fresh-state probes, new nominees and canonical regraduation; original timing/real ordering retained |
| PONS_PROVIDER_FAIRNESS | NOT_PROVEN operationally — fair bounded work and shared-governor regressions pass |
| PONS_POSITION_PRIORITY | PASS_OFFLINE; real deadline starvation remains NOT_PROVEN |
| PONS_RESTART_RECOVERY | PASS_OFFLINE for tested lifecycle states; operational acceptance not started |
| PONS_EXECUTION_ECONOMICS | NOT_PROVEN — missing real delayed fills/cost/capacity paths |
| PONS_RIGHT_TAIL_CAPTURE_AUDIT | NOT_PROVEN historically — frozen mechanics pass controlled paths |
| PONS_PROVIDER_EFFICIENCY | NOT_PROVEN operationally — reuse repairs tested, actual savings/cost missing |

The final classification is **D — PONS_NOT_READY**. A is unsupported; B is not used to substitute for missing historical evidence; C requires demonstrated material strategy-rejected winners with correct machinery, which this archive does not establish. No economic change is proposed or implemented to manufacture a pass.

## Verification and isolation

CPython 3.12.14 and all pinned requirements match. Tests use offline providers and temporary engineering state. The historical audit blocks socket connection/name-resolution and records zero network attempts and zero provider calls. It extracts only existing repository blobs; it does not generate historical market state.

| Suite | Operational baseline | Final | Result |
|---|---:|---:|---|
| Focused Pons machinery | New regressions | 46 | All pass |
| All Pons tests plus Pons root lifecycle/recovery tests | 376 | 424 | All pass |
| FAST | 496 | 542 | Same one baseline failure, zero errors |
| Affected OPERATIONAL | 582 | 630 | Same one baseline failure, zero errors |
| Shared-governor/Ramses transport regressions | Additional isolation check | 26 | All pass |

The sole FAST/affected OPERATIONAL failure identity is `tests.test_robinhood_usd_valuation.RobinhoodUSDTests.test_strategy_sources_and_nine_change_tests_byte_unchanged`. On both exact baseline and final it first fails the same pre-existing historical byte-equality assertion for `meme_machine/lanes/meteora/dlmm_discovery.py`. That file is unchanged. It was not fixed, removed, skipped or relabeled. New failure identities: **0**. This is failure-identity and first-trace parity: the legacy all-lane byte guard stops at its first assertion, while authorized Pons machinery edits also change source bytes. Frozen economics are separately verified against the current operational AST, policy hashes and all 33 whole vectors. The affected OPERATIONAL module list, traces, exact counts and elapsed times are retained in the verification JSON.

Protected byte checks cover 205 source/config/workflow files, including Pump, Meteora, Ramses, generic economics/accounting/sleeve components and operational/deployment sources: zero differences. The Pons-specific Robinhood adapter changes its owned observation/cache behavior. The only shared generic transport change is the independently tested position admission rule; Ramses source/economics are unchanged. Shared-capital feature work and PR #121 remain isolated.

No PAPER, CAPACITY, RECOVERY or AUTONOMY acceptance run was started. Unit regressions exercising paper books and crash recovery are engineering tests only. No wallet/signing/submission, live process state, merge or deployment was touched.

## Reproduce the provider-free historical audit

Extract the following existing blobs from archive `d1fc161401869522db9abbf50e3f6073e80a4374` to a temporary directory without modification: the gzipped fixture and four attribution files listed above. Extract Current policy from operational source `5bd1a8bfb58b0a9e3df2b0a5194c6b11e0328bd0` and archived strategy `3de3d376847531ccb90e260cfcc96c37587ccb23` to `source-policy.py` and `archived-policy.py`. Keep the four attribution basenames used by the report generator: `hourly-pons-attribution.json`, `hourly-provider-attribution.json`, `smoke-pons-attribution.json`, `smoke-provider-attribution.json`.

Run with the pinned interpreter:

```bash
PYTHONPATH=. .venv/bin/python -m operational.pons_finalization \
  --fixture /tmp/pons-finalization-results/robinhood-runs-355-368.json.gz \
  --source-policy /tmp/pons-finalization-results/source-policy.py \
  --archived-policy /tmp/pons-finalization-results/archived-policy.py \
  --attribution /tmp/pons-finalization-results/hourly-pons-attribution.json \
  --attribution /tmp/pons-finalization-results/hourly-provider-attribution.json \
  --attribution /tmp/pons-finalization-results/smoke-pons-attribution.json \
  --attribution /tmp/pons-finalization-results/smoke-provider-attribution.json \
  --output /tmp/pons-finalization-results/reproduced-audit.json
PYTHONPATH=. .venv/bin/python -m operational.pons_finalization_map \
  --output-dir /tmp/pons-finalization-results/reproduced-map
.venv/bin/python -m operational.tests FAST
```

The historical generator rejects a fixture checksum mismatch and any network attempt. The complete reconstructed-vector comparison must report zero divergences, eight qualifying evaluations and five qualifying curves. The map verifies each source symbol and records source content hashes. FAST retains the documented baseline failure until that independent issue is addressed.
