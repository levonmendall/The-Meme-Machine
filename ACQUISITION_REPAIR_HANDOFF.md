# Meteora acquisition repair

Source branch research/solana-dlmm-independent-v1, exact source SHA
45836b18c9afdda29909ebe9cb68d386a47b074f. Stacked repair base:
957ff70af2065c7bf0227f00a7fab0f44e0f81f0 (continuous paper campaign).
Frozen v1.7 policy hash
171605162c857d90ef7f880fc7f444dff615e452659e78a2f38fd563acfb6ad5.
No strategy gates, trigger authentication, warmup length, position size,
transaction reconstruction cap, finality or live-money authority changes.

Read-only retained review 35485976103 of smoke 35483374004 proves four of eight
attempts reached authenticated fresh swaps. Every triggered warmup's first
census fetched 16 pages / 1,024 rows although the start-boundary witness was
already present on its first page. Three warmups then failed transaction
hydration; the fourth reached the experiment runtime deadline. The other four
had no observed wakeups and timed out. No economic conclusion follows from
these incomplete vectors.

The broker-backed census now stops a cold query at the exact authenticated
lower boundary. A warm incremental query must finish its bridge to the prior
head; a full page at the pagination cap is explicitly incomplete. New rows and
covered-through metadata are published together only after boundary, cardinality
and transaction-index validation. A failed query cannot poison the durable head
and cause a later retry to skip an unauthenticated chain range. Missing witnesses,
nonfinal rows, duplicate pages and the unchanged 16-transaction bound fail closed.

Shared neutral broker deadline/lease repairs match the Pump EvidenceBroker:
time-sensitive decisions share earliest-deadline ordering, positions remain
first, background research remains last, expired pending work can be re-requested
without wasting a refresh, and active leases stay protected. Meteora's existing
stream classes and trigger-only/economic-reconstruction separation remain intact.

Regression reproductions demonstrate 16 reads reduced to one for the identical
complete cold interval, and show the old code incorrectly publishing coverage
after an incomplete warm bridge or invalid cardinality. All 356 unit tests and
both resource checks pass:
python -m unittest discover -v
python -m tests.resource_check
python -m tests.dlmm_resource_check

Live improvement requires a fresh integrated smoke and four-hour campaign.
This repair is not a natural paper lifecycle or profitability claim.
