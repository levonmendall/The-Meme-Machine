# Targeted SQLite/public-RPC diagnosis — 2026-10-14

Diagnostic phase complete; **stop for owner direction**. No behavioral production
correction, deployment, provider request, PAPER restart or acceptance followed.
This document supplements the retained failure receipts; it does not replace them.

## Preserved source and operating state

- Receiving/reviewed baseline: `engineering/pump-history-separation-20261013`,
  `e6aab04871a1f1c03d36905993cd3bdcf5c77ee7`.
- Diagnostic-only publication branch: `diagnostics/sqlite-public-rpc-20261014`.
  Its published SHA and remote verification are recorded in
  `E/SQLITE_PUBLIC_RPC_DIAGNOSIS_PUBLICATION_20261014.json`.
- Tested/installed implementation remains
  `a70e2610743d8595b3d1a36ed25821a6689c29f3`, installed checkout clean.
  Existing FAST result: 1,949 tests, zero failures/errors/skips. It was not rerun.
- Untested, undeployed WIP remains separately preserved at
  `66a87ac32f969195352ade7d35150dd2be53b81b`; do not integrate automatically.
- At `12:59:42.705147Z`, PAPER was inactive/dead, disabled, MainPID 0; funding
  closed. The $1,000 epoch reconciled, cash $1,000.00, no positions, reservations,
  commitments, obligations or pending deliveries. Sequence 8,826. Historical
  $500 epoch also reconciled; its legacy encoding has no direct `cash` field.
  Both state hashes match the previous preservation checkpoint.
- Source-only diagnostic unit remains failed/MainPID 0. No source/strategy
  worker, new provider experiment or engineering test remains running.
  Existing read-only monitor/observer/dashboard were left intact.
- No authoritative contents, usage counters, strategy configuration, pacing,
  capital policy, subscription, infrastructure or recovery evidence changed.
  One-hour qualifying progress remains zero.

## Pump — STOPPED — INSUFFICIENT EVIDENCE

**Fatal database, SQL/transaction phase and competing actor remain unknown.**
The original `OperationalError:SQLITE_BUSY:5` occurred at `06:29:08Z`. Its final
worker diagnostic retains the SQLite name/code but not the owned traceback or
connection. `runtime/evidence_worker.py:failure_diagnostic` supplies an origin
for unknown evidence exceptions, not for SQLite exceptions.

The retained syscall trace ends roughly 37 seconds before that failure. Eight
8–13-microsecond unsuccessful WAL read-lock probes on the canonical SHM byte
124 occurred earlier. Such probes are not an attribution of the fatal error.
The last isolated sample reports BEGIN peak 12.5 ms and COMMIT peak 140.5 ms;
it does not demonstrate sustained write-lock admission waiting.

The exact source review identifies possible, **unproved** escape paths:

- `solana_selective_source.py:candidate_history_delivery` captures before its
  SQLite BUSY/LOCKED handler.
- `solana_history_delivery.py:capture` opens a zero-wait read-only candidate
  connection for proof verification.
- `solana_evidence_plane.py:checkpoint` and `solana_checkpoint.py` use independent
  zero-wait connections. Canonical, governor and provider-accounting operations
  also remain possible origins.

No retry, timeout, permission, sidecar, checkpoint or transaction change is
justified by these possibilities. Supervisor Budget operations do not retain a
persistent connection; isolated and combined native streams retain the same
read-only usage-ledger keepers. A missing supervisor keeper therefore does not
explain the isolated failure.

| Retained measurement | Incoming slots/s | Durable slots/s | Group CPU cores |
| --- | ---: | ---: | ---: |
| Combined restored baseline, 391.186 s | 4.3892 | 1.8687 | 1.6549 |
| Isolated source, 63.711 s | 4.4890 | 4.4105 | 1.0810 |

These are not controlled equivalents. The source-only run retains canonical
intake/preparation/delivery but omits strategy workers, Pons acquisition and
supervisor work. The combined baseline also uses an earlier source. Same-source
`a70e261` combined startup shows larger owner wall/CPU ratios and 20.74 s of CPU
throttling versus 0.316 s in isolation, but durations, restoration state and work
cardinality differ. Exact counters are in the result JSON. They do not separate
disk wait, GIL wait, runnable delay and locking or establish a causal percentage.

Additional mandatory work/shared-resource competition is plausible. Neither a
dominant limiter nor SQLite's contribution to the combined deficit is proven.
No throughput repair or new live/offline recurrence was dispatched.

**Evidence/capability needed:** original failing-operation context, or a faithful
isolated state/actor reproduction. No such replica has been established under
current copy quotas; the canonical database alone is about 13.85 GB. A tiny
synthetic BUSY fixture would validate diagnostics, not identify this historical
actor. Do not bypass quotas or write production state to force a reproduction.

If separately authorized, the smallest attribution change should retain original
exception identity/code/name and sanitized owned module/function/line, configured
database path, connection identity/transaction state, fixed SQL phase/template
and reporter PID/TID **before optional probes**. Capture a failing executor's
thread separately at the operation. Never export expanded SQL, parameters,
third-party exception text or credentials. A bounded recurrence requires a
specified faithful fixture or explicit authority for an actual source run.

## Pons — two distinct decisions

**Provider throttling: STOPPED — INSUFFICIENT EVIDENCE.** Four retained HTTP 429s
are four-element `eth_getLogs` batches to
`https://rpc.mainnet.chain.robinhood.com`, not the Alchemy credential.
Rejection preceding-start gaps are 0.805/0.899/0.576/0.749 s. The audit shows
no overlapping public transport at those instants and retry attempt zero.
This does not establish external shared-quota use or a method/weighted limit.
Earlier accepted batch/single controls with exact seven-event parity already
disprove unconditional batching incompatibility; they were not repeated.

`provider.py:_http_batch` discards HTTP 429 headers/body, so no actual error
message, Retry-After or numeric quota can be recovered. Accounted zero response
bytes does not establish an empty server response. Exact original request
parameters/hashes are also absent. Public documentation identifies rate limiting
and recommends a production provider, but the reviewed pages give no numeric
per-method/batch window:
[connection documentation](https://docs.robinhood.com/chain/connecting/),
[public-RPC terms](https://docs.robinhood.com/chain/terms-of-service/).

**Dispatch-spacing defect: ROOT_CAUSE_CONFIRMED / READY_FOR_TARGETED_CORRECTION.**
`provider_topology.py:PacedRpc._http/_http_batch` reserves its public 500-ms
role interval before shared admission. The reservation can expire during the
existing eight-second cooldown; the shared operating interval is 100 ms.
Retained admitted-start gaps after 6.69–7.62 s of shared waiting are
0.165/0.276/0.234 s. The audit records admission times, not separate socket-start
timestamps; the following offline replay directly measures synthetic dispatch.

One bounded offline experiment executed the actual PacedRpc/Admission path with
two tiny ledgers, a fake clock, 125-ms synthetic service time and no real HTTP:

- Control physical dispatch gaps: 500/500/500/500 ms.
- One synthetic 429 plus original cooldown: 8,125/**125**/500/500 ms.
- Ten synthetic physical attempts, zero retries, correct original failure and
  audit accounting; 0.299 s wall, 0.206 s CPU, 31,628 KiB peak RSS, 200,704 bytes
  disposable fixtures. Fixtures cleaned only after the result was saved.
- Zero market requests, native openings, modeled provider expense or production
  database writes. No behavioral correction was implemented.

**Recommended narrow correction, awaiting approval:** enforce the public
adaptive interval at the existing shared admission/dispatch boundary using the
maximum of account and public intervals. Preserve shared priority, absolute
deadlines, durable accounting, existing cooldown and adaptive slowdown/recovery.
Avoid sleeping after a priority grant or adding a second scheduler. Canonical
Alchemy pacing and held-position paths must remain unchanged.

Verify the same control/cooldown fixture, concurrent public consumers, adaptive
slowdown/recovery, terminal 429 accounting, original deadlines and independent
canonical protection. Expected benefit is removal of the demonstrated spacing
violation; no numerical throughput gain or first-429 cure is established.

Actual rejection cause still needs provider restriction information or useful
headers/body from a natural recurrence, tied to bounded request identity/timing.
A generic 429 or no recurrence remains inconclusive. No new provider observation
was dispatched: repeating the prior short control would not resolve that gap,
and inducing overload is prohibited. Changing Alchemy rates, unbatching all
requests or moving all discovery to another endpoint is unsupported here.

## Evidence, publication and resume boundary

E is `/root/Documents/Codex/2026-10-10/the-meme-machine-eliminate-redundant-data/blocker-repair-20261011`.
The small published result is
`evidence/sqlite-public-rpc-diagnosis-20261014.json`; it references original
artifacts with byte sizes/SHA256 rather than copying large datasets. New external
records are `SQLITE_PUBLIC_RPC_DIAGNOSTIC_GATE_20261014.json`,
`PONS_RETAINED_429_CONTEXT_20261014.json`,
`PONS_OFFLINE_DISPATCH_COOLDOWN_20261014.json` and its log,
`SQLITE_PUBLIC_RPC_FINAL_SAFE_STATE_20261014.json`, and
`SQLITE_PUBLIC_RPC_DIAGNOSIS_RESULT_20261014.json`.

Reproduction harness:
`engineering/diagnostics/public_dispatch_cooldown_20261014.py`; it is offline
diagnostic code only, not part of a production entrypoint. No broader suite,
recovery copy/check, provider probe or CI campaign was initiated. Production
`meme_machine/`, tests and the test runner are byte-equivalent to the previously
tested implementation.

After owner direction, first inspect this branch, deployed source and actual
obligations. Implement only the explicitly approved pacing/attribution scope and
its focused tests. Do not automatically integrate preserved WIP, deploy, renew
provider workloads, start PAPER or credit acceptance. Pump attribution, original
public throttling, Pons demand-writer fault, latest backup/storage failure and
backup/protection freeze conflict remain separate unresolved issues.
