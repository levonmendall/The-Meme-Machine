# DLMM point-in-time strategy replay

Research branch only. Base is verified PR #4 head `1ef599b49cb411ed4c238ec08be83ce9c0986cda`.

This experiment does not alter `dlmm_allocation_enabled`, Store authority, Pump/PumpSwap policy, signing, submission, deployment, or live-money capability.

The live experiment uses separate finalized intervals:

1. a warmup interval observed before entry to compute only contemporaneously available regime features;
2. a later outcome interval replayed through PR #4's verified integer bin/swap/fee mechanics.

The fixed strategy grid is declared before outcome collection:

- PR #4 generalized one-sided `foundation_spot`;
- pinned-SDK one-sided `BidAsk` weighting;
- widths 2, 4, 8, 16, and 32 bins;
- 0.1 SOL virtual capital;
- unchanged 350,000-lamport modeled entry+exit cost hurdle;
- exact virtual withdrawal and residual-token liquidation back to SOL.

Current live pilot is bounded to at most four pools, three warmup/outcome cycles, 18 seconds per interval, one public read-only RPC budget, and no paid data source. Unsupported or incomplete intervals are excluded rather than inferred.

A single pilot cannot establish repeatability. `pilot_sample_adequate` requires at least 8 verified opportunities across 3 pools with 4 nonempty outcome intervals. `repeatability_sample_adequate` remains false until at least 200 point-in-time opportunities across 20 pools exist. Prospective allocation remains disabled regardless of either flag.

The live pilot is triggered only by the dedicated research workflow; ordinary Pump live diagnostics are suppressed on that trigger commit.

## Pilot 1 result

Exact research execution head: `17668ae637670c8b69df4b198b0b8e1b595d732a`.
Workflow: `35259863580` (`dlmm-strategy-research`), successful. The research-harness regressions and live finalized replay both passed and the report artifact was preserved for 30 days.

The bounded pilot produced **6 verified point-in-time opportunities across 2 validated pools**, but all six warmup intervals and all six outcome intervals contained **zero supported swaps**. There were no interval reconstruction errors and no provider failures/retries. Two additional discovered pools were correctly rejected for unsupported mint authority/freeze state.

Because observed turnover and fee density were zero, every tested strategy earned zero fees and no tested range was reached. With the unchanged 350,000-lamport modeled entry+exit cost, the best observed result was `foundation_spot`, width 2, at approximately **-35.0002 bps** per 0.1-SOL experiment (the extra 2 lamports are integer share rounding). Wider Spot and BidAsk variants were similarly negative from fixed costs plus rounding.

This is **not evidence that DLMM is unprofitable** and does not compare Spot versus BidAsk in an active regime. It proves a narrower point-in-time result: structural pool eligibility without contemporaneous flow is insufficient, and an entry selector must reject inactive/no-turnover regimes because fixed costs dominate before any fee opportunity exists.

Current conclusion: `insufficient_point_in_time_sample_for_pilot`. `pilot_sample_adequate=false`; `repeatability_sample_adequate=false`; allocation authority remains disabled.

The next research iteration should improve only candidate discovery, not the verified simulator: source current high-activity SOL-paired DLMM candidates from a read-only activity index (prefer the official Meteora Data API if accessible), then independently revalidate every candidate on finalized chain state before the same warmup -> entry -> outcome replay. Do not use current activity metrics as historical outcome data and do not grant allocation authority.
