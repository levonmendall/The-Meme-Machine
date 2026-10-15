# Pons three-defect repair report

2026-10-07. **Quiet reactivation: PASS. Startup recall repair: PASS. Execution
attribution: PASS.** These are offline engineering results. The branch is ready
for separate authorization of the handoff's bounded technical observation;
no observation, PAPER service, deployment or historical study was started.
Economic performance and real provider throughput remain unproved.

**Preserved provenance and exact validated implementation.**

| Item | Value |
| --- | --- |
| Repair branch | `engineering/pons-three-defect-repair-20261007` |
| Validated repair commit | `f6f21a3d10e1e3460122ffb8db016e929ffa5b44` |
| Validated repair tree | `3335f0611b5264c4fd66a8f15cd06cc648292d82` |
| Immutable implementation URL | [GitHub commit f6f21a3](https://github.com/levonmendall/The-Meme-Machine/commit/f6f21a3d10e1e3460122ffb8db016e929ffa5b44) |
| Branch source | Published handoff `30b289d50529595431bbe8b01d70cf881273cc9a`, tree `54771a339f0e527ed260a5ea84ed431d54cdaa1d` |
| Original verified implementation | `86bdcac4afb6cb6290f32f495d81489bb572ec65` |
| Selectively reviewed WIP | `2ca2afd3f2ae9d5fcfa7d935a8d898a2b1ba7210` |

This report is a documentation-only child of the validated repair commit. The
final response identifies its containing commit/tree. The original handoff,
original evidence artifacts, preserved engineering/WIP branches and operational
branch are unchanged. No merge, rebase, reset, amend or force-push occurred.
Only directly relevant WIP code/tests were reused. Its blocking cold-start loop,
partially updated reports and stale certification artifacts were not imported.

**Original failures reproduced before runtime changes.**

The three permanent regressions were first run with the published handoff's
runtime, which is byte-identical to `86bdcac` for these paths. All three failed
their behavioral assertions; none failed because a new implementation API was missing.

| Baseline reproducer | Observed failure | Corrected result |
| --- | --- | --- |
| `CurrentRecheckEvidenceTests.test_age_gate_reopens_without_new_trade_using_real_receipt_decoder_and_current_state` | Actual Current evaluation rejected age 87; after completion/consumption, no new buy and advancing time produced `Broker.pop() is None`. | A separately timed canonical evaluation at age 90 passes the fixed vector with no new trade. Actual receipt decoding, complete window reconstruction and mutable read pinning are exercised with offline RPC fixtures. |
| `ContinuousCampaignTests.test_startup_prehead_buy_is_nominated_without_a_new_trade` | `cohort.run(campaign=True)` started at head 200 and never nominated the retained buy at block/time 195; zero lifecycles instead of the expected one. | The same cohort fixture discovers the pre-start buy. Qualification/position effects are stubbed in this discovery integration case; full qualification authority is tested separately. |
| `ContinuousCampaignTests.test_execution_block_is_durable_after_qualification` | Two durable qualifications were TRUE, but the journal's funding dispositions were empty while public output reported `same_curve_lifecycle_active`. | Two TRUE decisions, one separately recorded conflict, and one admitted lifecycle. |

These fixtures establish the original machinery failures and their repairs;
they are not actual market fills, winner recall or profitability evidence.

**Exact source repairs.**

| File / function | Change |
| --- | --- |
| `meme_machine/runtime/robinhood/pons.py`: `Broker.enqueue`, `reactivate_one`, `pop`, `finish`, `failure`, entry-guard release | Pons-owned durable watch retains original identity/nominee/time and real-event ordering. Timer work has a new fenced generation and requests fresh canonical facts; it never renews an old attempt. Due probes alternate with live nominations and rotate fairly. Known minimum-age crossings schedule the earlier boundary. Recoverable failures back off from 5 to 60 seconds. Authenticated buying outside the positive 15-second window suspends quiet probes until a real buy; authoritative Current horizon expiry removes only the Current watch. Unconsumed decisions, reserved entries and live native ownership remain protected. Restart repairs the observation/watch projection gap. |
| `meme_machine/lanes/pons/pons_selective_acquisition.py`: `refreshed_current_candidate`, `evaluate_candidate`, `public_evaluation` | Fresh canonical head and numeric membership, complete canonical demand census, real latest buy receipt and current pinned mutable state precede each timer/primed evaluation. Original nomination and receipt timing remain distinct from current state authority. Future heads, changed membership, missing buying or expired acquisition fail closed. No cached old vector grants qualification or entry. |
| `meme_machine/lanes/pons/pons_current_window.py` | Names the existing 60-second demand-window constant without changing its value or inclusive coverage. Startup reuses this frozen evidence window; positive independent buying in the last 15 seconds is required by the existing strategy, so older quiet curves need a new buy to qualify. The 90–900-second eligibility domain remains unchanged. |
| `meme_machine/lanes/pons/pons_selective_cohort.py`: `_prime_current_step`, `run` | Canonical startup nominations advance in bounded newest-first slices, making urgent candidates available before the whole window finishes. Live and startup work use separate slots in the existing discovery executor. Factory/deployer/native-quote authentication remains mandatory in qualification. Ordered broker fences and idempotent raw identities reconcile priming/live overlap. All page nominations persist before a fresh post-log membership check seals the durable suffix watermark. Restart resumes that exact suffix; reorgs invalidate coverage and restart the bounded scan. Missing pages/history and exhausted history bounds remain explicit coverage gaps. |
| Same cohort: authorization-rejection branch | Complete qualification persists first. A separate append-only `funding / OTHER_EXPLICIT_REASON` record retains the conflict reason, blocking cohort lifecycle index and trial-ledger locator, with `entry_authorized=False`. Capital denial uses its separate category. Existing same-curve, flat-prior-lifecycle and regime-reset authorization predicates are unchanged. |
| `meme_machine/lanes/pons/pons_attempts.py`: `failure_category` | Missing recent canonical buying is `INCOMPLETE_EVIDENCE`, not an economic rejection. |
| `tests/lanes/pons/test_pons_finalization.py`; `tests/lanes/pons/test_pons_continuous_campaign.py` | Permanent regressions for the three original failures, freshness, age transition, fair population scheduling, restart/retirement, native ownership, exact startup boundaries, incomplete pages, reorg sealing, bounded calls, concurrent service and idempotent execution attribution. |

Changed implementation/test files: **seven**, listed above. This report is the
eighth changed file relative to the handoff. Shared `plane.py`, provider admission,
shared-capital accounting and all other lane implementations are unchanged.

**Bounded regression verification.**

CPython 3.12.14; temporary state and offline providers. Final targeted and provider
runs used `operational.tests.network_guard`. Exactly one FAST run was performed;
neither the full Pons suite nor affected OPERATIONAL was rerun.

| Run | Result |
| --- | --- |
| Original failure reproductions | 3 tests, 3 expected baseline failures |
| Final targeted Pons/integration suite | **111/111 PASS**, 170.37 seconds |
| Directly affected provider/admission/fairness/immutable-reuse suite | **36/36 PASS**, 0.58 seconds |
| Final quiet/restart/reservation guard check | **7/7 PASS**, 55.90 seconds; included in the final targeted run |
| Single final FAST comparison | **565 tests, one baseline failure, zero errors**, 192.98 seconds |
| Preserved FAST baseline | 542 tests, the same one failure and zero errors |
| New failure identities | **0** |

Final targeted modules: `tests.lanes.pons.test_pons_finalization`,
`test_pons_continuous_campaign`, `test_pons_candidate_plane`,
`test_pons_entry_confirmation_ordering`, plus
`tests.test_current_survivor_independence` and `tests.test_pons_ongoing_scale`.
Provider modules: `tests.lanes.pons.test_provider`, `test_provider_admission`,
`test_shared_position_fairness`, `test_immutable_rpc`.
Reproduce with `python -m unittest` followed by those fully qualified module names;
FAST uses `python -m operational.tests FAST`. Baseline reproduction names are
the three methods in the table above, evaluated against the original runtime.

The unchanged local failure identity is
`tests.test_robinhood_usd_valuation.RobinhoodUSDTests.test_strategy_sources_and_nine_change_tests_byte_unchanged`.
Its first trace remains the pre-existing Meteora `dlmm_discovery.py` byte assertion.
No unrelated test was changed. That first failure masks later assertions; economic
preservation is independently verified below. Previously documented GitHub
`storage_configuration_permissions` failures were not repaired or treated as green.

**Frozen policy and preservation checks.**

Current policy source and Survivor policy source are byte-identical to the handoff:

- Current `pons-selective-continuation-v1`:
  `888904d0e58865f1a701560a5be8386f57d88f66a0c25d7094c994cafa7f448f`.
- Survivor `pons-postgrad-survivor-momentum-v1`:
  `ed17402a75470801fda47877b6b1f3b1266793b7e0750b7a7cd821f327541e5f`.

All **205 protected source blobs** matched the published baseline. Existing
capital-independence, Current-to-Survivor, native continuity and reservation
regressions pass. Retention tests preserve 4,096 identities per strategy;
1,025 quiet Current candidates receive fair turns under continuous new-buy
pressure. Same authoritative as-of inputs produce the same economic rejection
vector. No threshold, 5% realized-equity sizing, stop, realization, trail,
adverse-flow, right-tail, bridge, staged-add, exposure ceiling or Survivor holding
rule changed. Pump/PumpSwap, Meteora, Ramses, Solana and shared-capital behavior
were not modified.

**Resource implications, limitations and next authorization.**

Startup adds one task slot to the existing discovery executor, not a service or
new infrastructure. Each startup step has the existing five-second acquisition
budget. Log pages remain ten blocks, at most four per step; canonical membership
witnesses keep the physical batch bounded. An existing 8,192-block history bound
produces `pons_startup_history_bound` with incomplete coverage, never an eligibility
veto. No receipts or full block bodies are acquired for nomination priming.
Native position admission remains priority zero; startup candidate work uses the
existing lowest candidate priority. The original 0.5-second physical ceiling and
burst fairness are unchanged. Actual provider latency, CU, monthly cost and live
position deadline performance remain unmeasured.

No directly relevant defect remains unresolved. Under unavailable canonical history
or inadequate budgets, startup can remain explicitly incomplete while live/native
work continues; full recall must not be claimed in that state. Existing source
interpretation fencing remains fail-closed: old-version operational-state migration
was not authorized or tested. A separate technical observation should use isolated
state, this reviewed revision, authoritative access and agreed resource caps as in
[PONS_EXIT_HANDOFF.md](PONS_EXIT_HANDOFF.md). No observation is authorized by this report.

**Deployment: NONE. PAPER service: UNCHANGED. Strategy changes: NONE.** The task
stops at these three verified repairs; economic optimization, historical research
and additional machinery improvements are outside this result.
