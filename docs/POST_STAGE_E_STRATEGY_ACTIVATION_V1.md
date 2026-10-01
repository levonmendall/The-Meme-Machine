# Post-Stage-E Strategy Activation v1

Status: **READY — WAITING ONLY FOR AUTHORITATIVE GREEN STAGE-E SHA/TREE**

PAPER ONLY. This branch does not modify the Stage-E candidate, does not authorize
a workflow dispatch or market run, and grants no live-money authority.

The authoritative machine-readable release contract is:

`certification/strategy-prep/post-stage-e-strategy-activation-v1.json`

## The nine required ACTIVATE items

All nine are mandatory release items. An integration that omits any one of them
is **not** the intended post-E strategy.

| # | Strategy change | Frozen activation state |
|---|---|---|
| 1 | Directional capital parity | Pump Current, Pump Survivor, Pons Current and Pons Survivor each request 5% of family sleeve before downsizing |
| 2 | Realized-equity compounding | That 5% target compounds from durable reconciled family-sleeve realized equity; unrealized P&L has no authority |
| 3 | Pump Current exits | -8% stop; +15% first realization; sell 25%; 14% proportional pre-tail high-water price trail |
| 4 | Pons Current exits | -8% stop; +18% first realization; sell 25%; 12% normal trail; adverse flow at sells >=1.20x buys; two-confirmation soft deterioration |
| 5 | Current -> Survivor preservation | Rejection/timeout/cancel/close/no-fill cannot suppress later Survivor discovery; Survivor reevaluates independently |
| 6 | Right-tail trail | At 2x+ all four directional regimes retain 60% of peak accrued gain (40% accrued-gain giveback) |
| 7 | Current tail bridge | Proven Current winners can remain on the same lifecycle across the Survivor timing gap, up to 36h from original open |
| 8 | Staged winner scaling | One bounded add after 2x, first realization, 15m persistence, <=15% drawdown and full fresh requalification |
| 9 | Meteora exit optimization | 18%/82% adverse-flow hysteresis and three verified 300s collapse confirmations |

There are **no unresolved strategy/economic parameters** in these nine items.

## What "ready" means

The following are already frozen:

- economic thresholds;
- capital targets;
- compounding basis;
- first-realization amounts;
- normal trails;
- high-multiple trail formula;
- tail-bridge admission and maximum duration;
- scale trigger, confirmation interval, add size and total exposure ceiling;
- Current/Survivor identity and conflict semantics;
- Meteora hysteresis and collapse-confirmation values;
- required failure behavior;
- restart/replay invariants;
- exact deterministic boundary vectors;
- which older policy behavior is superseded by later layers.

The only values that cannot exist yet are the **authoritative final Stage-E SHA/tree**
and hashes mechanically regenerated from the final composed post-E bytes.

Those are not strategy decisions.

## Composition rule

Do **not** merge the prep branches directly into the green Stage-E branch.

After Stage E passes:

1. preserve/freeze the green E SHA, tree and evidence receipt;
2. create a new integration candidate from that exact SHA;
3. verify the expected six-regime + moderate-admission baseline;
4. regenerate/apply the nine-item semantic composition in the manifest's order;
5. regenerate all affected policy/source/runtime identities from the final bytes;
6. run the complete deterministic activation matrix;
7. run affected native/accounting/restart/provider suites;
8. run exact-SHA non-market certification;
9. only after that passes may the separately authorized PAPER smoke occur;
10. start fresh Pump/Pons/Meteora profitability cohorts.

The green E evidence remains immutable evidence for the machinery candidate. The
post-E strategy candidate receives its own exact identity and certification.

## Supersession rules that must not be missed

### Sizing

Directional capital parity defines **500 bps** for all four directional regimes.

Realized-equity compounding is the final sizing authority. A final implementation
must not leave any runtime path calculating 5% from fixed genesis capital when
the shared sleeve's realized-equity primitive is available.

### Pump Current trail

The old 14-return-point trail must not survive.

Below 2x, Pump uses a **14% proportional high-water price drawdown**.

At 2x+, the common right-tail rule takes over.

### Pons Current trail

Both Pons Current trail locations are covered:

- pre-graduation runner;
- post-graduation runner.

Below 2x they use the 12% normal trail. At 2x+, both use common tail mode.

### Survivors

Pump Survivor and Pons Survivor keep their existing pre-tail policies. At 2x+,
the shared Survivor risk path uses common tail mode.

The existing six-hour Survivor minimum is **not lowered** by the bridge.

### Scaling

Scaling is part of the right-tail activation package, not a free-standing second
position:

- one add only;
- +100% high-water trigger;
- first realization already committed;
- 900 seconds persistence;
- within 15% of high;
- full fresh requalification;
- add <= 2.5% of realized sleeve equity;
- add <= 50% of original committed basis;
- original + added committed basis <= 7.5% of realized sleeve equity;
- unrealized gains cannot fund it;
- original-entry high-water cannot reset.

## Release blocker rule

If any one of the nine items:

- is missing,
- has an unresolved parameter,
- fails its deterministic boundary test,
- changes Stage-E evidence in place,
- weakens PAPER-only authority,
- or cannot be reconciled under restart,

the post-E strategy candidate is **not ready for PAPER market smoke**.

This is the single intended release bundle for all nine ACTIVATE-labeled changes.
