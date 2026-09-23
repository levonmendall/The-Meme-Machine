# Alchemy scarcity finalization

## Runtime authority

- Solana Pump and Meteora use public finalized Solana WebSockets for discovery/observation and **Alchemy as the only authenticated Solana HTTP evidence provider**.
- OnFinality has no executable/configured runtime role. Prepared Pump and Meteora worktrees fail source certification if executable Python, tests, or workflows contain an OnFinality reference.
- Pump retains every finalized discovery/log hint but campaign mode does not proactively hydrate transaction bodies merely because provider capacity is idle. Transaction bodies are acquired on demand for admitted decision evidence, reconstruction, or open-position lifecycle work.
- Robinhood Pons uses the official sequencer feed plus official public Robinhood RPC for routine broad discovery. Its Alchemy primary remains authoritative for candidate/position evidence and is used as a bounded fallback only when an exact public observation read fails on an allowlisted transport/rate-limit boundary.
- Ramses retains complete factory observation with durable append-only inventory reuse and uses its authenticated DLMM evidence transport for state/reconstruction. No strategy scope is narrowed.

## Preserved controls

Market breadth, raw observation retention, finality/freshness rules, strategy thresholds, position sizing, accounting, paper-only authority, append-only evidence, and fail-closed handling are unchanged.

## Acceptance

Canonical lane source heads and exact applied-diff hashes are pinned in `certification/sources.json`. Hosted non-market certification must pass source integrity, lane suites, restart safety, integrated acceptance, resource gates, historical exposure resolution, and bounded production-adapter connectivity before this work is considered complete.
