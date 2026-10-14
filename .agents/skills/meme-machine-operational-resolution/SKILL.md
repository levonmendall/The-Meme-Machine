---
name: meme-machine-operational-resolution
description: Use for Meme Machine Pump/Pons operational defects, startup and shutdown failures, SQLite/provider bottlenecks, performance attribution, and release readiness. Diagnose retained evidence first; use risk-based diagnostic validation and reserve complete suites for release promotion or demonstrated broad risk.
---

# Meme Machine operational resolution

This skill standardizes investigations; it does not grant deployment, provider-workload, funding, or trading authority. Follow repository `AGENTS.md` and current owner scope.

## Work from the actual state

1. Read the latest owned branch/handoff and retained first-error, native-drain, portfolio, provider, and CI receipts. Confirm exact source, workload, identity, and freshness; do not reuse obsolete “ready” claims.
2. Separate **monetary reconciliation**, **native recovery**, **graceful drainage**, **readiness**, **sustained throughput**, and **held protection**. One PASS never implies another.
3. Build one causal failure chain for related problems. Mark each finding **observed**, **offline reproduced**, **hypothesis**, or **live evidence required**. Never fill missing counters with zero.
4. Select the smallest evidence-supported source correction. Keep existing strategy economics (active opportunity-access v1, nine changes, volume-quality), deadlines, SQLite ownership, financial state and provider admission unchanged unless the owner explicitly approves a change.

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

A live run is appropriate only for genuinely live-only uncertainty (provider throttling, authentic workload throughput, held-position quote/valuation timing). Before requesting it, supply one precise question, expected measured discriminator, current-source identity, preflight, safety stop, bounded clock, recovery reference and shutdown review. Do not automatically retry unchanged conditions.

Never issue real market requests, start PAPER, alter provider routing, write authoritative databases, accept trades or purchase infrastructure without separate explicit runtime authorization. Do not weaken protection/reconciliation/backup boundaries to get a green result.

## Hand-off format

Report **source commit**, **first supported cause**, **implemented correction**, **focused/full validations with exact verdicts**, **unresolved live-only issue**, **financial/provider/native safety**, and **single next decision**. Preserve original receipts; link existing evidence rather than duplicating large artifacts.
