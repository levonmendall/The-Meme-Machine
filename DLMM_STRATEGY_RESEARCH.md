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

Workflow `35262612233`, execution head `1f3f728947cca41e1c6b973b2d112a34649a26ed`, established three distinct evidence gaps without weakening any predicate:

- **STONK-SOL** exceeded `MAX_TRANSACTIONS=16` in the monolithic warmup.
- **USELESS-SOL** exposed a `last_update` terminal mismatch.
- **CARDS-SOL** exposed more than one current exact-input swap surface inside a transaction.

No P&L was inferred from those rejected intervals.

## Narrow evidence/replay extension

The continuation keeps `MAX_TRANSACTIONS=16`, the `sdk_bidask`/8-bin selected strategy, the nonzero-warmup gate and the 350,000-lamport cost hurdle unchanged.

Implemented evidence-layer changes:

- Authenticate and replay multiple exact-input Meteora swaps inside one transaction in actual top-level/inner-instruction execution order, with durable per-swap cursors `[slot, transactionIndex, swapIndex]`.
- Preserve the pinned IDL rule that `lb_pair` is account zero for both `swap` and `swap2`; a routed transaction may contain authenticated swaps for other Meteora pools, which are ignored only when the target pool is absent from that instruction/event. A target pool appearing in any wrong IDL position remains rejected.
- Break dense observation windows into sequential independently verified chunks. Every chunk still has a complete signature census, `MAX_TRANSACTIONS<=16`, ordered transaction evidence, supported mutation identities and exact terminal-state equality before it can chain into the next chunk.
- Correct the replay model's `last_update` semantics. The pinned Meteora SDK/commons `updateReference(s)` logic reads `last_update_timestamp` for volatility-reference decay but does not overwrite it for each swap. Finalized STONK and USELESS evidence likewise showed the field remaining unchanged across authenticated swaps. `dlmm.swap()` therefore now preserves the authoritative field rather than inventing a swap-time update. A real unexplained terminal change remains fail-closed.

Workflow `35264407618` proved that 2-second chunking admits dense STONK activity without raising bounds: six warmup chunks reconstructed **4 authenticated swaps** with zero provider failures/retries. A later diagnostic run proved the prior outcome identity rejection came from a `swap` whose 18-account list contained the target STONK pool in **no position**; it was an unrelated Meteora pool swap in the same routed transaction, not a malformed STONK instruction. The parser now filters that unrelated invocation/event by authenticated pool identity while retaining strict target-pool account-zero validation.

The next workflow reruns the exact same 12-second top-active experiment against these evidence-only repairs. Allocation authority remains disabled. No strategy, sizing, cost, entry threshold or portfolio authority changes are part of this extension.
