BLOCKED_BY_SPECIFIC_EVIDENCE_OR_PROVIDER_CONSTRAINT

MODEL B remains the only normal startup candidate. MODEL A stays archived. The final mixed run identifies an actual native concurrent-subscription constraint; startup reconstruction is no longer the remaining question. Do not start operational PAPER validation yet.

Tested implementation: `476bad205014c8c3d586f45d87f84ec44306817a`, tree `e9158889bd78b42ffd93b9fe563d0a64b54b5928`. [PR #121](https://github.com/levonmendall/The-Meme-Machine/pull/121) stays draft/open/unmerged. Subsequent delivery changes only reports and preserved artifacts. [Measurements](measurements.json), [validation](validation.json), [source identities](source_identities.json) and the [complete capture manifest](captures/final-476bad20/manifest.json) identify the evidence independently of the delivery commit.

## Startup architecture

Broad historical warmup is absent from ordinary startup. Necessary work is durable frontier/history/index restoration, finalized control authority, feed installation, bounded overlapping delivery, durable publication and contiguous initial coverage. Candidate consumers then start independently; candidate-specific gaps do not hold the entire market in startup. Existing positions need their own restored pinned lineage and fresh safety/mark evidence, not an all-candidate historical census.

| Final boot milestone | Seconds from measured boot |
|---|---:|
| Rolling feeds connected | 15.778 |
| Contiguous coverage verified | 17.555 |
| Consumers released | 17.559 |
| Steady-state transition | 17.561 |
| Legacy invocations | 0 |
| Cold reconstruction / transaction bodies / historical gap RPC | 0 / 0 / 0 |
| Startup RPC calls / estimated RPC CU | 4 / 70 |

Continuous normalized economics remains authoritative and shared. Actual Current trajectory, Survivor age/history and Meteora trigger/warmup/confirmation requirements remain unchanged. Promotion consumes retained history or waits for its durable publication with the original deadline. Recovery is needed for a proven disconnect/restart loss, missing exact field or genuinely late discovery. It is not a fallback to legacy startup.

The new source retains lossless control backpressure and unchanged membership suppression. Earlier completed repairs make delayed-log readiness incremental rather than repeatedly rebuilding every signature, prevent cold-maintenance work competing with initial publication, and replace the expensive oldest-retirement lookup with an equivalent scoped lookup. This task did not increase workers, queues, RPC limits, subscription ceilings or infrastructure.

## Capacity and native error diagnosis

Alchemy's Geyser `Subscribe` returned `RESOURCE_EXHAUSTED` **665 times**, with the precise detail **`too many active connections`**. This occurred on stream reads (662) and subscription writes (3). HTTP 429s were **zero**. There were also 55 native INTERNAL errors: 43 HTTP/2 stream resets and 12 Core write errors. They are recorded separately from RPC responses and local owner admission pressure.

At the first resource rejection, the client tracked 51 native streams, 50 of which had already delivered data. They contained 1,649 unique addresses, including 1,646 Meteora addresses. Peak client-active streams were 58. All requests retained the demonstrated maximum of 50 filter entries and at most 47 addresses. Thus the observed problem is aggregate native connections, not a demonstrated larger-filter rejection or HTTP rate ceiling. The numeric account quota was not independently probed; client-active includes subscription attempts, so this is not a certified claim that the quota is exactly 50. [Native-origin trace](captures/final-476bad20/native-origin.json).

Membership requests: 202; plans: 53; unchanged requests suppressed: 148 (73.27%). Installs/retries: 766. Retry/rebuild traffic persisted despite no-op suppression. Faster owner service cannot be claimed to remove this provider connection ceiling. The existing hybrid RPC governor remained at its pre-existing 0.05-second ceiling; expensive candidate workers stayed at two. The historical phase-0 generic 0.5-second setting is distinguished from this actual hybrid setting in the measurement artifact.

| Canonical owner | Measured result before shutdown |
|---|---:|
| Queue capacity / peak | 64 / 60 |
| Depth p50 / p95 / p99 | 56 / 59 / 60 |
| Oldest queued wait | 11.140 s |
| Producer admission-wait peak | 65.597 s |
| Time at ≥75% / ≥90% capacity | 337.1 / 114.0 s |
| Peak to half capacity | 9.506 s, transient |
| Peak to ordinary baseline | Not reached |
| Final live depth | 59 |
| Stable normal drainage | FAIL |

The planned workload was 180 seconds with 150 seconds of additional normal service. Owner admission/service delayed the loop and final census: close occurred 407.931 seconds after measured boot, 390.372 seconds after durable consumer release; clean stop completed at 411.456 seconds. This overrun is a failure of bounded drainage, not a deliberate extension or a successful shutdown drain. No further provider-backed run followed it.

The gap census on preserved frozen evidence returned the identical gap identity `13706` in 0.004584 seconds versus 8.490371 seconds. A 3,000-view/alias/repaired-gap regression checks its complete result and bounded work. It resolves bindings through their index and makes one linear gap-table pass; a purely indexed gap-table read is not claimed. A 20-second passive profile found zero census/state-observer samples among 147 owner-worker samples. Remaining owner work included real publication, canonical JSON encoding and durable commits. Frame/RPC metering and sampling still have overhead; the measurement optimization is not advertised as a production capacity pass.

## Trading readiness

| Evidence obligation | Final live outcome |
|---|---|
| Meteora EDF jobs | 17 requested: 8 completed structural/unsupported assessments; 9 expired; 0 pending |
| Pump observation checks | 49; 48 needed zero rich calls; one failed on continuity |
| Complete strategy qualification vectors | Pump 0, Survivor 0, Meteora 0 |
| Promotion history categories | 83 total: 0 already-complete/no-backfill; 1 targeted gap; 4 late recovery; 78 incomplete/censored |
| Pump position-equivalent | 77 requests: 0 complete, 72 incomplete, 5 failed |
| Survivor/PumpSwap position-equivalent | 77 requests: 0 complete, 76 incomplete, 1 pending at close |
| Meteora position-equivalent | 310 requests: 11 complete, 297 failed, 1 bootstrap, 1 pending at close |
| Feasible deadline misses | UNPROVEN; not reported as zero |

Pump's incomplete position samples comprised 21 unresolved-gap and 51 continuity failures. Survivor's 76 incomplete samples lacked authenticated pre-graduation lineage in the disposable position fixture; mark reads do not substitute for that lineage. Meteora had 254 entry-geometry initialization refusals under current state and 43 stale-heartbeat failures; 11 later samples traversed complete mark, flow, confirmation, safety and settlement-prerequisite functions. A historical positive pool is not assumed to remain a valid new opportunity today.

There was no complete prospective qualifying opportunity/vector. Preserved authenticated replay still proves Pump and Survivor decision parity, Current→Survivor independence, and positive Meteora full/minimal equality/TRUE with original timing. Established 1,064/1,064 Pump routing and 879/879 body-free PumpSwap decoding remain preserved; they are not relabeled as live recall for this interrupted cohort.

There were 107 scoped acquisition jobs: 31 completed and 76 expired. Causes: 64 late-discovered Pump prefixes, 22 provider gaps, 19 recovery gaps, one position gap and one checkpoint gap. Pump's absent authenticated launch boundary required the bounded address-specific prefix search; those 64 prefixes begin at slot zero. They must not be presented as small steady-state gaps or cheap normal promotion incidence. Exact job intervals and deadlines are in the frozen audit; exact physical RPC parameters/receipts are in the HTTP archive.

At close, acquisition/EDF pending counts were zero **because expired work became terminal**, not because every required history completed. There were 27,067 unrepaired gap rows and 81 expired publication waits. The active-candidate-only gap census was zero after expiry and excludes terminal/cheap-retained scopes; it does not certify position completeness. The two pending position identities are retained explicitly in the audit. Original deadlines were not refreshed or evidence freshness fabricated.

## Efficiency and resource bounds

| Phase | Raw delivered application payload | HTTP bytes | RPC calls | Estimated RPC CU |
|---|---:|---:|---:|---:|
| Startup | 60,987,493 | 210 | 4 | 70 |
| Post-release failed mixed/retry interval | 527,389,923 | 95,057,628 | 3,625 | 85,120 |
| Shutdown, separately | 1,837 | 1,739 | 2 | 40 |
| Total | 588,379,253 | 95,059,577 | 3,631 | 85,230 |

Total Yellowstone delivery was 91,201,730 bytes; WebSocket delivery was 402,117,946 bytes (80,423.5892 estimated WebSocket CU). All delivery/overlap/recovery bytes count before local compression/deduplication. There were 17 exact missing-log transaction-body requests, 9,454 scoped archive bodies and zero block requests. Broad normal Pump/PumpSwap body ingestion was not restored.

The 78 JSON-RPC -32600 responses were optional concentration `getProgramAccounts` requests; the existing largest-account fallback remained active. They are not native resource exhaustion or required-history success. Repeating those unsupported optional scans remains unnecessary work, but this report does not confuse it with the dominant connection/recovery failure. No -32016 response occurred in this final run.

Process CPU averaged 52.85% of two vCPU, with a measured one-second peak of 77.19%. Peak RSS was 365.2 MiB; steady mean/last RSS was approximately 291/364 MiB. Memory exhaustion was not demonstrated. Canonical DB was 218,370,048 bytes; peak WAL 156,745,432 bytes; WAL before stop 6,241,832 bytes, after clean stop zero. SQLite changes: 465,291. Physical process writes were approximately 4.50 GB, including SQLite and measurement archives. This is transient initialization/retry pressure, not a certified continuous storage rate. Two-vCPU sufficiency is unproven while the owner cannot drain; neither a bigger host nor a larger provider plan is justified by the evidence yet.

Current published [RPC pricing](https://www.alchemy.com/pricing), [gRPC pricing](https://www.alchemy.com/solana-grpc), and [CU/byte charges](https://www.alchemy.com/docs/reference/compute-unit-costs) were briefly rechecked for diagnostic accounting. The payload/CU estimate is $0.093808 for this final run, excluding unmeasured wire framing and any account-specific adjustments. It is not an invoice. Monthly LOW/EXPECTED/HIGH remain **NOT_CERTIFIED**; this failed retry regime is not extrapolated into production incidence. Host/storage reference remains $73/month. Former assumed 6,700 promotions/day and 5,000 bodies/day remain retired.

## Delivery and minimum next action

Focused final-source checks: 175 passed, one archived test skipped. Full FAST and affected OPERATIONAL on the completed runtime/census repair were 665 and 780 passed respectively (eight OP archive skips). The later native observer-only change received focused coverage; unrelated full suites were not repeated. Exact-source GitHub push and PR runs retained the same accepted 9 failures/2 errors: zero new and zero changed/missing identities. Frozen readback passed integrity, 5,472 distinct canonical identities, no canonical-count loss and no checkpoint regression. This reconciliation does not prove missing market evidence exists.

All 231 protected strategy/policy/nine-change files remain byte-unchanged. Pons/Ramses and shared-capital are untouched. Diagnostic state is disposable; no PaperBook, portfolio, signing, submission or monetary position was instantiated. PAPER remains inactive, CAPACITY retains its pre-existing failed/stopped state, RECOVERY/AUTONOMY inactive, with unchanged service start stamps. No deployment or merge occurred.

The next minimum work is to bring aggregate native subscriptions within the observed connection budget through bounded prioritized admission/consolidation while preserving every required interest. Then the same bounded proof needs complete authenticated position lineage and stable normal drainage. Do not increase workers or buy capacity before removing unnecessary connection/rebuild pressure. Do not reopen MODEL A or start operational PAPER until those prerequisites are proven.
