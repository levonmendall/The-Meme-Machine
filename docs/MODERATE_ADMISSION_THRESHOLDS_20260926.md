# Moderate admission threshold revision — 2026-09-26

PAPER ONLY. This revision changes threshold calibration, not strategy design.

Base runtime: `48e46b27086a8058fcbd7752a42420c1f9186af7`.

Affected active regimes:
- Pump current: broader buyer breadth, demand, concentration, fill-retention, post-graduation and second-leg admission.
- Pump Survivor: earlier survivor eligibility, lower liquidity/reset floors, broader concentration and fill-retention admission.
- Pons current: broader curve/age/ETA windows and moderately looser momentum, flow, concentration, impact and continuation thresholds.
- Pons Survivor: moderately looser trend, reset, demand, execution-cost and fill-retention thresholds.
- Meteora: authenticated fee-density 5% -> 4%, local-liquidity multiple 5x -> 4x, two-way balance 25% -> 20%, drift ceiling 75% -> 80%, stress-unwind ceiling 150 -> 200 bps.

Unchanged:
- all six strategy designs and lane topology;
- exits/profit protection for the five revised regimes;
- Ramses Active Wide Maker v4;
- evidence finality/freshness and fail-closed reconstruction;
- provider topology and accounting;
- PAPER-only authority; no signing, transaction submission, live money, deployment, or market run authorization.

Frozen lane policy identities:
- Pump composite: `0f909d1e7eb90cdbb504b4e52fec693ccaf810f87f80259be760c81361a3babc`
- Pons composite: `b9f3aff04336d22fac8a8a8f38c821a8fb776b8ccd891774a8d46012d9124db2`
- Meteora: `78a9658dfc8dda7a35c20486527f24553b00b9a20b8140e65dedde90c9a93408`
- Ramses unchanged: `58d6ca2a911c4d27ea35da8c972f0a6b1c65c3e9192d811834b92d63d2c08b1e`

Focused threshold preflight and the repository-wide deterministic CI passed before this certification trigger. Promotion to `cert/prospective-market-v1` is permitted only after the exact resulting SHA passes full non-market certification.

## Certification repair note

Full non-market certification exposed stale Pons age-boundary regressions after the intentional current-Pons token-age window changed from 120–600 seconds to 90–900 seconds. The repair changes only deterministic test fixtures and the test BatchContext launch-time parameter; active runtime logic and all thresholds remain unchanged. Retained historical v9 policy epochs remain digest-pinned separately from the v14 prospective policy.

## Final directional acceptance repair

The six-regime directional gate previously required `meteora_unchanged`, which is incompatible with this authorized threshold-only Meteora revision. The gate now binds the prepared Meteora runtime to the exact v14 policy hash and revision and separately verifies that exit thresholds, positive expected-net authority, range width, core hold, and PAPER-only authority remain unchanged. Ramses remains required unchanged. No lane strategy or threshold was modified by this certification repair.

## Six-regime acceptance repair

The original six-regime acceptance gate assumed Meteora was unchanged because that earlier upgrade only added Pump/Pons Survivor regimes. For v14, the gate now allows exactly the declared Meteora moderate-admission threshold overlay, validates its policy/composed-file identities and active admission metadata against the Run 376 certified baseline, and executes Meteora's focused deterministic strategy regression. No additional strategy change is introduced by this certification repair.
