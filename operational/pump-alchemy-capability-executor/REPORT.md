PUMP_ALCHEMY_OPTIMIZATION_READY_FOR_PROVIDER_VALIDATION

The finite executor is implemented and offline validated. Keep existing Pump
acquisition unchanged. No live market-provider request, production configuration
change, subscription switch, deployment or PAPER restart occurred. Verified
provider savings remain **0 bytes**. The practical next step is the already
specified single, separately authorized 60-second capability probe.

The isolated publication branch is
[`engineering/pump-alchemy-capability-executor-20261008`](https://github.com/levonmendall/The-Meme-Machine/tree/engineering/pump-alchemy-capability-executor-20261008).
Its exact published commit SHA accompanies the completion response. It descends
from the requested authoritative commit
`874e94a915900215993566822e8adc9ce9524a6b`, on
`engineering/pumpswap-provider-bandwidth-20261008`. The initial remote-head
inspection found no newer Pump-specific implementation. Concurrent Pons,
Robinhood and maintenance branches were inspected as references without merging
or editing their work. The original [HANDOFF](../pumpswap-provider-bandwidth/HANDOFF.md)
and [EXPERIMENT](../pumpswap-provider-bandwidth/EXPERIMENT.md) remain intact.

The owner's subsequent administrative update supersedes assumptions that PAYG
capabilities or billing data are unavailable. The owner verified Pump/Solana app
`9bin99s96t7ga5e9`, Pons/Robinhood app `v5h0vqr0wpp9zscj`, approximately 1.73M
account CU and $0.91 reported usage value, with Solana address-history queries
and WebSocket logs as primary CU drivers. No usage interval or numerical method
breakdown was supplied, so these figures are neither a monthly forecast nor an
allocation of this experiment's cost. This thread's two read-only administrative
calls returned `Unknown tool` for `alchemy.list_apps` and
`alchemy.get_usage_summary`; that routing failure does not contradict the
owner's verified administrative visibility. [ACCOUNT_UPDATE.json](ACCOUNT_UPDATE.json)
records the distinction.

Read-only reconciliation of the Droplet's configured service environment found
correct Solana and Robinhood endpoint roles, distinct credentials, and a native
Pump token matching the configured Pump key. The Pump endpoint fingerprint
matches the authoritative capture. No key, key suffix, credential URL path or
raw credential exception is published. The queried PAPER service has MainPID=0,
so this establishes configured credentials, not a running process's credential
binding or account-wide connection headroom. A comparison against the admin
app-key masks remains pending tool routing or the owner's last-four-character
comparison. [CREDENTIAL_RECONCILIATION.json](CREDENTIAL_RECONCILIATION.json)
reports this explicitly. Pons acquisition, credentials and subscriptions were
not changed. The live preflight requires an affirmative Pump app/credential
association before any provider request.

The five new engineering modules provide the executor, resource boundary,
paired evidence comparison, offline validation runner and secret-free
credential reconciliation. They reuse the existing endpoint parser,
`SelectiveSource.stream`, transport archive, `RepairRPC.call_delivered`, shared
governor, request builder, native join, finalized fence, startup gate and durable
candidate-history publication. They do not call the broader source worker or
retrying RPC/stream wrappers. All experiment evidence owners are new disposable
databases. The existing shared governor is used only during a future authorized
live run; offline tests use fixtures and temporary state.

Architecture A consumes both program WebSocket logs and the existing native
scout/status/control data. Architecture B consumes the same Pump logs and shared
native data, replacing PumpSwap economic logs with full successful native
transactions. Both independent status filters leave `failed` **unset**, retaining
native successes and failures. The full PumpSwap filter sets `failed=false` and
`vote=false`, with the exact PumpSwap program include. Scout, finalized slots,
block metadata and overlap are retained. The common candidate floor is the
original WebSocket frontier, not a synthetic eligibility or capital boundary.
[PROTOCOL_VALIDATION.json](PROTOCOL_VALIDATION.json) records serialization and
optional-field checks against the pinned Yellowstone 14.0.1 protocol.

Two disposable owners consume original receipt clocks and production reducers.
Parity compares exact signatures, transaction/log indices, canonical economic
rows, independent native failure witnesses, candidate lifecycle, coverage,
checkpoints, gaps, pending proofs, outbox, consumer references, candidates and
work/deadlines. Only private canonical database paths are normalized, with
reference checksums verified and recomputed. No economic identity, timestamp,
deadline, population, qualification rule or capital rule is normalized away.
Missing statuses/bodies and contradictory errors, indices, memberships or logs
prevent proof. Failed logs never enter economic joins. Bodies cannot act as
independent status witnesses. No top-N selection, eligibility pruning, lossy
history compression or snapshot replacement was added.

The simultaneous measurement window is at most 45 seconds including startup. Suppression occurs
only after at least three complete common linked finalized intervals, successes
from both programs, equal committed populations, exact durable projections and
Model B publication release. If incomplete, the executor stops. Otherwise it
uses the actual returned PumpSwap subscription ID for one unsubscribe, charges
its acknowledgement and trailing notifications, and preserves Pump logs plus
all native interests for at most the final 15 seconds. Post-suppression proof
checks successful bodies against independent statuses and linked children; a
window without successful PumpSwap economics is explicitly UNSAMPLED. Original
pending tails remain pending. No probe result grants production-switch authority.

Every receive boundary charges observable application bytes before parsing,
routing or deduplication. Raw bounded frames are archived incrementally; stopping,
malformed and trailing frames cannot disappear from accounting. Oversized
observable payloads retain a size/uncaptured receipt and invalidate the proof.
Per-phase raw totals include native heartbeat data consumed internally by the
collector. Delivery after the 45-second measurement cutoff while parity/admission
and unsubscribe are pending is separately charged as transition overlap; the
overall 60-second deadline is unchanged. HTTP response/error chunks are also charged before decoding. Total
bytes, local decode time, commit time, CPU, peak RSS, SQLite changes and process
I/O are recorded. Duplicate deliveries remain in byte totals even when economic
identities are deduplicated.

The enforced limits and independent offline checks are:

| Resource | Enforced boundary | Offline proof |
| --- | --- | --- |
| Duration/startup | 60 s from parent startup; comparison at 45 s; cancel at deadline | Clock-bound tests and actual stuck-process supervisor |
| Shutdown | 2 s; cancel native calls before awaited close; independent hard-kill reserve | Actual SIGTERM-ignoring process; stalled WS close still cancels tasks/closes native channel |
| Native channel/RPCs | 1 channel, 3 Subscribe RPCs | Independent claims; finite harness opens exactly 1/3 |
| WebSocket | 1 connection, 2 subscribes, at most 1 unsubscribe | Independent claims; returned-ID suppression test |
| HTTP | 5 physical single POSTs; genesis once, finalized slot four times | Actual single-attempt RepairRPC harness; sixth/method/batch/redirect rejection |
| Method CU | 90 HTTP CU | Independent CU overrun; positive harness exactly 90 |
| WS planning CU | Conservative ceiling 26,844 including reserve | Independent published-tariff ceiling test; no native-byte-to-CU conversion |
| Physical methods | 11 maximum | Independent physical-method bound; positive harness exactly 11 |
| Native writes | 3 subscription writes, 12 ping replies | Independent write budgets; ping/rebuild rejection |
| Receive stop | 48 MiB WS/native, stopping frame retained, at most 64 MiB before cancellation | Threshold/capture/stopping-ceiling tests |
| Cancellation | Additional 64 MiB; 128 MiB observable streaming ceiling | Independent reserve and total-ceiling tests |
| Frames/read queue | 16 MiB; 1 native outstanding read/RPC; WS max_queue=1 | Oversize archive receipt, overlapping-read rejection, exact connect options |
| Output | Admit 256 MiB; stop at 224 MiB | Independent soft/hard limits; actual disk-pressure supervisor |
| Memory | 512 MiB process peak RSS | Independent RSS failure; actual child allocation detection |
| Join storage | Existing 32 MiB/256-slot bounds per join; existing bounded early/recent logs | Actual production join byte/slot overflow checks and affected-module regressions |
| Auxiliary bounds | 100,000 receive records, 256 output inventory entries, 1 MiB report | Explicit record/inventory/receipt failure paths; no population pruning on overflow |
| Admission/reconnect | Zero tolerated admission errors, retries, reconnects or filter rebuilds | WS 429, HTTP error and native RESOURCE_EXHAUSTED fixtures stop; no extra attempt |

The parent enforces wall/RSS/output limits independently when a child decoder,
governor or shutdown stalls. Resource violations produce fixed explicit reason
codes and an invalid/inconclusive receipt. A forced kill marks otherwise
unobservable bytes UNKNOWN. The local reserve is not a guarantee about vendor
dispatch, transport buffering, rejected oversized messages or billing. Protocol,
TLS and billed traffic remain separate from measured application bytes.

Existing engineering storage admission is loaded from the published
[`artifact_storage.py`](https://github.com/levonmendall/The-Meme-Machine/blob/5978ceb054044197ea9d64fb7e7b03bc18be6e0d/meme_machine/operational/artifact_storage.py),
verified by SHA256
`24d4362f465586d08fe8f917dcf69b553d39a2b9b0c87635e5b0ae9200bce87d`.
It is an explicit read-only input, not a merged maintenance implementation.
Fresh output must be named `mm-engineering-pump-capability-*`, admitted under
headroom/retained quota, and contain the disposable marker. Inherited production
state paths are removed from the child environment. Symlinks are rejected.

All validation used CPython 3.12.14 and pinned packages, supervised disposable
scratch, and the existing offline network guard. Synthetic transports exercised
the actual finite executor, production joins and independent decoder-derived
economic/index expectations; native envelopes and constructed later identities
are labelled synthetic and provide no real provider size/admission evidence.

| Validation | Result | Wall time / peak RSS |
| --- | --- | --- |
| Final executor/regression class | 35 PASS | See [executor receipt](validation/executor-receipt.json) and resources |
| Affected provider, join, startup, history, Current/Survivor, Pump recovery and capital modules | 175 PASS | 25.66 s / 74,288 KiB |
| Unchanged full corrected capture replay | Exact 287-event canonical digest; all 12 frozen output digests match | 12.47 s / 110,256 KiB |
| Required routine FAST suite | 857 tests, 1 known historical source-freeze failure | 389.74 s / 228,764 KiB |
| Original-file preservation | 363/363 production files, 37/37 economic freezes unchanged | [PRESERVATION.json](PRESERVATION.json) |

The affected run preceded the last credential-role test and final executor-only
hardening; the final 35-test run covers every changed executor module. Frozen
replay and existing production sources remained unchanged throughout. The
canonical digest is
`ed2e970c41ee81c8955aa6a48eddfa63fd060cd0bb9700559c319118b6d3d037`.
Existing incomplete evidence was not promoted to complete. No new candidate
coverage gap or economic expectation change appeared in the frozen comparison.

FAST fails only
`test_strategy_sources_and_nine_change_tests_byte_unchanged`, comparing the
already approved Pons source to an older historical freeze. The prior handoff
already reproduces this on the untouched reference; this task changed no Pons
source or existing test. The baseline's separate OPERATIONAL failures/errors
remain documented in its [VALIDATION](../pumpswap-provider-bandwidth/VALIDATION.md).
No deployment was attempted, so OPERATIONAL and broader acceptance workloads
were not rerun. An initial new affected-suite run hit the new synthetic harness's
overly short phase timer under concurrent CPU load. Its failure evidence is
retained as `validation/initial-affected-*`. The harness now synchronizes fake
phases on delivery completion; a live-clock override is forbidden and real
supervisor deadline tests remain intact. Existing tests and economic expectations
were not weakened. All observed market-provider calls in offline validation: 0.

The authoritative prior measurements remain:

| Measured baseline | Application bytes |
| --- | ---: |
| Total metered delivery | 50,331,681 |
| Captured WebSocket | 48,501,501 |
| Captured Yellowstone | 1,829,265 |
| Charged but uncaptured | 915, still UNKNOWN content |
| All failed WebSocket logs | 16,441,310 |
| PumpSwap successful WebSocket logs | 27,538,305 across 9,819 messages |
| PumpSwap failed WebSocket logs | 13,400,141 |
| Verified savings | 0 |

The PumpSwap replacement removes 40,938,446 gross WS bytes in that captured mix
while retaining shared native witnesses/control/scout. Dividing by 9,819 success
messages gives the approximate **4,169.31-byte native-success break-even**. Actual
full native transaction size, including metadata and envelope, is still
UNMEASURED. Failed-transaction filtering alone does not prove a reduction.

The new receipt records physical full-message averages, distinct success
identities, gross matching-interval WS/native bytes, prefixes/tails and allocated
whole-paired components. Accounting is never based only on locally retained
logs. It labels A/B subtraction from one simultaneous session as a component
allocation, not two independent provider runs. The general adjusted threshold
is `(matching removed WS bytes - differential native/prefix/recovery/HTTP/position
bytes) / matching successes`. Differential overhead and pending tails must be
reconciled before claiming a whole-system reduction. Synthetic test payload
averages are excluded from the real comparison.

The existing thirty-day [cost model](../pumpswap-provider-bandwidth/COST_MODEL.json)
is preserved. Public rates checked on 2026-10-08 are Solana WS 0.0002 CU/byte,
PAYG $0.525/M CU and Yellowstone $75/TB, with decimal TB assumed. [Alchemy CU
documentation](https://www.alchemy.com/docs/reference/compute-unit-costs) and
[pricing](https://www.alchemy.com/pricing) support those model inputs. These are
usage estimates; actual invoice units, contract terms, credits, taxes and any
separate capacity charges require account reconciliation. Native bytes are not
converted into invented compute units. No 10-million-CU acceptance gate applies.

| Modeled market | A WS / native GB per 30 days | A usage USD | B USD at 3,000 / 4,200 / 6,000 B per native success |
| --- | ---: | ---: | ---: |
| Quiet | 21.77 / 4.07 | 2.86 | 1.98 / 2.45 / 3.15 |
| Normal | 242.61 / 13.98 | 29.24 | 17.79 / 22.46 / 29.45 |
| Busy | 1,595.99 / 80.28 | 200.82 | 104.29 / 127.61 / 162.61 |
| High volume | 11,478.03 / 615.63 | 1,360.23 | 450.65 / 543.96 / 683.93 |

These scenarios assume Pump success/failure and PumpSwap success/failure rates
per second of 0.2/0.2 and 2/1; 2/2 and 20/15; 10/15 and 100/150; and 40/120
and 400/1,600 respectively. They are independent activity assumptions, not
extrapolations of the finite capture or the owner's 1.73M-CU usage. Statuses,
scouting, finality, metadata, subscription prefixes and existing method charges
are included. HTTP response bytes remain unmeasured. Baseline streaming totals
are 25.84, 256.58, 1,676.27 and 12,093.66 GB; B at 4,200 bytes models 28.09,
254.14, 1,290.16 and 5,563.80 GB. Quiet B therefore consumes more bytes even
though its modeled dollar cost is lower. Busy B at 6,000 bytes also consumes
more bytes (1,756.72 GB) despite a lower dollar estimate. Both would fail a
minimum-byte criterion at those traffic mixes.

The preserved normal reconnect/recovery scenario is $30.42 for A and
$18.98/$23.64/$30.65 for B; the normal independent open-position scenario is
$61.57 and $50.12/$54.79/$61.78. Those figures retain modeled archive gaps,
overlap, duplicate position delivery and maintenance HTTP interests. They are
not new measurements, and the finite executor creates no extra position
subscription or reconnection. The same model makes universal per-success HTTP
acquisition approximately $1,095/month in the normal case, before unmeasured
response traffic. That alternative lacks demonstrated cost/admission/latency
superiority and is not implemented. Actual account history-query CU must be
evaluated by app/network/method against required recovery evidence, not pruned
because a token is initially weak.

Local CPU, memory, write activity and latency receipts measure the two-owner
engineering workload, not an automatically inferred production improvement.
Full payload parsing can cost more CPU/memory than logs; lower priced bandwidth
does not certify lower provider load, native throughput or admission pressure.
Original native-minus-WS receipt latency and commit/decode times are retained.
The probe contains no funded-position sample and cannot establish long-horizon
recovery or clear `combined_position_and_candidate_provider_latency_not_certified`.
Existing position subscriptions and recovery paths remain unchanged.

To reproduce the offline checks with the approved pinned environment, use the
published storage-policy source as an explicit input:

```bash
python -m engineering.solana_capacity.capability_executor
python -m engineering.solana_capacity.validate_capability executor --storage-policy-source /path/to/pinned/artifact_storage.py --receipts /path/to/offline-receipts
python -m engineering.solana_capacity.validate_capability affected --storage-policy-source /path/to/pinned/artifact_storage.py --receipts /path/to/offline-receipts
```

The first command only prints the [offline plan](OFFLINE_PLAN.json); it does not
read credentials, create owners or open transports. Offline receipts/logs and
their hashes are indexed in [VALIDATION.json](VALIDATION.json).

The exact minimal next action is separate authorization for **one execution of
the existing 60-second experiment**, preceded by read-only Pump app/key
association and current account headroom reconciliation. Headroom must cover
all concurrent account interests plus one channel/three Subscribe RPCs, one
WS/two subscriptions and the five-filter candidate request, without production
changes or purchased capacity. The [example receipt](HEADROOM_RECEIPT.example.json)
is deliberately expired/unverified and cannot authorize calls. A real receipt
must name the Pump app, this endpoint fingerprint and the separate authorization,
with a validity window of at most 300 seconds. The existing shared governor path
must be supplied; it is never replaced by a private live governor.

Only after that separate authorization, the prepared invocation is:

```bash
MM_PROVIDER_GOVERNOR_DB=/path/to/existing/shared/governor.sqlite python -m engineering.solana_capacity.capability_executor --execute-provider-experiment --authorization-reference SEPARATE_AUTHORIZATION_REFERENCE --headroom-receipt /path/outside-git/current-headroom.json --storage-policy-source /path/to/pinned/artifact_storage.py --env-file /etc/meme-machine/paper.env --output /admitted/scratch/mm-engineering-pump-capability-UNIQUE
```

This command has **not** been run. Obtain Pump-scoped administrative usage
receipts before/after the authorized probe to reconcile concurrent workloads
and billing lag. Review application-byte components, status/body census,
original clocks, coverage, tails, shutdown, admission, CPU/write pressure and
latency before selecting a replacement. If B loses the measured total-byte or
evidence comparison, close the Yellowstone replacement comparison and retain
WebSockets. If the bounded window lacks a specific case or provider capability,
record that exact missing item and stop without extending or retrying. Any
production configuration preparation, deployment or switch remains separately
authorized. Rollback for this disposable probe is to cancel its fixed interests
and preserve its receipts; production continues on its original acquisition.
