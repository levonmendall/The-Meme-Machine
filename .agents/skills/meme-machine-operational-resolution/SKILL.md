---
name: meme-machine-operational-resolution
description: Use for Meme Machine Pump/Pons operational defects, startup and shutdown failures, SQLite/provider bottlenecks, performance attribution, and release readiness. Diagnose retained evidence first; run focused offline validation and one final integrated release gate.
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
- **Final release candidate:** one complete FAST on the exact final merged executable, preserve skip/failure disclosures; then the applicable OPERATIONAL gate before deployment, with owner-approved exceptions only. Any code change after a release PASS invalidates at least affected checks; ensure final integrated-source proof is current.
- Prefer draft PRs and separate worktrees for iterative changes. Coordinate one integration/test owner and avoid concurrent resource-heavy validation. Existing CI runs complete FAST for review-ready PRs, main, or explicit dispatch; canceled/superseded runs and draft skips are not passes.

## Live boundary

A live run is appropriate only for genuinely live-only uncertainty (provider throttling, authentic workload throughput, held-position quote/valuation timing). Before requesting it, supply one precise question, expected measured discriminator, current-source identity, preflight, safety stop, bounded clock, recovery reference and shutdown review. Do not automatically retry unchanged conditions.

Never issue real market requests, start PAPER, alter provider routing, write authoritative databases, accept trades or purchase infrastructure without separate explicit runtime authorization. Do not weaken protection/reconciliation/backup boundaries to get a green result.

## Hand-off format

Report **source commit**, **first supported cause**, **implemented correction**, **focused/full validations with exact verdicts**, **unresolved live-only issue**, **financial/provider/native safety**, and **single next decision**. Preserve original receipts; link existing evidence rather than duplicating large artifacts.
