# Solana Skilled-Wallet Alpha Research — Robustness Findings

Research only. No strategy, sizing, qualification, or execution authority.

## Frozen cohort

The current historical study uses the exact 20-wallet cohort frozen from run `35301582766`:

- 30-day ROI leaderboard
- minimum 10 qualifying Pump.fun early-buyer tokens
- bots excluded
- 10/20 also present in the 7-day top-100 ROI cohort

The cohort must not be changed based on downstream outcomes.

## Completed historical study

Run: `35304557419`

- 84 Shrine archive hours
- 416 independent cohort wallet buys
- 389 records with usable forward outcomes
- 161 paired 15-second-entry / 5-minute comparisons
- 109 wallet×mint clusters
- 103 unique mints in the paired 5-minute sample
- 10 wallets represented in the paired 5-minute sample

### Primary single-control result

15-second delayed entry, 5-minute outcome:

- target mean return: +2.27%
- matched-control mean return: -10.87%
- mean edge: +13.14 percentage points
- median edge: -0.11 pp
- 76 target beats vs 85 losses
- sign-test p=0.529
- raw bootstrap 95% interval for mean edge: +0.56 to +27.90 pp

This is not evidence of broad positive median alpha. The mean is strongly right-tailed.

## Heavy-tail stress test

For the 161 paired 5-minute observations:

- largest positive edge contributes 12.6% of all positive edge
- top 3 contribute 32.7%
- top 5 contribute 46.6%
- top 10 contribute 66.6%
- top 20 contribute 83.4%

Mint clustering reduces the apparent mean:

- event-level mean edge: +13.14 pp
- unique-mint mean edge: +8.88 pp
- unique-mint median edge: -0.93 pp
- unique-mint positive/negative count: 49 / 54
- exact sign p≈0.694

Therefore repeated participation in the same winning mint contributes to the event-level mean and must not be treated as independent evidence.

## Right-tail enrichment

In the paired 5-minute sample:

| Threshold | Skilled-wallet token | Control |
|---|---:|---:|
| >= +10% | 14.3% | 13.7% |
| >= +25% | 9.9% | 8.1% |
| >= +50% | 7.45% | 3.73% |
| >= +100% | 6.21% | 2.48% |

The >=50% and >=100% rates are roughly doubled, but discordant-pair tests are not yet significant because the number of tail events is small.

## Temporal robustness

The paired sample was split chronologically at its median timestamp without changing any thresholds.

Early half (n=81):
- mean edge: +5.74 pp
- median edge: -0.18 pp
- >=+50%: 6.17% target vs 3.70% control
- >=+100%: 4.94% target vs 2.47% control

Late half (n=80):
- mean edge: +20.62 pp
- median edge: +0.56 pp
- >=+50%: 8.75% target vs 3.75% control
- >=+100%: 7.50% target vs 2.50% control

The right-tail enrichment has the same direction in both halves. This is encouraging but remains small-count evidence.

## Wallet-ranking relationship

Historical ROI rank does not monotonically predict forward edge in this sample.

Event-level Spearman tests:

- 30-day rank vs 5-minute edge: rho≈+0.077, p≈0.331
- 30-day ROI vs 5-minute edge: rho≈-0.077, p≈0.331
- 30-day win rate vs edge: rho≈+0.010, p≈0.898
- token count vs edge: rho≈-0.097, p≈0.220

The current leaderboard score should therefore not be treated as a direct copy-weight.

## Control-quality issue

Several of the largest event-level edges combine:

- a genuine target moonshot, and/or
- a single matched control that subsequently loses 60–100%.

This makes a one-control counterfactual too noisy for decision use.

## Pre-registered next test

Run `solana-skilled-wallet-robust-counterfactual` on the exact frozen cohort.

For each wallet buy:

1. select up to 12 contemporaneous controls;
2. require same protocol and quote asset;
3. match only on pre-buy information:
   - market cap,
   - prior 5-minute return,
   - 5-minute volume,
   - trade count,
   - token age where known;
4. exclude controls receiving a frozen-cohort buy within +/-15 minutes;
5. require at least 3 controls;
6. use the median control outcome, not one control;
7. primary specification:
   - +15-second entry,
   - +5-minute outcome,
   - match distance <=2.0;
8. report sensitivity at distance <=1.0 / 1.5 / 2.0 / 2.5 / 3.0;
9. report:
   - mean edge,
   - median edge,
   - 5% and 10% trimmed means,
   - +/-50 pp winsorized mean,
   - sign test,
   - wallet clustering,
   - wallet×mint clustering,
   - +10/+25/+50/+100% tail enrichment.

No subgroup discovered in this sample may become a strategy threshold without a fresh prospective sample.

## Current interpretation

The evidence does not support indiscriminate copying of high-ROI wallets.

It does support continued testing of a narrower hypothesis:

> previously successful wallets may enrich the probability of rare extreme upside events even when their median follower trade is near zero or negative.

That hypothesis remains research-only until it survives robust multi-control and frozen prospective validation.
