# Directional Realized-Equity Sizing v1 — isolated preparation

Status: **PREPARED ONLY — NOT ACTIVE**

Parent preparation:

- branch: `strategy/directional-opportunity-preservation-prep-20261001`
- commit: `76e5bfb96b73e2d1e56f3b8bb3d127b7d2bb4065`

This layer follows the prepared capital-parity, exit-optimization, and directional-opportunity-preservation work. It does not modify the active Stage-E lineage.

## New sizing rule

For Pump Current, Pump Survivor, Pons Current, and Pons Survivor:

```
realized_equity = immutable_genesis_sleeve_capital + reconciled_realized_pnl
target = floor(max(realized_equity, 0) * 500 / 10000)
```

The target is therefore **5% of current realized sleeve equity**, not 5% of the original sleeve forever.

The target remains only an upper bound. The actual reservation/fill is still limited by available sleeve capital and the strategy's existing turnover, independent-demand, depth, execution-stress, breadth-retention, freshness, generation, concentration and creator/distribution controls.

## What counts as equity

Included:

- immutable sleeve genesis capital;
- durable realized P&L already reconciled into the shared sleeve.

Excluded:

- unrealized gains or losses from open positions;
- mark-to-market estimates;
- hypothetical exits;
- shadow/marginal-reject outcomes;
- profits not yet acknowledged by native terminal accounting.

Held/open capital remains part of realized equity but reduces **available** capital, so it cannot be allocated twice.

If realized equity is zero or negative, no new directional entry is permitted.

## Compounding behavior

Using USD-equivalent values only as an illustration:

| Realized sleeve equity | 5% target |
| ---: | ---: |
| $125.00 | $6.25 |
| $150.00 | $7.50 |
| $187.50 | $9.375 |
| $100.00 | $5.00 |
| $250.00 | $12.50 |

This works in both directions. Durable profits increase the next target; durable losses reduce it.

Pump and Pons compound **independently**. This change does not rebalance money between sleeves and does not introduce cross-sleeve borrowing. The four-lane genesis allocation remains auditable and immutable.

## Minimum sizing

- Pump Current: preserve existing gas/entry-overhead semantics.
- Pump Survivor: preserve the existing gas-based minimum.
- Pons Current: preserve existing execution, impact and demand sizing caps.
- Pons Survivor: the existing 5 bps minimum-capital floor should use the same realized-equity basis as the 500 bps target.

## Shared implementation requirement

Final implementation should expose one deterministic shared sizing primitive from the directional sleeve authority, returning at least:

- genesis capital;
- reconciled realized P&L;
- realized equity;
- currently held/reserved capital;
- currently available capital;
- requested target bps;
- raw target;
- allocatable target.

All four directional regimes must use that primitive. No regime may maintain its own competing notion of compounded equity.

## Required proofs

Before promotion:

1. $125 realized equity produces a $6.25-equivalent 5% target.
2. Durable profit to $150 realized equity produces $7.50.
3. Durable loss to $100 realized equity produces $5.00.
4. An unrealized open-position gain does not change the next target.
5. Restart/replay reconstructs exactly the same realized equity and target.
6. Held capital can constrain allocation below 5% but never increases it.
7. Turnover/depth/stress/breadth controls can only downsize the target.
8. Current and Survivor cannot double-spend a family sleeve.
9. Zero/negative realized equity fails closed for new directional entries.

## Stage-E isolation

No active Stage-E branch, candidate, workflow, diagnostic budget, or workload is modified or authorized.

This is a prepared post-Stage-E economic-policy layer only. It must be regenerated against the exact final machinery SHA, composed with the other prepared strategy layers, fully recertified non-market, and only then considered for PAPER market execution.

No live-money authority is introduced.
