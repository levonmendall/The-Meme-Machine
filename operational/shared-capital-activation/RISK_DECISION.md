# Fixed caps — OWNER APPROVED, not deployed

The owner explicitly answered **"Approve these fixed caps"** in this task.
The authority and exact configuration are recorded in `OWNER_APPROVAL.json`.
`risk-policy.proposed.json` retains its original review filename and is now the
approved configuration for a future verified cutover. Its SHA-256 under the existing canonical policy
schema is `e87385900145e53956df18956ee2390f0d95787e6ffc44243251f9b147eb65f2`.

| Limit | Feature illustration | Approved | Consequence at $500 inception |
|---|---:|---:|---|
| Portfolio gross risk exposure | 90% | 75% | $375 maximum new-risk exposure |
| Each active family | 65% | 45% | $225; both regimes compete inside this ceiling |
| Each active regime, fixed soft budget | 50% base / 60% maximum | 30% base and maximum | $150; no cash is held for unused budget |
| Each canonical asset / lineage | 15% | 2.5% | $12.50; same-family overlapping lifecycles remain prohibited |
| Solana / Robinhood group | 70% each | 45% each | $225 per network, including actual holds |
| Crypto correlation / directional group | 85% / 80% | 75% each | $375 aggregate, includes both families |
| Cash floor for new risk | None | 10% of conservative risk base | $50; a ceiling, not a durable cash reservation |
| Transaction cost floor for new risk | None | $5 | Additional floor; actual fee/settlement commitments counted separately |
| Drawdown stops new risk | 20% | 10% | Restrict new entries/adds; preserve exits and settlement |
| Adaptive allocation | False | False | No changing multipliers or performance fitting |
| Position sizing basis | Family equivalence | Family equivalence | Native 5% remains $6.25 at $125 family equity |

Risk exposure uses the greater of remaining basis and fresh net mark, plus
actual reservations/commitments and possible capitalized entry costs. Losses
reduce the risk base; unrealized gains do not compound sizing or create cash.
Missing/expired portfolio marks deny new risk, independently of native safety
management. Funding obligations and protected commitments retain priority.

Native contracts still limit an add to the single eligible winner addition,
2.5% realized family-equivalent equity, half original basis, and 7.5% original
plus added basis. All original timing, realization, lineage, execution and
safety gates apply. Concentration caps may deny an otherwise eligible add,
especially when a right-tail winner's marked exposure already exceeds the
asset ceiling. Existing positions are never forcibly sold to restore a budget.

The four original family inception records remain $125. Sharing the $500 cash
authority does not redistribute family equity, P&L or sizing genesis. At zero
fees/marks equal basis, a family can fund 36 $6.25 positions instead of 20,
one regime can fund 24, and the portfolio can fund 60. Actual native fee,
valuation and concentration constraints can reduce those counts. Paused
Meteora/Ramses requests are rejected before competition; their schema entries
are one basis point solely because the existing schema requires positive
entries. They do not create workers, cash holds, or usable admission rights.

Measured isolated four-regime pressure funded $375, left $125 actual free cash,
and denied four additional qualified requests at the correlation/portfolio
ceiling. Thus idle paused-family cash is eligible without targeting maximum
deployment. Controlled tape returns are scripted accounting comparisons and
are not profit forecasts.

Approval covers this exact numeric configuration only. Live cutover remains
conditional on verified recovery/backup, authentic provider proof, unchanged
epoch/obligations, exclusive authority installation, and the existing acceptance
contracts. No illustrative defaults may be activated silently.
