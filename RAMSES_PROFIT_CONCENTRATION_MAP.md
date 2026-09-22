# Ramses Profit Concentration Map

**Status:** COMPLETE PRE-HOLDOUT PROFIT MAP / NO STRATEGY NOMINATION / HOLDOUT UNTOUCHED  
**Scope:** frozen Ramses history only; no market-wide recollection  
**Protected holdout:** not read

## Executive map

The Ramses money is not concentrated in one universal LP rule. It is concentrated in two very different economic modes:

1. **Large directional/inventory winners in specific pairs**, dominated by r33/SPY.
2. **Repeatable fee-driven USDG market-making by multi-action operators**, especially when entry activity is low, ranges are relatively wide, and positions are actively adjusted.

The earlier passive one-entry/one-exit studies mixed these together and therefore obscured where the money was actually being made.

## 1. Venue-wide owner/pool books

Using the already-collected owner/bin history, 500 closed pre-holdout owner/pool books were reconstructed.

- 500 closed books
- 218 owners
- 136 pools
- 300 multi-action books
- lower-bound cash-flow P&L: **+USD 236,495**
- gross positive P&L: **USD 659,582**
- losses: approximately **-USD 423,087**
- attributed LP fees, lower bound because some fee events lack a uniquely matched owner/bin version: **USD 190,975**
- residual P&L after attributed fees: **+USD 45,520**

Fee attribution is conservative. The median book matched roughly 83% of eligible fee events, so residual inventory P&L is an upper bound where fee attribution is incomplete.

## 2. Where the largest raw dollars are

### r33/SPY dominates absolute venue P&L

The largest single pool cluster is r33/SPY:

- 14 closed books in the leading r33/SPY pool
- 14 owners
- net lower-bound P&L: **+USD 300,697**
- win rate: **78.6%**
- median book return: **+6.0%**
- attributed LP fees: only **~USD 13,518**
- residual inventory/directional P&L: **~USD 287,179**

Across the r33/SPY symbol family, net P&L is roughly **+USD 300,825**.

This is not primarily a fee-harvesting edge. It is overwhelmingly an **inventory / asset-price move** captured while providing liquidity.

If r33/SPY is removed, the remaining 500-book universe becomes approximately **-USD 64,330 net**. This is why raw Ramses P&L must be decomposed before treating it as an LP strategy.

### Quote-asset split

| Quote | Books | Net P&L | Attributed fees | Residual inventory P&L | Win rate |
|---|---:|---:|---:|---:|---:|
| SPY | 17 | **+USD 300,906** | ~USD 13,529 | ~USD 287,377 | 82.4% |
| USDG | 455 | **+USD 72,842** | **~USD 165,884** | **~-USD 93,043** | 51.0% |
| WETH | 28 | **-USD 137,253** | ~USD 11,562 | ~-USD 148,814 | 32.1% |

Interpretation:

- **SPY-quoted profit is mostly directional inventory.**
- **USDG is where genuine LP fee economics are visible**, but inventory/adverse selection consumes a large portion of fees.
- **WETH-quoted books were poor in aggregate.**

## 3. The clearest repeatable LP edge: multi-action management

Across all quote assets:

| Management style | Books | Net P&L | Attributed fees | Residual inventory P&L |
|---|---:|---:|---:|---:|
| Multi-action with burn-to-mint adjustment within 1h | 177 | **+USD 284,236** | ~USD 127,343 | ~USD 156,893 |
| Multi-action without quick adjustment | 123 | **+USD 19,113** | ~USD 45,495 | ~-USD 26,382 |
| Simple one-mint / one-burn | 200 | **-USD 66,854** | ~USD 18,136 | ~-USD 84,991 |

The venue-wide distinction is not simply entry timing. **Active position management separates the profitable books from the passive books.**

### USDG only

The picture becomes much cleaner after removing the directional SPY effect:

| USDG management style | Books | Net P&L | Attributed fees | Residual inventory P&L |
|---|---:|---:|---:|---:|
| Multi-action with quick adjustment | 158 | **+USD 109,205** | **~USD 109,006** | ~USD 199 |
| Multi-action without quick adjustment | 109 | **+USD 29,556** | **~USD 39,020** | ~-USD 9,463 |
| Simple one-mint / one-burn | 188 | **-USD 65,919** | ~USD 17,859 | ~-USD 83,778 |

This is the strongest result in the entire profit map:

> **The actively managed USDG cohort is genuinely fee-driven.**

For the quick-adjustment cohort, attributed fees are almost identical to net P&L even though fee attribution is conservative. By contrast, static USDG positions earn fees but lose more through inventory/adverse selection.

## 4. Operator concentration

A frozen repeatability screen identified 12 profitable operators with:

- at least 3 closed books
- at least 3 distinct pools
- positive lower-bound aggregate P&L
- positive median book return
- at least 66.7% winning books

Those 12 operators account for:

- 59 books
- 40 pools
- **+USD 101,962 net P&L**
- **72.9% win rate**
- median book return around **+0.76%**

They are only **11.8% of books** but contribute about **43% of total venue net P&L**.

Their attributed fees are about **USD 53,483**, with about **USD 48,478 residual inventory P&L**.

This confirms that operator behavior matters independently of the pool regime.

## 5. USDG entry regime: quiet is genuinely important

For USDG books, first-entry activity in the prior 30 minutes maps strongly to realized P&L:

| Prior 30m swaps | Books | Net P&L | Attributed fees | Residual inventory P&L |
|---|---:|---:|---:|---:|
| 0-2 | 205 | **+USD 181,574** | ~USD 92,003 | ~USD 89,571 |
| 3-10 | 47 | **+USD 21,060** | ~USD 8,924 | ~USD 12,136 |
| 11-30 | 75 | **-USD 18,414** | ~USD 12,677 | ~-USD 31,091 |
| 31-100 | 93 | **-USD 59,076** | ~USD 39,795 | ~-USD 98,871 |
| >100 | 35 | **-USD 52,303** | ~USD 12,485 | ~-USD 64,787 |

This is broader and stronger than the old Quiet-Mint implementation:

> **Low pre-entry activity is a real profit concentration, but copying another LP's public-mint geometry was the wrong implementation.**

The signal survives; the old execution rule does not.

## 6. USDG geometry: money is in wider, balanced ranges

### First-mint width

| Width | Net P&L |
|---|---:|
| <=8 bins | -USD 249 |
| 9-16 | -USD 16,615 |
| 17-32 | -USD 35,867 |
| 33-64 | +USD 3,410 |
| 65-128 | **+USD 66,012** |
| >128 | **+USD 56,150** |

The active multi-action money is not concentrated in narrow ranges. It shifts strongly toward **65+ bin initial widths**.

### First-mint sidedness

| Sidedness | Net P&L | Attributed fees | Residual inventory P&L |
|---|---:|---:|---:|
| Two-sided | **+USD 145,862** | **~USD 118,748** | ~USD 27,114 |
| Y-only | +USD 14,484 | ~USD 19,153 | ~-USD 4,669 |
| X-only | **-USD 87,504** | ~USD 27,983 | ~-USD 115,487 |

The broad profit concentration is therefore **two-sided**, not directional X-only placement.

## 7. Bin-step regime

USDG books show a major concentration in the widest-fee-step pools:

| Bin step | Net P&L |
|---|---:|
| <=5 bps | -USD 186 |
| 6-10 bps | -USD 39,298 |
| 11-25 bps | -USD 1,821 |
| 26-50 bps | +USD 66 |
| 51-100 bps | -USD 12,284 |
| >100 bps | **+USD 126,365** |

Attributed fees in the >100 bps segment are roughly **USD 66,519**.

This does not prove that high bin step alone is sufficient. It does show that a large share of the successful actively managed USDG economics occurs in **high-bin-step / high-fee pools**.

## 8. Pool lifecycle stage

USDG P&L by pool age at book entry:

| Pool age | Net P&L |
|---|---:|
| <=1h | **+USD 54,017** |
| 1-6h | **+USD 15,965** |
| 6-24h | -USD 2,155 |
| 1-3d | **-USD 20,811** |
| 3-7d | +USD 1,675 |
| >7d | **+USD 24,150** |

There are two distinct profit zones:

1. **Launch / very early pools**
2. **Mature pools**

The weak middle is roughly the first 1-3 days after launch.

Launch alone is not enough: the prior operator study showed that all operators' launch books were much weaker than launch books managed by repeatably profitable operators.

## 9. Duration of actively managed USDG books

Book duration is not equivalent to a passive holding period because these books can rebalance internally.

| Closed-book duration | Net P&L |
|---|---:|
| <=1h | +USD 12,618 |
| 1-6h | **-USD 61,744** |
| 6-24h | +USD 8,394 |
| 1-3d | **+USD 48,272** |
| 3-7d | -USD 8,920 |
| >7d | **+USD 74,222** |

The money is therefore not concentrated in one fixed 24-72h passive hold. The profitable operator books often remain active longer while managing ranges internally.

## 10. Historical TVL / fee-density / volume map from the clean lifecycle sample

The 218 clean realized lifecycles are useful for historical TVL and activity measurements, even though they exclude much of the profitable multi-action behavior.

To preserve the protected holdout, only the 191 derivation+validation lifecycles were used here.

Aggregate result:

- deployed capital: ~USD 789,122
- net realized P&L: **-USD 68,507**
- aggregate return on deposits: **-8.68%**

No historical TVL band was positive in aggregate.

More importantly, high-activity / high-fee regimes were distinctly bad:

### Volume / TVL

- 30-100% trailing-hour volume/TVL: **~-USD 31,499**
- >100%: **~-USD 32,919**

### Fee / TVL

- 0.5-2% trailing-hour fees/TVL: **~-USD 31,482**
- >2%: **~-USD 33,007**

### Fee bps

- >50 bps trailing-hour fee intensity: **~-USD 67,233**

This confirms the earlier observation:

> **The hottest visible fee/volume pools are not where passive LP profits live.**

Fees are high precisely where inventory/adverse-selection risk is also high.

## 11. Top realized profit pools

Leading pool-level lower-bound P&L:

| Pool / symbol | Books | Net P&L |
|---|---:|---:|
| r33/SPY | 14 | **+USD 300,697** |
| RAM/USDG | 16 | **+USD 61,599** |
| MEME/USDG | 17 | **+USD 36,339** |
| CASHCAT/USDG | 8 | **+USD 35,222** |
| UBIK/USDG | 10 | **+USD 23,783** |
| FRONG/USDG | 25 | **+USD 22,655** |
| PONS/USDG | 4 | **+USD 10,867** |

The top r33/SPY result is primarily directional inventory appreciation. The USDG leaders are more relevant to repeatable LP economics.

## Bottom line

The Ramses profit map is now much simpler:

### Where the raw dollars are
- **r33/SPY and a few other highly directional inventory winners.**
- This is mostly price/inventory exposure, not LP fee alpha.

### Where the repeatable LP money is
- **USDG pools**
- **multi-action position management**
- especially books with **burn-to-mint/range adjustment**
- **low pre-entry activity**
- **two-sided placement**
- generally **wide ranges (65+ bins)**
- disproportionate profit in **>100 bps bin-step pools**
- strongest around **pool launch** and again in **mature pools**
- not in simple passive one-mint/one-burn LPs
- not in the hottest fee/volume windows

The economically important Ramses distinction is therefore:

> **Profitable Ramses LP behavior is active market making, not passive fee farming.**

The previous Quiet-Mint study correctly detected that quieter entry conditions matter, but it failed because it attempted to convert that signal into a passive public-mint-copying strategy. The actual money is being made by operators who actively manage inventory and ranges.
