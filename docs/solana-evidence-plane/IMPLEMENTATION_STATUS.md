# Solana Evidence Plane — runtime cutover candidate

PR #109 remains draft. The production-paper cutover is implemented. Final hosted
non-market certification is pending; this is not market-run authorization.

## Runtime changes

The canonical source remains the later run-368 composition, with the original
Pump counterfactual / profit-protection-v2 / fill-persistence policy and Meteora
fee-density / core-hold policy. Pons and Ramses native sources are unchanged.

- `solana_evidence_service.py` runs one authenticated source writer, independent
  Unix interest IPC, bounded asynchronous repair, and asynchronous archive I/O.
- `certification.evidence_worker` and `evidence_supervisor` provide the actual
  shared process entrypoint, bounded restarts, and the unchanged shared governor.
  No service or provider connection has been started during development.
- Pump's composed `pump_acceleration_natural_prospective.main` uses LocalPumpTape
  and LocalPumpHistory. Normal PumpSwap and second-leg history have no RPC fallback.
  Obsolete prefetch orchestration/imports are removed from that runner.
- Meteora's composed `_new_finalized_swaps` and `_capture_chunk` read finalized
  local transactions. Public discovery/wakeup spooling remains intact. The old
  bounded census primitive requires explicit `gap_repair=True` and has no normal
  runtime caller. The service's repair path uses full address-history transactions.
- Lane consumers cannot submit evidence, proofs, frontiers, SQL, or coverage through
  IPC. They can register interests, acknowledge consumption, and update counters.

## Finalized completeness and transport

| Evidence | Authoritative transport | Completeness boundary |
|---|---|---|
| Pump / PumpSwap events | Alchemy finalized program logs plus filtered block signature census | All census signatures delivered; a linked later finalized child seals the parent and proven skipped slots |
| Meteora instructions / balances | Alchemy finalized program-filtered full blocks | Complete transaction array plus linked finalized child; explicit filtered ordering witness |
| Candidate / reserved / open accounts | Dynamically registered finalized account subscriptions | Content only; account notifications never manufacture interval coverage |
| Missing intervals | Bounded `getTransactionsForAddress` pages outside consumers | Exact finalized bounds, verified completed pagination, atomic content/cursor/proof |
| Pump fill current fields | One physical finalized batch: accounts, largest accounts, chain identity | Original delay/timeout, exact adapter validation, locally authenticated block timestamp |

A socket ACK, highest notification, silence, or elapsed time never grants coverage.
Unknown parents, missing census delivery, disconnects and restarts create explicit
unresolved gaps. Old sessions cannot bridge reconnects. Later repair availability
cannot rewrite an earlier prospective `as_of` cutoff. Conflicting immutable content
or finalized source receipts poison the evidence store.

A filtered block rank is explicitly labeled as such, never presented as the global
chain transaction index. The Meteora verifier preserves execution ordering and
rejects mixed order authorities within a slot. All economics/density bounds remain.

Official transport documentation was inspected without live capability probes.
No Yellowstone dependency or Alchemy setting/key/app modification was introduced.
Sparse filtered delivery can require bounded repair; unsupported address-history
entitlement/response contracts remain fail-closed.

## Execution and recovery

Pump preserves the 2-second delay, 20-second timeout and exact fill-time thesis.
The required account interest is registered before reservation. A durable one-shot
refresh claim prevents a second physical round after a crash. The response is saved
in the Pump journal database; an interrupted claim without response fails closed.
A reserved request outranks queued background work even at the unchanged 256-entry
queue capacity. Open-position priority remains above reservations. Provider rate
and cooldown ceilings were not raised.

Pump startup restores reservations, positions, authenticated graduation, high-water
state, partial realization, deterioration and intended exits. Runner context and
refresh claims live in its separate transactional ledger. Recovery does not append
another reservation/fill. Legacy unresolved context that cannot be reconstructed
remains fail-closed.

Meteora startup uses the provider-free verified canonical journal recovery, including
recorded tapes and eligible exits. Resumed monitoring does not append another entry.
An unresolved pre-entry reservation without sufficient context stays unresolved.
Process termination does not authorize settlement.

Evidence, Pump lifecycle and Meteora lifecycle have separate transactional failure
domains. JSON is publication only. Native and Solana-worker report exports use unique
fsync/replace paths; production exports use bounded asynchronous mailboxes. A stalled
report write does not own a lane's execution thread. Pons/Ramses publication behavior
was not changed.

## Retention and telemetry

The service retains a rolling 2-hour hot baseline plus durable candidate/lifecycle,
open-position, reservation and unresolved-gap pins. Candidate leases expire after
20 minutes without renewal; reservation/open-position pins never expire implicitly.
Archive compression/fsync runs outside the writer. Pins are checked again before
hot payload removal, including interests arriving during archive I/O.

Older immutable raw material, hashes, provenance and associated coverage proofs are
compressed into content-addressed archives. Hot indexes/old metadata are compacted
behind a monotone retention floor. Reintroducing old evidence below that floor fails
closed. Passive WAL checkpoints cannot wait for readers; DB/WAL bytes remain visible.
The unchanged 256-MiB hot-capacity guard fails closed rather than dropping evidence.
Archive storage itself remains an immutable growing replay archive, not a bounded
long-term disk allocation; external capacity/retention provisioning remains operational.

Durable counters cover ingestion, repair, gaps/restarts/conflicts, local decisions,
local triggers/warmups, refreshes and cancellation causes. Readers expose finalized
frontiers, ingestion lag, consumer cursors/lag, interests, DB/WAL/archive bytes and
retention floors. Pump's journal retains refresh claims/results and fill-stage latency.

## Deterministic evidence completed locally

- Actual Pump `main()` restores a journal-backed candidate, constructs a complete
  qualified decision from local history, and performs zero historical provider calls.
  Its one mocked current-holder-state call is reported separately.
- Actual Pump reservation/fill servicing under 256 queued background jobs completes
  with exact thesis persistence, one physical refresh round, delay 2 / timeout 20.
  A lost refresh response/claim remains fail-closed and cannot launch another round.
- Actual Meteora trigger and 12-second capture functions use local evidence only.
- Retained run-368 warmup: 12 real `_capture_chunk` reconstructions, exact original
  qualification input dictionary and result, zero historical provider calls.
- Retained run-368 open position: repeated journal recovery, resumed-monitor
  interruption and report failure preserve one open position and zero settlements.
- Service ingestion continues while each independent reader holds an old WAL
  snapshot; restart retains records and exposes unresolved gaps.
- Controlled retention boundary retains pins, archives eligible rows, compacts hot
  indexes, rejects old reinsertion and preserves indexed active-window queries.
- Reservation arriving during blocked archive I/O retains its hot evidence.
- Report publisher stall: one bounded mailbox, caller continues, failure isolated.
- All four production restart safety probes passed. Native Pons/Ramses probes and
  policies retain their original behavior.

The workspace prohibits Unix socket creation. Local service tests therefore use
fake WebSocket and IPC server I/O. A separate **real Unix IPC** gate is included in
hosted offline certification, with the authoritative WebSocket still deterministic.

## Retained Pump limitation — no invented parity

The compact exports were audited once against both immutable broker bodies and raw
Alchemy HTTP receipts. All seven historical "complete" decision summaries lack
some authoritative bodies for their reported trailing 30-second census:

| Run | Successful census signatures | Missing authoritative bodies |
|---|---:|---:|
| 367 | 69 | 31 |
| 367 | 98 | 93 |
| 367 | 190 | 190 |
| 367 | 172 | 168 |
| 368 | 290 | 290 |
| 368 | 21 | 18 |
| 368 | 109 | 100 |

The old implementation treated public stream logs as authoritative. This migration
does not promote those observations. These seven intervals remain censored; full
retained Pump decision/execution parity cannot be claimed from the available bytes.
The committed audit includes signature-set hashes and examples. Raw authenticated
sample-event parity remains valid. No original large artifact was redownloaded.

## Certification and authority

The existing fixture-export workflow now also supports an explicit, offline-only
runtime certification job. Its export job is disabled unless separately requested
by its marker. The runtime job has no provider secrets, connectivity probes, market
commands, dispatch, or deployment path. Architecture gates precede broad suites.

Economic identities are unchanged:

- Pump policy: `825084f162efdc10ca4d1faad747902b858bb6e7b4441f7ff48bf089a182f28b`.
- Meteora manifest policy: `90c711e5e3e521fb79f93bc386af5a3067d0a30c83ae3407c550f70db581f966`.
- Meteora native policy: `a69ec239772a86bc7526594c9822b6fc1e611b45b7e661f618099656b288d55b`.

Exact composed diff identities and module hashes are in `checkpoint.json` and the
source manifest. Broad certification and hosted IPC results must be recorded before
claiming engineering completion. Full retained Pump window parity remains unavailable.
No market run, provider probe, deployment, Render interaction, merge, portfolio
activation, active/cert/main promotion, signing or transaction submission occurred.
