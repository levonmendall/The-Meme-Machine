# Run 377 machinery iteration

Run 376 repairs and the complete six-regime runtime were composed on the certified
strategy base `6c0f78a8b112df90564586fe59ba1288df6a5c53`. Candidate
`48e46b27086a8058fcbd7752a42420c1f9186af7` passed full hosted non-market certification
`36268315085` (artifact `10914971713`, SHA256
`da909f3c63b40bd59196f1a6f04213b7e50c248c09a2f4bd845a2a3a2e3eda50`).

One smoke was explicitly authorized on ref
`cert/single-market-run376-six-regime-48e46b-20260926`: Actions `36268952456`, number
377, native `99684511-c93b-48f2-9f88-d4aa8d2c7f7f`. It failed. No promotion occurred.
Hourly and all successors were skipped. Final campaign state is HALTED with native
exposure **flat**, all four reconciled books, and no hourly phase record.

## Preserved evidence

* Primary artifact `10915370907`, 1,049,142,348 bytes, SHA256
  `22dc98ff79f87d45a1c8f12268f64e5d981ed2e4af849d1711b8bc14694ed6cc`.
* Compact diagnostics `10915395749`, SHA256
  `b6d053f24d8fe908a07b7475a4110ae79e20fd116a61f59da1680e5e438bfa8b`.
* Terminal state `10914976710`, SHA256
  `59f38881adc4244edee678dcd4cf2a4d1b9a31b70fbb594789805c0dcff736b4`.
* Read-only, no-provider archive review `36269955790`, reviewer SHA
  `bc1771694ec425196da65f599453432355ab6428`, artifact `10915755490`, SHA256
  `92c630ae0ed08250c0e14ccf4828d9fa66293378902cafb09e2423730f30ee93`.
  It verified the primary archive digest and exact runtime identity and exported
  native logs, provider failures, durable plane state and lossless record samples.

## Findings and repairs

1. **Solana persistence CPU remains material.** Dispatch overflow was eliminated,
   but receive backpressure still caused ping timeouts: terminal plane telemetry
   recorded nine backpressure ping timeouts and one other connection closure,
   33 gaps created/19 repaired/14 unresolved, 568.83 seconds in ordered commit, a 2.60
   second commit peak, 13.76 second ordered wait peak and a 71.36 second background
   owner wait. Pump stopped at 342.11 seconds with finalized evidence stale. The
   lane snapshot had 11 unresolved gaps; the repaired readiness gate rejected it.
   The final shared-plane snapshot is now recorded independently of a stopped
   Pump process and used for both Solana lanes. Ping-timeout backpressure is
   classified as capacity censoring, separately from frontier liveness.

   A CPU profile replayed 1,339 retained transactions across 20 production slots,
   with 73,723 address references. Original writer time was 2.23 seconds; equivalent
   repaired replay was approximately 1.27 seconds on the same host. The dominant
   avoidable work was Unicode regex scanning of large ASCII payloads and repeated
   canonical JSON serialization. A logically equivalent ASCII prefix precheck
   retains the original regex for possible matches and all non-ASCII strings.
   One bounded canonical body now supplies size, identity hash and storage input.
   Lossless compression, all evidence fields, address indexing, source attribution,
   ordering, SQLite FULL durability, and existing memory/queue bounds are retained.

2. **Normal stop cancelled the admitted backlog.** The outer stop waiter won
   FIRST_COMPLETED and cancelled the source's own drain. The regression against
   the Run 377 code admitted 49 frames but committed only three. The repaired
   coordinator waits for source drain, bounded at 30 seconds with an explicit
   fail-closed timeout. The supervisor permits that drain plus protocol teardown
   instead of killing the service after ten seconds. Escalation also cleans up
   the service's own decoder process group and is a readiness failure.

3. **Pons Survivor never constructed its provider session.** All 120 completed
   steps reported `invalid_request_bounds`; requested bounds were 240/220 although
   Rpc permits at most 200. Caller bounds are now 200/200. Provider governance,
   shared pacing, policy, allocation and strategy thresholds are unchanged. The
   real constructor and discovery-watermark regression fails on the old code and
   passes with the repaired caller, including session rotation and shared sleeve.

4. **Ramses RPC -32000 lacks causal message attribution.** At 194.10 seconds,
   authenticated factory count `eth_call` (selector `0x4e937c3a`) at exact block hash
   `0x890a0e9e75346d579b7714346193bbd752903ea6fe6f808687babd0ca7949db1`
   failed. Native transport discarded the RPC message before instrumentation, so
   the original message cannot be recovered. Do not claim its cause is known.
   New bounded telemetry retains code, allowlisted category, truncated length and
   message hash, never provider prose or credentials. Precisely recognized
   missing-block/header responses defer a scan through the existing cadence,
   without positive evidence, partial screening or a new provider. Unknown errors,
   reverts and structural/authentication failures still fail closed. A new smoke
   is necessary only after full certification to resolve any remaining ambiguity.

5. **Archive attempted to read a Unix socket.** The artifact stage aborted on
   `solana-evidence-plane.sqlite.sock`, preventing automatic artifact review.
   Snapshot collection now explicitly records transient socket exclusion and
   continues durable ledger capture. The existing disappearing-WAL regression
   still passes; the successful Run 375 WAL repair is preserved.

## Deterministic evidence

* Old Run 377 writer fails the single-canonical-materialization regression;
  identity hash, decoded payload and 64 address references are verified unchanged.
* Old Run 377 service fails stop-under-backlog (49 admitted versus 3 committed).
* Credential checks preserve ASCII, mixed case, Unicode and configured bare keys.
* Forty blocks of retained production-shaped transaction bodies (160 per block)
  replay through receive, process decode, ordered commit and SQLite with no
  disconnect, complete coverage, all frames drained and <=64 frames/96 MiB.
* Existing Run 376 pressure, ordering, durability and gap regressions remain gates.
* Shared-plane telemetry cannot be masked by Meteora's legacy current frontier.
* A forced evidence-service kill cannot pass smoke readiness.
* Missing-state RPC regression tests single and batch transport, deferred scan,
  later success, secret-safe attribution and terminal unknown/revert behavior.

No market run is authorized by these source changes. The task controller must
first verify the new exact SHA's complete hosted non-market certificate and quiet
market-workflow inventory, then issue one fresh smoke-only authorization.

Runtime repairs are isolated on `repair/run377-runtime-six-regime-20260926`.
The previous repair branch advanced concurrently with an independent, not-yet-promoted
threshold task. Those commits are preserved and are not silently substituted into
this task's frozen six-regime strategy contract.

Candidate `9f9c8a4aaf242acc5ffc636f3ae0fab9ced26865` passed standard CI
`36271244411` (687 tests), but full certificate `36271244619` failed because the
new native Pump/Meteora regression imported an integration-only fixture helper.
Pons (421 tests), Ramses (362 tests), and supervisor passed. No market ran on this
SHA. The regression is now self-contained; its four cases pass from both actual
prepared lane roots. Full certification is required again on the revised SHA.
