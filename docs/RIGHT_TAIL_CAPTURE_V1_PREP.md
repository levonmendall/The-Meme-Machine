# Right-Tail Capture v1 — isolated strategy preparation

Status: **PREPARED ONLY — NOT ACTIVE**

PAPER ONLY. No signer, submission, live-money authority, workflow dispatch, market run, or Stage-E candidate change is introduced by this branch.

## Objective

Preserve the Meme Machine's exposure to rare 5x–50x directional winners without weakening the controls that reject the much larger failed-token population.

This layer addresses three specific right-tail defects:

1. Pump Current's fixed return-point trail becomes mechanically tighter as a winner gets larger.
2. Current positions can be forced flat minutes after entry even though measured right-tail peaks often occur hours later and Survivor cannot enter until six hours after migration/graduation.
3. Staged winner scaling had safe machinery semantics but no frozen economics.

The authoritative machine-readable contract is `certification/strategy-prep/right-tail-capture-v1.json`. The external calibration record is `certification/strategy-prep/right-tail-market-evidence-20261001.json`.

## 1. Pump Current trail repair

Below a +100% high-water mark, Pump Current uses a **14% proportional high-water price drawdown**, not a 14-return-point subtraction.

At +100% high-water and above, all four directional runners enter the same bounded tail mode:

```
exit when current_gain <= 60% of peak_gain
```

Equivalently, the runner may give back 40% of accrued gain from the original entry reference.

Examples:

| Observed peak | Tail exit level | Peak-to-exit price drawdown |
| ---: | ---: | ---: |
| 2x | 1.6x | 20.0% |
| 5x | 3.4x | 32.0% |
| 10x | 6.4x | 36.0% |
| 25x | 15.4x | 38.4% |
| 50x | 30.4x | 39.2% |

This fixes the high-multiple pathology in which a fixed 14-point return giveback would require only about a 2.8% price decline at 5x, 1.4% at 10x, 0.56% at 25x and 0.28% at 50x.

The trail is not the only exit. Creator/distribution failure, invalid exit liquidity, lineage/integrity failure, generation/freshness failure, confirmed persistent demand deterioration and an already-durable full-exit intent retain priority.

## 2. Current tail bridge

The six-hour Survivor minimum remains unchanged.

Blindly lowering it would be the wrong response: the external migration record is overwhelmingly populated by failures. Instead, when a normal Current timeout arrives, an already-proven winner may transition to `tail_bridge` on the **same native lifecycle**.

Bridge requirements:

- the first 25% realization is already committed;
- high-water return reached at least +50%;
- current after-cost return remains positive;
- state/generation and an executable exit quote are fresh;
- canonical lineage/venue is intact;
- creator/distribution, concentration and exit-liquidity safety pass;
- persistent confirmed demand failure has not occurred;
- no irreversible full-exit intent exists.

If any requirement fails, the existing Current timeout behavior remains.

The bridge may remain open for at most **36 hours from the original open time**. It creates no new entry, reservation or capital. It does not sell and rebuy. Open time, high-water, realization state, stop state and deterioration state all survive the transition.

Survivor may continue observing the asset. The shared sleeve must reject a same-asset Survivor fill while the bridged Current position remains open. After the bridge is terminal, Survivor remains free to qualify independently under its existing rules.

## 3. Staged winner scaling

One scale event is permitted per lifecycle after calibration:

- peak/high-water must have reached at least **+100% (2x)**;
- first realization must already be committed;
- at least **15 minutes** must pass after the first 2x crossing;
- current price must remain within **15% of the high**;
- the position must still be profitable after costs;
- the strategy must freshly requalify;
- independent demand must freshly confirm;
- all existing generation, freshness, quote, turnover/depth, 1x/2x stress, breadth-retention, concentration, creator/distribution and available-capital checks remain binding.

The add is:

```
min(
  2.5% of reconciled realized family-sleeve equity,
  50% of the original committed basis,
  currently available sleeve capital,
  all existing execution/capacity downsize caps
)
```

There is at most one add. Original plus added committed basis may never exceed 7.5% of realized sleeve equity.

Unrealized profit is not spendable capital. A partial, nonterminal profit does not enlarge the sizing basis. A failed add leaves the original lifecycle unchanged.

The tail high-water remains anchored to the **original entry reference**, not the blended post-add basis. Scaling therefore cannot make the position appear safer by resetting its risk state.

## Why these values

The external evidence does not justify simply widening every stop.

Pump CTO timing data updated 2026-10-01 shows a small but useful timing sample in which the median peak arrived about seven hours after detection and one-third of measured winners were still making highs after 24 hours. The same source's broad migration record, however, shows 92% of 8,050 migrations at 20% of migration price or lower on the later reading. That combination supports conditional continuity for proven winners, not blind migration holding.

On Robinhood Chain, the September 13 snapshot included four Pons V2 Dex top-ten movers at 7–24 hours old, including Milk Frog at +2,423% in a seven-hour-old pool. A contemporaneous DexScreener snapshot of Milk Frog showed +1,126% over 24h while the rolling 1h and 6h changes were -42.46% and -58.04%, respectively. Rolling windows are not an exact peak-to-trough reconstruction, but they demonstrate that right-tail Pons assets can remain extraordinarily volatile.

The 40% accrued-gain giveback is deliberately bounded. It is wide enough to stop the trail from becoming absurdly tight at high multiples, but it does not attempt to survive every 40–60% collapse. Survivor and the separately staged reset-recovery research remain the recovery mechanisms after a true tail exit.

The single 2.5%-of-sleeve add is likewise bounded. Scaling amplifies a winner only after 2x proof and persistence; base runner retention does not depend on scaling.

## Structural right-tail checks

With the prepared 5% initial sleeve target and a 25% first realization, a Pump Current runner using the new tail mode would, before costs/slippage beyond the strategy's return representation, convert these peak observations into approximately:

| Peak observed | Tail exit | Approx. total portfolio NAV gain, no add | With one full 2.5%-sleeve add at 2x |
| ---: | ---: | ---: | ---: |
| 2x | 1.6x | +0.61% | +0.48% |
| 5x | 3.4x | +2.30% | +2.73% |
| 10x | 6.4x | +5.11% | +6.48% |
| 25x | 15.4x | +13.55% | +17.73% |
| 50x | 30.4x | +27.61% | +36.48% |

The 2x case exposes the intended scaling cost: if the add occurs and the asset immediately exhausts the new tail allowance, the add loses money while the original trade remains profitable. Scaling is therefore an amplifier with a bounded false-positive cost, not a free improvement.

These figures assume a full 5% family-sleeve initial fill and a 25% portfolio sleeve. Capacity and execution controls can downsize actual deployment.

## Promotion requirements

Do not compose this into the active Stage-E/F/G candidate.

After final machinery certification:

1. regenerate this layer against the exact final machinery SHA;
2. compose the prior six-regime, moderate-admission, capital-parity, exit-optimization, opportunity-preservation and realized-equity-sizing layers first;
3. retain the staged-scaling safety machinery, then apply these frozen economics;
4. implement the Current tail-bridge state on the existing native lifecycle;
5. regenerate affected policy/runtime hashes;
6. run exact boundary tests for proportional Pump trailing and 2x/5x/10x/25x/50x tail mode;
7. run same-lifecycle bridge, restart/replay, Survivor-conflict and terminal-accounting proofs;
8. run scale idempotency, basis, capacity and no-risk-reset proofs;
9. run exact-SHA non-market certification;
10. begin a fresh affected Pump/Pons profitability cohort because exposure duration and sizing economics changed.

No part of this document grants live-money authority.
