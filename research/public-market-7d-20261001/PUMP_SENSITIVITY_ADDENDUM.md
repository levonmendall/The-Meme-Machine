# Pump Parameter Sensitivity Addendum

## Answer

**Yes — the original Pump research grid was too aggressive to fully represent the higher-volume Pump market.**

That matters most for reset-recovery. Starting the reset grid at a 15% drawdown meant that the liquid Pump.fun cohort produced almost no repeated candidates. The earlier dramatic Pump rebounds were therefore heavily influenced by very small, highly volatile names.

However, a much wider Pump-only sensitivity test does **not** reveal a strong hidden strategy that the original grid simply missed.

## Wider staged-scaling test

The expanded grid tested:

- strength from recent low: 2.5%, 5%, 7.5%, 10%, 12.5%, 15%;
- several short local-high and local-low lookbacks;
- 6h, 12h and 24h forward horizons;
- first ~4 days for development and last ~3 days for holdout.

For the original 5%+ region, **no adequately sampled configuration had positive equal-asset means in both development and holdout**.

The only robust configuration in the entire expanded grid was much shallower:

- +2.5% strength;
- short local breakout;
- 6-hour forward horizon.

Its equal-asset return was only about **+0.09% in development and +1.06% in holdout**.

That is far smaller than the Pons effect and small enough that exact fees, slippage, execution stress and stricter strategy qualification could erase it.

### Revised scaling conclusion

The original +5% minimum was somewhat too high for liquid Pump names, but broadening the grid does **not** justify Pump staged-scaling allocation or a frozen shadow trigger.

## Wider reset-recovery test

The expanded Pump reset grid tested:

- drawdown: 5%, 7.5%, 10%, 12.5%, 15%, 20%, 25%;
- recovery: 3%, 5%, 7.5%, 10%, 12.5%, 15%;
- multiple trailing-high windows;
- one- and two-observation stabilization gaps;
- 6h, 12h and 24h forward horizons.

This confirms that the original 15% minimum was too high.

The only repeated region with any cross-sample stability was approximately:

**5% drawdown -> 3% recovery -> short (~6h) horizon**

Two closely related configurations survived the development/holdout filter. Their equal-asset results were roughly:

- development: **+0.37% to +0.63%**
- holdout: **+1.69% to +2.05%**

But only **2 of 54** adequately sampled 5%-drawdown configurations were positive in both halves. That is not a broad stable parameter neighborhood.

### Revised reset conclusion

Pump reset-recovery should not be described as disproven.

It should be described as:

> **The original deep-flush hypothesis was poorly matched to higher-volume Pump assets. A shallow, short-cycle recovery hypothesis remains plausible but unvalidated.**

No trading threshold should be frozen from this evidence.

## Why Pump and Pons looked so different

The contrast is less mysterious after this sensitivity analysis.

1. Pons V2 assets in the seven-day sample repeatedly produced 15-20% flush/recovery structures. Higher-volume Pump.fun assets generally did not.
2. The dramatic Pump examples in the first study were tiny volatile markets; removing those names materially changes the result.
3. Pons reset-recovery is explicitly post-graduation and the public Pons V2 universe is well aligned with that research question.
4. Public listed Pump.fun ecosystem coins are mature survivors; they are not a faithful representation of the Pump Current late-curve/newborn universe.
5. Therefore Pump and Pons should not share one reset/scaling parameter family.

## Research state

- Pump staged scaling: **no parameter freeze**
- Pump reset-recovery: **reframe toward shallow-reset research; no parameter freeze**
- Pons provisional shadow findings: **unchanged**
- Allocation authority: **none**
- Stage E/runtime changes: **none**
