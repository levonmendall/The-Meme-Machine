# Pump Expanded Market Research v2

**Status: COMPLETE — COMPRESSION BREAKOUT IDENTIFIED; SHADOW ONLY**

The retained Pons reset-recovery v2 strategy remains unchanged and reserved for later implementation.

This study returns to Pump with the same breadth used for Pons, but does not force the Pons reset thesis onto Pump.

CoinGecko currently defines its Pump.fun Ecosystem category as tokens launched via pump.fun. The category currently spans established liquid names and extreme recent breakouts, which permits a three-part test:

1. established development;
2. established holdout;
3. separate recent-breakout stress cohort.

Only public market data is used.

# What was tested

Four price-path hypotheses were swept broadly:

- simple strength continuation;
- reset/recovery;
- impulse -> pullback -> reclaim;
- compression -> breakout.

Results:

| Hypothesis | Result |
|---|---|
| Simple strength | only one established robust setting; failed recent-breakout stress |
| Reset/recovery | 0 robust established configurations |
| Pullback/reclaim | 0 robust established configurations |
| Compression breakout | **6 robust established configurations and survives current stress** |

So there **is** a similarly quantified Pump opportunity, but it is not Pons-style reset-recovery.

# Pump compression breakout

The recurring market structure is:

**tight base -> early breakout -> short economic lifecycle**

The stable parameter neighborhood is approximately:

- base lookback: 3–5 public observations;
- central candidate: **5 observations** (~7h at this public sampling);
- base range: **<=5%**;
- breakout above base high: **2.5% to 7.5%**;
- avoid chasing larger extension;
- short lifecycle.

A broad entry/exit sweep tested 9,360 eligible configurations. Sixty were robust across the established development and holdout samples.

Every established robust configuration used a **6-hour maximum hold**.

The balanced cross-regime candidate is:

- 5-observation compressed base;
- base range <=5%;
- breakout 2.5–7.5%;
- hard stop **-2.5%**;
- target **+10%**;
- maximum hold **6 hours**.

## Results

| Sample | Gross equal-asset mean | After 0.75% stress | After 1% stress |
|---|---:|---:|---:|
| Development | +1.36% | +0.61% | +0.36% |
| Holdout | +1.15% | +0.40% | +0.15% |
| Recent-breakout stress | +2.43% | +1.68% | +1.43% |

The recent-breakout stress result is not caused by baton or the most extreme winner: baton did not qualify under this balanced rule.

Qualifying recent-breakout asset means:

- Codec Flow: -2.50%
- apeonfone: +10.00%
- OTC: +1.67%
- Fwog: +1.33%
- Alon: +1.62%

Four of five are positive.

## Why not use the spectacular recent-market settings?

The newer breakout cohort alone strongly favored wider +15% targets and looser stops.

Those configurations were forced back through the established development sample and failed there.

They are therefore rejected as current-regime chasing rather than frozen as policy.

This is important: the selected candidate deliberately sacrifices headline return to preserve cross-regime stability.

# Comparison with Pons

Pons reset-recovery remains the stronger opportunity.

After a 1% research haircut:

- Pons reset: roughly +1.40% / +1.95% / +1.93% across development / holdout / current.
- Pump compression breakout: roughly +0.36% / +0.15% / +1.43%.

Pump therefore has a positive signal, but its margin is much thinner and much more sensitive to real transaction costs.

That is why the Pump candidate remains shadow-only until exact PumpSwap PAPER quotes/costs prove that the residual edge survives.

# Strategy relationship

This is **not primarily a Pump Current strategy**.

The public universe is post-launch and most closely represents the post-migration PumpSwap market. The structure also resembles the existing Pump Survivor thesis: base/compression plus breakout.

The research therefore suggests a future:

**Fast Pump Survivor / Compression Breakout subregime**

rather than another generic Pump momentum add-on.

The likely value is tighter selection and a much shorter economic lifecycle than the existing multi-day Survivor runner.

# Frozen shadow shape

- base: ~5 observations
- compression: <=5%
- breakout: 2.5–7.5%
- stop: -2.5%
- target: +10%
- max hold: 6h
- full existing Pump lineage, liquidity, breadth, concentration, creator safety, execution capacity and stress gates remain mandatory

No allocation authority is granted.

No Stage-E, runtime, workflow or active strategy policy is changed.
