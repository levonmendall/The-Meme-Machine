# Pons Expanded Market Research v2

**Status: COMPLETE — RESET-RECOVERY PRIORITIZED; SHADOW ONLY**

This study expands the Pons analysis substantially beyond the original 15% drawdown / 10% recovery proxy.

The current Pons V2 market is broad enough to support a better test: CoinGecko currently shows hundreds of Pons V2 coins, with active Pons-native names ranging from established names such as Harmonic Agent, Priors Agents, Orbio, NovaAI, ZZZ and Bundle Cat to newer names such as SCROOGE, HyperDex, OYSTER and Commander Vrax.

Only public market data is used.

## Three-sample design

To reduce overfitting, the study uses three separate groups:

1. **development** — first ~4 days of 11 Pons-native names with full seven-day public history;
2. **holdout** — final ~3 days of those same 11 names;
3. **current-market stress** — six shorter-history/newer Pons listings excluded from fitting.

A parameter does not count as robust merely because it fits the seven-day established cohort; it must also remain positive in the newer current-market stress set.

# Staged scaling

A large sweep tested 1,122 eligible combinations of:

- strength threshold;
- recent high/low lookbacks;
- one- vs two-observation confirmation;
- breakout extension cap;
- 3h/6h/12h continuation.

Only **2** parameterizations survived all three samples.

The best price-path observation candidate was roughly:

- +12.5% strength from recent low;
- break above the prior ~3 observations;
- recent-low window ~5 observations;
- maximum ~10% breakout extension;
- ~3h continuation horizon.

Equal-asset returns were approximately:

- development: +2.30%
- holdout: +3.67%
- current newer listings: +1.22%

This is positive, but narrow and much weaker in the current set.

An overlap study also shows staged scaling is not the main opportunity:

- established holdout reset-only events: about +5.76%
- established holdout scaling-only events: about +2.37%
- current reset-only events: about +5.07%
- current scaling-only events: about +1.28%

**Disposition: deprioritize staged scaling.** Keep collecting observations but do not freeze add size or total exposure.

# Reset-recovery

The reset sweep tested 2,391 eligible combinations spanning:

- 7.5–20% drawdown;
- 5–15% recovery;
- several trailing-high windows;
- stabilization gaps;
- optional extra breakout confirmation;
- 3h/6h/12h continuation.

Five parameterizations survived development, holdout and the newer-listing stress set.

All five shared the same important structure:

- **12.5% recovery confirmation**
- trailing-high lookback around **9 observations** (~12–13h at this public sampling)
- at least **3 observations of stabilization** between trough and entry
- **no additional breakout requirement**
- short **~3h continuation** tendency

The exact drawdown floor was much less important: robust variants existed from about 7.5% through 20%.

This says the edge is not "buy any 15% dip." It is:

> a meaningful reset, enough time for the low to hold, then a strong recovery that proves the market actually turned.

## Entry/exit optimization

A second sweep tested 14,928 entry/exit combinations.

Seven configurations remained positive after requiring a **1% stress haircut** in development, holdout and the current newer-listing set.

Every robust configuration capped recovery at **20%**. None of the 25%+, 30%+, 40%+ or uncapped recovery configurations survived. The edge disappears when the strategy chases a recovery too late.

Every robust configuration used a **6-hour maximum hold**. Neither 3h nor 12h exit families survived the stressed three-sample test.

The strongest balanced shadow candidate is:

### Entry

- prior reset: **at least 10%**
- recovery from trough: **12.5% to 20%**
- trailing high context: ~9 public observations
- trough must hold for at least **3 observations**
- no extra local breakout requirement
- entry no more than **5% above the pre-flush high**
- all non-price structural/safety/execution gates still required

### Provisional shadow exit

- hard stop: **-7.5%**
- take profit: **+15%**
- maximum hold: **6 hours**

## Robustness

Equal-asset mean results for that candidate:

| Sample | Gross | After 1% stress | After 2% stress |
|---|---:|---:|---:|
| Development | +2.40% | +1.40% | +0.40% |
| Holdout | +2.95% | +1.95% | +0.95% |
| Newer/current listings | +2.93% | +1.93% | +0.93% |

Leave-one-asset-out means remain positive in all three samples.

The current cohort is more dangerous, however:

- about 32% of sampled events reached +15%;
- about 53% reached the -7.5% stop;
- event-weighted current gross mean was only about **+1.17%**.

So this is an asymmetric strategy: many small losses, fewer large winners. It is not robust enough to trade merely from price-path conditions. The already-staged breadth/concentration/creator/liquidity/execution gates are essential and are expected to decide whether the theoretical edge survives actual PAPER execution.

A prior-24h trend filter was also tested. It did not improve all samples consistently enough to become a gate, so it remains telemetry only.

# Research decision

## Primary Pons opportunity

**Reset-recovery.**

Freeze the v2 shape for prospective shadow validation:

- >=10% reset
- 12.5–20% recovery
- 3-observation stabilization
- <=5% above pre-flush high
- -7.5% stop
- +15% TP
- 6h max hold
- full existing Pons structural/execution safety stack

## Secondary

**Staged scaling stays observation-only.**

Its best public price-path signal is real enough to keep measuring, but it is substantially less attractive than reset-recovery in the currently observed Pons market.

## Authority

This package grants **zero allocation authority**.

No Stage-E source, runtime, workflow or active strategy policy changes.
