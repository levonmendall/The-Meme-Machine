# DLMM capital-case research split

Branch: `research/dlmm-capital-case-ranking-v1`

This branch is research-only and is stacked on the latest density-screened DLMM
profitability work. Prospective DLMM allocation remains disabled.

## What changed

The DLMM path now computes a pre-entry economic case for the **exact proposed one-sided
range** rather than relying on broad 210-bin pool activity.

For the fixed selected `sdk_bidask` / width-8 research variant it records:

- current SOL-valued liquidity inside the proposed bins;
- verified warmup volume that actually traversed the proposed bins;
- verified warmup volume in the proposed bins plus the immediately adjacent bins;
- LP-fee generation in the range and near the range;
- a transparent decision-time capital-share fee-capture proxy;
- a 60-second projected fee-capture case;
- the projected 60-second net case after the existing fixed entry/exit costs;
- whether that point-in-time case exceeds the existing **35 bps** research hurdle.

Host fees remain excluded from LP revenue. Verified swaps are replayed through the
existing exact DLMM simulator to recover per-bin traversal before these metrics are
computed.

## Authority

The range case is diagnostic only. It does not:

- enable DLMM allocation;
- alter the fixed strategy or width;
- alter the 16-transaction verifier;
- weaken mutation, finality, host-fee, or provider fail-closed behavior;
- skip outcome collection when the economic case fails;
- use future outcome data.

Outcome observations remain necessary to determine whether this pre-entry case has
predictive value before any allocation decision is considered.
