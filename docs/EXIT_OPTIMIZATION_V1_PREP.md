# Exit Optimization v1 — isolated preparation

Status: **PREPARED ONLY — NOT ACTIVE**

This branch layers the reviewed exit-policy changes on top of the existing directional-capital-parity preparation without changing the active Stage-E certification lineage.

Parent preparation:

- branch: `strategy/directional-capital-parity-prep-20260930`
- commit: `4a3d4516ea75a14e18018c8e7defcadf353ab072`

The current Stage-E machinery branch remains separate and untouched.

## Prepared exit changes

### Pump Current

Unchanged:

- hard stop: -8%
- first realization: +15%
- first sale: 25% of original position
- demand-exit confirmation count: 2
- graduation-continuation rules and hold deadlines

Prepared change:

- runner peak-return giveback: **12 percentage points -> 14 percentage points**

The existing implementation measures this as peak return minus current return, not as a conventional percentage drawdown from peak price.

### Pons Current

Unchanged:

- hard stop: -8%
- first realization trigger: +18%
- two-confirmation soft deterioration
- creator-distribution safety
- 900-second total hold limit

Prepared changes:

- first sale: **33.33% -> 25% of original position**
- runner high-water drawdown: **10% -> 12%**
- immediate adverse-flow liquidation: **sell flow merely > buy flow -> sell flow >= 1.20x buy flow**

A sell-flow reversal below 1.20x no longer forces immediate liquidation by itself. Existing persistent deterioration logic remains available to exit a weakening runner after confirmation.

### Meteora

The moderate-admission policy currently accepts:

- two-way balance >= 20%
- drift ratio <= 80%

The old immediate one-way-flow exit uses:

- two-way balance < 25%
- drift ratio > 75%

That overlaps the admission envelope. The prepared hysteresis revision changes the immediate one-way-flow exit to:

- **two-way balance < 18%**
- **drift ratio > 82%**

The ordinary post-core-hold economic-collapse requirement changes from:

- **2 consecutive verified 300-second segments -> 3 segments**

The 4-hour core hold, range-boundary risk exit, inventory-imbalance risk exit, stress-unwind evidence requirement, and 24-hour maximum hold remain unchanged.

Because Meteora's policy hash is stored statically in its JSON policy, the prepared patch deliberately replaces it with `REGENERATE_AFTER_FINAL_COMPOSITION`. This is a fail-closed staging guard: the patch is not eligible for certification or promotion until the final composed policy hash is regenerated.

## Explicitly unchanged

No changes are prepared for:

- Pump Survivor exits
- Pons Survivor exits
- Ramses Active Wide Maker exits/recenter rules
- any directional entry/admission threshold
- capital targets or the capital-parity preparation
- execution stress limits
- fill-time breadth retention
- turnover/depth capacity
- freshness/finality
- generation fencing
- accounting or shared-sleeve identity
- provider topology
- signing/submission/live-money authority

## Stage-E isolation

This preparation does not edit the Stage-E branch, the frozen Stage-E candidate, any Stage-E workflow, or any active certification artifact.

No workflow dispatch or market run is authorized.

The files under `certification/strategy-prep/` are staging inputs only. They do not participate in the active runtime or patch sequence.

## Promotion after the machinery lineage is complete

1. Rebase/regenerate the capital-parity and exit-optimization patches against the exact final machinery SHA.
2. Compose the frozen six-regime strategy and moderate-admission revision first.
3. Apply `directional-capital-parity-v1.patch`.
4. Apply `exit-optimization-v1.patch`.
5. Regenerate all affected Pump, Pons, and Meteora policy hashes and exact policy identities. Replace the Meteora hash sentinel.
6. Run exact boundary tests for Pump +14-point giveback, Pons 25% harvest / 12% trail / 1.20x adverse-flow exit, and Meteora 18%/82% hysteresis plus three collapse segments.
7. Run restart/replay, accounting, shared-sleeve, fill-persistence, and execution-capacity regressions.
8. Run exact-SHA non-market certification.
9. Only after that certification may one PAPER market smoke be considered.
10. Start a fresh affected-lane profitability cohort because the economics changed.

No live-money authority is introduced.
