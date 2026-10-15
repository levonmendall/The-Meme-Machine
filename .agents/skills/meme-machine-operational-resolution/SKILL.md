---
name: meme-machine-operational-resolution
description: Use for Meme Machine Pump/Pons operational defects, startup and shutdown failures, SQLite/provider bottlenecks, performance attribution, and release readiness. Diagnose retained evidence first; use risk-based diagnostic validation and reserve complete suites for release promotion or demonstrated broad risk.
---

# Meme Machine operational resolution

This skill standardizes investigations; it does not grant deployment, provider-workload, funding, or trading authority. Follow repository `AGENTS.md` and current owner scope.

Current owner standing scope: [issue134](https://github.com/levonmendall/The-Meme-Machine/issues/134), effective until revoked. The owner removed the global three-start limit, 24-hour expiry and routine per-run approval requirement. Repeated sequential live-provider capability checks, compatible deployment and guarded PAPER diagnosis are authorized after cause-based analysis, affected validation and fresh safety preflight. The original per-run one-start controller and readiness/resource/shutdown bounds remain. Diagnosis stays funding closed; once original gates and final release validation pass, the standing scope also permits actual one-hour simulated acceptance and sustained autonomous PAPER under the existing policy. No real-money orders, new capital, strategy-policy expansion, provider quota increases or infrastructure purchase. Never interpret a numbered historical campaign or expired one-time permission in an old handoff as a new active approval gate.

## Work from the actual state

1. Read the latest owned branch/handoff and retained first-error, native-drain, portfolio, provider, and CI receipts. Confirm exact source, workload, identity, and freshness; do not reuse obsolete “ready” claims.
2. Separate **monetary reconciliation**, **native recovery**, **graceful drainage**, **readiness**, **sustained throughput**, and **held protection**. One PASS never implies another.
3. Build one causal failure chain for related problems. Mark each finding **observed**, **offline reproduced**, **hypothesis**, or **live evidence required**. Never fill missing counters with zero.
4. Classify the demonstrated cause as an isolated implementation defect, a shared subsystem contract defect, or a systemic architectural limitation. Select a complete evidence-supported correction with the least justified complexity, rather than automatically preferring a local patch. Keep existing strategy economics (active opportunity-access v1, nine changes, volume-quality), deadlines, financial authority/state and provider safeguards unchanged unless the owner explicitly approves a change.

## Correct the shared cause when demonstrated

Escalate to one bounded review of the affected subsystem when failures share an invariant/ownership/recovery path, two corrections fail to resolve the mechanism, fixes repeatedly cause connected failures, measured capacity remains inadequate, workarounds accumulate, or mandatory deadlines remain unattainable. Do not reopen unrelated completed investigations or infer a common cause from exceptions alone.

Compare retaining the design with a targeted correction, refactoring the affected subsystem, and replacing its problematic mechanism. Evaluate causal evidence, end-to-end throughput/latency, CPU/storage/provider demand, recovery, persistent-state compatibility, opportunity/protection preservation, complexity, implementation/verification time and maintenance. Develop a justified subsystem solution offline without duplicating pipelines or authoritative writers. Material changes require affected integration and appropriate broader validation before live deployment; financial authority, economics, protective safeguards or incompatible state-contract changes require explicit design approval before deployment.

Verify the full relevant outcome, not just absence of an exception: processing/commit/publication and backlog for throughput; restoration, pending-work preservation, cancellation and native drain for recovery; complete quote/USD deadlines for Pons; consistency and uninterrupted protection for maintenance. Synthetic proof remains synthetic. If the causal discriminator is missing, name it and stop that branch instead of adding another speculative patch. After interruption, preserve the historical failed or unverified drain verdict; do not require a retroactive graceful-shutdown PASS. Establish whether the current authoritative state is consistent, recoverable and safely resumable. Classify unavailable evidence honestly and require separately authorized recovery operations when read-only checks and disposable rehearsals cannot establish that boundary. Resume runtime only under its applicable current-state recovery gate and fresh preflight, never by treating monetary flatness or empty processes as native recovery.

## Evidence and testing tiers

- **Narrow edit:** invoke only affected named modules or cases under the repository network guard, e.g. `python -m operational.tests FAST --modules tests.test_current_combined_diagnostic`. Modules outside FAST use `OPERATIONAL --modules`. Test negative/fault-injection paths, not just happy-path assertions.
- **Subsystem integration:** add adjacent owner/provider/recovery/strategy invariants; for supervisor/startup/shutdown work use existing `tests.test_integrated_startup_rehearsal` and actual disposable child paths. This fixture is NOT a faithful market replay or a sustained-capacity proof.
- **Funding-closed diagnostic candidate:** apply the risk-based gate below. Full FAST or complete OPERATIONAL is not automatically required after a repair or before this diagnostic. Focused-test success is scoped evidence, never a general release PASS.
- **Final one-hour acceptance/normal-operation candidate:** freeze the combined executable when genuinely ready for promotion, then run one complete FAST and the applicable complete OPERATIONAL release validation on that exact candidate. A change with demonstrated broad safety/dependency risk can require broader validation earlier; record the specific reason and scope. Preserve skip/failure disclosures. After subsequent changes, rerun affected checks and release checks actually invalidated; reuse still-valid evidence instead of repeating unrelated suites.
- Prefer draft PRs and separate worktrees for iterative changes. Consolidate related fixes before the next integration checkpoint, using one integration/test owner. Do not manually dispatch full FAST after every draft repair or mark a draft ready just to trigger CI. Publish scoped diagnostic evidence separately from a promotion claim.
- Let useful running CI finish unless it becomes obsolete. Do not repeatedly poll `gh run view`, create replacement polling/watch loops, or duplicate the running suite. Continue independent lightweight offline engineering without competing resource-heavy tests/profilers. Obtain the terminal result at a meaningful checkpoint; canceled/superseded runs, draft skips and fragmented suites are not passes.

## Risk-based diagnostic validation gate

Use existing tests, receipts and preflight machinery; this is not a new permission or certification system. Record the exact candidate and changed dependencies, then require:

1. **Affected behavior:** focused network-blocked tests on the combined source, including the demonstrated failure and relevant negative, replay, cancellation and restart paths. Consolidate related fixes before shared-path integration testing.
2. **Actual startup:** run the existing integrated startup rehearsal and actual disposable supervisor/child paths when startup, configuration propagation, worker lifecycle, native recovery or shutdown dependencies change. Preserve pending work and accurate unfinished-reconciliation status. Synthetic rehearsal is not authentic market replay or throughput proof.
3. **Source and economics:** run the applicable exact source-integrity guards and relevant strategy-policy regressions. Preserve all six active opportunity-access changes, nine original economic changes, attention-only volume-quality behavior, Current/Survivor independence and the existing $1,000 epoch/historical accounting. Never broaden a source exemption or weaken an assertion to obtain a pass.
4. **Safety dependencies:** run the accounting/authority, canonical completeness/durable delivery, provider admission/protection, recovery and maintenance regressions implicated by the edit. Keep original three-/five-second Pons protection, readiness and shutdown requirements. An unmet decision-critical invariant blocks the affected operation; funding closed is not permission to ignore it.
5. **Fresh runtime preflight:** before an independently authorized diagnostic, verify actual source/runtime/configuration, service identity/access, obligations and monetary reconciliation, native pending-work resumability, applicable recovery reference, storage/resources, workload non-overlap and installed provider controls. Reuse valid recovery proofs with fresh applicability checks; do not repeat bulk verification without a changed dependency or evidence requiring it.

Disclose failures, skips, unavailable evidence, remaining live-only questions and why the selected checks cover the diagnostic's risk. A fresh preflight or focused PASS neither authorizes a service start/provider workload nor establishes sustained capacity, held protection, full release readiness or acceptance. Preserve all original safety stops and explicit owner scope. If dependency reach cannot be bounded safely, expand validation with a stated reason or stop that branch; do not silently promote the candidate.

## Live boundary

A live run is appropriate only for genuinely live-only uncertainty (provider throttling, authentic workload throughput, held-position quote/valuation timing). Before executing it under applicable standing authority, record one precise question, expected measured discriminator, current-source identity, preflight, safety stop, bounded clock, recovery reference and shutdown review. Ask only for actions outside that scope or a genuine unresolved external/safety decision. Do not automatically retry unchanged conditions.

Use issue134 standing authority for its expressly covered live-provider, controlled diagnostic/deployment, recovery and conditional PAPER operation; do not request routine per-run reapproval. Actions outside that scope still require their actual owner decision. Real-money trading, infrastructure/service purchases, quota increases and economic-policy expansion remain unauthorized. Do not weaken protection/reconciliation/backup boundaries to get a green result.

## Hand-off format

Report **source commit**, **first supported cause**, **implemented correction**, **focused/full validations with exact verdicts**, **unresolved live-only issue**, **financial/provider/native safety**, and **single next decision**. Preserve original receipts; link existing evidence rather than duplicating large artifacts.
