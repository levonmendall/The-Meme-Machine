# DLMM final replay repair — 2026-09-24

## Scope

This revision closes the two narrow post-reconstruction questions without changing
strategy economics, target scope, provider ceilings, freshness/finality, position
sizing, accounting policy, or paper-only authority.

## Ramses qualified-at-close audit

The repaired one-hour validation contained one Ramses observation that reached
`screening_qualified` / `evidence_required` but did not reach
`evidence_requested`. The final native trace shows that the qualifying screen was
published at the final completed frontier scan essentially at lane shutdown; there
was no remaining observation time in which canonical receipt/header reconstruction
could start. This is an end-of-observation-boundary condition, not a dropped
qualified candidate or lifecycle scheduler defect. No Ramses code change is made.

## Meteora legacy add_liquidity_one_side

The preserved natural transaction at run `35949285193`, slot `449907325`,
signature `5PeXkA5PLLR39ZecnB2khGcLiqPjUoDnK2kERgcZLSY8qpWFJEwdUnK5sJuULFPqBeJ2VzKFxFsQtnKZyb6jwM3J`
contains Meteora discriminator `5e9b6797465fdca5`, matching the published
legacy `add_liquidity_one_side` instruction.

The authenticated instruction contains:
- amount: 786,069,230 lamports WSOL
- active bin: -489
- max active-bin slippage: 3
- 37 explicit {bin_id, weight} rows spanning -595 through -559

The authenticated AddLiquidity event records 786,069,211 lamports deposited on the
Y side. Applying the published bid-side integer weight allocation to the captured
37 weights produces exactly 786,069,211 lamports of per-bin deposits and 19 lamports
of rounding dust. The ordered SPL transfer and transaction token-balance deltas
independently match the same 786,069,211 lamports.

The source repair authenticates the instruction identity, event, sender/position,
classic SPL token transfer, token-balance deltas, active-bin slippage and captured
weight vector, then feeds the exact per-bin deposits through the existing
`apply_external_adjustment` replay machinery. The opposite ask/X-side legacy form
remains fail-closed because no authenticated retained occurrence currently proves
its rounding against terminal bin state.

The previously frozen 16-transaction reconstruction capacity remains unchanged.
Historical intervals exceeding that capacity continue to fail closed; they are not
treated as engineering defects.

## Verification

- Source repair SHA: `32b7de83dd1f002a0037cb6d3dc951cb470d90b4`
- Captured composition diagnostic: `36013735127`
- Captured one-side regression: PASS
- Exact recomposed Meteora source-diff SHA256:
  `e24d8ae6c18515c640df79e40cdb413a0f7110a5ce58210c31632d3de1b53ed7`

A new prospective cohort identity is frozen because executable source changed:
`prospective-four-lane-v8-dlmm-one-side-replay-20260924`.

No market run is authorized by this repair.
