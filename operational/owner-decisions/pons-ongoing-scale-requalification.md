# Owner interpretation: mature Pons staged-winner scaling

Approved by the owner on 2026-10-04 during migration-completeness closure.

`PONS_ONGOING_SCALE_REQUALIFICATION` is a separate qualification path for an
already-open, already-qualified Pons position. It grants no initial-entry authority.
Initial token age <=900 seconds and initial 5–45-second graduation/observation
timing gates remain authoritative for new Current entries, but do not apply to
mature scale-add qualification. Full requalification means that every currently
relevant strategy, structural, demand, safety, liquidity and execution gate is
freshly satisfied; it does not require repeating historical entry timing gates.

The ongoing window is the rolling 900 seconds ending at the scale decision.
Current authenticated evidence must independently establish demand and momentum;
the original entry vector alone cannot authorize an add. Re-prove canonical Pons
lineage, token/curve/pool identity, venue, authenticated market state, creator and
distribution safety, absence of incompatible transition, and executable exit
liquidity. Immutable facts can be reused only under their durable authenticated
identity. Evaluate buyer breadth, buy/sell and net flow, acceleration/persistence,
buyer and top-buyer concentration, adverse flow, deterioration and price
persistence using the currently applicable existing substantive constraints.

For pre-graduation positions, evaluate current curve state, flow, demand,
concentration, liquidity and thesis validity. Actual graduation, invalid curve,
failed thesis, adverse distribution, deteriorated demand, stale evidence, unsafe
concentration, invalid liquidity or an exit condition blocks scaling. Elapsed
initial-entry timing gates alone do not. For carried post-graduation positions,
use authenticated current post-graduation evidence over the ongoing horizon;
require current breadth, adequate positive flow, concentration safety, liquidity,
venue/lineage, price persistence and absence of an exit condition. Do not require
the original early-observation window to remain open.

Common prerequisites remain: open position; >=2x relative to the original
reference; durable first realization; first tail crossing persisted >=900 seconds;
no committed add or outstanding add reservation; no pending or irreversible exit;
price within 15% of the applicable high-water mark. After strategy qualification,
repeat execution capacity with a fresh executable quote inside the existing
freshness window. Preserve ordinary execution loss, 2x stress, minimum-size
feasibility, available capital, provider and finality requirements.

The maximum add remains exactly the minimum of 2.5% of durable realized sleeve
equity, 50% of original basis, available capital and executable capacity. Total
position remains capped at 7.5% of sleeve. Exactly one add; no sell/rebuy, new
lifecycle, open-time reset or high-water reset. Recovery/replay cannot create a
second add.

This interpretation changes no entry economics, stop, first realization, 12%
normal trail, 1.20x adverse-flow rule, right-tail behavior, add size, sleeve cap,
realized-equity compounding, Current→Survivor behavior, execution stress, provider
or finality requirements.

Required permanent regressions: mature >900-second winner can scale; expiration
of early-entry/graduation windows alone cannot reject scaling; scale qualification
cannot authorize a new entry; <900-second persistence, stale evidence, failed
current demand, unsafe concentration, active/pending exit, >15% drawdown and fresh
capacity failure each block; success is exactly once across restart/replay;
initial-entry timing remains unchanged; both pre- and post-graduation paths are
covered; original entry vector alone cannot authorize a mature add.

Implementation: `ongoing_scale_requalification` and `_ongoing_scale_evidence`
provide the separate authority and fresh authenticated horizon.
`tests.test_pons_ongoing_scale` covers both lifecycle phases, timing and safety
failures, fresh execution rejection, final requalification failure, unchanged
initial-entry timing, and real native-store reopen with exact reservation replay.
The initial-entry/exit policy remains pinned by the historical source comparison.
This record does not declare migration completeness or authorize CAPACITY.
