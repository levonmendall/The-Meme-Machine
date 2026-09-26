# Latest promoted policies with Run 376–378 runtime repairs

The user explicitly approved using the latest promoted policies on 2026-09-26,
after the threshold task advanced `cert/prospective-market-v1` to
`4ab66653a23475a72abe88bc96adf9f6e0b7fd9a`. This supersedes the original repair
prompt's older numerical thresholds. No additional strategy optimization is made.

The new strategy base passed complete certificate `36273166496`, artifact
`10916441653`, SHA256
`d51783f8a19281af51e6c64e45cf5ecb0707d7b3b9c38e4784e59b1115c2dc1a`.
The archive and exact integration identity were independently verified. It retains
four portfolio lanes and six active PAPER regimes, with both Survivors inside
their original shared sleeves and no additional capital.

Composition merges that exact promoted source with repair head
`b81530c73049291b791f1757ec865339a750dfba`. All promoted policy hashes, active
regime identities, allocation manifests, threshold patches and policy source
bytes are preserved. Conflicts are limited to source-diff hashes, composed
infrastructure hashes and the deterministic integration gate. The approved
Meteora threshold revision gate remains intact. Ramses infrastructure overlays
are distinguished from its unchanged approved strategy. Pons Survivor keeps both
its promoted thresholds and the repaired 200/200 provider session bounds.

## Certification observer failure

Candidate b815's certificate `36273519880` failed one of 1,633 native tests;
all 367 supervisor tests passed. Artifact `10915604816`, SHA256
`e84a7149ffc6d4bc2dcb7ceab7863403978f23943ca532f56837f644b7bf5b2e`, records a
0.609152845-second heartbeat gap against the unchanged 0.5-second limit.
Asyncio attributes 0.588 seconds to the **test coroutine**, at its synchronous
independent SQLite observer before the next polling sleep, not to a service task.

The Run 372 harness opened/read the independently scheduled evidence reader on
the same event loop it was measuring. That allowed observer SQLite/filesystem
latency to manufacture a transport failure. Injecting a 0.60-second reader delay
reproduced the old failure deterministically (0.603022549-second gap).

The independent reader now opens, snapshots and closes off the transport event
loop. All message, coverage, queue, disconnect, process-decode, and durability
assertions remain. Both heartbeat and native loop-lag limits remain 0.5 seconds.
The slow-reader regression passes, while deliberate 0.60-second **receive-loop**
blocking still fails the original limit. No production evidence gate or strategy
threshold is relaxed. Full exact-SHA certification remains mandatory before smoke.

No market run has passed yet. Run 377 remains the latest actual market exposure;
Run 378 and the next launcher attempt stopped before provider-backed native work.
