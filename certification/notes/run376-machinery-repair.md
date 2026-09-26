# Run 376 machinery repair and integration

PAPER only. No strategy parameters or provider topology changed.

## Evidence and source identity

- Incident workflow 36265299828, number 376, native smoke
  `d93ddf14-b126-4ff9-a92a-0b7bf5e5afa6`.
- GitHub's incident SHA is `2d93e6b5fdb751a3a3e9b057cca759bb0549839f`.
  The supplied task SHA has a one-character transcription error.
- Primary artifact 10914286247, SHA-256
  `570ea57cd361569d98d6486e311b7de6749b32479f24addc25959da8b079da5c`.
  Preserved complete review 10913846765 verifies the primary archive digest;
  compact diagnostics 10913781758 and terminal state 10913503683 corroborate it.
- Six-regime integration base `6c0f78a8b112df90564586fe59ba1288df6a5c53`,
  successful full certificate 36265768097, promoted `cert/prospective-market-v1`.

## Causes and repairs

1. Block-only batching split at interleaved account notifications. Run 376
   had 3,070 account records among 3,963 accepted observations in the reviewed
   snapshot; only 71 transactions were saved by 803 block batches. Mixed
   block/account batches now share one durable commit, retain exact wire order
   and per-frame savepoints, and retain the 8-frame/16-MiB commit bound.
2. Receive admission discarded the next frame on hitting local capacity, even
   when the ordered committer could drain the accepted backlog. Admission now
   reserves space for one maximum frame before receive and waits for durable
   commits to free capacity. The original 64-frame/96-MiB bounds and bounded
   protocol queue remain. Oversize/transport discontinuities still drain accepted
   predecessors and create explicit gaps. Owner queue/execution and admission
   wait telemetry are bounded and final counters are persisted at shutdown.
3. Successful smoke unconditionally enabled hourly workflow progression.
   Explicit phase authorization is checked before state mutation and before
   native work. Smoke-only success ends as `SMOKE_COMPLETE`. A phase that never
   starts native work has `not_started` exposure, not invented unresolved exposure.
4. Readiness trusted current frontier/process/accounting health despite local
   evidence censorship. It now separately classifies continuity, local gap
   blocking and capacity failures. Six-regime manifests, shared sleeve accounting
   and active Survivor evidence-worker progression are also verified. No trade
   or qualifier requirement was introduced.

The existing Pons WAL and bounded provider retry/governor repairs are preserved.
Recovered isolated 429s do not justify strategy or topology changes.

## Deterministic evidence

- `tests/test_run376_dispatch_pressure.py`: mixed 4-MiB block/account traffic,
  memory bounds, durability, ordering, candidate coverage, invalid-frame boundary,
  saturated receive admission. The original mixed workload reproduced capacity
  overflow before repair. The admission saturation test fails source 8288897
  with a capacity disconnect and passes the repaired source without frame loss.
- `tests/test_run373_dispatch_throughput.py`: existing throughput/batch bounds
  plus oversized-frame drain before fail-closed gap creation.
- `certification/tests/test_run376_readiness_authority.py`: preserved Run 376
  smoke cannot pass; unauthorized hourly cannot mutate state or dispatch;
  no-native-run exposure is distinguished; healthy zero-trade smoke can pass.

## Certification iteration 1

Candidate `828889709eb44eadc0254b066816aff1b0dea2cb` did not touch the market.
Full non-market run 36267616463 passed 357 supervisor tests and Pons/Meteora/Ramses
component suites, but Pump's accelerated mixed replay overflowed. Standard CI
36267616095 also exposed a fixture subscription-ACK timing race. The fixture now
waits for the actual ACK, and admission saturation is reproduced independently
of host speed. Failed certificate artifact 10914319643, SHA-256
`8a1267e0490a4ec295ae6ac5b58855074e81ade2a6e6d0eb46a13a00b64eab1c`.

The resulting candidate requires a new complete exact-SHA certificate before
any smoke. This note is not a certification or a market-success assertion.
