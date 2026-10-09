# Pons held-position efficiency: offline partial implementation

Disposition: **IMPLEMENTED_PARTIAL / EVENT_DRIVEN_SAVINGS_NOT_PROVEN**.

Branch: engineering/pons-held-efficiency-20261009
Parent: inactive exceptional-winner candidate 743dcd9df2902941d3f3d6e4204d15f7469bba79.

No deployment, merge, provider calls, funding, host service, change to the $500 epoch, or position/holding-policy activation. Pump optimizations retained; Ramses and Meteora remain paused.

## Implemented

1. **Survivor head reuse.** A successful exact-quantity, canonical V4 exit quote already has an authenticated block number and hash. The immediately subsequent history read now uses this same head if it is under five seconds old, is at or after durable PonsHistory, and matches the saved hash at the same height. Incremental history still verifies numeric canonical membership. Failed, stale or inconsistent quotes retain the original latest-head request.
2. **Current V4 head reuse.** Current already reads the head each five-second turn. It now passes that authenticated head to the same-turn V4 marking quote. Reuse is limited to heads at most three seconds old, with a hard five-second total acquisition limit. The native exact-quantity simulation, code/manager checks, gas, numerical post-read membership, exit settlement and other quote paths retain their prior semantics. Invalid/stale shared headers fall back to a fresh head.
3. **Offline held-event classifier.** Pool-specific PoolManager Swap, ModifyLiquidity, Donate and protocol fee events, Pons hook fee/control events and global configuration events wake a fresh quote. Unknown events wake. Other pools can be classified separately but are never evidence of interval completeness.
4. **Fail-closed quote-wakeup scheduler.** The pure planner requires complete canonical manager/hook/token state coverage, exact quantity and identity, proven gas/fee bounds, distant protective thresholds, and no pending execution, scale, requalification or renewal. Incomplete evidence requires a quote. A quiet tick cannot publish a new P&L/HWM mark or execute with a stale quote. The original 3s/5s safety tick is not changed.
5. Authored focused offline unit tests and added them to the FAST/OPERATIONAL registry.

## Bounded modeled savings from head reuse only

Using frozen 20 modeled CU per redundant header and $0.525 per million CU:
- Survivor, 72h / 3s: up to 86,400 avoided calls, 1.728M CU, **$0.9072**.
- Current, 36h / 5s: up to 25,920 avoided calls, 0.5184M CU, **$0.27216**.
- Current, counterfactual 72h / 5s: up to 51,840 avoided calls, 1.0368M CU, **$0.54432**.

These are ceilings assuming every reuse succeeds and the old request was actually billed; they are NOT observed savings or proof of invoice reduction.

## Not implemented or activated

- There is **no authenticated completeness producer** for the event-wake planner yet. Public scout messages, a silent WebSocket and historical price alone cannot seal absent economic and hook events, forks or fee/token changes. Consequently the event-based plan does NOT skip any production quotes today. The $0.53-$4.91 previous event-driven scenarios remain hypothetical.
- The original inactive 36h Current / 72h Survivor exceptional-winner renewal rules, organic demand and historical requirements are unchanged. A price-only renewal is a material policy change and must be separately reviewed before it can replace those rules.
- No quoter code/manager identity is assumed immutable across blocks, and no widened provider log entitlement is assumed verified.
- The existing quote/fee/creator-safety semantics and full fresh execution requirements are retained. A V4 hook return delta makes a raw spot or Swap log insufficient as an exact sell quote.
- No authorization for provider observations, larger resource limits, production startup, deployment, CAPACITY, AUTONOMY or real-money operations.

## Next technical blockers

A. Produce canonical, sealed, gap-recoverable manager and Pons-hook event intervals, including all global fee controls and token state changes, on the existing authenticated provider without new services or unwanted duplication.

B. Prove event-delivery equivalence against independent native logs/receipts in empty, busy, reconnect, fork, fee-change and failure fixtures. No auto-renewal or successful empty-interval inference from a silent feed.

C. Integrate quote wake decisions into each Pons management loop while preserving original protective cadence, fresh exact-quantity exit attempts, partials, high-water and native journal/accounting. Prove a quiet tick never advances economic marks and any uncertainty forces a new quote.

D. Independently review an inactive price-first extended-winner policy. Retain resource sufficiency, positive net profit, working exits and native accounting; explicitly evaluate what is lost when demand-based protective exits are suppressed.

E. Run offline affected quote, native-book, Current, Survivor, provider-governor, and exceptional-winner regressions; only then request a separately authorized bounded provider observation measuring full billable RPC, WS bytes, tail latencies and multi-position throughput.

## Validation status

Focused new tests are authored at tests/test_pons_held_quote_wakeup.py, registered in operational/tests.py. **They have not been executed.** GitHub connector permits file/commit changes but no local clone or remote test execution is available in this session. No passing test result, provider cost reduction or production readiness is claimed. The original baseline tests were not rerun.
