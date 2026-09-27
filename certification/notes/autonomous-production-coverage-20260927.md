# Autonomous PAPER production-path coverage audit

Authority: `autonomous_paper_task_manifest.json`; four sleeves, six active regimes. No strategy or allocation change. This is a gap audit, not a new certificate. PROVEN means an existing production-code regression and source path were identified; all must pass again in the final exact-SHA certificate. MISSING includes missing composed end-to-end or cross-window proof even when unit coverage exists. BROKEN identifies a reproduced defect.

| Production path | Pump current | Pump Survivor | Pons current | Pons Survivor | Meteora | Ramses |
|---|---|---|---|---|---|---|
| discovery | PROVEN | MISSING | PROVEN | MISSING | PROVEN | PROVEN |
| target-market routing | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| authoritative evidence | PROVEN | MISSING | PROVEN | MISSING | PROVEN | PROVEN |
| reconstruction | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| feature computation | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| qualification | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| commit-time revalidation | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| capacity/sizing | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| shared-sleeve reservation | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| PAPER fill | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| durable position state | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| ongoing monitoring | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| partial realization where applicable | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| protective/trailing management | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| stop/invalidation | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| max hold | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| exit | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| settlement | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| realized/unrealized P&L | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| lane accounting | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| portfolio accounting | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN | PROVEN |
| restart/replay | MISSING | MISSING | BROKEN | MISSING | MISSING | MISSING |

## Existing proof map

- Pump current: native `test_strategy_prospect_admission`, `test_pump_acceleration_strategy`, `test_pump_acceleration_paper`, `test_pump_durable_strategy_recovery`, and `test_pump_shared_survivor`; native accounting journal and strategy-local entry/exit code. Canonical native decision capture/replay covers current frozen decisions.
- Pons current: native `test_pons_selective_continuation`, `test_pons_entry_confirmation_ordering`, `test_pons_execution_acquisition`, `test_pons_partial_accounting`, `test_pons_cohort_capital`, `test_pons_shared_survivor`; captured finalized reconstruction and continuous campaign suites.
- Both Survivors: native `test_pumpswap_survivor` / `test_pons_postgrad_survivor`, canonical `test_survivor_commit`, `test_survivor_risk_boundaries`, `test_directional_execution_capacity`, `test_survivor_history`, `test_directional_accounting`. These exercise actual commit/monitor/book/sleeve code with bounded authoritative-adapter fixtures. Native Pump lineage/oracle tests and Pons graduation/provider regressions prove their components but do not yet close complete runtime reconstruction/feature composition.
- Meteora: native `test_solana_dlmm_independent_v1`, `test_dlmm_independent_accounting`; canonical `test_continuity_state` restores a native mark without resetting elapsed hold. Existing full lifecycle test uses actual `_lifecycle`, `_advance_position`, `_segment_exit`, durable book and economic replay over virtual authoritative observations through the 24-hour maximum. Core four-hour hold and hard-risk exceptions have frozen-policy boundary coverage. No directional partial-harvest policy applies.
- Ramses: native `test_ramses_strategy`, `test_ramses_connected_lifecycle`, native ledger/crash suites; canonical `test_continuity_state`, `test_position_continuation`. Existing controller tests enforce seven-day maximum and frozen 210-second recenter deadline; repeated whole-runtime recenter across restarts remains a Phase-D integration proof. No directional partial-harvest policy applies.
- Portfolio: canonical `test_certification`, `test_prospective_acceptance`, `test_terminal_reconciliation`, `test_directional_accounting`. One Pump sleeve and one Pons sleeve have concurrent reservation, no-capital-creation, attribution and restart checks. Existing directional concurrency test proves the shared implementation with Pump identity; add Pons identity only if native binding coverage proves insufficient.

## Open gaps and bounded next work

1. Both native Survivor steps can starve candidate retirement when discovery hits the full hot set. Old production steps fail the new bounded History(capacity=1) regression. Scheduling repair now composes into the declared runtime overlays and passes; position management already ran before discovery.
2. Both Survivor schedulers hard-code six hours despite the frozen approved four-hour minimum. Old native boundary regressions fail at 14,400 seconds; repaired runtimes pass. Pons also retains runtime turnover divisor 40 where the approved policy specifies 30; its native capacity regression fails. Repaired runtimes now bind to existing policy fields without changing policy hashes.
3. Native reconstruction → features → qualification now passes for both Survivors, including reopen and sticky-continuity rejection. Close acquisition/discovery composition with authoritative input fixtures, preserving venue and native-quote exclusions. Do not replace this with another direct feature-dictionary qualification test.
4. Existing within-process restart/book tests do not prove all durable state survives a normal workflow boundary. Normal campaigns create fresh prepared lanes; unfilled Survivor history needs continuity across their four-hour approved minimum age. Audit source-watermark catch-up and candidate retirement at bounded capacity.
5. Reuse the existing position continuation and Git StateStore machinery. Prove normal successor and position-only dispatch contracts against the actual workflows, including durable intent, exact SHA/manifest, availability, overlap/duplicate rejection, and review gates.
6. Phase D must join repeated windows, archive/cleanup, candidate/position state, crash boundaries and provider recovery in an accelerated multi-day production soak. Standalone unit successes do not close that gate.

## Current verification

On the Phase-A candidate checkout, 38 canonical production conformance/Survivor/accounting/continuity tests passed using prepared native lanes. No provider calls or market workflows were used. Prepared native lanes still contain parked scheduling prototypes and need final manifest composition before certification.

Fresh declared-overlay preparation and source-integrity verification pass for all four lanes. Forty focused canonical native conformance/worker-policy/Survivor/accounting tests pass on those fresh lanes. Policies and approved base source/execution SHAs are unchanged.

Current Pons restart was reproduced BROKEN after a real partial exit: its native book survived but controller state did not. Atomic state/resume and crash regressions now pass in the prepared-lane prototype. Keep BROKEN until cohort and workflow continuation are connected and verified.
