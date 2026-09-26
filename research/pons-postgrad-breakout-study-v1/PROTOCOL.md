# Pons independent post-graduation breakout study

## Scope

This branch evaluates the already-frozen research signal
`pons-post-graduation-breakout-v1`. It does not change or relax the active
`pons-selective-continuation-v1` production-paper strategy.

The candidate universe is independent of pre-graduation qualification: graduations
are discovered directly from the authenticated Pons V2 factory and V2 -> Uniswap V4
lineage must be proven.

## Frozen signal

The existing research thresholds remain unchanged:

- 30-900 seconds after graduation;
- at least 500 bps settling pullback;
- breakout above the frozen consolidation high;
- at least 3 new independent buyers in the trailing 15 seconds;
- at least 1.5x buy:sell quote flow;
- current 15-second buy flow greater than the prior 15-second buy flow.

No threshold search or outcome-dependent tuning is authorized by this study.

## New measurement

When the frozen signal appears, the collector obtains an authenticated
Uniswap V4Quoter exact-input **shadow** buy for 25 bps of the existing 1-native-unit
Pons research capital reference (0.0025 native quote). It does not reserve capital,
write a paper position, sign, or submit a transaction.

The exact quoted token output is then re-quoted back to native quote at fixed
30, 60, 120, and 300 second horizons. Reported return includes the entry input and
a conservative 2x-quoter-gas proxy on both entry and exit.

This first run is evidence collection only. A single candidate or single return
cannot promote a strategy. Production allocation authority remains false.

## Authority

- research only;
- paper only;
- no signing;
- no submission;
- no live money;
- no production Pons source promotion;
- no change to the active Pons policy hash.
