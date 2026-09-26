# Run 372 Solana large-frame transport repair

Base runtime: `dd0615ae66f84b0e0caf1efae53db3550a7e7019`.

Run 372 showed eight `local_receive_backpressure_ping_timeout` disconnects after
270 accepted finalized block messages totaling about 1.62 GB. The expected Run 371
dispatch-queue telemetry was absent from every compact live snapshot. Inspection of
`certification/sources.json` confirmed the integration-root websocket decoupling
had never been composed into the frozen Pump or Meteora lane worktrees.

This repair makes the Solana evidence service an explicit integration-owned overlay
for both Solana lanes, verifies exact byte equality during source-integrity checks,
and stages it into each prepared worktree. Large raw provider frames are now queued
behind a bounded message+byte budget, credential-scanned and JSON-decoded off the
websocket event loop, while a watchdog records peak event-loop lag and transport
queue/decode telemetry.

A deterministic regression feeds four approximately 7 MB finalized block messages,
artificially slows decoding, and requires the event loop to remain responsive while
coverage is completed without ping-timeout or dispatch-capacity disconnects.

PAPER ONLY. No market workflow is authorized by this repair or its certification.

Focused regression note: small-message queue depth remains 64, while a 96 MiB byte cap bounds large-frame memory.

Large-frame decode now crosses a spawned-process boundary; only compact program-relevant transactions return to the service process.

Transport hardening: websocket application receive now requests raw bytes; multi-MB decode/filter remains isolated in a spawned worker process.

Composition hardening: shared Pump/PumpSwap protocol decoding is now strategy-independent and staged identically into Pump and Meteora worktrees.
