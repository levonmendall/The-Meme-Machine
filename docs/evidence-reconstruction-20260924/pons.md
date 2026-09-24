# Pons evidence reconstruction repair findings

Primary immutable dataset: accepted run `35949285193`, runtime `1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`.
Frozen policy hash: `19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84`.
Prepared baseline tree: `ee8e8179262195ca92dda0e0e5e3ee12f4cbd9f6` (source HEAD alone does not contain prior overlays).
Historical records and cohort admission are unchanged. The taxonomy below is a separate engineering interpretation, keyed by transaction plus log index at each original observation. No token-wide rejection cache was introduced.

## Complete causal explanation

The nominal **0/86** is an incorrect full-reconstruction denominator, not 86 lost reconstructions. All 86 reached an authoritative frozen token-age veto, and all 86 were older than 600 seconds. Eight acquired complete trajectories and were rejected (six age + velocity + ETA; one age + velocity; one age alone); 78 reused authenticated immutable launch times and correctly skipped trajectory reconstruction. None required the 60-second receipt window, normalization, full-vector validation or evidence promotion. Eight complete trajectories are not eight complete qualification vectors. The age decisions completed in 0.348–4.357 seconds. No completed full vector was discarded or hidden.

The original **239 reconstruction_incomplete** rows are disjoint from those 86:

| Original boundary | Count | Causal bucket | Evidence |
|---|---:|---|---|
| natural_non_native_quote_not_supported | 193 | Valid early structural rejection | Authenticated pair token is outside the already-frozen native-quote scope |
| invalid_current_snipe_bps | 46 | Valid early strategy rejection | All raw snipe rates are 9900 bps; the frozen strategy requires zero |

All 239 were independently reverified against the exact accepted artifact's pinned code, token and factory-record RPC reads. None is missing immutable evidence. All 46 raw-snipe observations have fee=100 bps and creator tax between 0 and 1000 bps. The verified deployed Solidity source returns raw decay in currentSnipeTaxBps(), then clamps a nonzero rate inside buy(). The acquisition primitive rejects a raw value above 9900-fee-creatorTax before the selective strategy can classify its zero-rate veto. This is an early-screen/classification defect; this repair leaves quote arithmetic and that primitive's rejection intact. Native pipeline terminal timestamps confirm all 239 decisions occurred within 5 seconds (maximum 4.998437s for snipe; 4.765037s for non-native).

## Required-evidence accounting

| Metric | Count |
|---|---:|
| Raw discovered observations (not the denominator) | 2056 |
| Unique screened / queued observations | 693 |
| Current-state evidence requests | 692 |
| Confirmed candidates requiring full qualification evidence | 0 |
| Full evidence necessity still unknown because preflight failed | 2 |
| Actual receipt-window full evidence requests | 0 |
| Full qualification completions in time | 0 |
| Infrastructure failures after confirmed full-evidence necessity | 0 |
| Preflight infrastructure failures | 2 |
| Full evidence unnecessary after authoritative earlier rejection | 691 |
| Pending at observation close | 0 |

The completion rate among confirmed required requests is **not applicable (0/0)**. The two unresolved necessities remain explicit and must not be described as strategy failures or assumed non-opportunities: one `provider_rpc_3` occurred in current authentication; one queue `deadline_insufficient` was recorded as stale_in_queue. The provider raw artifact retains only exception-level RPC code 3, not a member response identifying the reverting getter; no per-member cause is invented. No scheduler change is justified from these two cases.

Exclusive taxonomy for all 693 screened observations:

- Valid early strategy rejection: **498** (366 normal current-state screens + 86 age/trajectory screens + 46 authenticated raw-snipe vetoes).
- Valid early structural rejection: **193** non-native quote observations.
- Provider failure: **1**, required full evidence not established.
- Deadline failure: **1**, required full evidence not established.
- All remaining requested taxonomy buckets: **0** for these screened observations.

This taxonomy preserves every observation, including later observations of the same curve; it does not treat an earlier rejection as authority over later candidate states. Discovery-only records never promoted to screening are not added to the denominator.

## Repairs

1. `pons_selective_acquisition.py`: move evidence_required / admitted / evidence_requested after frozen trajectory admission. Keep trajectory_requested / trajectory_complete separate. A cached age veto has no trajectory or full evidence request. Add explicit decision-necessity metadata while preserving full-qualification requirements for any entry.
2. `pons_natural_observation.py`: preserve authenticated current-state facts when the two existing quote boundaries fire. All native identity/authentication, quote bounds and freshness rules remain in place.
3. `pons_selective_cohort.py`: classify only fresh, explicitly authenticated early vetoes as strategy/structural screens; emit evidence_not_required and retain original boundary, fields and incomplete-vector status. Bare exception strings, missing/invalid proof, unknown failures and stale proof remain infrastructure/reconstruction failures. Reset per-candidate evidence so a previous candidate cannot authorize a later rejection.
4. `pons_selective_acquisition.py`: when the first trajectory batch authenticates an out-of-range launch age, stop before further historical headers, reserve anchors and speculative receipt-window prefetch. This repairs the unnecessary work demonstrated by the eight first-seen curves. In-age candidates retain exactly the same trajectory evidence requirements and requests.

No repeated full histories or discarded usable vectors were found. Cross-candidate launch/header reuse is active (78 cached age vetoes); no serial final-stage bottleneck is evidenced because no candidate reached the final stage. No reconstruction was failed at window termination.

## Validation and ownership

New regressions are in `robinhood_tests/test_pons_evidence_reconstruction_semantics.py`: 12 tests covering authenticated vs unproven boundaries, original snipe quote failure, stale evidence, append-only pipeline restart, cached-age/no-request semantics, complete-trajectory/non-complete-vector distinction, full-evidence required successes and failures, per-candidate reset, cold-age early stop, and unchanged in-age requests.

Final focused command:
`python -m unittest robinhood_tests.test_pons_evidence_reconstruction_semantics robinhood_tests.test_coverage_acquisition robinhood_tests.test_pons_factory_hint_reuse robinhood_tests.test_pons_natural_observation robinhood_tests.test_pons_market_scope_efficiency -v`

Final affected-lane command:
`python -m unittest discover -s robinhood_tests -v`

Final results on Python 3.12.14: **35 focused tests passed** (0.353s); **363 full Pons lane tests passed** (1.688s). See `pons-focused-tests.log` and `pons-lane-tests.log`. Native arithmetic, execution, provider recovery, accounting, and lifecycle tests are included in the lane suite. Tests use offline synthetic/captured fixtures; no natural run, provider call or workflow action was performed by this lane agent.

Root owns the shared `pipeline.py` snapshot change and its integrated required-evidence summary; it is already present in the prepared lane and included in the final lane validation. The four Pons-owned changed files are the three source files above plus the new test module. Root should compose the final overlay against the saved prepared baseline, not source HEAD.

Strategy economics unchanged: yes. Target scope unchanged: yes. Provider limits unchanged: yes. Evidence requirements unchanged: yes. Accounting unchanged: yes. Paper-only unchanged: yes. No commits, pushes, workflow polling/cancellation/dispatch, history edits or cohort reclassification by this lane agent.

## Audit artifacts

- `pons-observation-taxonomy.json`: all 693 observations, unique immutable identities, original statuses, original boundaries, diagnostic causal bucket, necessity, timing and per-boundary proof.
- `pons-authenticated-rejection-audit.json`: all 239 code/factory-authenticated original boundary observations, raw rates, fees and pair tokens; zero missing evidence.
- `accepted-review/complete-review.json`: primary digest-verified projection.
- `native/certification-hourly/pons/rpc-evidence.jsonl.gz`: byte-verified original RPC evidence.
- `native/certification-native/hourly/pons/pons-selective-continuation-v1-cohort/opportunity-pipeline.sqlite`: original append-only observations (opened read-only/immutable).

Pons implementation complete: **yes**, subject to parent integrated verification and exact-SHA handoff. No profitability claim. No missing-evidence-as-strategy-failure inference.
