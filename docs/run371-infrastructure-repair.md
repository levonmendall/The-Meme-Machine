# Run 371 infrastructure repair

Base runtime: `14c12c671d0e1389584e662b1712e77311330c5f`.

This repair is PAPER-only and does not authorize a market workflow.

## Solana Evidence Plane

The websocket receive path is decoupled from SQLite-owner ingestion so persistence,
compaction, gap repair, and consumer work cannot block protocol receive/pong handling.
The receive side uses a bounded in-process dispatch queue with explicit overflow
telemetry. A deterministic regression reproduces a 23-message burst while the
evidence owner is intentionally slowed and requires the socket to continue draining
without receive-backpressure disconnects or continuity loss.

## Ramses

Transient provider pressure is contained at the individual finalized-frontier poll
or market scan. Exhausted HTTP/RPC 429 and shared-provider admission boundaries
produce an infrastructure-censored/deferred observation and never qualify from a
partial screen. Structural/finality boundaries remain fail-closed and strategy
thresholds, market scope, provider ceilings, and paper-only authority are unchanged.

## Observability

Sanitized process-terminal boundary information is retained in the compact
certification result/readiness handoff. Smoke workflows publish a separate compact
diagnostic artifact so terminal diagnosis does not depend on downloading the full
native evidence archive.

## Certification order

1. Focused Run 371 regressions.
2. Full deterministic/non-market certification on the same exact final SHA.
3. No smoke or market campaign is started by this certification.
