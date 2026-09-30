# Directional Capital Parity v1 — isolated preparation

Status: **PREPARED ONLY — NOT ACTIVE**

This package prepares the PAPER-only directional sizing revision discussed on 2026-09-30 without changing the current Stage-E certification lineage.

## Intended economic change

The directional families use one common position target: **500 bps (5.00%) of the applicable family sleeve per qualified position**.

| Regime | Previous target | Prepared target | Existing hard stop | Approx. sleeve loss at stop |
|---|---:|---:|---:|---:|
| Pump Current | 500 bps | 500 bps | -10% | 50 bps |
| Pons Current | 25 bps | 500 bps | -8% | 40 bps |
| Pump Survivor | 25 bps | 500 bps | -12% | 60 bps |
| Pons Survivor | 25 bps | 500 bps | -10% | 50 bps |

This is **capital-target parity**, not a relaxation of market-quality or execution gates.

## Controls deliberately unchanged

Current and Survivor continue to share their existing Pump or Pons family sleeve. No additional sleeve and no hidden capital are created. Available-capital reservation remains authoritative.

Turnover capacity, independent-demand capacity, execution loss ceilings, 2x stress checks, fill-time breadth retention, quote/state freshness, generation fences, concentration/creator safety, stop losses, staged profit realization, runner trails, deterioration exits, and maximum holds remain unchanged.

Meteora and Ramses are intentionally excluded. Their LP/maker sizing remains range-local and economics/capacity driven.

## Why the Survivor change is bounded

The old 25-bps Survivor target made a valid Survivor position one-twentieth the size of Pump Current regardless of liquidity or evidence quality. The prepared revision removes that artificial throttle, but the strategy still cannot force a 5% fill: turnover, available sleeve capital, fresh executable quotes, and stress capacity can only reduce or reject the requested size.

At the unchanged hard stops, a full 5% directional target represents approximately 0.4%–0.6% of the relevant sleeve at planned stop loss.

## Stage-E isolation

This branch was forked from:

- branch: `cert/autonomous-paper-machinery-20260927`
- commit: `a775849c940d48bc8f809e99c075e421744bc53f`

The active Stage-E branch/candidate is not edited. No workflow is added or changed. No workflow dispatch or market run is authorized. The prepared patch is stored under `certification/strategy-prep/` and is not part of the active patch/composition sequence.

**Do not merge or compose this revision into the active exact-candidate lineage while Stage E/F/G certification is still using a frozen SHA.** Doing so would create a new runtime identity and defeat exact-candidate continuity.

## Post-certification promotion procedure

After the current machinery lineage is complete:

1. Rebase/regenerate `directional-capital-parity-v1.patch` against the exact final machinery SHA and the final strategy composition order.
2. Apply existing six-regime strategy changes and moderate-admission changes first; apply this capital-parity patch last.
3. Regenerate all affected policy hashes and frozen strategy identities. Do not reuse pre-sizing-change hashes.
4. Run the affected Pump/Pons deterministic suites, shared-sleeve reservation/conflict tests, restart/recovery tests, fill-persistence tests, and execution-capacity/2x-stress tests.
5. Prove that a requested 500-bps target is still downsized by turnover, liquidity, available capital, and stress limits and fails closed when evidence is missing.
6. Run exact-SHA non-market certification for the newly composed PAPER candidate before any market smoke.
7. Start a fresh economic/profitability cohort for affected directional lanes because position sizing is an economic-policy change.
8. Preserve PAPER ONLY. No signer, submission, or live-money authority is introduced.

## Prepared files

- `certification/strategy-prep/directional-capital-parity-v1.json` — machine-readable intent and activation guards.
- `certification/strategy-prep/directional-capital-parity-v1.patch` — post-composition source delta.
- `certification/tests/test_directional_capital_parity_prep.py` — static guard tests ensuring the preparation is capital-only and non-activating.

This branch is a staging artifact for later promotion, not a new certified strategy candidate.
