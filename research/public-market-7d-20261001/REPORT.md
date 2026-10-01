# Seven-Day Public-Market Extension — Staged Scaling + Reset-Recovery

**Status: COMPLETE EXTENDED MARKET RESEARCH**

Window: approximately **September 24, 2026 12:00 PM PT through October 1, 2026 12:05 PM PT**.

This extends the previous 48-hour study to the full seven-day public CoinGecko window, the longest available range that preserves useful intraday path resolution (roughly 85-minute observations). Public market data only was used.

CoinGecko defines its Pump.fun Ecosystem category as tokens launched through pump.fun. The robustness cohort deliberately emphasizes the higher-volume names from that category rather than the tiny STONKS/Yippee/HypurrClaw markets that drove parts of the first 48-hour result.

For Pons, the robustness cohort uses public names visible on Pons V2 DEX with enough seven-day chart history: Bundle Cat, Orbio.so, ZZZ, Harmonic Agent, Priors Agents and NovaAI. Commander Vrax did not have enough comparable chart history.

# Staged scaling

## Pump

The expanded higher-volume Pump.fun cohort **rejects the simple price-strength scaling hypothesis**.

At +10% strength/local-breakout:

- 8 events
- 3 independent assets
- 5 days
- mean subsequent 12h return: **-3.80%**
- equal-asset mean: **-6.28%**
- approximate asset-level interval: **[-11.75%, -0.81%]**
- zero positive assets.

At +15% the result is even worse:

- mean: **-7.22%**
- equal-asset mean: **-9.17%**
- interval: **[-17.23%, -1.10%]**
- zero positive assets/days.

The earlier positive Pump evidence was therefore microcap-driven and does not survive a higher-volume robustness cohort.

**Decision: do not parameterize Pump staged scaling.**

Keep only the generic lifecycle machinery concept. Any future Pump add-to-winner thesis would need additional non-price evidence and a new validation study.

## Pons

Pons is materially different.

A +5% recent-low strength signal combined with a local breakout produced:

- 59 events
- 6 Pons V2 names
- all 7 days
- event-weighted mean subsequent 12h return: **+7.91%**
- equal-asset mean: **+6.67%**
- approximate asset interval: **[+0.82%, +12.52%]**
- 5 of 6 assets positive on average
- 6 of 7 days positive on average.

Most importantly, dropping any single asset leaves the equal-asset mean positive, ranging from **+4.56% to +8.25%**.

Higher +10/+15/+20% triggers have positive raw returns but their asset intervals cross zero.

**Research decision: freeze +5% strength plus local breakout as a Pons-specific provisional SHADOW trigger.**

This does **not** set the amount to add. Add size and maximum total exposure remain unset because public market data cannot reconstruct the actual open-position basis, executable quote, turnover/depth, or after-cost position risk.

# Reset-recovery

## Pump

The Pump signal disappears after removing the low-volume microcap dependence.

In the higher-volume Pump.fun cohort:

- 15% drawdown / 5% recovery produced only one event (NEET), returning about **-6.3%** over the following 12h.
- 15%/10% and stronger reset confirmations produced no useful repeated sample.

The prior STONKS PARK rebounds are real market paths, but they are not enough to define a Pump strategy.

**Decision: no Pump reset threshold freeze.**

## Pons

Pons reset-recovery is the strongest result in the extended study.

The 15% drawdown / 10% recovery shape produced:

- **28 events**
- **4 independent Pons V2 assets**
- occurrences across **all 7 days**
- event-weighted 12h mean: **+6.96%**
- equal-asset mean: **+9.71%**
- approximate asset interval: **[+2.75%, +16.66%]**
- **4/4 assets positive on average**.

Asset means:

- Bundle Cat: +14.38%
- Orbio.so: +16.99%
- Harmonic Agent: +2.20%
- Priors Agents: +5.26%

The result is not dependent on one winner: dropping any single asset leaves the equal-asset mean between **+7.28% and +12.21%**.

Neighboring parameter shapes also remain positive:

- 15% / 5%: equal-asset mean +7.82%, interval [+2.18%, +13.45%]
- 15% / 15%: +8.31%, interval [+0.95%, +15.68%]
- 20% / 5%: +6.50%, interval [+0.24%, +12.76%]
- 20% / 10%: +7.34%, interval [+0.87%, +13.80%]

20% / 15% loses the positive interval, suggesting waiting for an extremely deep reset plus an extremely large recovery may enter too late.

**Research decision: freeze 15% drawdown / 10% recovery as the provisional Pons reset-recovery SHADOW shape.**

It remains incomplete without the structural gates already staged:

- retained executable liquidity;
- safe concentration trajectory;
- creator/distribution safety;
- selling exhaustion;
- independent demand recovery;
- recovery-reference proof;
- turnover/depth;
- 1x/2x execution stress;
- freshness/generation.

Those gates are not optional. The daily result was negative on three of seven days, so 15%/10% is a candidate-shape detector, not an unconditional dip-buy rule.

# What is now conclusive

Within the limits of public price-path research:

1. **Do not activate simple Pump staged scaling.**
2. **Do not freeze Pump reset-recovery thresholds.**
3. **Pons staged scaling has enough repeated evidence to use +5% strength/local breakout as a provisional shadow trigger.**
4. **Pons reset-recovery has enough repeated evidence to freeze a provisional 15% flush / 10% recovery shadow shape.**

This is conclusive for **research triage and shadow parameterization**.

It is **not** profitability certification and does not grant PAPER allocation. Public market charts do not prove the buyer breadth, concentration, creator safety, exact depth, execution cost, or actual open-position state required by the Meme Machine strategies.

No Stage-E or active runtime work is changed by this result.
