# Staged Winner Scaling v1 — isolated preparation

Status: **PREPARED ONLY — NOT ACTIVE**

Parent: `f41c7348054eac59d18488ee83688559c6a40d1f`

This layer stages a bounded **add-to-winner** capability for Pump Current, Pump Survivor, Pons Current, and Pons Survivor. It is a position-lifecycle extension, not a new lane or independent entry strategy.

## What is frozen now

The safety semantics are frozen:

- the original position must already be valid, open, and reconciled;
- no averaging down;
- current after-cost return must be positive;
- the thesis must pass a fresh point-in-time requalification;
- fresh generation/state, quote, turnover/depth, 2x stress, breadth retention, concentration, creator/distribution and available-capital checks remain mandatory;
- a pending or irreversible full-exit intent blocks scaling;
- the add stays on the **same lifecycle identity**;
- the add cannot reset high-water, deterioration, realization, stop, or exit state;
- a failed add must leave the original position unchanged;
- shared Pump/Pons sleeve fencing remains authoritative.

## What is intentionally not frozen

No final value is set for:

- the return/proof trigger that arms a scale;
- the added-capital percentage;
- the maximum total position size;
- the exact lot-reduction rule used by later partial realizations.

Those economics require shadow evidence. This prevents hindsight-based sizing from becoming policy merely because the machinery can support it.

## Required accounting model

A scale-in must be an append-only event on the existing native lifecycle. It records the added lot separately while maintaining exact aggregate quantity and remaining basis.

The shared sleeve must increase its durable hold before the add commits. On a failed add, only the incremental reservation is released; the original position remains untouched.

The common portfolio layer must treat added basis as an extension of the same lifecycle, not as a second trade.

## Risk semantics

Scaling is not allowed to buy a falling position simply to improve average cost.

A scale signal may use fresh unrealized performance as evidence that the thesis strengthened, but **unrealized P&L never increases capital authority**. Added capital still comes from realized/reconciled sleeve equity under the prepared sizing rule.

Existing hard stops may not be widened because basis increased. Existing high-water and deterioration state survive the add. If a full-exit intent is already durable, scaling is forbidden.

## Research before economics

While allocation authority remains false, preserve scale-eligible observations and compare:

- unchanged no-add lifecycle;
- hypothetical bounded add;
- incremental fees/slippage;
- additional maximum drawdown;
- incremental terminal P&L.

Use 5m, 15m, 1h, 6h and terminal measurements where evidence exists.

## Stage-E isolation

No Stage-E candidate, branch, workflow, diagnostic budget or workload is modified.

No market run is authorized.

Final runtime work is post-E/F/G only, against the exact final machinery SHA, followed by deterministic recertification and a fresh PAPER profitability cohort.
