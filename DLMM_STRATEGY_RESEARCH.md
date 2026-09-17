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

A single pilot cannot establish repeatability. `repeatability_sample_adequate` remains false until at least 200 point-in-time opportunities across 20 pools exist. Prospective allocation remains disabled regardless of research outcome.

## Pilot 1 result — structural pools

Workflow `35259863580` produced **6 verified point-in-time opportunities across 2 validated pools**, but all warmup and outcome intervals contained zero supported swaps. Every strategy therefore earned zero fees; fixed costs dominated. The best observed result was `foundation_spot`, width 2, at approximately **-35.0002 bps** per 0.1-SOL experiment.

This proved only that structural eligibility without contemporaneous trading flow is insufficient.

## Active-pool continuation

The current continuation changes candidate discovery only:

1. use the official Meteora Data API current `volume_30m` ranking as a discovery source;
2. require a SOL/WSOL pair and supported pool metadata;
3. prefilter non-SOL mint accounts in one finalized read to remove unsupported token-program/authority candidates without spending repeated pool-snapshot calls;
4. independently re-read and validate every surviving pool/bin state from finalized Solana accounts;
5. observe a separate finalized warmup interval;
6. only a verified nonzero warmup may select the predeclared `sdk_bidask`, 8-bin research variant;
7. evaluate that selection and the unchanged shadow grid on a later verified outcome interval.

The public-RPC path remains bounded. `getTransaction` evidence is physically batched but consumes the same logical request budget and still requires complete signature coverage, unique transaction ordering, supported swap identity, and terminal-state equality. Unsupported or rate-limited intervals are excluded rather than inferred.

Prior active-pool attempts identified STONK-SOL, JUP-SOL and CARDS-SOL as current high-activity pools that can pass the supported finalized structural subset. The first attempts were blocked by public Solana RPC transaction-history rate/errors; CARDS additionally exhibited terminal state movement not explained by the supported swap-only tape and correctly failed closed. No P&L inference was made from those failed intervals.
