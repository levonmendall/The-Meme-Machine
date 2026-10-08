**INCONCLUSIVE — retain the existing WebSocket acquisition.** Exactly one experiment ran. No verified provider-side savings can be measured: savings bytes and percentage are undefined, and zero bytes receive savings credit. Complete economic evidence, ordered history, candidate work deadlines and position safety were not certified. The replacement path remains inactive.

The run used published base `91ad8b608da357049c8c02e783fc41904634a535` and the owner's revised admission-first authorization. It began at 2026-10-08 19:01:42.536152 UTC and finished at 19:02:29.191002 UTC. Supervisor wall time was 46.374050460 seconds. At the unchanged 45-second paired-phase boundary, the completeness comparison failed and the executor stopped. Bounded shutdown took 0.278453165 seconds. A `ConnectionClosedError` was also recorded while closing; no earlier native admission rejection is recorded. There was no WebSocket suppression, retry, reconnect, extension or second experiment.

The four physically delivered PumpSwap successful-transaction protobuf payloads were **6,688, 6,688, 9,717 and 14,898 bytes**, totaling 37,991 bytes across four distinct signatures. Mean size was **9,497.75 bytes**, versus the prior approximately **4,169-byte** bandwidth break-even estimate. Nearest-rank p50 was 6,688 bytes; p95 and p99 were 14,898 bytes; the ordinary median was 8,202.5 bytes. Three packets arrived during the paired phase and one during transition. The fourth is counted in the raw capture and final accounting even though the executor's live evidence counter recorded only three.

All four native bodies were at slot 454632166, **31 slots below** the candidate stream's requested floor of 454632197. They are prefix observations, not a representative production distribution or a complete finalized comparison sample. The Pump scout likewise observed only slots 454631894–454631900 against its requested floor of 454631925. Shared control progressed through slot 454631938. These observations establish the missing coverage; they do not establish its provider or client cause. See [NATIVE_PAYLOAD_DISTRIBUTION.json](NATIVE_PAYLOAD_DISTRIBUTION.json).

The complete raw archive accounts for every observable received application payload, including unsuccessful WebSocket transactions, simultaneous overlap, subscription acknowledgments, transition and shutdown. No locally discarded traffic or duplicates are deducted. TLS, HTTP/2 framing and provider-dispatched bytes that the client did not receive are outside this application-byte meter.

| Received application bytes | Paired phase | Transition | Shutdown | Total |
| --- | ---: | ---: | ---: | ---: |
| WebSocket | 20,363,735 | 288,019 | 8,090,482 | **28,742,236** |
| Yellowstone | 58,512 | 15,171 | 0 | **73,683** |
| HTTP | 167 | 0 | 0 | **167** |
| All transports | 20,422,414 | 303,190 | 8,090,482 | **28,816,086** |

Yellowstone's 73,683 bytes include 37,991 transaction-body bytes and 35,692 account, status, slot and block-metadata bytes. Observed native ping/pong payload bytes were zero. The WebSocket census includes 5,812 failed Pump and 5,594 failed PumpSwap messages. The 8,090,482 shutdown bytes are included in both the total and cancellation reserve accounting. All 19,414 delivery records are present; observable uncaptured bytes are zero. See [BYTE_ACCOUNTING.json](BYTE_ACCOUNTING.json) and [capture/provider.frames.zlib](capture/provider.frames.zlib).

The two interests ran in one simultaneous session. They did **not** produce two complete architectures with identical evidence. Removing only measured components yields diagnostic allocations of 28,778,095 bytes for the original architecture and 8,435,940 bytes for the filtered architecture. Their 20,342,155-byte difference is **not verified savings**: the smaller allocation lacks the required canonical evidence. Complete same-evidence totals for both architectures remain undefined. The original executor receipt is preserved unchanged in [capture/result.json](capture/result.json); the offline accounting additionally includes the fourth native packet and all shutdown delivery.

Alchemy administrative usage was read through the authenticated connection before the run, shortly afterward, and once after reporting had advanced. At 19:04, the initial report contained only 40 HTTP CU and 0.0000009616 native TB. The final snapshot has freshness through **19:12 UTC**, with partial hourly buckets. Account CU increased from 1,730,149.7724 to 1,737,101.5362, exactly matching the Pump-app window's 6,951.7638 CU. The Pump window also reports 0.0000353903 native TB.

| Authenticated reported usage | Amount | Billing-unit byte equivalent |
| --- | ---: | ---: |
| Pump HTTP | 50 CU | HTTP method priced; 167 response bytes observed |
| Pump WebSocket | 6,901.7638 CU | **34,508,819 bytes**, derived at 0.0002 CU/byte |
| Pump Yellowstone | 0.0000353903 TB | **35,390,300 bytes**, assuming decimal TB |
| Streaming total | Separate CU and TB meters | **69,899,119 bytes** |

The metered equivalents exceed received application bytes by 5,766,583 WebSocket bytes and 35,316,617 native bytes. Protocol overhead, buffering, dispatch before cancellation and unknown external Pump-app activity are not separately attributable. The observation window is app scoped, not exclusive experiment attribution or a finalized invoice. These differences receive no savings credit. Native TB is a separate billing meter and cannot be inferred from the zero native CU entry. See [USAGE_RECONCILIATION.json](USAGE_RECONCILIATION.json) and the three retained administrative snapshots.

At published list prices, the reported CU and native TB changes imply **$0.006303948495** of usage. This dollar amount is calculated, not an authenticated invoice charge: the account's displayed rounded USD remained $0.91. The applicable published prices are $0.525 per million CU, Solana WebSocket 0.0002 CU/byte and Yellowstone $75/TB. Reporting delay was directly observed, and no further polling is needed to turn an incomplete comparison into a savings claim. Sources: [Alchemy pricing](https://www.alchemy.com/pricing), [compute-unit costs](https://www.alchemy.com/docs/reference/compute-unit-costs), [Admin API metering](https://www.alchemy.com/docs/reference/admin-api/overview).

Economic and candidate parity remain incomplete:

| Evidence requirement | Result |
| --- | --- |
| Complete common finalized intervals | **0**, versus the required three |
| Canonical economic-event rows / native witnesses | **0 / 0** |
| Complete ordered economic history | **Not established** |
| Candidate locator, lifecycle and consumer projections | 52 rows each, equal; no differing projection digests |
| Candidate history outbox | 246 rows each, equal |
| Canonical coverage/checkpoint publication | No complete interval; Model B publication remained blocked |
| Independent status evidence | Delivered, but no complete success interval or failed PumpSwap status case |
| Current/Survivor independence | Sources unchanged; live end-to-end certification unavailable |
| Candidate and position deadline / latency parity | Zero work or position samples; **not established** |

Matching locator projections and empty economic tables do not prove complete economic parity. Unreleased early logs remain pending rather than being normalized into a favorable comparison. The comparison reasons are `fewer_than_three_complete_common_intervals`, `pump_or_pumpswap_success_unsampled` and `model_b_publication_not_released`.

Preflight securely reconciled the configured Pump credential with authenticated app `9bin99s96t7ga5e9`, Solana Mainnet, and the owner's masked identifier. No credential, masked suffix or secret-bearing endpoint is published. The verified Pump endpoint fingerprint is `8f3feda9d10baa64d74b5ecb3a97cfa48af379982666f93a425e537668a51749`. PAPER was inactive/dead with MainPID zero; no known competing local acquisition workload was found. Passive monitoring processes were inspected. The existing shared governor was available, with an empty queue and no active cooldown or rate errors. Storage admission and the pinned Python 3.12.14 transport dependencies passed.

The owner's PAYG, unlimited monthly CU, 10,000 CU/s capacity and seven-day peak of 431.667 CU/s are recorded as dashboard facts. **External Yellowstone occupancy and account-wide live headroom remain unknown.** Neither published capacity nor this finite admission result certifies spare account-wide stream capacity. The only executor adjustment recognizes the owner's explicit admission-first policy with these facts kept false/unknown and all local safeguards required. Identity, freshness, topology, request, byte, memory, storage and shutdown checks are unchanged. Every executor AST node except that receipt gate matches the published base; production source is unchanged.

| Admission or resource measurement | Actual | Unchanged maximum |
| --- | ---: | ---: |
| Native channels / Subscribe RPCs | 1 / 3 | 1 / 3 |
| WebSocket connections / initial subscriptions | 1 / 2 | 1 / 2 |
| HTTP requests / published HTTP CU | 3 / 50 | 5 / 90 |
| Physical methods / native writes / ping writes | 8 / 3 / 0 | 11 / 3 / 12 |
| Observable application receives | 28,816,086 bytes | 48 MiB stop, 64 MiB stopping-frame allowance |
| Cancellation bytes | 8,090,482 | 64 MiB reserve |
| Peak process RSS | 89,300,992 bytes | 512 MiB |
| Peak allocated output | 20,660,224 bytes | 256 MiB; soft stop 224 MiB |
| Supervisor wall / shutdown | 46.374050460 / 0.278453165 seconds | 60 / 2 seconds |

All ten shared-governor grants succeeded. Maximum queue wait was 1.483840051 seconds; the final queue was empty, with no new rate errors, admission rejection or `RESOURCE_EXHAUSTED`. Original four-second HTTP admission deadlines and at-most-eight-second stream-initiation deadlines remained unchanged. Candidate/position deadline parity and native-versus-WebSocket event latency were unsampled. Shutdown canceled all three native calls without a hard kill or resource breach. The child consumed 20.835442902 CPU seconds. Cumulative process `write_bytes` was 995,827,712 bytes, distinct from the 20,660,224-byte peak retained-output allocation; no Droplet monthly compute/storage savings are established. See [ADMISSION_RESULTS.json](ADMISSION_RESULTS.json), [LOCAL_PREFLIGHT.json](LOCAL_PREFLIGHT.json) and [capture/supervisor.json](capture/supervisor.json).

Monthly Pump usage remains a scenario estimate, not a forecast derived from this prefix-only capture. The inherited activity assumptions and common acquisition costs are unchanged. Substituting the four-packet mean into the existing native size sensitivity gives:

| Monthly scenario | Original WebSocket architecture | Filtered-native size sensitivity |
| --- | ---: | ---: |
| Quiet | **$2.86** | $4.51 |
| Normal | **$29.24** | $43.05 |
| Busy | **$200.82** | $230.60 |
| Stress | $1,360.23 | **$955.91** |

These estimates exclude account-specific credits, taxes and unallocated billed overhead; scenario rates are assumptions, not extrapolated experiment rates. Four below-floor packets cannot calibrate steady-state native billing. The normal scenario favors retaining WebSockets, while the stress sensitivity favors native delivery; **the measured economic winner remains undetermined**. Full assumptions are in [COST_ESTIMATES.json](COST_ESTIMATES.json), and the inherited model is [COST_MODEL.json](../pumpswap-provider-bandwidth/COST_MODEL.json).

Production remained preserved: no deployment, PAPER restart, subscription switch, credential change, trading, strategy change or capital reallocation. Meteora and Ramses remain paused. The original $500 epoch `paper-1791089005190643467` remains intact. Five protected production files have identical before/after content hashes; a 64-file durable-state metadata inventory changed only in the authorized shared-governor database/WAL. All 363 production source files match their preserved hashes. Disposable experiment databases remain outside Git, with hashes retained in [EXPERIMENT_ARTIFACTS.json](EXPERIMENT_ARTIFACTS.json); the full received-frame archive and original executor/supervisor receipts are published. See [PRESERVATION.json](PRESERVATION.json).

The four new preflight tests and seven unchanged executor boundary tests passed offline (**11 tests**). The repository-required offline FAST check was attempted once with a 180-second timeout, removed production environment selectors and the repository network guard. It timed out after displaying one failure marker, before a final test summary; its current failure identity is unconfirmed and **no full FAST pass is claimed**. The base also retains a prior full FAST failure in an unchanged Pons source-equivalence test, but that does not establish this run's failure identity. Logs, source hashes, secret scanning and report arithmetic checks are retained in [VALIDATION.json](VALIDATION.json), [SOURCE_IDENTITIES.json](SOURCE_IDENTITIES.json) and [MANIFEST.json](MANIFEST.json). No unrelated engineering was reopened to improve the result. GitHub CI is explicitly skipped for this report publication; no workflow deploys production.

The next action is to **retain WebSockets and review the captured prefix-only native progress offline**. Remaining blockers are missing complete finalized evidence, missing live candidate/position deadline coverage, and unresolved reconciliation between billing meters and observable receives. This authorization is consumed. No repeat, longer experiment or production activation follows from this report. Any later provider experiment requires fresh authorization; production activation requires a separate owner decision after complete validation. No production-change recommendation to adopt the replacement is warranted by this result.
