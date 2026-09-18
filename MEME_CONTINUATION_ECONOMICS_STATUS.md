# Meme continuation economic-ranking split

Branch: `research/meme-continuation-expected-value-v1`

This branch is research-only and is stacked on the current market-native opportunity
outcome study. The active `continuation-v1` policy, thresholds, sizing, exits, and
paper execution are unchanged.

## What changed

A second **economic shadow ordering** is now computed for policy-feasible Pump
candidates using only finalized information available at the decision timestamp.

The shadow features include:

- 10s / 30s / 60s gross buy, gross sell and net buy flow;
- recent unique buyer/seller breadth;
- buy-share and sell-pressure;
- short-horizon net-flow acceleration;
- recent-buyer acceleration versus the preceding 20 seconds;
- point-in-time price change / positive extension.

The existing policy-feasibility prioritizer still determines which candidate receives
scarce live qualification evidence. The new economic ordering has **no order
authority**.

## Forward comparison

The existing opportunity-outcome study now tags every feasible candidate with its
point-in-time economic features and adds an `economic_shadow_selected` cohort. It
records how often that shadow choice differs from the current policy-budget choice.

Both cohorts continue to receive the same forward outcome labeling. This creates the
data needed to test whether economic ranking improves 60s/300s/900s returns, +15%
tail frequency, MFE/MAE and post-exit upside before any active prioritizer is changed.

## Frozen boundaries

- no `Engine.qualify` change;
- no threshold change;
- 10 SOL liquidity minimum unchanged;
- 3 independent buyers unchanged;
- 1 SOL independent net-buy minimum unchanged;
- 100-event trading cap unchanged;
- +15% / -10% / timeout exits unchanged;
- no Fomo or DLMM authority;
- no live money, signing or transaction submission.

The shadow ordering is deliberately not called an expected-return model yet. It must
first demonstrate incremental forward economic value on an unbiased sample.
