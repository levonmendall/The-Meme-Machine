# Bounded native continuity keyset seeks

This component changes only the SQL lower-bound composition in `continuity_retirement_page`, based on application780f4015efd9fba528e97223f8e8e3b1a7322e12. It does not implement EDF/witness handoff, change the maintenance service cadence or claim to correct AWS390857's now-observed51-second interval after successful service.

The original resumed query combined `slot>=lower` with a stronger complete-key `key>after`. SQLite3.45.1 could start at the weaker lower bound and revisit protected keys before returning the bounded page. Merely seeing an index SEARCH or zero fullscan steps did not prove the expected cursor seek.

Use one effective lower bound:

- If the complete `after` key is at or above the current range lower slot, use the original strict complete-key bound alone. Keep all signature components.
- If the cursor is absent or below the range lower slot, retain the current slot lower bound; the weaker cursor predicate is implied.

The current upper bound, fixed complete-key horizon, scope, ordering, limit+1 lookahead and original guard recheck remain. Horizon wrap/reset, page-hint publication, cancellation, native deletion transactions and service-credit accounting are unchanged. No schema, index, row, byte, time or VM limit changes. No prefix scan or cursor movement earns durable progress.

## Evidence and validation

The existing private SQLite3.45.1 CAPI check on the actual original native fixture found equivalent rows in81 lower/upper/horizon/signature comparisons. As protected prefixes grew1024→2048→4096 slots with a fixed eligible256-slot suffix, original receipt page work grew8724→14868→27156 VM instructions; normalized work remained2067. Signature page work grew34334→60958→114206; normalized work remained7719. The original bounded guard recheck remained6925/13837 VM instructions. This is SQL-only evidence, not a full Python3.45 runtime or AWS capacity rehearsal.

The observer's original guarded witness search still has its original cost and250000-VM bound. Both SELECT1 and primary-key-returning witness triplets stopped at that same bound in the larger fixture. This access-path component does not change or bypass observation limits.

Preserved external evidence: `/workspace/recovery-evidence/maintenance-780-witness-sqlite345.{py,json,log,md}`; final script SHA256 `7c791fd8ff8c2b53a3e9be6356d6540504a6b82b4d0d02c951a2cccf27c6f626`, JSON `34c7b8a521bc7f2c9834e86e596687c9ea71f0214a28c9d654d36add6689322d`.

New original-driver tests use real native SQLite and deferred proofs: VM work does not grow with a longer protected prefix;66 current-bound/full-signature/horizon cases preserve exact selected rows and conservative unexamined status; cancellation preserves the actual resumed hint, no uncommitted service is credited, and a real close/reopen reexamines retained keys and commits only actual eligible continuity while preserving all1024 proof anchors. Existing protected-boundary, yield, rollback, restart and maintenance regressions remain unchanged.

Validation: the three new original-FAST-driver cases pass in0.500s. The four affected original-OPERATIONAL-driver modules (`test_pipeline_retention_boundary`, `test_retention_progress`, `test_retention_outcomes`, `test_production_maintenance_arbiter`) pass89 cases in32.485s, with no skips. An in-memory exact780 original-function counterfactual makes the unchanged new VM regression fail as expected (34125 instructions against a16773 bound); the current implementation passes. The first attempted combined FAST command was rejected before tests because three modules belong to OPERATIONAL; its selection-refusal log is preserved and the correctly scoped command passed.

Focused receipts and exact verdicts are recorded separately under `/workspace/recovery-evidence/maintenance-keyset-bounds-*`. The component remains subject to independent review and exact-source approval before integration/deployment. It grants no boot, funding, trading, historical-completion or capacity authority.
