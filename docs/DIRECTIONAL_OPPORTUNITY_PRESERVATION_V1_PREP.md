# Directional Opportunity Preservation v1 — isolated preparation

Status: **PREPARED REQUIREMENT — NOT ACTIVE**

Parent preparation:

- branch: `strategy/exit-optimization-prep-20260930`
- commit: `540ac62504403b3d5d31b7b17b3461891af94159`

This is the third off-path strategy-preparation layer after directional capital parity and exit optimization. It does **not** modify the active Stage-E lineage, any Stage-E candidate, any workflow, any provider limit, any entry/exit threshold, or any capital target.

## Purpose

Make two properties mandatory for **both Pump and Pons** before the prepared strategy stack is promoted:

1. **Airtight Current -> Survivor recovery.**
2. **Durable marginal-reject / opportunity-loss instrumentation.**

The purpose is to learn which gates exclude high-quality winners without weakening safety or allowing hindsight to authorize trades.

## Pump and Pons continuity requirement

For both directional families, Survivor discovery must remain independent of whether Current qualified, rejected, timed out, or never opened a position.

A Current rejection:

- may be preserved as research/diagnostic context;
- must **not** tombstone, blacklist, retire, or suppress the asset from later Survivor discovery;
- must **not** become a Survivor admission gate;
- must not bypass or weaken Survivor's own point-in-time qualification.

Pump must link a Current mint to the later verified Pump.fun -> PumpSwap migration identity when that lineage exists.

Pons must link a Current token to the later verified Pons graduation -> Uniswap V4 market identity when that lineage exists.

The link and Survivor interest must be durable across restart/replay.

Fresh Survivor evidence remains authoritative. A Current safety failure is not automatically permanent: the Survivor strategy reevaluates its own current safety and alpha gates. Only an immutable lineage/integrity defect owned by the Survivor policy may permanently disqualify the asset.

Existing shared-sleeve fencing remains unchanged. A Current position may not create duplicate family exposure through Survivor.

## Marginal-reject instrumentation

Every evaluated Pump Current and Pons Current rejection must preserve a bounded durable receipt containing, where available from the existing decision path:

- exact asset identity and decision time;
- Current strategy/policy identity;
- every rejection reason, not just the first;
- observed value, threshold, comparator and signed distance for each measurable gate;
- hard-safety/evidence/execution pass state;
- generation/freshness/source cursor;
- any executable quote and capacity evidence already present in the decision path.

**No new provider request may be made solely to produce this receipt on the Current decision critical path.**

"Marginal reject" is an analytic label only. It never changes qualification. A candidate may be labeled marginal only when applicable hard-safety, evidence and execution categories passed; failed alpha gates are then ranked by normalized distance from their thresholds.

Hard-safety categories include authoritative evidence/finality/freshness, canonical lineage/venue/quote identity, creator/distribution safety, hard concentration safety, exit liquidity, execution-capacity stress and generation fencing.

Alpha categories include age/curve position, velocity/acceleration, buyer breadth/growth, net demand, continuation/price retention, extension/reset/base/breakout and score/ranking.

## Outcome follow-up

Using persisted/canonical evidence, enrich rejected candidates at:

- 5 minutes
- 15 minutes
- 1 hour
- 6 hours
- 24 hours

Record MFE, MAE, terminal return when observable, whether Survivor later enrolled the same asset, whether Survivor qualified, whether it filled, and the Survivor terminal outcome.

Outcome enrichment has **zero** order, reservation, sizing or qualification authority.

This should allow four especially useful classifications:

- Current reject -> Survivor admit -> profitable
- Current reject -> Survivor admit -> loss
- Current reject -> Survivor never qualifies -> large winner
- Current reject -> Survivor never qualifies -> collapse

The third bucket is the primary threshold-opportunity-loss audit target. The fourth is the control population showing filters doing useful work.

## Required deterministic proofs

Before promotion, both Pump and Pons must prove:

1. Current rejection followed by native migration/graduation still creates a Survivor candidate.
2. Restart between rejection and Survivor enrollment cannot lose that opportunity.
3. Current hard-safety rejection does not become permanent Survivor suppression unless Survivor independently owns the immutable failure.
4. Open/reserved Current exposure prevents duplicate Survivor exposure while still allowing observation.
5. Reject receipts round-trip durably with all measurable gate distances.
6. MFE/MAE enrichment cannot affect trading decisions.
7. Reject capture adds no decision-critical provider calls.

## Stage-E isolation

No Stage-E branch or candidate is modified.

No workflow dispatch is authorized.

No market execution is authorized.

This requirement is staged only. Exact runtime wiring should be done **after the Stage E/F/G machinery lineage is complete**, against the exact final machinery SHA, together with the other prepared strategy changes.

## Final composition order

1. Certified final machinery.
2. Six-regime strategy + moderate-admission policy.
3. Directional capital parity v1.
4. Exit optimization v1.
5. Directional opportunity preservation v1.
6. Regenerate affected identities.
7. Deterministic continuity/telemetry/restart/provider-accounting tests.
8. Exact-SHA non-market certification.
9. Only then consider one PAPER market smoke.

No live-money authority is introduced.
