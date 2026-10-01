# Staged Winner Scaling v1 — implementation contract

This is a future implementation contract, not an active patch.

## Native lifecycle changes

The final composed runtime should add one deterministic scale transition to the existing directional native books. The event must contain:

- lifecycle ID;
- strategy/regime;
- scale sequence;
- decision generation;
- decision timestamp;
- added quantity;
- added basis;
- fees/gas;
- pre-add aggregate quantity/basis;
- post-add aggregate quantity/basis;
- exact quote/capacity evidence;
- policy identity.

Repeated delivery of the same scale sequence must be idempotent. A conflicting duplicate must fail closed.

## Shared sleeve changes

The directional sleeve authority needs an incremental reservation operation bound to an existing filled lifecycle. It must:

1. prove the lifecycle already owns the original reservation/exposure;
2. prove the incremental amount is available;
3. hold the increment before native commit;
4. atomically acknowledge the increment after native commit;
5. release only the increment on proven commit failure;
6. survive restart without duplicating or losing the incremental hold.

## Risk replay

Risk replay must consume scale events without resetting:

- opened_at;
- high-water return / high timestamp;
- first-realization state;
- tightened-trail state;
- deterioration streak;
- last observation;
- irreversible pending exit.

The v1 choice is frozen: right-tail return/high-water is measured from the **original entry reference** and cannot be reset or diluted by an added lot. Aggregate and lot-level basis remain authoritative for economic accounting, but not for resetting tail risk state.

## Current-regime integration

Pump Current and Pons Current must request scale authority through the same shared sizing/capacity path used for entry. They may not bypass Current fill-time freshness, generation, quote, turnover, impact or breadth checks.

## Survivor integration

Pump Survivor and Pons Survivor use the same scale transition but retain their strategy-owned requalification and risk policies. Scaling does not create a new Survivor regime and does not bypass same-asset shared-sleeve fencing.

## Portfolio accounting

Use the existing same-lifecycle basis-add/rebalance accounting boundary rather than creating a new position/trade identity. Native provenance remains authoritative.

## Forbidden shortcuts

- no second synthetic position to represent the added lot;
- no resetting the stop/high-water clock;
- no use of unrealized gains as spendable capital;
- no scale after exit intent;
- no scale because price alone rose;
- no provider work solely for research instrumentation on the decision critical path;
- no Stage-E integration.
