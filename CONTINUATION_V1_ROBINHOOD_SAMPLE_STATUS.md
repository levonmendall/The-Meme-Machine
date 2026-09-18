# continuation-v1-robinhood unbiased natural sample — 2026-09-18

## Frozen policy

Policy: `continuation-v1-robinhood`

Policy hash:
`f363c234daa549365ca00ee5b33247deb1c591a1084b991263233ba9f3870e36`

No threshold changed during or after this run.

Frozen dimensionless gates:
- >=3 independent buyer groups
- <=35% top-five concentration
- <=120% price extension
- <=5% modeled round-trip loss
- <=100 evidence events
- +15% take profit
- -10% risk exit
- 900-second timeout

Only the two SOL-denominated entry gates were translated before enrollment:
- 10 SOL minimum real liquidity -> 0.429742223375869849 ETH
- 1 SOL minimum independent net buy -> 0.042974222337586985 ETH

Translation snapshot:
- SOL/USD: 112.58
- ETH/USD: 2619.71
- source: CoinGecko spot snapshot captured before the sample

## Exact live run

GitHub Actions run:
`35385242146`

Artifact:
`10563828142`

Artifact SHA256:
`4432632068013420dd55187bd828496fe88332eb321240a2a3e1a01388ff7540`

Elapsed: 409.5 seconds.

Selection was outcome-blind and non-ranked:
`first_previously_unseen_authentic_current_pons_v2_buy_after_prior_enrollment_attempt`.

No candidate was reranked or replaced because of qualification or forward outcome.

## Sample result

- natural enrollments: **21**
- fully evaluated enrollments: **15**
- acquisition-incomplete enrollments: **6**
- complete frozen-policy vectors: **13**
- decision-eligible complete vectors under the existing 5-second Robinhood state gate: **0**
- live-qualified vectors: **0**
- policy-threshold passes if the independent operational freshness rejection is inspected separately: **5 / 13 complete vectors**

The 5/13 figure is descriptive research only. Those rows were not qualified because
their complete evidence bundles were available too late for the existing 5-second
current-state requirement.

### Strategy-gate rejection counts among the 13 complete vectors

Ignoring only the independent `stale_state_after_evidence` operational rejection:
- independent demand: **6**
- modeled round-trip cost: **6**
- translated minimum real liquidity: **2**
- concentration: **0**
- price extension: **0**
- evidence-capacity: not applicable to the 13 complete vectors; one additional evaluated enrollment crossed the >100 event cap

Multiple strategy rejections can apply to the same vector.

### Evidence latency

All 13 complete vectors missed the current-state freshness requirement.

Observed complete-vector evidence ages:
- minimum: **19 seconds**
- median: **22 seconds**
- maximum: **33 seconds**

This is an acquisition/runtime bottleneck, not evidence supporting a threshold change.
The 5-second gate remains unchanged.

## Acquisition-incomplete rows

Of the six rows that failed before a full evaluation:
- five used a non-native Pons quote token and were outside the frozen ETH translation scope;
- one failed the current-snipe evidence boundary.

These rows remain part of the unbiased enrollment record; they were not replaced.

## Forward marks

The run captured 10 executable full-position marks after the minimum 60-second
horizon, plus explicit unavailable-exit outcomes.

These are **not certified +60-second outcomes**. Because marks were processed
sequentially after enrollment collection, actual delays ranged from **67 to 350
seconds**. They must not be used to infer +60s profitability. The sampler has been
relabelled to `forward_after_60s` for future runs so actual delay cannot be mistaken
for an exact horizon.

No profitability conclusion is authorized from this run.

## Current conclusion

The unbiased sample is valid for:
- natural opportunity incidence;
- frozen qualification-vector distributions;
- exact strategy-gate rejection frequencies;
- identifying the current evidence-latency boundary.

It is **not** sufficient for:
- live Robinhood qualification, because no complete vector met the 5-second evidence-availability boundary;
- exact +60s expected-return estimation;
- changing any frozen continuation-v1 threshold.

The next causal step is to reduce evidence acquisition latency while preserving the
same point-in-time evidence, then rerun the **identical frozen policy**. Do not relax
the 5-second rule or any continuation-v1 threshold to manufacture qualified trades.
