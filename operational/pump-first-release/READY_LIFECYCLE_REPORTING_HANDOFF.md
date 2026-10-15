# Ready lifecycle and reporting implementation

Addressed to the integration owner of `engineering/pump-history-separation-20261013`.
This is source publication only. It grants no deployment, PAPER restart, funding,
provider workload or acceptance credit. Return to the existing reliable one-hour
PAPER objective under the owner's operating instructions after integration.

## Source and integration

Assessment reference: `c3c753c3bdf8bf6e3dd5c253e21799fb52e8d743`.
Actual base: `e8f7d2ec8ccc0d530c94171390e1966d5c42a70f`.
The clean integration checkout and remote were reconciled at that newer base;
its Pump history/economics work and integrated Pons failure diagnostics are retained.
Other sessions' checkouts were read only. Task worktree:
`/root/Documents/Codex/2026-10-13/the-meme-machine-implement-ready-lifecycle/repo`.

Publication branch: `implementation/ready-lifecycle-reporting-20261013`.
Source commits, in integration order:

1. `41dd376471e59fe29d41bd8d243f8922357efef0`: Current confirmation evidence and breadth reporting.
2. `d3b0350c9bd56143356b5fba3546a5851847216a`: native component reporting and retention coverage.
3. `2188fb47721c01a7f60f7025a2076328a0f9ad85`: Pons attempt/filled references, exact joins, release ACKs and generation fence.

The subsequent documentation commit adds this handoff. Exact published head/tree,
remote verification, artifact checksums and regression inventory are recorded in
`../PUBLICATION_RECEIPT.json` in the task workspace. All commits use the existing
`[skip ci]`, normal branch-push workflow. No PR, merge, deployment or workflow
dispatch is part of this assignment. Integrate these commits into the owner's
current branch and run the focused affected-path checks on that combined source.

## Implemented behavior

Verified never-filled cancellation requires complete exact native lifecycle
history, explicit zero paid cost/entry quantity, terminal cancellation, no exposure
or pending execution, and native/cohort/sleeve/portfolio release evidence. Summary
status, exceptions, absent fields and current zero holdings do not establish it.
Provider usage and incurred costs are unchanged. Active, unresolved or late-ACK
outcomes block another conflicting attempt.

Last attempt and last genuinely filled trade are distinct derived checkpoint
references. A later cancellation retains an earlier filled trade's original reset
reference; without an earlier relevant filled trade it adds no post-trade reset.
Fresh generation, full qualification, execution economics, capital, scheduling and
freshness checks still apply. The existing plane transaction now claims a Pons
entry generation once even across concurrent, different native controller paths.

Original qualifying vector digest and market timestamp bind to native reservation
and recovery evidence. Missing/conflicting joins remain unresolved. Derived
references update at collection/recovery/checkpoint boundaries, including delayed
ACK repair; nomination does not scan historical trials. Existing reset predicate,
thresholds, elapsed requirement and changed-dimension count are unchanged. Decision
records expose reference identities, elapsed result, signed ETA/progress/concentration
changes, changed dimensions, new groups, reset/qualification results and missing fields.

Current pre/post-graduation streaks consume complete canonical frontier/covered
market time once. Replay cannot increment or clear them. Fresh adverse/healthy
observations update them; missing data does neither. Existing history invalidation
and non-overlapping coverage break continuity. Checkpoints retain consumed identity
and streak atomically. Committed exit obligations, hard stops, trails, partials and
precedence remain intact. Lifetime-new buyer growth is named explicitly; loaded
rolling active group counts are separate reporting fields. Survivor policy is unchanged.

Actual original/add reporting uses native quantities, booked costs, sale quantities,
basis releases and net proceeds. The documented pooled integer convention conserves
quantity/basis/P&L at every event and deducts no included costs again. Native prefixes,
completed records and existing retirement facts preserve component detail; folded
component totals retain coverage after individual learning records expire. See
`COMPONENT_PERFORMANCE_REPORTING.md` for rounding, units and consumer conventions.

## Focused offline validation

CPython 3.12.14 and the repository's network-guarded `operational.tests` driver were
used with temporary fixtures. No reference-package results substitute for these checks.
Final retained results contain **235 distinct passing tests** (238 executions because
three relevant cases were repeated after review/source changes or an overlap concern).

| Retained task log | Passed | Test seconds |
| --- | ---: | ---: |
| `native-final-regressions.log` | 24 | 11.949 |
| `component-focused-final.log` | 12 | 3.425 |
| `generation-focused-initial.log` | 48 | 1.907 |
| `generation-focused-final.log` | 2 | 0.279 |
| `policy-accounting-regressions.log` | 100 | 2.631 |
| `lifecycle-integration-regressions.log` | 52 | 102.954 |

These exercise actual Current lifecycle loops, zero-fill/earlier-fill sequence,
delayed capital/sleeve/portfolio ACKs, concurrent generation/controller ownership,
native prefix/restart/retirement, missing/conflicting joins, signed reset parity,
exact component attribution before/after adds and partial/final sales, and independent
Survivor/accounting/protective behavior. The retention slice includes existing bounded
prefix fixtures; it was not repeated. Exact commands/modules/cases are in the receipt.
`git diff --check` passes. AST/source comparison confirms unchanged `reentry_regime_reset`,
`REENTRY_POLICY`, `ENTRY_THRESHOLDS`, `EXIT_POLICY` and `POLICY` against the actual base.

One expanded ACK fixture initially failed because it tried to create new legacy
combined funding under the existing shared-selection guard. Only the historical
fixture construction was corrected; production guards and assertions were preserved.
Failure log `reentry-focused-final.log` and scratch `/tmp/mm-engineering-8edb7ixy`
remain available. The corrected cases pass in `native-final-regressions.log`.

Host coordination limitation: the short initial generation batch overlapped the
owner's `HISTORY_REFINEMENT_PONS_CI_FAILURE_ISOLATION_20261013` offline capacity batch.
No active profiling process was observed. Further tests waited for that batch to end;
the two new generation cases were repeated separately. Subsequent launches used a
task-local process guard. This is observed non-overlap, not resource isolation or a
reserved test window; no timings here establish market/operating performance.

## Evidence limits and remaining handoff

There is no unresolved source implementation blocker. Owner combined-branch
integration remains necessary. Relevant legacy filled records without an immutable
exact vector/time join deliberately stay unresolved. No clock or historical reference
is fabricated. Normal native retirement proves a curve has exceeded Current's unchanged
900-second eligibility horizon before removing its acknowledged derived map entry;
original reference identity/time facts first enter existing selective terminal learning.
This is not a permanent full-history archive. An eligible or unresolved earlier filled
reference is never erased by cancellation or age alone. Survivor eligibility is independent.

Missing/retired component detail remains unavailable with authoritative totals retained.
The shared-capital snapshot lacks native component executions, so its export reports
an unavailable split with separate USD totals. Native adapters/prefix/completion consumers
provide available facts for Pump Current and Pump/Pons Survivor. Selective learning rows
are labeled as such; missing older records and unknown historical cancellation counts
are exposed rather than presented as a complete trade population.

No excluded strategy experiment, threshold optimization, no-add simulation, shadow
infrastructure, new feed, provider backfill, blacklist or position restriction was added.
No improved-profitability, Pons operating-readiness or acceptance claim is made.
Operating-state changes: **none**. Final read-only service observation: inactive/dead,
disabled, MainPID 0. No operating database was edited or used as a test fixture; no
funding, provider work, infrastructure purchase or operating restart occurred.

## Changed files

Source: `meme_machine/lanes/pons/{pons_reentry.py,pons_selective_capital.py,pons_selective_cohort.py,pons_selective_continuation.py,pons_selective_paper.py,pons_selective_recovery.py}`;
`meme_machine/runtime/{component_performance.py,learning.py,pons_terminal_archive.py,robinhood/plane.py,storage.py,survivor_paper_book.py,survivor_terminal_archive.py}`;
`meme_machine/shared_capital/{native_sleeve.py,reporting.py}`.

Regression files: `tests/lanes/pons/{test_pons_current_recovery.py,test_pons_entry_confirmation_ordering.py}`;
`tests/{test_learning_retention.py,test_robinhood_plane.py,test_survivor_terminal_retirement.py}`.
Documentation: this handoff and `operational/pump-first-release/COMPONENT_PERFORMANCE_REPORTING.md`.
