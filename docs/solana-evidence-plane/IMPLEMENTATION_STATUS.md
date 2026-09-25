# Solana Evidence Plane — implementation checkpoint, NOT CERTIFIED

This branch is **incomplete and must not be promoted or used for a market run**.
It contains implemented storage/reader/transport-boundary components and the lane
report-publication repair. It does not replace the production evidence paths yet.
Green component tests do not satisfy the owner's architecture completion standard.

## Refreshed source baseline

- Repository: `levonmendall/The-Meme-Machine`.
- Implementation branch: `repair/solana-evidence-plane-v1-20260925`.
- Base: `b1504b962a719c2b7e1032100eaea74402f63d0d`.
- Main at refresh: `54712c4c6470cc4dc267888f934bd693aac030d0`.
- Certification branch at refresh: `c9308774ad80edcaaea0a8e62bdf61668f9214c7`.
- The implementation base was selected after comparing current refs. It adds four
  control-layer commits beyond the certification head and retains the current
  Pump counterfactual revision and Meteora one-side source repair.
- No later relevant 20260925 source repair was returned by the bounded ref refresh.
- Unrelated historical branches were not exhaustively enumerated.

| Lane | Pinned source | Manifest policy identity |
|---|---|---|
| Pump | `3c9553afb3caa92ab5f3db769f870df033a9630f` | `825084f162efdc10ca4d1faad747902b858bb6e7b4441f7ff48bf089a182f28b` |
| Meteora | `a3579b4cc748fdbb7b4a466680f8a224773adc8b` | `90c711e5e3e521fb79f93bc386af5a3067d0a30c83ae3407c550f70db581f966` |

Pump strategy: `pump-acceleration-independent-v1/profitability-v1-profit-protection-v2-counterfactual-replay-v1`.
Meteora strategy: `solana-dlmm-independent-v2.0-profitability-fee-density-v1-core-hold-v2`.

New composed lane diff identities (publication and Pump recovery deltas):

- Pump: `fab6c6fea533399702e7d3412db5279801c6fd724191e82947c6e44c9fa4f7c8`.
- Meteora: `24576f7b5933a1386fcfa31b6302a7803fe71261b3c6be86a61e670d6b2714e8`.

`certification/sources.json` declares the new overlay files and exact diff hashes.
All existing frozen source/config file hashes still verify. Economic policy hashes
were not changed to represent evidence/runtime work. Pons and Ramses lane sources are unchanged. The shared continuation atomic writer also uses writer-unique temporary paths.

## Implemented components

- `meme_machine/solana_evidence_plane.py`: SQLite WAL single-writer ownership;
  independent read-only connections; atomic immutable records, provenance, cursors,
  interval receipts, gaps, repair pagination receipts; durable interest ownership;
  unresolved reservation/position retention pins; consumer cursors and lag;
  compressed immutable payload archives; fail-closed hot-store capacity guard;
  bounded asynchronous writer actor; restart discontinuities and conflict poisoning.
- `meme_machine/solana_evidence_transport.py`: finalized filtered subscription
  requests, strict Alchemy endpoint derivation using the existing app key, offline
  notification decoder, bounded `getTransactionsForAddress` repair adapter.
  Page content, pagination cursor and terminal coverage commit atomically.
- `meme_machine/solana_evidence_queries.py`: local Pump event view and Meteora
  transaction/census view, with no RPC interface or historical fallback.
- `meme_machine/durable_publication.py`: unique temporary files, file fsync,
  replace and directory fsync; explicit non-authoritative publication result.
- `certification/patches/evidence-plane-publication-{pump,meteora}.patch`:
  applies publication isolation to the **actual composed** Pump/Meteora runners,
  including Meteora's exception-report path. Injected export failures do not escape
  into lane processing. The existing separate transactional accounting journals
  retain separate failure domains.

The writer API is internal to the service boundary. Only a trusted source adapter
may submit `IntervalProof`; consumers must never be given writer/proof authority.
The service does not infer coverage from socket connection, elapsed time, latest
trade, highest slot, or a single notification. Query `as_of` prevents a later repair
from changing an old prospective decision's evidence availability.

## Transport selection and unresolved contracts

Proposed routing encoded by the subscription boundary:

| Evidence | Transport | Current state |
|---|---|---|
| Pump/PumpSwap event fields | filtered finalized authenticated logs | request/decoder boundary implemented; socket orchestration and strict unsupported-event audit pending |
| Candidate/reserved/open account state | dynamically interested finalized account subscriptions | request/decoder boundary implemented; coherent multi-account snapshot assembly pending |
| Meteora instruction/balance evidence | candidate-pool filtered finalized blocks with transaction contents | request/decoder boundary implemented; exact chain transaction index and interval-completeness contract pending |
| Missing interval | bounded authenticated address-history transaction pages | offline-tested adapter; exact deployed response contract/entitlement unverified |

Official documentation consulted without provider probes:

- https://www.alchemy.com/docs/reference/block-subscribe
- https://www.alchemy.com/docs/reference/logs-subscribe
- https://www.alchemy.com/docs/reference/account-subscribe
- https://www.alchemy.com/docs/chains/solana/solana-api-endpoints/get-transactions-for-address

Alchemy documents a separate streaming WebSocket host for `blockSubscribe` and
account/program filtering. A filtered block array's ordinal must **not** be invented
as the original chain transaction index. Current decoder preserves explicit indexes
when supplied; the Meteora view fails closed when ordering proof is unavailable.
A filtered source emits no notification for a block with no matching transaction.
An observed upper slot is therefore not, by itself, a complete interval witness.
These contracts must be resolved before live coverage can be enabled.

No Yellowstone dependency, public-provider authority, new provider, secret change,
provider probe, streaming connection, or throughput increase was introduced.

## Additional native recovery milestone

- Pump's journal now records authenticated graduation as a cash-neutral strategy
  transition. `PumpAccelerationPaperLifecycle.restore` reconstructs original
  reservations, filled inventory, graduation, high-water marks, partial harvests,
  deterioration streaks, and intended exits without appending any events. Startup
  integration and durable runner context are still pending.
- `certification.position_continuation.restore_meteora_strategy` extracts the
  existing continuation replay into a provider-free function using the verified
  native ledger. The continuation caller uses it. Meteora continuation report
  failure is isolated; no continuation workflow was run.
- Actual run-368 ledger contains genesis, reserve, and entry: one open position,
  zero settlements. Economic replay and repeated strategy recovery match exactly.
  Injected report publication failure leaves that ledger and position unchanged.
- The retained Meteora native runtime policy digest is
  `a69ec239772a86bc7526594c9822b6fc1e611b45b7e661f618099656b288d55b`.
  It matches the current prepared lane's `digest(load_policy())`. This is distinct
  from the manifest policy identity above; neither has changed.

## Retained evidence and replay boundary

Full hourly artifacts were requested once each and rejected by the connector's
536,870,912-byte limit:

| Run | Artifact | Bytes | SHA-256 |
|---|---|---:|---|
| 367 / 36087556931 | 10846820233 | 735872126 | `faedd0389b57dae7c38790d6f3470cf97632c6f8e5d65ec5b3c7716da6318c5d` |
| 368 / 36144662109 | 10872772276 | 572286420 | `af99edde03cca57bf0e9e2c1dd1737de550346c4c3d2a52ddca5e27d2a519a0a` |

Smaller review artifacts 10846543162 and 10872434579 were downloaded once and
cached. Minimal committed fixtures retain 4 and 3 complete Pump **decision summaries**,
qualifiers, original policies and fill timing. They explicitly carry
`raw_transaction_replay_available: false`. They are not raw evidence and were not
used to claim reconstruction or execution parity. Censored cases were not promoted.

The full completed artifacts were subsequently downloaded once each by an
explicitly offline Actions extraction job (36160313578), using read-only artifact
access. It produced a cached 68,930,178-byte compact export. The export's initial
28-MiB delivery bound failed, so a second offline job (36160804350) split that
cached export into transportable parts; it did not redownload the originals.
All parts were downloaded once, assembled, and verified against
`b7f25be0857bee238831dd6624ace391af86f42e757b9233dd4f04aea81fc2bb`.

Committed small fixtures now additionally contain two authenticated Pump raw
transaction receipts per run and the compressed exact run-368 Meteora journal.
Raw Pump decoder outputs and immutable store payloads match. These samples do
**not** prove whole-window completeness or full strategy decision parity. Tests
explicitly ensure they cannot manufacture coverage. No censored case is promoted.
The larger cached subset remains available locally for the unfinished interval
replay extraction; no repeated full-artifact processing is needed.

## Verification completed at this checkpoint

- 38 focused offline tests: storage, transport boundary, local queries, publication, retained raw events; plus 1 protocol-freeze test (39 total in that invocation).
- 6 Pump harness/publication tests.
- 31 Meteora harness/publication tests.
- 20 native Pump accounting/lifecycle/recovery tests.
- 3 retained run-368 Meteora ledger recovery/economic/publication tests.
- 16 continuation/continuity/assurance tests with prepared native worktrees (no skips).
- All four prepared lane source-integrity checks passed with the new declared
  Pump/Meteora overlay hashes and unchanged frozen file/policy identities.
- Writer SIGKILL: uncommitted cursor rolled back; committed evidence retained;
  restart creates a gap; SQLite integrity check passes.
- Two held WAL read snapshots do not prevent 100 subsequent ingestion commits.
- 160 simultaneous exports across eight threads: no shared temporary collision.
- Local views contain no provider interface; the tested covered queries use zero
  historical provider calls. This is **not** proof that production decisions do.

No final broad architecture certification was attempted: required architecture
integration/pressure/replay gates are still incomplete. Generic existing push/PR CI
may run deterministic tests; it is not final architecture certification.

## Required remaining implementation

1. Build and supervise the actual shared socket/repair service, with durable
   dynamic-interest IPC and strict delivery/completeness witnesses. The current
   actor is a storage worker, not a complete network service.
2. Wire Pump's tape, PumpSwap and second-leg history, confirmation provenance and
   fill-time decision construction to the local views. Remove normal historical
   foreground acquisition only after these paths are covered and tested.
3. Wire Meteora registration before trigger/warmup, trigger authentication and
   `_capture_chunk` to the local view without changing its verifier or discovery
   spool. Preserve structural exclusions and the 12-second warmup.
4. Implement coherent execution-state interest and the one-physical-refresh-round
   path, then prove reserved fills under saturated repair within the unchanged
   2-second delay and 20-second timeout. No such pressure result is claimed yet.
5. Complete durable Pump strategy/reservation/monitoring recovery context and
   Meteora monitoring reconstruction; test independent evidence/consumer/publisher
   process deaths against the real lifecycle entrypoints.
6. Finish archive/index compaction and automatic lifecycle-derived retention.
   Current raw payload compression is bounded per operation, but retained hash
   tombstones/coverage metadata accumulate. The hard hot-store cap stops ingestion
   fail-closed; it is not a completed steady-state retention solution. Long reader
   snapshots can retain WAL pages and must also remain capacity-visible.
7. Complete durable lane telemetry. Current query counters are process-local and
   count queries, not economic strategy decisions; ingestion counters are durable.
8. Extract complete replay intervals from the cached raw subset and run actual
   strategy-input/decision/execution parity. Current sample-event and native-ledger
   parity do not meet that full gate.
9. Run the complete requested crash/concurrency/load matrix, then one final broad
   non-market certification. Preserve all failed historical evidence.

## Explicit completion answers

| Question | Checkpoint answer |
|---|---|
| Is getSignaturesForAddress absent from normal Pump foreground decisions? | **No. Production cutover is pending.** |
| Covered Pump decision with zero historical calls? | Local event view: yes. Full production decision: **not demonstrated**. |
| Covered Meteora warmup with zero historical calls? | Local transaction view: yes. Production warmup/reconstruction: **not demonstrated**. |
| Reserved fill proceeds while repair saturated? | **Not implemented/proven.** |
| Open Meteora position survives all listed process failures? | Actual run-368 open position survives native replay and report failure; complete process recovery matrix **not proven**. |
| Is JSON publication-only? | Modified lane exports have no canonical state authority; complete runtime recovery migration **pending**. |
| Explicit fail-closed gaps? | **Yes in the new store/readers; runtime cutover pending.** |
| Strategy economics unchanged? | **Yes.** |
| Provider ceilings unchanged? | **Yes.** |
| Paper-only authority unchanged? | **Yes.** |
| Any market workflow launched? | **No.** |
| Any deployment or Render interaction? | **No.** |
| Any active/cert/main branch changed? | **No.** |

No signing, transaction submission, portfolio inception, branch promotion, merge,
market campaign, smoke, diagnostic, continuation, replacement, deployment or Render
interaction occurred in this work. The draft branch is an implementation checkpoint,
not an approval-ready completed architecture.
