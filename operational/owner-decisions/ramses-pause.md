# Ramses operational pause

Status: **PAUSED — MARKET_OPPORTUNITY_INSUFFICIENT**

Owner decision date: 2026-10-07

Ramses is removed from the live PAPER supervisor launch/restart set. Its strategy code,
policy, tests, accounting identity, historical evidence, and state are preserved unchanged.
The pause is reversible and is not a strategy-failure classification.

## Runtime behavior

- Live PAPER launches Pump, Pons, and Meteora only.
- Ramses health remains explicit as `PAUSED`; the lane does not disappear from four-lane accounting.
- Ramses discovery, candidate hydration, position management, and new capital allocation are not launched.
- Startup fails closed if Ramses has an active position, reservation, or pending native delivery, so pausing cannot strand economic state.
- Acceptance/recovery excludes the paused Ramses process from process-restart requirements while preserving portfolio reconciliation and historical attribution.
- Offline/archive fixtures retain Ramses so its historical and recovery evidence stays testable.

## Scope

No Ramses strategy economics are changed. Pump, Pons, Meteora, the nine approved strategy changes, the $500 inception policy, and shared-capital isolation are unchanged.

## Reactivation

Reactivation requires an explicit owner decision after new Robinhood DLMM evidence shows enough opportunity to justify Ramses provider, hydration, and operating complexity.
