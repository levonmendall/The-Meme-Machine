# Reset-Recovery v1 — future research/implementation contract

## Research collector

The collector must be read-only with respect to allocation. It should attach to existing Pump/Pons candidate identity and persisted market history.

Candidate creation must be outcome-blind. A later rally may not create a retrospective candidate that did not satisfy the point-in-time flush/stabilization state machine.

## Candidate identity

Use the canonical family asset plus verified graduation/migration lineage. A reset research identity must additionally include a reset-cycle identifier so multiple natural flush/recovery cycles are distinguishable without double-counting the same episode.

## Required transition evidence

### observed -> flush_candidate
Prove a prior local high and a material decline. Threshold remains unset.

### flush_candidate -> stabilizing
Prove the asset is structurally alive: authoritative venue, retained executable liquidity, safe creator/distribution state and acceptable hard concentration.

### stabilizing -> recovery_watch
Prove new lows have stopped expanding for the eventual frozen stabilization interval and sell pressure has decelerated.

### recovery_watch -> shadow_qualified
Require fresh independent demand, a frozen recovery-reference reclaim, and positive executable capacity after existing stress/downsize controls.

### any state -> shadow_invalidated/retired
Record immutable lineage failure, creator/distribution failure, hard concentration/liquidity failure, renewed breakdown, research expiry, or evidence incompleteness explicitly.

## Future allocation integration

If evidence later supports promotion:

- add a separate policy hash and strategy ID;
- use the existing family shared sleeve;
- use realized-equity sizing and existing execution-capacity primitives;
- define deterministic conflict priority against Current/Survivor/staged scaling;
- create a native paper lifecycle and restart-safe reservations;
- define independent exits rather than borrowing Survivor exits by convenience;
- begin a fresh profitability cohort.

No part of this file grants that authority.
