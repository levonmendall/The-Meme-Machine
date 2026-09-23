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
- Pump/Pons native discovery records precede strategy-domain screening. Those
  broad event counts are acquisition activity, not observed target market. Both
  the full target denominator and target observation counts remain unknown where
  membership is not preserved. The separate acquisition funnel, incomplete
  evidence, latency and source-loss classifications remain visible.

Coverage is not inferred from profitability. Open position monitoring is allowed
to follow that same position through state changes under its frozen lifecycle;
entry-scope filters are not retroactively applied as exits.

## Recovery and exact-SHA gates

This repair batch requires a new full exact-SHA certificate and successor v5
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

Fresh v5 admission begins only when all four predecessor native books are
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

## Preserved recovery checkpoint and successor

Run `35931988977` on `e5f45fa6c88aa9228ca8b8a5d15f9ded6cd48c71`
passed all full non-market gates. Its Ramses recovery then failed at the receipt-set
equality check before any native monitor or settlement. The individual log check
already ignored the optional provider `blockTimestamp` annotation; the aggregate
comparison had not adopted that same contract. The retained public census event
has `blockTimestamp=0x0`. The repair uses the existing exact identity/payload
comparison throughout. Matching authenticated headers remain the time authority;
missing events, changed payloads, unknown extensions and terminal inequality fail.

The successor restores artifact `10781229175`, digest
`285b2096ce08d02a81f2affe8b4b471a7f7bc9d3720cd9465cbff684d2671ea5`.
It retains the original two-event Ramses reserve/open journal and its original
clock/geometry/costs, 73 successful observation pages, the Pons zero-fill cancel
acknowledgement, the previous authorization and the append-only artifact chain.
Only this stopped, digest-pinned checkpoint can bridge to the next certified SHA.
It does not restore the earlier genesis artifact over newer recovery state.

The sanitized worker environment now carries the actual checked-out runtime SHA.
Continuation traces likewise bind to the checkout instead of the workflow ref.
The v4 cohort is durably HALTED on state commit
`52da07457d2fff936ae1dc9f8f9f4c8950c5e081`; it has zero prospective blocks.
Candidate `0aba736158b3b09a9de6641f9f23ef9044e93d66` also passed its
full certificate in `35932858225`, then correctly refused to clone the earlier
genesis because recovery had already started. Neither candidate starts new market
collection. The v5 successor requires its own full exact-SHA certification.
