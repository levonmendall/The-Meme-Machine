# Separate opt-in rolling-write discriminator

Base source: `4d255c12cbb7f516d06bb31ce3f6af79b8c6be96`.

This component is separate from the frozen Pump reader/Pons candidate. It is not
an approved source, deployment, throughput repair or release. Selecting it for
an integrated candidate requires that candidate's original exact-source guards
and protected receipt projection to be updated and validated explicitly.

The production delta touches only `runtime/operation_costs.py` and
`solana_rolling_history.py`. Six fixed, batch-level spans surround the six
existing `store_many` write calls:

| Operation | Existing write |
| --- | --- |
| `owner.rolling_events_write` | `rolling_economic_events` |
| `owner.rolling_addresses_write` | `rolling_economic_addresses` |
| `owner.rolling_receipts_write` | `candidate_content_receipts` |
| `owner.rolling_order_write` | `native_order_attestations` |
| `owner.rolling_lineage_write` | `rolling_event_lineage` |
| `owner.rolling_cursors_write` | `cursors` |

They use the existing opt-in process-local recorder and fixed numeric schema.
Their wall/thread-CPU spans include construction of the unchanged argument
lists; their selected SQL buckets separately time the original `executemany`
API calls. All six skip runnable sampling, so they add no proc-file reads.
There is no per-record timer, new recorder thread, provider call or disk log.

SQL, parameters, order, transaction/savepoint boundaries, rowcount use,
exceptions, replay fallback, FULL/WAL durability, accounting and ACKs remain
unchanged. When disabled, the fixed contexts do not sample recorder clocks or
proc state. Recorder failures retain the original work/error contract.

The six rows become direct children of `owner.rolling_store`. Its parent total
continues to overlap them; selected write SQL moves to those innermost rows.
Compare the six rows and the parent's residual using complete child timing;
do not add them to the parent. Calls describe executed API work, including work
later rolled back. They do not count committed economic records or coverage.

This initial component deliberately changes no batch/lease diagnostic schema.
Existing `candidate_phase:batch_commit` measures outer context exit, including
rollback. Complete batch size/record/byte cohorts and failure-only maintenance
clock/owner-sequence attribution remain separate capabilities if still needed
after the retained Pons thread-I/O evidence is analyzed. No current terminal
lease label is reclassified by these counters.

Focused checks compare complete native SQL traces and final bytes with the
recorder off/on; preserve the original mid-write exception and atomic rollback;
exercise recorder failure; and concurrently submit two fresh batches through
one real `PriorityOwner`, checking every write's actual owner/context and the
absence of extra runnable probes. Existing bulk/scalar, replay, accounting and
recorder tests remain relevant. No market speed is claimed from these fixtures.
