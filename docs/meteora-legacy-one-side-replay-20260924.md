# Narrow evidence questions — final repair handoff

## Scope

This handoff resolves the two narrow questions raised after evidence-reconstruction run `35962402406`.
No market workflow is authorized or launched by this repair.

## Ramses — no repair required

The final repaired hour reported one `screening_qualified` / `evidence_required`
observation with no downstream `evidence_requested`.

Inspection of the retained hourly result shows that the observation was created in the
last completed frontier scan immediately before the Ramses process returned. The lane
had no remaining runtime in which to invoke canonical pre-entry reconstruction.

Disposition: **legitimate observation-boundary pending state, not a dropped lifecycle
transition.** No Ramses strategy/runtime change is justified.

## Meteora — legacy one-sided weighted liquidity replay repaired

The retained accepted evidence for run `35949285193` contained a required warmup
interval that previously failed closed on legacy Meteora instruction discriminator
`5e9b6797465fdca5` (`add_liquidity_one_side`).

The repaired Meteora source is:

`a3579b4cc748fdbb7b4a466680f8a224773adc8b`

It implements only the independently demonstrated classic-SPL Y-side weighted shape.
X-side and unsupported/ambiguous shapes remain fail-closed.

The implementation authenticates:
- pool/program/token identity;
- instruction amount, active bin, slippage, bin IDs and weights;
- the matching AddLiquidity event;
- ordered SPL transfer amount;
- deterministic integer per-bin weight allocation and rounding;
- tracked-bin inventory/share deltas;
- exact aggregate vault contribution for bounded-state bins outside the retained
  three-array snapshot;
- ordered coexistence with a disjoint authenticated range removal and swap.

It does not fabricate untracked bin state. A later replay that requires unavailable
bin state still fails closed.

## Exact historical replay proof

Offline projection run: `36013677709`

Immutable evidence source: reconstruction projection artifact `10791522985`
derived from accepted run `35949285193`.

Exact interval:
- pool: `FtwzPjTqoFuy8aF8bMBi7QF7UxpdYN5n9YUH6R7DcHjB`
- start slot: `449907316`
- end slot: `449907330`
- finalized transactions: 5
- swaps: 1
- external adjustments:
  - `add_liquidity_one_side`
  - `remove_liquidity_by_range2`
  - `add_liquidity_one_side`
- terminal retained-state match: **true**

The captured 37-bin one-side instruction requested 786,069,230 lamports and the
published Meteora weight rule produces 786,069,211 deposited lamports plus 19 lamports
of integer rounding dust, matching the authenticated event/transfer.

## Offline verification

Projection run `36013677709`:
- focused `tests.test_dlmm_tape`: **21 passed**
- complete Meteora suite: **447 passed**
- generic synthetic resource gate: **passed**
- DLMM synthetic resource gate: **passed**
- real provider calls in resource gates: **0**
- exact pre/post historical interval replay: **passed**
- prepared-tree source identity before/after tests: identical

Pinned prepared Meteora source diff:

`3a2d3b6f6c2c117c3fd2f7d6824231a87fab39a52b0faf8b9633b5df09d8d689`

## Frozen boundaries

Unchanged:
- Meteora strategy version and policy hash;
- qualification thresholds and economics;
- target-market scope;
- provider rate/capacity policy;
- evidence freshness/finality;
- transaction-capacity ceiling;
- paper accounting authority;
- paper-only boundary.

The three retained >16-transaction historical intervals remain fail-closed because
supporting them would change the frozen reconstruction-capacity envelope.

## Cohort identity

Because the Meteora executable source changed, a new clean cohort identity is frozen:

`prospective-four-lane-v8-meteora-one-side-replay-20260924`

The prior v7 one-shot evidence remains historical and is not blended into v8.

Final next action: exact-SHA non-market certification only. No market run is authorized.
