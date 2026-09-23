# Four-lane market assurance and preserved-position recovery

The strategies, policy hashes, entry/exit economics, provider pacing, quote assets
and target-market definitions remain frozen. Observation counts refer to each
strategy's approved target market. Broader source rows needed to identify those
targets are acquisition overhead and never count as target-market coverage.

## Sealed predecessor

Runtime `b57835dc50dd4047cefed13cfe0be975779af1e8` was certified by full run
`35920022541`. Market run `35921058163` completed normally with a failed smoke;
this task did not cancel it. The v3 program is HALTED at state commit
`82695be7a2206b8714c528408da05efbaf47d48b`, with zero accepted economic blocks.

Artifact `10777564248` has SHA-256
`7675f47346844a4ae0fac4dea0bb8187519b9fbb8b2697b1a51e47aaa17154b4`.
Original raw artifacts and native journals remain unchanged. The public rollup is
`results/market-assurance-35921058163.json`; private raw evidence is not committed.

- Pump and Meteora had no native entries or settlements.
- Pons had two unfilled cancellations, zero token fills and zero natural
  settlements. One legitimate native cancellation lacked its cohort reserve
  acknowledgement. A stale cohort reservation is not evidence of a filled trade.
- Ramses had one genuine native reserve/open pair and no native monitoring or
  settlement before a lifetime request budget was exhausted by ten-block log
  pagination. Its exact proposal, costs, entry time and funded book are preserved.

No profitability conclusion follows from this failed smoke.

## Engineering changes

1. A post-decision bounded trace records typed inputs, mutated strategy state,
   outcomes, runtime/source/version/policy identity and a hash chain. A separate
   process replays frozen decision functions without network or ledger writes.
   Capture failures, missing records and divergence cannot become accepted blocks.
   Zero decisions explicitly mean an unexercised surface, not a natural lifecycle.
2. Post-block assurance reuses retained telemetry, source responses and native
   journals opened read-only. It separates operational validity, market-observation
   validity and economics. Unknown denominators and unavailable marks remain null.
3. Pons completes the already-authorized cohort acknowledgement when an unfilled
   entry is cancelled after fill-time persistence checks.
4. Ramses uses the existing public observation endpoint's 1,000-block log pages,
   durable reuse of successful pages and unchanged one-request/one-second pacing.
   Receipt/header/state authentication remains authoritative. Monitoring request
   counters are bounded per operation rather than across a seven-day position;
   authenticated immutable caches, physical pacing and retry limits are retained.
   Transient 500/502/503/504 responses preserve the position for the next normal
   monitoring attempt and do not invent an exit.
5. Ramses asynchronous monitoring uses another connection to the existing funded
   campaign book. A write-ahead bridge restores either side of an interrupted
   native checkpoint without duplicate costs, a second entry or state reset.
6. Meteora marks durably record elapsed observation time, raw/eligible exit
   reasons and consecutive-collapse counters. Continuation applies the same
   four-hour core hold and full confirmation segments as the native strategy.
7. Smoke boundaries can preserve valid LP handoffs. Fresh campaign admission
   waits for terminal native proofs, then reuses the admitted exact-SHA smoke.
   Smoke continuations never become profitability samples.

## Measured breadth and limits

The frozen sources remain the acquisition plan, not permission to broaden or
silently narrow a strategy's target market. No numerical breadth threshold was
introduced. Existing infrastructure censoring remains the economic gate.

- Meteora acquired one of six configured ranking pages. Its 250 raw source rows
  contained 186 exact-one-WSOL pairs; 17 reached discovery, or 9.1398% of that
  acquired pair subset. Five pages and 169 acquired pairs were not processed in
  the observation window. Discovery and expensive evidence share an ordered lazy
  generator, which explains this observed source gap. The source API's global
  total includes out-of-target pairs. Neither that total nor the six-page union
  is a fabricated full strategy-target denominator. Full target coverage is
  unknown. Missing pages and within-page attrition are explicitly reported.
- Ramses acquired a complete 287-pool factory census, but only four authenticated
  target candidates reached the native candidate funnel. The 287 factory rows
  are not counted as 287 observed strategy opportunities. New reports preserve
  preflight truncation and identity failures so a complete target denominator is
  claimed only when those counts establish it.
- Pump/Pons absolute independent target denominators are unavailable. Native
  funnels, incomplete evidence, latency and source-loss classifications remain
  visible; they do not become fictitious 100% coverage.

Coverage is not inferred from profitability. Open position monitoring is allowed
to follow that same position through state changes under its frozen lifecycle;
entry-scope filters are not retroactively applied as exits.

## Recovery and exact-SHA gates

This repair batch requires a new full exact-SHA certificate and successor v4
cohort because actual accounting/lifecycle defects required runtime changes.
The v3 cohort is not reset merely for optional reporting.

The all-market workflow first runs every non-market gate. Only then may it restore
the digest-pinned predecessor on a copy, append the missing proven Pons cancel
acknowledgement and continue the original Ramses position. The recovery bridge
accepts only the reviewed predecessor, unchanged frozen policy and certified
successor SHA. Each slice preserves its artifact chain, native event prefix,
decision replay and accounting proof. It cannot initiate a new position.
The first recovery slice observes for 300 seconds after initial authentication;
an open position then continues in the regular 3,000-second slices. This exercises
one real artifact transfer promptly without changing any strategy clock or exit.

Fresh v4 admission begins only when all four predecessor native books are
verified flat. There is no forced exit or deadline substitute. A legitimate
long position may require further bounded continuation workflows. Engineering
recovery and smoke evidence remain excluded from prospective economics.

Local checks passed: 1,404 native tests, 157 supervisor tests, existing resource
gates, clean overlay reproduction, native decision capture/replay, process-cut
checkpoint replay, shared smoke/hourly books, and idempotent recovery seeding on
copies of the sealed evidence. This local result is not a hosted exact-SHA
certificate or a natural-market lifecycle claim. The workflow artifact and state
branch remain the durable authority for the next run and its outcomes.

The first hosted candidate, `f24811098a39745ccc8734203bef46992949a704`,
failed the Meteora component suite's unchanged 300-second limit in run
`35930615830`. Recovery was skipped. Its artifact `10780584763` has digest
`01ec27aed616dcffdda1f7d7bb3e8ff3338a4e5e7a0983e8a38b4869da9096ab`.
The new strategy-progress record had copied the full start snapshot into every
mark. Repeated native journal replay amplified that avoidable serialization cost.
Normal marks now reference the already-preserved preceding state by hash; an
actual recovery change still preserves its full distinct start state. A process-cut
regression verifies restoration without resetting elapsed time or shortening a
confirmation segment. The suite timeout and native economic rules are unchanged.
The complete local Meteora suite passed all 421 tests in 142.183 seconds after the
change, compared with 253.047 seconds before it. Restoring prior marks also avoids
duplicating old decisions in the new live trace; restoration still verifies their
saved inputs, counters and outcomes.
