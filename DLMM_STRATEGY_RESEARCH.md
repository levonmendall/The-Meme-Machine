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

## Active-pool experiment

The active continuation changed candidate discovery only:

1. official Meteora Data API current `volume_30m` ranking for discovery;
2. SOL/WSOL and supported metadata screen;
3. one finalized mint-account batch to cheaply remove unsupported token programs/authorities;
4. complete PR #4 finalized pool/bin revalidation for every survivor;
5. separate finalized warmup interval;
6. only a verified nonzero warmup may select the predeclared `sdk_bidask`, 8-bin research variant;
7. later verified outcome interval for counterfactual P&L.

Physical `getTransaction` reads were batched without changing logical request counts, complete signature coverage, ordering, supported-event identity or terminal-state equality.

### Provider/ranking proof

Meteora activity discovery succeeded and repeatedly surfaced current supported high-activity candidates. Finalized on-chain revalidation admitted examples including STONK-SOL, USELESS-SOL, JUP-SOL and CARDS-SOL while rejecting unsupported Token-2022/authority/freeze candidates. A finalized mint prefilter reduced the successful 6-second run to **34 logical RPC calls, zero provider failures and zero retries**.

That 6-second run verified complete warmup/outcome intervals for USELESS-SOL and CARDS-SOL, but both intervals had zero supported swaps. No strategy was selected; the shadow grid again produced approximately -35 bps solely from the unchanged cost hurdle. STONK-SOL contained an unsupported non-swap pool mutation and was correctly excluded.

### Bounded-max 12-second result

Authoritative active test workflow: `35262612233`, exact execution head `1f3f728947cca41e1c6b973b2d112a34649a26ed`.

Three current activity-ranked pools passed finalized structural validation, but none produced a complete interval eligible for strategy selection:

- **STONK-SOL**: warmup exceeded the unchanged `MAX_TRANSACTIONS=16` evidence bound (`dlmm_transaction_bound`).
- **USELESS-SOL**: the later interval ended with `last_update` state movement not explained by the supported swap-only reconstruction (`dlmm_terminal_state_disagrees_with_forward_reconstruction:last_update`).
- **CARDS-SOL**: the later interval contained a pool transaction outside the current assumption of exactly one supported exact-input swap per transaction (`dlmm_requires_one_exact_input_swap_per_transaction`).

The run completed with no weakened evidence predicate. `opportunity_count=0`, `selected_trade_count=0`, `nonempty_warmup_count=0`, `nonempty_outcome_count=0`, and the conclusion remains `insufficient_active_point_in_time_sample`.

This is not evidence that the proposed BidAsk strategy is unprofitable. It establishes a narrower engineering/research boundary: **the pools active enough to matter currently exercise a richer Meteora mutation/transaction surface than PR #4's deliberately narrow swap-only tape supports.** Point-in-time strategy profitability cannot be evaluated honestly on those intervals until that authentic current behavior is interpreted and terminal-state-verified rather than discarded or inferred.

Allocation authority remains disabled. No P&L, strategy ranking or repeatability claim may be derived from rejected active intervals.
