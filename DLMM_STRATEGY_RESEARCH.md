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
