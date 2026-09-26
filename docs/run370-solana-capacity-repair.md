# Run 370 Solana capacity repair

PAPER ONLY. Base: `53ed759dc6fea989d7262d01d5b4894cee88475c`,
`cert/single-market-run369-repairs-20260925`. Repair branch:
`repair/run370-solana-evidence-capacity-20260925`.

Evidence: workflow 36209572689, native run
`06176554-6452-4f21-8607-1e9e44f062aa`, artifact 10894299703,
verified SHA-256 `c28ce3c2d2ba1375c4bc5035145b52da039d09e4c677e78c2911bc89d7ed77c3`.
The exact base passed non-market certificate 36209019422.

## Reproduction before production changes

`certification.run370_reproduction` audits the artifact read-only and runs a
minimized retained-transaction-shape pressure fixture. The unmodified base
exhausted a deliberately scaled 32 MiB limit after 1,020 simulated seconds:
29,495,296 DB bytes + 5,253,032 WAL bytes, 1,700 ingested transactions,
804 hot payloads and 896 archived/compacted records. This is a mechanism
reproduction, not a claim that the scaled fixture reproduces the exact market
failure time. The same fixture after repair completed 2,400 simulated seconds
with 16,004,984 final hot bytes and no capacity failure, even retaining the
original 64-record maintenance slice in this comparison.

Two other pre-repair failures were reproduced: 2,049 unrelated transactions
caused `filtered_block_bound` before scope filtering, and a repaired interval
starting at slot 100 was reopened by a later disconnect despite advancement
to slot 200. After repair the unrelated block is accepted and the next gap
starts at 201. Historical coverage remains unavailable before its repair time.

## Measured causes

At the original Pump failure, hot storage was 2,061,034,952 bytes:
1,908,203,520 DB + 152,831,432 WAL. The preserved DB is a later checkpointed,
post-shutdown/restart snapshot; its 2,000,011,264-byte size must not be confused
with that earlier failure snapshot.

The preserved DB contains 2,202,553 address references for 33,164 distinct
addresses. Repeated long native address and record identity strings occupy
932,081,664 bytes across `addresses` and its two indexes. The records table
occupies another 886,996,992 bytes. Thus physical index amplification, as well
as payload storage, matters materially. Of retained payload bytes, Meteora
transactions account for roughly 710 MB and Pump/PumpSwap events for roughly
111 MB. There are not three complete physical copies of each full block:
the single transport is filtered into scoped transactions and decoded events.
Transaction logs are nevertheless repeated in transaction/event lineage.

Archive scheduling originally selected only 64 records per slice, without an
archive-time index. In the preserved post-shutdown state, 2,880 records had
been archived but only 15 compacted. Twenty-two candidate interests and
repeated broad unresolved gaps held conservative scope retention floors back.
The original disconnect path inspected unsealed receipts from every old
session. Successful repair closed gaps without retiring those receipts, so
later disconnects repeatedly reopened the same old lower bound. This coupled
gap churn, retention pressure, and local ingestion/maintenance backpressure.

The original broad-pressure comparison grew from 164,899,304 hot bytes at
second 50 to 823,592,584 at second 350; that long execution was interrupted
before a final result. It is not reported as a completed test. The separate
scaled reproduction above establishes actual capacity exhaustion.

## Production changes

* `solana_evidence_storage.py` dictionary-indexes addresses and record IDs,
  losslessly compresses full immutable bodies, and content-addresses shared
  large log arrays. Decoding restores every field before original hash checks.
  Instructions, loaded addresses, balances, logs, transaction order and
  finality inputs are preserved. Existing plain JSON records remain readable;
  legacy address indexes migrate transactionally.
* `solana_evidence_plane.py` uses an archive-time index and bounded archive
  plans. Archive publication precedes payload removal, with a pin recheck at
  commit. Garbage collection is bounded. Read paths remain local hot reads.
* `solana_evidence_service.py` drains bounded 512-record / 4 MiB-body archive
  plans. Existing priority scheduling and SQL interruption preserve foreground
  and lifecycle priority; compression and publication remain off the writer.
  The 2 GiB hot limit and all freshness/finality limits are unchanged.
* Disconnect fences use only their current session. Completed authenticated
  repairs retire covered receipts; contained duplicate gaps are not recreated.
  Account snapshots retain their independent freshness/pinning contract and
  do not acquire fictitious continuous-interval authority on writer restart.
* Full blocks are filtered before applying the existing scoped transaction
  bound. Recently retired account subscriptions tolerate late notifications.
  Close attribution distinguishes message-size rejection, local ping timeout,
  received provider close codes and normal shutdown without recording secrets.
* Pump's smoke gate requires authenticated shared stream activity, current
  usable health, discoveries, completed local reads, reconciled accounting,
  responsiveness, and zero historical foreground RPC. Direct RPC activity
  cannot substitute for local evidence. Continuation export retains this proof.

All prior Pump/Meteora overlays remain declared, with one incremental Run 370
overlay per lane. `certification.run prepare` applies them; source integrity
and shared-module identity checks pass. Pons/Ramses composition entries are
unchanged. No strategy source identity, policy hash, economics, market scope,
provider authority, provider ceiling, finality or freshness rule changed.

## Reconnect and consumer findings

The original pre-failure evidence distinguishes five `filtered_block_bound`
closures and twelve generic `ConnectionClosedError` closures. The five local
filter errors are reproduced and repaired. The twelve generic exceptions do
not preserve enough information to distinguish provider closure, message-size
failure and local ping/backpressure; no stronger retrospective attribution is
claimed. A later shutdown/restart snapshot has one additional filter failure.

Pump's 52 discoveries already arrived through the local event tape. Repeated
broad continuity gaps prevented its required 60-second covered window, before
the canonical local-read counter increment. The production-path regression
uses the actual adapter, local tape, screening and qualification construction
with finalized local records. It reaches screening and a valid strategy
rejection, preserves the as-of slot, and makes zero foreground historical RPC.

`certification.run370_meteora_replay` loads an entire original 249-transaction
finalized block and its original linked-child coverage witness. Through the
composed production trigger it reconstructs one authenticated swap for an
actually attempted Run 370 pool. Earlier-than-available access fails closed;
historical RPC is zero. This is not an invented complete economic vector or
a reconstruction of missing historical account/warmup intervals.

## Validation and limits

The first repaired pressure profile completed 1,200 simulated seconds, with
601 approximately 7 MB full messages, 86,544 transactions, 43,873 events,
110,887 archived records and 110,453 compacted records. Sampled peak hot storage was
141,547,776 bytes; the final hot payload population was 19,530 records. Pump
and Meteora each completed 113 local reads; each correctly rejected the one
query made during the explicit simulated disconnect.

The stronger profile adds 17 reconnects, 22 candidate leases, an open lifecycle
pin, dense out-of-scope blocks and lease expiry. Its finalized result is stored
separately with the validation evidence. Synthetic event/timing/padding fields
are explicitly labeled, and network access is forbidden. The pressure profile
does not claim historical economic counterfactuals; account pin safety is
covered separately by retention regressions.

The strengthened local replay completed 1,800 simulated seconds in 795.56 wall
seconds: 901 dense messages / 6,269,743,647 stream bytes, 129,744 transactions,
65,773 events, 175,987 archived records and 175,553 compacted records. All 17
reconnects produced 51 explicit program gaps, all repaired. All 22 candidate
leases expired; no active pin was discarded. The hot population stabilized
at 19,530 payloads. Sampled peaks were 529,175,040 hot bytes, 415,182,848 DB
bytes and 113,992,192 WAL bytes; the last 400 seconds varied by only 819,200
hot bytes, declining rather than growing. Archive size reached 226,657,377
bytes. Whole-replay observed ingestion/archive throughput was 245.76/221.21
records per wall second, including fixture generation overhead and startup
retention; the fixed hot tail accounts for their difference.

Pump and Meteora each completed 159 of 174 planned local queries. Each of the
15 remaining queries occurred in an intentionally disconnected interval and
failed closed. Capacity, service-unavailable, command-unacknowledged, stale
and reconstruction-gap rejections were zero in this controlled replay.
The unmodified base fails the identical dense profile immediately with
`filtered_block_bound`; the separate scaled storage comparison isolates
capacity behavior instead of conflating these two failure mechanisms.

The final hosted pressure gate additionally observes hot/DB/WAL sizes at every
transaction/checkpoint boundary and after source/maintenance calls; its peak
measurements therefore include transient WAL growth that coarse trend samples
may miss. The retained local development reports use 50-second trend sampling.

New regressions comprise seven storage/gap tests, one smoke-proof test with
multiple negative cases, and one composed Pump production-path test. Existing
disconnect/retry/priority, retention, accounting, reconstruction and provider
tests remain enabled. Local results before the final hosted certificate:
312 root tests; 346 Pump, 452 Meteora, 387 Pons and 357 Ramses native tests;
283 supervisor tests (all passed with prepared lanes; the aggregate runner
separately skips 10 optional prepared-lane tests); and all 24 offline certification gates passed. Real Unix IPC is
blocked locally by `Operation not permitted` and remains a mandatory hosted
gate, not a waived test.

Unresolved evidence remains explicit and pinned. Indefinitely unavailable
repair evidence or indefinite lifecycle retention can still correctly exhaust
a finite hard store and stop admission; no finite-capacity system can promise
unlimited preservation. The repair does not recover absent historical evidence
or authorize another market run. No market workflow or deployment was launched.
