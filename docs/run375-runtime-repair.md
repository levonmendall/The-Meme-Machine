# Run 375 runtime repair

Incident workflow: `36260920839` (Run 375)  
Incident SHA: `87679280006ebf22c8b410fdf558658d190fd235`

Run 375 failed for two independent runtime reasons while remaining PAPER-only.

## Pons telemetry race

`certification/robinhood/provider_usage.py::snapshot` used an
`exists() -> stat()` sequence for the SQLite WAL sidecar. SQLite checkpointed
and removed the WAL between those calls, causing `FileNotFoundError` and an
unexpected Pons process exit after about 522 seconds.

The repair performs one race-safe `stat()` and treats only
`FileNotFoundError` as a zero-byte transient sidecar. Other filesystem errors
remain visible.

## Solana evidence-plane write amplification

The preserved Run 375 evidence store contained 186,131
`stream_deliveries` rows and 186,131 `stream_order` rows. Pump and PumpSwap
never consume transaction-order rows, while full-block ingestion already
processes the entire authenticated census in one atomic outer SQLite
transaction.

The repair:

- records one `stream_completions` census digest per fully processed scope/block;
- uses that atomic completion receipt when sealing interval coverage;
- retains per-signature delivery rows for independent log-notification compatibility;
- retains `stream_order` only for transaction-mode evidence consumed by Meteora;
- batches Pump/PumpSwap log-decoded events into one bounded ingest per block
  instead of one ingest/savepoint per transaction;
- leaves the 64-frame / 96 MiB dispatch bounds, ordered commits, fail-closed
  discontinuities, evidence requirements, provider limits, and PAPER authority
  unchanged.

Focused regressions cover the disappearing-WAL race, the block-completion proof
path, Run 373 sustained dispatch pressure, Run 372 large-frame keepalive, and
prepared Pump/Meteora runtime composition.

No market workflow is authorized by this repair.
