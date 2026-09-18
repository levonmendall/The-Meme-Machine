# continuation-v1-robinhood unbiased natural sample — latency-repaired rerun

## Frozen policy

Policy: `continuation-v1-robinhood`

Policy hash:
`f363c234daa549365ca00ee5b33247deb1c591a1084b991263233ba9f3870e36`

The policy hash is identical to the first unbiased sample. No strategy threshold,
translation value, selection rule, or five-second state-freshness gate changed.

Frozen gates:
- >=3 independent buyer groups
- <=35% top-five concentration
- <=120% price extension
- <=5% modeled round-trip loss
- <=100 evidence events
- +15% take profit
- -10% risk exit
- 900-second timeout
- 10 SOL-equivalent real liquidity = 0.429742223375869849 ETH
- 1 SOL-equivalent independent net buy = 0.042974222337586985 ETH

## Latency repair

The first sample required 19–33 seconds (median 22) to assemble a complete vector
because every candidate performed roughly 60 serial historical `eth_getLogs` calls
plus serial receipt/header reconstruction.

The repair changes acquisition only:
- continuously warm the global Pons CurveBuy/CurveSell tape for >60 seconds before enrollment;
- use that already-collected point-in-time tape instead of rescanning candidate history;
- authenticate current candidate state in bounded JSON-RPC batches;
- batch receipt/header authentication for prior-window events;
- batch exact holder-balance verification;
- run exact concentration reconstruction in parallel with market-window authentication;
- keep logical RPC budgets, exact evidence, provider failure behavior, and the
  five-second freshness rule unchanged.

No strategy logic changed.

## Exact optimized rerun

GitHub Actions run:
`35392529357`

Artifact:
`10565519564`

Artifact SHA256:
`cfc713ab5907a4fa745f4ae9ba57bfa513d2ecfe3fd73b9171935179fc49ee15`

Elapsed: **156.59 seconds**.

Warm tape:
- 64 seconds of chain-time coverage;
- 883 authentic CurveBuy/CurveSell logs collected before enrollment.

Selection rule remained:
`first_previously_unseen_authentic_current_pons_v2_buy_after_prior_enrollment_attempt`.

No candidate was reranked, replaced, or selected using its outcome.

## Rerun result

- natural enrollments: **19**
- fully evaluated: **11**
- acquisition-incomplete: **8**
- complete frozen-policy vectors: **10**
- decision-eligible complete vectors under the unchanged 5-second gate: **10 / 10**
- live-qualified frozen-policy vectors: **1**
- evidence-capacity rejection: **1**

Complete-vector state ages:
`[2, 2, 2, 5, 2, 2, 5, 2, 2, 2]` seconds.

Evaluation latency:
- median: **1.59 seconds**
- maximum: **4.00 seconds**

Candidate authentication median:
- approximately **0.59 seconds**

Provider transport usage for evaluated rows:
- median: **8 transport requests per candidate**
- prior complete-vector median: **121 transport requests per candidate**

This closes the proven evidence-acquisition latency blocker without weakening
freshness or strategy rules.

## Frozen strategy rejection counts

Across the rerun vectors:
- modeled round-trip cost: **8**
- independent demand: **7**
- translated minimum real liquidity: **3**
- concentration: **1**
- evidence capacity: **1**

Multiple reasons can apply to the same vector.

## Genuine frozen-policy qualifier

One natural candidate passed every frozen continuation-v1-robinhood gate while the
complete evidence bundle was still current:

- token:
  `0x5b5f72fd56ea273f603f4c68ca6ac89842692aaa`
- curve:
  `0x740e1ade8c93bf79dc8b367252d36d5b48c63624`
- source transaction:
  `0x53d7a040252028896281de65eb19745f4919b78694fd0cb6c0607e58c8741e2a`
- source block: `66517648`
- complete evidence age: **5 seconds**
- concentration: **12.41%**
- real quote liquidity:
  `0.839048410250868462 ETH`
- evidence events: **95**
- independent buyer groups: **5**
- independent net buy:
  `0.102585276480156894 ETH`
- price extension: **105.06%**
- modeled round-trip loss: **2.99%**
- all frozen rejections: **none**

This is the first genuinely decision-eligible natural Robinhood candidate observed
under the frozen Solana-translated strategy.

## Exact +60-second marks

The optimized run produced **9 exact +60-second executable marks** rather than the
67–350 second delayed marks from the original runner.

For the single frozen-policy qualifier:
- exact +60s gross return: **-16.53%**
- exact +60s net return after modeled gas: **-16.66%**

This is one qualified observation, not enough to estimate expected value or justify a
strategy change. It is retained without filtering because the sample is outcome-blind.

Across the exact +60s marks with complete net accounting, 1 was positive and 7 were
negative; those rows include candidates that failed the frozen strategy and therefore
are not a qualified-strategy performance estimate.

## Acquisition-incomplete rows

Eight enrollments failed before full evaluation:
- six: `invalid_current_snipe_bps`
- two: non-native Pons quote token outside the frozen ETH-translation scope

They remain in the unbiased enrollment record and were not replaced.

## Current conclusion

The original operational blocker is repaired:
**complete Robinhood continuation-v1 evidence can now be assembled inside the
unchanged five-second gate.**

The sample has also now produced one genuine natural frozen-policy qualifier.

What is not established:
- profitability or expected value;
- enough qualified observations to change or validate the strategy;
- authority to alter any threshold;
- ordinary Robinhood paper allocation.

Next research should continue the **same frozen sample** until there is a meaningful
qualified cohort and evaluate its exact forward outcomes. Do not change thresholds
based on the current single qualified observation.
