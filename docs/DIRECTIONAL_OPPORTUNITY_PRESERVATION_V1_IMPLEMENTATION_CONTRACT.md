# Directional Opportunity Preservation v1 — implementation contract

Status: **READY FOR POST-STAGE-E FINAL-SHA INTEGRATION — NOT ACTIVE**

This contract closes the implementation decisions for the already-frozen
`directional-opportunity-preservation-v1` requirement. It grants no current
allocation authority and must not be wired into the Stage-E candidate.

## 1. Canonical opportunity identity

Use one durable opportunity namespace per directional family:

- Pump: `pump:<mint>`, later linked to the verified Pump.fun -> PumpSwap migration lineage.
- Pons: `pons:<token_address>`, later linked to the verified Pons graduation -> canonical post-graduation market lineage.

The Current decision identity and Survivor market identity remain separate native
strategy identities, but both must be linkable to this family opportunity identity.

A Current rejection, timeout, cancellation, or no-fill state must never write a
permanent Survivor tombstone.

Only a Survivor-owned immutable lineage/integrity failure may permanently retire
the Survivor opportunity.

## 2. Durable Current reject receipt

For every evaluated Pump Current and Pons Current rejection, append one bounded
receipt to a durable opportunity journal. The receipt schema is frozen as:

- schema/version;
- family and canonical asset ID;
- Current strategy ID, policy hash and policy epoch;
- decision timestamp;
- source cursor / finalized evidence identity;
- freshness and generation;
- every rejection reason;
- for every measurable gate: name, observed value, threshold, comparator,
  signed distance and category;
- hard-safety/evidence/execution aggregate pass state;
- alpha aggregate pass state;
- executable quote/capacity evidence **only when already present on the decision path**;
- receipt hash and previous-journal hash.

The decision path may not make a new provider call solely to populate the receipt.

Receipt failure is observable and auditable, but it cannot mutate the trading
decision that produced it.

## 3. Survivor continuity

Survivor discovery remains native-event driven and independent of Current state.

When a verified migration/graduation event proves that a Survivor market belongs
to an asset with a Current receipt:

1. append a durable opportunity-link event;
2. create/continue Survivor observation under the Survivor policy;
3. re-evaluate every Survivor gate from fresh point-in-time evidence;
4. never import a Current alpha rejection as a Survivor rejection;
5. preserve the link across restart/replay.

A Current hard-safety rejection is context only unless the same immutable defect
is independently owned and observed by the Survivor policy.

## 4. Shared-sleeve conflict rule

Observation is independent from allocation.

A Survivor candidate may be observed while the same family asset has an open,
reserved, bridged or scaling Current lifecycle.

A same-asset Survivor **fill** must fail closed while such Current exposure
exists. After the Current lifecycle is terminal and the sleeve is reconciled,
Survivor may independently qualify/fill under its own existing rules.

No duplicate economic exposure is created by opportunity preservation.

## 5. Outcome enrichment

A read-only enrichment worker uses persisted/canonical evidence to append outcome
snapshots at:

- 5 minutes;
- 15 minutes;
- 1 hour;
- 6 hours;
- 24 hours.

Record where observable:

- MFE;
- MAE;
- terminal/last observable return;
- Survivor candidate creation;
- Survivor qualification;
- Survivor committed fill;
- Survivor terminal outcome.

The enrichment worker has **zero** order, reservation, sizing, policy, threshold
or qualification authority and may not add decision-critical provider work.

## 6. Marginality classification

A receipt can be labeled `marginal_alpha_reject` only if all applicable
hard-safety/evidence/execution categories passed.

Failed alpha gates are ranked by normalized signed distance. Multiple failures
remain visible; do not collapse to first failure.

The label is research/telemetry only and can never grant entry.

## 7. Restart/replay invariants

Replay must reconstruct exactly:

- all Current reject receipts;
- all Current -> Survivor links;
- Survivor observation eligibility;
- all outcome-enrichment checkpoints;
- the same-asset allocation fence.

Duplicate receipt/link delivery is idempotent. A conflicting duplicate fails
closed and is surfaced as integrity failure.

## 8. Provider accounting

Certification must prove:

- zero additional provider calls on the Current decision-critical path solely for reject capture;
- zero additional entry authority from enrichment;
- Survivor continues to use its existing provider/evidence boundaries;
- all research enrichment can be disabled without changing any trading decision.

## 9. Required final-SHA tests

Before PAPER market execution:

1. Pump Current reject -> verified migration -> Survivor observes and independently evaluates.
2. Pons Current reject -> verified graduation -> Survivor observes and independently evaluates.
3. Restart between Current rejection and Survivor event preserves the opportunity.
4. Current alpha rejection does not suppress Survivor.
5. Current hard-safety rejection does not suppress Survivor unless Survivor independently proves an immutable owned failure.
6. Open/reserved/tail-bridge/scaled Current exposure blocks only the Survivor fill, not observation.
7. Terminal Current reconciliation allows later Survivor fill.
8. Receipts round-trip every measurable gate distance.
9. MFE/MAE enrichment cannot change decisions.
10. Provider-call accounting proves no decision-path research call inflation.

No economic threshold remains unresolved in this contract.
