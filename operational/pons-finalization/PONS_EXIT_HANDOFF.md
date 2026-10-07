# Pons finalization exit handoff

2026-10-07. **Offline engineering deliverables are complete; economics are NOT_PROVEN.**
Classification remains **D — PONS_NOT_READY**. This is a stop and handoff, not
authorization for repairs, provider spending, deployment, acceptance, or PAPER execution.

**1. Preserved sources and publication.**

| Role | Branch / commit | Exact tree |
| --- | --- | --- |
| Operational source at isolation | `operational/paper-v1` at `5bd1a8bfb58b0a9e3df2b0a5194c6b11e0328bd0` | `65c2f85f1c67676372ab2b449499d76a17bb224f` |
| Verified implementation and evidence | `engineering/pons-finalization-20261007` at `86bdcac4afb6cb6290f32f495d81489bb572ec65` | `f03405080491ae47002bcfae9426814cb2b52e59` |
| Separately preserved, unvalidated experiments | `engineering/pons-finalization-wip-preservation-20261007` at `2ca2afd3f2ae9d5fcfa7d935a8d898a2b1ba7210` | `c66e59ca1260346ffa256681afa145c9764871d9` |

Both implementation and WIP commits were verified published on GitHub. The WIP
commit preserves all ten outstanding files byte for byte, plus a preservation
notice. It includes quiet-market timer rechecks, restart guards, execution-block
attribution, and **unfinished cold-start nomination priming**. Its partially updated
reports and old manifests are not a consistent certification bundle. Earlier
scratch test results do not validate this exact snapshot. No WIP changes are
incorporated into the verified branch; this handoff adds documentation only.
The containing documentation commit/tree are obtainable with `git rev-parse HEAD HEAD^{tree}`.

**2. Completed meaningful engineering.**

The published implementation provides non-lossy cheap Current/Survivor retention,
capital-independent qualification before funding, durable incremental candidate
history, complete canonical Current windows, fair Survivor history progression,
Current-to-Survivor independence, and reactivation on fresh nominations/canonical
regraduation. It validates fresh canonical membership and exact ordinary/stressed
execution quotes, reuses immutable authenticated facts, protects position admission
and native maintenance, journals explicit failures, and preserves restart state.
Partial realization, HWM, right-tail, staged-add, bridge, reservation and accounting
continuity have offline regressions. See the [lifecycle map](PONS_EVIDENCE_LIFECYCLE_MAP.md)
and [implementation report](PONS_FINAL_REPORT.md) at the verified commit.

Frozen policies remain:

- Current: `pons-selective-continuation-v1`, revision
  `profitability-v1-profit-protection-v2-execution-capacity-v1-moderate-admission-v1-operational-nine-v1`,
  hash `888904d0e58865f1a701560a5be8386f57d88f66a0c25d7094c994cafa7f448f`.
- Survivor: `pons-postgrad-survivor-momentum-v1`,
  hash `ed17402a75470801fda47877b6b1f3b1266793b7e0750b7a7cd821f327541e5f`.

Both retain 5% realized-equity sizing. Current retains -8% stop, +18% realization
selling 25%, 12% ordinary trail and 1.20x adverse flow. Common >=2x protection
uses **40% giveback of peak profit**. The original-open 36-hour bridge preserves
basis/HWM. The one permitted add retains all timing, requalification, capital,
capacity and exposure conditions. No economic threshold was changed.

**3. Verified results and reproducibility.**

Read-only checks against commit `86bdcac` matched all 39 mapped source hashes,
all 30 non-self-referential changed-file hashes, and all 205 protected blobs.
The pinned local interpreter remains CPython 3.12.14. Recorded offline commands,
suite results and baseline comparisons remain in [PONS_VERIFICATION.json](PONS_VERIFICATION.json).
No test suite or historical replay was rerun for this handoff.

| Recorded suite | Verified implementation | Baseline comparison |
| --- | --- | --- |
| Pons | 424/424 PASS | 376/376 PASS |
| Focused regressions | 46/46 PASS | New focused coverage |
| Shared governor | 26/26 PASS | Original governor ceilings preserved |
| Local FAST | 542 tests, one failure, zero errors | 496 tests, same failure |
| Affected OPERATIONAL | 630 tests, one failure, zero errors | 582 tests, same failure |

Local failure identity is
`tests.test_robinhood_usd_valuation.RobinhoodUSDTests.test_strategy_sources_and_nine_change_tests_byte_unchanged`.
Both first traces fail the pre-existing Meteora `dlmm_discovery.py` byte assertion;
that file is unchanged. New failure identities: **0**. This does not prove later
assertions masked by that first failure; frozen economics have separate AST/hash/vector checks.
GitHub FAST [implementation run](https://github.com/levonmendall/The-Meme-Machine/actions/runs/37664719459)
and [source baseline run](https://github.com/levonmendall/The-Meme-Machine/actions/runs/37548780045)
both contain two `storage_configuration_permissions` failure annotations at
`meme_machine/operational/storage_guard.py:40`. CI is not green; these are distinct
from the local byte-guard failure.

**4. Remaining unproved criteria and documented limitations.**

Independent market coverage, real deadline-complete Current/Survivor evidence,
simultaneous provider fairness, real position deadline performance, executable
portfolio profitability, actual winner recall, tail/add/bridge contribution and
attributable monthly provider costs remain unproved. Offline population tests
cover 4,096 identities per strategy and 1,025 fair history/qualification turns;
they establish retention behavior, not real-market timely recall.

Three source-level limitations identified before this handoff remain documented,
without further repair work. Locations below refer to `86bdcac`:

| Limitation / source | Reproducer | Severity / impact |
| --- | --- | --- |
| Quiet Current reactivation: `meme_machine/runtime/robinhood/pons.py:71,111`; `meme_machine/runtime/robinhood/plane.py:299` | Finish an age-87-second rejection or provider failure; let age/provider recover while the latest buy remains valid, with no new buy. Finish clears pending work; no timer nominates a fresh evaluation. | High recall risk for recoverable quiet opportunities; actual missed winners are unmeasured. Published reactivation proof covers fresh nominations, not this case. |
| Current startup boundary: `meme_machine/lanes/pons/pons_selective_cohort.py:386,471` | Start without a saved cursor after a qualifying curve's last buy five seconds before the initial head; no later buy. Discovery begins after that head. | High startup recall risk; no recent pre-start census. The WIP priming attempt is unfinished and excluded. |
| Execution-block journaling: `meme_machine/lanes/pons/pons_selective_cohort.py:987` | Qualify a second evaluation while a same-curve lifecycle is active. Public output records `same_curve_lifecycle_active`, but the attempt journal lacks the separate funding disposition. | Moderate attribution gap; no duplicate-entry permission and no economic decision change. A WIP patch is preserved separately. |

These are machinery limitations, not evidence of an economic strategy defect.
No strategy-review classification or optimization is justified by the archived sample.

**5. Historical evidence boundary.**

The preserved [historical audit](PONS_HISTORICAL_AUDIT.json) records 15,051 decision
rows, 1,312 identified curves, 33 complete reconstructed evaluation vectors across
19 curves, and eight qualifying evaluations across five curves. Whole-vector
divergences against the operational evaluator: **zero**. Source: archived commit
`d1fc161401869522db9abbf50e3f6073e80a4374`, fixture
`certification/evidence/robinhood-runs-355-368.json.gz`, SHA256
`1be70cb9f53bfc9bce039f6913813a6d2a0a21dde39b6b10bf95b9123f47597f`;
archived strategy reference `3de3d376847531ccb90e260cfcc96c37587ccb23`.

The archive lacks an independent census, continuous outcome price/quote paths,
complete chronological fills/accounting and timestamped provider service/billing.
Reprocessing the same rows cannot supply those missing facts. Major-winner counts,
before-move qualification, portfolio returns, real tail/add/bridge contributions
and monthly costs stay **UNMEASURABLE**. Synthetic paths establish mechanics only.
Further broad offline historical investigation has diminishing value and is stopped.

**6. Minimum prospective validation design — planning only.**

Use the existing Robinhood provider, Pons history, evidence plane, native PAPER
books, attempt journal and telemetry on existing compute. Pin an explicitly
reviewed commit and the policies above; exclude the WIP snapshot by default.
Keep validation state separate from the unchanged operational PAPER service.
For the nonfunding sample, invoke existing acquisition/qualification functions and
persist decisions without invoking entry/reservation. Keep the positive realized-equity
sizing base; disabling funding must not zero the qualification target or change a gate.

The target is chain **4663**, authenticated compiled native-quote Pons V2 curves
from factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e` and deployer
`0x3711ceA4feaDE896C913C68F01Eda97Cb06D1A42`, plus their authenticated
`PoolGraduated` transitions into registered native V4 pools. Current's existing
90–900-second domain and Survivor's 4-hour–7-day domain are unchanged; the
[machine-readable map](PONS_EVIDENCE_LIFECYCLE_MAP.json) specifies hook/manager and all gates.

| Question | Required prospective evidence |
| --- | --- |
| A. Market coverage | Independently enumerate canonical factory/deployer launch records, all-address CurveBuy/CurveSell logs and factory PoolGraduated logs, using verified ABI/identity checks. Cover the startup Current horizon and prior seven-day graduation cohort, then every observed contiguous block range. Seal header hashes, receipts, range watermarks and ordered event IDs. Reconcile identity sets against runtime retention after discovery/restart; do not use runtime candidates/decisions as the census. Missing ranges or an unavailable census mean coverage NOT_PROVEN. Public nominations and sequencer clocks are compared against canonical evidence, not treated as authority. |
| B. Qualification | Save each full frozen vector, input provenance/windows, policy hash, first observation, original deadline, completion time, generation and durable decision. Enforce no future inputs and deterministic ordering. Repeat identical complete evidence with available/unavailable capital in isolated replay. Economic rejection, structural exclusion, incomplete evidence, provider failure, deadline miss, capacity restriction and funding denial remain separate. Current decisions never control Survivor membership. |
| C. Execution | For every qualifier retain fresh pinned entry/exit quotes at the realized-equity 5% target and admitted capacity step, double-size stress, gas/tax/slippage, quote age and remaining original deadline. Record executable size and ordinary/stressed round-trip loss, not mark-price arithmetic. Funding may differ only after durable qualification; qualified-unfunded opportunities stay in the denominator. |
| D. Winner capture | Predeclare a major winner as >=5x its first canonical executable market reference price in the cohort; separately report 2x/10x/25x/50x+ paths. Track every census member, including rejects, through curve-to-pool identity continuity. Preserve earliest observability, complete evidence, valid Current/Survivor qualification, first 2x/5x crossing, executable entry and exact blocking gate. Chronological native PAPER accounting must report partial proceeds, add basis, peak/exit value, realized/marked P&L and sleeve contribution with frozen exit/bridge/add rules. Missing/censored paths never become losses, passes or strategy rejects. |
| E. Efficiency | Attribute unique physical transports and logical RPC members to public discovery, sequencer observation, canonical evidence, qualification and position maintenance. Record batches, CU when available, request/response bytes, cache hits, latency, queue depth/oldest age/waits, deadline slack/misses, 429/errors/retries, physical rate, CPU and RSS. Include census overhead separately. Count shared Robinhood/Ramses transports once; exclude Solana costs. Estimated CU is distinct from billed CU. |

Two bounded samples serve different purposes:

- **Technical first assessment:** 24 hours of read-only observation and qualification,
  with funding disabled. Minimum useful coverage: 30 distinct native identities,
  ten complete Current and five complete Survivor decision lifecycles, one controlled
  restart, and two position-equivalent maintenance timelines, one per regime, under
  concurrent candidate pressure using the existing harness. Artificial position basis
  is labeled and excluded from economic results. A controlled outage must produce an
  explicit recoverable disposition. These are engineering coverage floors, not
  statistically derived counts or limits on candidate retention. Record physical
  position deadline performance only if the real provider path is exercised;
  offline pressure replay alone leaves that criterion NOT_PROVEN.
- **Economic first assessment, separately authorized:** enroll for 24 hours, observe
  the enrolled graduation cohort through its seven-day eligibility horizon, and
  allow at most 72 hours for the latest admitted Survivor hold: **11 calendar days
  total maximum**. Continue observing Current-to-Survivor transitions; late graduates
  whose full horizon does not fit are explicitly censored. Seek at least ten completed
  executable PAPER entries, at least three per regime, and three independently identified
  >=5x market winners. Report every observed opportunity even if these floors are not
  met. This small sample can test capture mechanics; it cannot establish profitability.

At each fixed cap, insufficient identities, vectors, entries, winners or position
evidence yields **INSUFFICIENT_SAMPLE** for the affected criterion; no automatic
extension. Report open positions and unsettled intents as censored, preserve their
native state, and never fabricate a closing fill to complete the sample.

Stop new admission immediately for identity/range loss, unauthorized provider
use, corrupt recovery, stale evidence authorizing execution, duplicate reservation,
accounting mismatch, or any observed position/safety deadline starvation. Preserve
logs and native intents; safety maintenance takes priority within the separately
authorized run. Provider/capacity/funding failures receive explicit dispositions,
not economic rejection. Stop at the agreed request/CU/storage/time caps as well.
Use the existing ten failure categories; record sample censoring separately.

**7. Provider and compute requirements.**

No additional infrastructure or cloud capacity is proposed. Existing admission
retains its 0.5-second physical interval and burst fairness; approximately 172,800
transports/day at sustained 2/sec is a shared ceiling reference, **not predicted
Pons usage or a spending allowance**. Actual requests/day, CU/day, bytes/storage,
cache rate, latency, CPU/RSS demand and monthly Alchemy cost are **UNKNOWN**.
The offline focused process's roughly 170 MiB peak RSS is not a live sizing estimate.
Before any later launch, identify existing read-only credentials, plan allowances
and explicit request/CU/time/storage caps, including the independent census.
An unknown spending cap is NO-GO. Do not purchase capacity or infer monthly cost
from the unrepresentative archive; use measured attribution and the actual provider plan.

**8. Dependencies and integration conflicts.**

Read-only upstream verification found `operational/paper-v1` at
`9f08f0db68fd3161c84bb955800db9a200a70f77`, tree
`384b94e290c0262f667c6605034c85f037c5fe47`. Its Ramses pause is not incorporated;
`operational/tests.py` has changes on both branches and requires later integration
review. [Solana PR #121](https://github.com/levonmendall/The-Meme-Machine/pull/121)
remains OPEN/unmerged, observed head `476bad205014c8c3d586f45d87f84ec44306817a`.
Any future common runtime/provider overlap must be reviewed independently, without
rebasing this handoff onto that architecture. Pump/PumpSwap, Meteora, Ramses economics,
shared-capital work and deployment remain isolated and unchanged by this task.

**9. Recommended next action and go/no-go.**

Request one separately authorized **24-hour, nonfunding Pons technical observation**
on existing resources, with the independent canonical census and fixed resource
caps above. This task does not start it. GO requires a pinned reviewed revision,
usable authoritative access, known caps, isolated state and functioning recovery.
Keep the documented quiet-reactivation/startup/journaling limitations visible;
their WIP experiments are not approved. NO-GO for freeze or funded economic
acceptance until these limitations are dispositioned and prospective coverage,
evidence, execution and safety results are demonstrated. Lack of market activity
produces INSUFFICIENT_SAMPLE, not another indefinite engineering investigation.

Post-`86bdcac` investigation had drifted into additional reactivation/cold-start
experiments and repeated test iterations. Those edits are quarantined on the WIP
branch. The stop task performed preservation, read-only artifact/CI verification
and documentation only. **Deployment: NONE. PAPER service: UNCHANGED. Strategy
changes: NONE. No PAPER/CAPACITY/RECOVERY/AUTONOMY campaign was started.**
