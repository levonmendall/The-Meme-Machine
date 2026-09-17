# Market-native prioritization status

## Purpose

Validate the policy-derived evidence prioritizer prospectively against the same
finalized Pump.fun stream while keeping `continuation-v1` frozen and preserving
zero order authority.

## Exact source boundary

Implementation head before this trigger:
`e565899c1f64359c3eee5ac34d3004506fcf513d`.

Deterministic CI run `35270233246` passed on that exact head:

- 113/113 unit tests;
- resource check;
- canonical synthetic qualification -> entry -> exit -> settlement;
- no live provider calls in CI.

## Live experiment

This commit exists only to trigger the dedicated `market-native-priority` workflow.
The experiment uses public/read-only Solana RPC, no signing, no transaction submission,
no live money, no scout lane, no scout storage, and no threshold changes.

Configured bounds:

- 3,300 seconds market-native observation;
- 90 snapshot preflight opportunities distributed across the whole window;
- 20 maximum full concentration/final qualification evaluations;
- frozen `continuation-v1` canonical qualification;
- maximum primary logical RPC budget remains 240.

The output artifact is `market-native-priority-report.json`. Results are research
evidence only and do not authorize promotion, merging, deployment, or live trading.
