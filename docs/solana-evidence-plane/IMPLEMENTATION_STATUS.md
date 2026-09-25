# Solana Evidence Plane — offline completion

PR #109 remains draft and unmerged. The production-paper cutover was already
certified offline; the focused authority/usage/storage cleanup is implemented and
awaits exact-runtime-SHA final offline certification. Prospective operational
validation is DEFERRED until a separately authorized run.

The seven historical Pump windows are PERMANENTLY CENSORED LEGACY EVIDENCE,
not an implementation-completion blocker. Their original audit is retained.
No bodies are fetched, historical availability reassigned, or public observations
promoted. This document never authorizes a market run.

## Runtime changes

The canonical source remains the later run-368 composition, with the original
Pump counterfactual / profit-protection-v2 / fill-persistence policy and Meteora
fee-density / core-hold policy. Pons and Ramses native sources are unchanged.

- `solana_evidence_service.py` runs one authenticated source writer, independent
  Unix interest IPC, bounded asynchronous repair, and asynchronous archive I/O.
- `certification.evidence_worker` and `evidence_supervisor` provide the actual
  shared process entrypoint, bounded restarts, and the unchanged shared governor.
  No live provider connection has been started during development.
- Pump's composed `tests/pump_acceleration_natural_prospective.py:main` uses LocalPumpTape
  and LocalPumpHistory. Normal PumpSwap and second-leg history have no RPC fallback.
  Obsolete prefetch orchestration/imports are removed from that runner.
- Meteora's composed `tests/solana_dlmm_independent_v1.py` `_new_finalized_swaps` and `_capture_chunk` read finalized
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
Account observations inherit the active lifecycle's address pins, including an
unchanged account last observed before reservation. They compact after all owners
release their interests; observations alone still never create interval coverage.

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

## Deterministic evidence completed locally and in hosted CI

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
fake WebSocket and IPC server I/O. The separate **real Unix IPC** gate passed in hosted offline certification,
with the authoritative WebSocket still deterministic.

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
source manifest. Hosted broad certification and real IPC passed at the exact runtime SHA below.
Full retained Pump window parity is permanently unavailable from legacy evidence;
it is excluded from the offline implementation completion standard.
No market run, provider probe, deployment, Render interaction, merge, portfolio
activation, active/cert/main promotion, signing or transaction submission occurred.


## Previous runtime-cutover offline evidence

Certified runtime SHA: `bc36a09d0cfd1c6131525c526d427076f085165b`.
Workflow: https://github.com/levonmendall/The-Meme-Machine/actions/runs/36171495473.
The subsequent documentation commit records these results; runtime sources are identical.

- Architecture: 64 tests plus real Unix IPC authority/pin checks.
- Broad component suites: 1514 tests (meteora 451, pons 369, pump 343, ramses 351); external socket attempts: zero.
- Supervisor/accounting: 233 tests.
- Standard CI: 520 tests plus resource and synthetic lifecycle checks; market jobs skipped.
- Native ledger SIGKILL matrix: 20 committed/uncommitted boundaries across four lanes.
- Production restart checks: all four lanes passed.
- Integrated acceptance: 50 existing protocol, qualification and lifecycle scenarios plus contract/contention checks.

Two concrete final-review regressions required corrected candidates: lifecycle
account pin inheritance during archive I/O, and disconnect-created account gaps
that could pin expired account history forever. Both now have deterministic
retention/restart coverage. Account observations retain content provenance but
never gain interval authority. Program discontinuity remains explicit/fail-closed.

Crash evidence combines real journal SIGKILL boundaries, actual runner recovery
and interruption, evidence-writer restart, independent reader lag and report faults.
It does not establish a combined six-process orchestration kill test.
No live CU savings or live provider completeness/entitlement are claimed.

Exact source, composed diff, policy, artifact digest and test identities are in
`certification_results.json` and `checkpoint.json`.

## Acceptance answers

| Question | Verified answer |
|---|---|
| getSignaturesForAddress absent from normal Pump foreground? | Yes; actual composed entrypoint uses LocalPumpTape/History. |
| Actual covered Pump decision has zero historical calls? | Yes in the real entrypoint with complete synthetic finalized evidence; retained full-window parity remains unavailable. |
| Actual covered Meteora warmup has zero historical calls? | Yes; retained 12-chunk reconstruction inputs and qualification match exactly. |
| Reserved Pump fill proceeds under saturated repair? | Yes in the actual reservation/fill path; delay 2 seconds, timeout 20 seconds, exact thesis validation unchanged. |
| Lifecycle state survives failures? | Native SIGKILL and actual restart/interruption tests passed without duplicate fills or fabricated settlement; see the crash scope above. |
| Unresolved program continuity gaps explicit/fail-closed? | Yes. Account content discontinuity is health state, never interval coverage. |
| JSON publication-only? | Yes for canonical Pump/Meteora/evidence runtime authority. |
| Steady-state storage bounded? | Hot DB/WAL are capacity bounded and fail closed; lifecycle pins are preserved. Immutable archive grows and needs long-term provisioning. |
| Economics unchanged? | Yes; economic policy hashes unchanged. |
| Provider ceilings unchanged? | Yes; Alchemy remains sole authenticated authority. |
| Paper-only authority unchanged? | Yes; no signing, custody or transaction submission. |
| Market workflow or deployment run? | No. Only deterministic/offline CI ran. |

Only the repair branch changed. Main, active and certification branches were not
promoted or updated. PR #109 remains draft and unmerged.


## Final cleanup gap disposition

| Requirement | Prior state / action |
|---|---|
| Runtime cutover, local finalized decisions, reservation priority, crash/recovery | Already satisfied; unchanged economic behavior, existing runtime gates retained |
| As-of proofs, separate journals, bounded repair/hot capacity, content-addressed archives | Already satisfied; no replacement architecture |
| Provider authority/configuration | Shared strict endpoint parser; canonical production constructors fail closed; secondary transport disabled; legacy diagnostic helpers remain outside production |
| Credential isolation | Credential-safe endpoint representation, transport payload checks, sanitized exceptions, publication/provenance/archive checks, final artifact/log scan |
| Foreground historical RPC | Added transport guard in both composed lanes plus composed factory regression gate; existing real runtime zero-history tests retained |
| Continuity/drain | Existing transactional semantics retained; phase/health visibility added. Supervisor drains/stops lanes before closing evidence service. Abrupt service stop persists uncertainty and pins; it never settles a lane |
| Interest ownership | Consumer-bound ownership, atomic owner/address/pin registration, lifecycle downgrade rejection, stale candidate reclamation, explicit subscription-capacity rejection |
| Meteora payload | Retained full finalized filtered blocks; smaller-payload equivalence not established |
| Provider usage/health | Added stream bytes/messages/subscriptions, repair HTTP usage, lane usage denominators, latency/purpose counters and bounded anomaly flags |
| Archive capacity | Added free-space health and fail-closed safety reserve; no destructive archive retention |
| Final offline certification | Pending exact-runtime-SHA workflow; previous results above are retained separately |

### Canonical provider contract

Only `MM_SOLANA_READ_RPC_URL` is required for Solana provider configuration:
`https://solana-mainnet.g.alchemy.com/v2/<credential>` (optional explicit port 443).
The credential must be 8–128 ASCII letters, digits, underscore or hyphen. Scheme,
exact mainnet host, exact `/v2/` path, credential shape, whitespace, userinfo,
query/fragment, extra path segments, escapes and ports are checked before I/O.
No independent API-key, WSS, rescue or legacy-alias configuration is consumed.
Canonicalization makes explicit-port and default-port endpoint identities equal.
Only SHA-256 endpoint identity is recorded; raw credentials remain inside transport.
Startup validates the mainnet genesis through the existing governed HTTP budget.

Topology: public Solana WebSocket is discovery-only; Alchemy finalized streaming
feeds authoritative evidence; Alchemy HTTPS performs bounded repair, startup
network identity, and separately accounted current/exact execution state reads.
Meteora's existing public discovery data remains non-authoritative. Production
Pump/Meteora cannot use OnFinality, public HTTP or a secondary evidence transport.
Root-only compatibility helpers remain for deterministic/isolated diagnostic
callers; the production DB context and actual entrypoint checks forbid fallback.

The HTTP consumer guard blocks `getSignaturesForAddress`, `getTransaction`,
`getTransactionsForAddress`, and `getBlock`. The service's separate bounded
`getTransactionsForAddress` repair transport is allowed. Current finalized
accounts/holder/network reads remain on the existing execution path and governor.

### Usage fields and interpretation

- Evidence counters: `stream_messages`, `stream_bytes`, `stream_accepted_messages`,
  `stream_rejected_messages`, `stream_reconnects`, bounded reconnect reason names,
  `stream_unsupported_methods`, accepted `ingested_event/transaction/account`,
  `rejected_evidence_records`, gaps and repair attempt/retry/page counters.
- Service health: active/pending subscriptions and evidence-class counts; phase;
  provider/network digest; repair HTTP physical/logical/method counts, 429s,
  unsupported methods, failures, queue/transport microseconds; governor cooldowns.
- Consumer counters: local Pump decisions; Meteora trigger polls/warmup intervals;
  local evidence reads, complete/incomplete reads, repair-assisted windows, and
  explicit historical-foreground-call counters (must remain zero).
- Lane `solana_usage`: complete decisions, incomplete/censored decision events,
  physical/logical calls, execution-refresh/current-state calls, retries and queue/
  transport microseconds. Existing append-only pipeline retains candidate and
  observation identity; overlapping incomplete/censored events are not summed as
  unique lost opportunities. Raw HTTP records preserve method, retry, latency,
  purpose and provider identity; existing status exposes method errors and 429s.
- Frozen CU schedule estimates only known methods. Unpriced address-history calls
  remain explicitly unpriced; no zero-cost assumption or live savings claim.

For future measurement, sum lane HTTP records and service repair/identity HTTP
records exactly once. Divide HTTP requests, known estimated CU, stream bytes and
repair attempts by the corresponding complete-decision denominator. A zero
complete-decision denominator produces no efficiency claim. Stream byte counts
measure decoded WebSocket message bytes, not TLS/framing overhead or invoices.

Health flags surface subscription-capacity rejections, reconnect loops, increasing
repair backlog, abnormal byte rate, repeated 429/unsupported-method failures,
excessive HTTP work per decision and DB/WAL/filesystem pressure. Flags are
observational; no evidence is dropped to satisfy an efficiency target.

### Storage safety and payload review

Hot DB/WAL retains the unchanged 256 MiB guard. Free-space warning is 512 MiB;
critical reserve is 128 MiB on both DB and archive filesystems. Ingestion and archive
publication additionally reserve bounded write headroom before accepting work.
Critical space rejects canonical queries/ingestion/archive writes, preserving
lifecycle pins and unresolved work. Health remains readable. No archive file is
removed for pressure. Operators must provision/expand long-term immutable archive
storage and leave headroom for lane journals, WAL and concurrent processes;
watermarks are safety reserves, not a retention policy or a hard archive-size cap.

Full-block Meteora payloads supply versioned account keys, loaded addresses,
instructions/inner instructions, token and native balances, transaction results,
filtered ordering and linked block/census witnesses. Logs or signatures alone do
not preserve the native verifier's current inputs or completeness proof. The
representation is retained; no bandwidth improvement is claimed from offline tests.

### Deferred prospective operational gates

All require a future separately authorized run: live Alchemy WebSocket entitlement/
capability; real stream completeness; `getTransactionsForAddress` entitlement and
response shape; actual reconnect → gap → repair behavior; actual stream bandwidth;
actual Alchemy CU usage and CU/complete-decision improvement; prospective complete
Pump replay parity; prospective Meteora operational reconstruction parity; actual
provider 429/reconnect characteristics. These are operational gates, not missing
implementation work. No combined six-process SIGKILL orchestration test is claimed.
