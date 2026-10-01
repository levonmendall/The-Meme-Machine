# Public-Market 48-Hour Research — Staged Scaling + Reset-Recovery

**Status: COMPLETE MARKET RESEARCH — NO PROMOTION**

Window: approximately **2026-09-29 19:05 UTC through 2026-10-01 19:05 UTC**.

This research follows the owner's explicit constraint: **market data only**.

No Meme Machine runtime evidence, historical trades, rejected-winner artifacts, candidate rows, fills, or internal outcome records were used. No Alchemy/private-provider data was used.

## Dataset

The sample contains 14 publicly tracked assets:

**Pump.fun ecosystem:** Fartcoin, pippin, The Black Bull, STONKS PARK, Yippee, HypurrClaw.

**Pons / Robinhood public-market sample:** PONS, Bundle Cat, Orbio.so, ubik, Thinking Cat, Longbow, MUSHROOM, ZZZ.

Public CoinGecko 7-day charts were restricted to the final 48 hours and split chronologically:

- first 24h: development/calibration;
- second 24h: untouched holdout.

The chart feed is downsampled to roughly 85-minute observations, so this is a **market-path study**, not transaction-level execution replay.

## 48-hour market paths

The sample contained both continuation and collapse regimes. Examples:

- STONKS PARK: +34.8% over 48h, but a 41.9% peak-to-trough drawdown.
- Yippee: -28.6%, with a 41.4% drawdown.
- Thinking Cat: +32.3%, with only ~10.7% maximum drawdown.
- Orbio.so: +15.1%, with ~20% drawdown.
- Bundle Cat: -21.2%, with ~30.4% drawdown.
- MUSHROOM: -43.9%, with ~45.8% drawdown.

That dispersion is useful for testing whether "add on strength" or "buy recovery after flush" survives a changed market regime.

# 1. Staged winner scaling

## Method

A price-only proxy scale event fires when price:

1. breaks above its recent local high; and
2. has gained at least X% from the rolling roughly-six-hour low.

Tested X = 5%, 10%, 15%, 20%.

After a trigger, 12-hour forward return/MFE/MAE were measured. Signals were spaced at least six hours apart.

This does **not** reproduce Current/Survivor qualification. It tests only whether buying additional exposure after observed strength had favorable subsequent market behavior.

## Development result

The +10% proxy looked best among rules with a minimally useful count:

- n = 5
- mean forward return: +5.07%
- median: +8.41%
- win rate: 60%
- median MAE: -4.90%

But the family split was unstable:

- Pump: n=3, mean +12.03%, 100% positive.
- Pons/Robinhood: n=2, mean -5.36%, 0% positive.

Pump's positive development observations were concentrated in STONKS PARK and HypurrClaw, both extremely small/low-current-volume markets.

## Holdout result

The +10% rule was frozen from development and applied unchanged:

- n = 9
- mean forward return: **-1.75%**
- median: +0.42%
- win rate: 55.6%
- median MAE: -4.45%

Family split:

- Pump: n=2, mean **-2.69%**
- Pons/Robinhood: n=7, mean **-1.48%**

The two Pump holdout events were in STONKS PARK and Yippee. Both had current 24-hour volume below $100k; after excluding such very-low-volume markets there were **zero Pump holdout scale events**.

### Staged-scaling decision

**Do not freeze a trigger, add size, or total-position ceiling from these 48 hours.**

The development-day uplift did not generalize. Staged scaling should remain prepared/shadow-only.

The sample also suggests a future Pump scaling rule may differ from a Pons scaling rule rather than forcing one shared trigger.

# 2. Reset-recovery

## Method

Price-only reset rules swept:

- drawdown from trailing ~12h high: 15%, 20%, 25%, 30%, 35%;
- recovery from a prior trough: 5%, 10%, 15%;
- the trough had to precede the trigger by at least two downsampled observations;
- 12h forward return/MFE/MAE measured after recovery.

This is deliberately less permissive than simply "buy a dip," but it still lacks breadth, concentration, creator safety, depth and VWAP evidence.

## Development result

The strongest development proxy was a 20% drawdown followed by 15% recovery:

- n = 2
- mean 12h forward return: +28.21%
- 100% positive

However, **both observations were STONKS PARK**. They are not independent assets, and STONKS PARK had only about $75k current 24h volume.

## Holdout result

The exact 20%/15% rule occurred **zero times** in the holdout.

Looser rules did occur, and they were not encouraging:

- 15% drawdown + 5% recovery: holdout n=2, mean **-5.0%**, 0% positive (Longbow, MUSHROOM).
- 20% drawdown + 5% recovery: holdout n=1, **-9.6%** (MUSHROOM).

### Reset-recovery decision

**The thesis remains plausible, but no threshold should be frozen.**

The development half demonstrates that sharp flush/recovery sequences can contain substantial follow-through. The holdout shows that a visually similar recovery can also be only a temporary bounce inside a continuing decline.

That is exactly why the future strategy needs the structural evidence already specified—liquidity retention, concentration trajectory, selling exhaustion, independent demand and recovery-reference proof—rather than a price-only drawdown/rebound rule.

# What this research changes

Nothing active.

- Staged winner scaling remains **prepared, shadow-only**.
- Reset-recovery remains **research-only**.
- No parameters are promoted.
- No allocation authority is added.
- No Stage-E code/workflow/candidate is touched.
- No market workload is dispatched.

## Next research step

Use the same methodology unchanged on additional daily holdouts. Do **not** refit the trigger grid every day.

If a stable price-path effect emerges across independent assets and market regimes, then freeze candidate economic parameters and let the finished PAPER runtime test the missing execution/breadth/concentration/safety dimensions.

Forty-eight hours is useful calibration evidence. It is not enough for profitability certification.
