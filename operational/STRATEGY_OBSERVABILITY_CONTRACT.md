# Strategy Observability & Opportunity Preservation Contract v1

Status: **ACTIVE STRATEGY INFRASTRUCTURE CONTRACT**

This contract changes observation and evidence scheduling only. It does **not** change
entry economics, exit economics, sizing, the nine approved strategy changes, or the
separate strategy identities for Current and Survivor.

## Core invariant

The observable market is a superset of the trading strategy:

```text
complete target-market awareness
-> cheap development observation
-> permissive promotion / reactivation
-> exact existing strategy qualification
-> capital decision
-> full-fidelity execution observation
```

Cost optimization may reduce observation depth and duplication. It may not reduce
market breadth, strategy eligibility, execution timeliness, open-position safety,
canonical correctness, or recovery.

## 1. Discovery is broader than qualification

A candidate may not be hidden merely because it does not currently resemble an
entry setup. Cheap discovery and development-state evidence must remain broad enough
to see any asset in the intended target market that could later qualify.

Discovery/promotional evidence has no trade authority.

## 2. Permanent vs recoverable state

Every observation-side rejection must be interpreted as one of:

- **permanent/structural**: the current economic identity can no longer qualify under
  the existing strategy; or
- **recoverable/temporary**: the condition can improve before the strategy's real
  expiry/deadline.

Recoverable candidates remain observable or periodically rescoutable. A temporary
failure is never a permanent tombstone.

## 3. Capital-independent qualification

The order is:

```text
observe -> reconstruct required evidence -> qualify -> record -> funding/execution
```

Capital availability is execution authority only. A candidate that passes the
strategy must remain durably identifiable as strategy-qualified even when funding
is unavailable. Funding denial may not censor qualification.

## 4. Candidate counts are scheduling pressure, not strategy authority

Candidate-count limits, full-evidence budgets, queue sizes, and provider budgets may
control scheduling or expose capacity pressure. They may not silently delete an
otherwise recoverable opportunity.

If machinery cannot keep up, report a capacity deficit. Do not convert it into an
economic rejection.

## 5. Promotion is deliberately permissive

Richer observation may begin before exact strategy thresholds are crossed so required
history can be warmed in time. Promotion thresholds have no entry authority.

A candidate may also be re-promoted by new market activity/acceleration after prior
weakness. The system must support:

```text
quiet -> developing -> near qualification -> quiet -> reactivated -> qualified
```

## 6. Compact market-awareness history

Retain the cheapest useful trajectory for the broader target market: economic
identity/lineage, discovery time, lifecycle transitions, compact market state and
promotion/demotion timing where available.

This history is research/observability evidence only. It has no qualification,
capital, or execution authority and does not justify a universal raw-transaction
fire hose.

## 7. Current and Survivor are independent

Current rejection, exit, lack of funding, observation demotion, or expiry of a
Current-specific window must not suppress later Survivor observation or eligibility.

Current and Survivor may share canonical market evidence but retain independent
eligibility and lifecycle state.

## 8. History may be hydrated selectively

Expensive history need not be maintained continuously for every candidate if it can
be reconstructed authoritatively before the strategy decision deadline.

If required history cannot be completed in time, admission fails closed and the miss
is recorded as an observability/warming failure, not a strategy rejection.

## 9. Open positions leave economy mode

Once capital is deployed, required position evidence has priority over cost saving.

Priority order:

1. safety and required settlement;
2. open-position management;
3. continuation / right-tail / staged-add management;
4. near-qualification candidates;
5. development watch;
6. broad discovery.

No optimization may materially delay stops, safety exits, structural exits, trailing
logic, high-water updates, Current tail bridge, staged winner scaling, Meteora
confirmation sequencing, or reconciliation.

## 10. Existing active strategy economics remain unchanged

The nine approved changes remain authoritative, including:

- directional 5% targets and realized-equity compounding;
- Pump Current exit package;
- Pons Current exit package;
- Current -> Survivor preservation;
- common right-tail behavior;
- Current tail bridge;
- staged winner scaling;
- Meteora exit optimization.

This contract does not alter those economics.

## 11. Two recall standards

### Strategy recall

Every candidate that becomes valid under the active strategy must be discovered,
retained, promoted, warmed and evaluated in time to preserve the original executable
decision.

### Opportunity-awareness recall

Major target-market opportunities should at least be visible in the cheap broad
awareness layer even when the active strategy ultimately rejects them. A strategy
rejection is a strategy/research result; failure to see the developing asset is an
observability defect.

## 12. Acceptance rule

An optimized evidence plane is acceptable only if it preserves:

- intended market breadth;
- recoverable-candidate retention;
- Current -> Survivor independence;
- capital-independent qualification;
- on-time entry/exit/scaling decisions;
- right-tail/high-water continuity;
- open-position monitoring;
- canonical evidence and replay/recovery;
- fail-closed behavior when evidence is incomplete.

**Reduce observation depth, not opportunity breadth.**
