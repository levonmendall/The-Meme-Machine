# Consumer-owned Solana evidence scheduling candidate

Prepared on 2026-09-20 while workflow 35489724704 continues at frozen integration
f7ee2b13036abb0171e0001608d589b51d28947e. This candidate does not change, cancel,
restart, or extend that campaign. No new live run or provider is started.

## Evidence and diagnosis

At 05:33:43 UTC the running Pump snapshot reported 26,434 expired broker jobs,
2,730 pending, and 84 complete vectors. The counter is the retained population of
distinct signature jobs currently expired, not cumulative retries or candidates.
Both Solana lanes display this shared state at their own checkpoint times.
An exact-code offline reproduction queued 2,000 signatures before a four-second
hydration loop: 160 hydrated, 1,840 expired with a fault-free simulated provider.
This reproduction used the broker pacing only; the stricter two-request/second
comparison below is the capacity comparison for the proposed repair.

## Change

Every requested signature has a durable consumer owner, purpose, original deadline,
and append-only terminal record. Repeated requests cannot rejuvenate that consumer.
Logical missing evidence is retained even when only one bounded batch is admitted
to transport. Cache completion, deadline censoring, and consumer retirement remain
separate. Retiring one owner does not cancel another owner's evidence or active leases.

For admitted PumpSwap pool subscriptions, finalized stream notifications register
prefetch interest immediately. One background service hydrates incremental batches
through the existing shared governor. This is enabled only under that governor;
standalone runners retain their original acquisition concurrency. Prefetch is priority
90, actual decision hydration retains its urgency, and position context is always 0.
The original stream coverage, exact decision window, bounded bootstrap, authentication,
and strategy gates still decide whether evidence is usable. Prefetch grants no authority.

Meteora receives the same broker implementation and explicit pool/interval/trigger
consumer identities. Its trigger-only authentication and reconstruction semantics remain
unchanged. Local request-budget exhaustion is separately counted and no longer mislabeled
as provider throttling. Real observed 429 failures still trigger shared broker backoff.
Raw transport records and the consumer terminal trail are retained. Live numeric output
includes reason counts grouped by kind, and overdue-active job counts.

## Frozen sources and repairs

| Lane | Source SHA | New repair SHA |
|---|---|---|
| Pump | 361d90dbfd12226467ac458f92b16a9f0b017fce | 4d094388b3101f1e8ff11357ac8a044b0ef75c63 |
| Meteora | 45836b18c9afdda29909ebe9cb68d386a47b074f | 686e1938da1ba1a275b65fe1e7be0694ce697a04 |
| Pons | 7ed22d3bdca3680869ef61b41f063389cb006366 | Existing integration overlays retained |
| Ramses | eebcb9136efa41db9a28f2ac95e4dddde0d17b15 | Existing integration overlays retained |

All policy/config hashes remain in sources.json unchanged. The integration commit
containing this document identifies the candidate; it is separate from the running f7ee2b1.

## Verification and commands

Pump: `python -m unittest discover -v` (259 passed).
Meteora: same command (364 passed).
Supervisor: `python -m unittest discover -s certification/tests -v` (38 passed).
Pump and Meteora: `python -m tests.resource_check`; Meteora additionally
`python -m tests.dlmm_resource_check` (all passed; synthetic).

The capacity experiment is reproducible with
`python -m unittest tests.test_evidence_consumers -v` in either repaired Solana lane.
With 80 signatures arriving over ten seconds and the same two-transport/second ceiling,
burst acquisition completes 64/80 inside its four-second acquisition budget. Incremental
acquisition completes 80/80 before evaluation, which then requires zero additional RPCs.
It uses ten batches over the earlier window versus eight late batches, not a higher rate
or a demonstrated improvement in RPCs per transaction. This is a synthetic scheduling
result, not a natural qualifier, live capacity certification, or profitability claim.

The overload case retains all 1,936 missing consumers out of 2,000 under the same
two-transport/second test, despite admitting at most 72 job rows. Lower expired job counts
alone are not a success metric. The remaining overload stays explicit and fail-closed.

## Next live comparison

After the frozen campaign ends and its terminal evidence is reviewed, verify this exact
candidate with `python -m certification.run prepare --worktrees <new-empty-path>` and
`python -m certification.run verify --worktrees <new-path> --output <gate-path>`.
Then a separately identified clean smoke and fresh uninterrupted campaign are required.
Compare full-window completions, consumer deadline success/censoring, requests per complete
candidate, queue wait, foreground/position latency, raw telemetry cost, and provider errors.
Measure storage/CPU for the new durable consumer trail under live volume; the existing
resource gates do not establish its long-run resource ceiling. A second provider is not
justified until this comparison identifies remaining useful demand beyond verified capacity.

No signing, submission, capital authority, paid infrastructure, threshold relaxation,
main merge, or reinterpretation of forced/zero-fill events is included.
