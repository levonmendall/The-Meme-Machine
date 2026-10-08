**BLOCKED_BY_SPECIFIC_PROVIDER_CAPABILITY.** The published Yellowstone protocol
supports successful-transaction filtering. Its full successful payload size,
account-level admission and complete PumpSwap equivalence have not been measured
on the existing account. The preserved tape contains statuses rather than full
native PumpSwap transactions. Standard WS cannot suppress failed log bodies.
Consequently no production subscription change is justified by the available
offline evidence, and **verified provider savings are zero**.

This engineering branch publishes a bounded whole-capture audit, authenticated
small regression envelopes, a conditional failed-log omission replay, a separate
30-day tariff model and [one finite capability experiment](EXPERIMENT.md).
No market-provider call, service deployment/restart, capacity purchase,
infrastructure change or capital initialization occurred.

The source is `repair/pump-provider-offline-20261008` at
`703d8764a775d9680e3b48baf2c96f3fb7cf8eb6`; publication is on
`engineering/pumpswap-provider-bandwidth-20261008`. The latest published Pons head
inspected initially was `engineering/forward-survivor-20261008` at
`d0c67bee09cb58f4b60627c6fdec1ecfee299caf`; its later evidence-only publication
`481bd11e918cda9c5de624a619f44688dc97fefb` was also inspected before this
publication. Its changes and the dirty concurrent
Pons/Robinhood checkouts were inspected and preserved. This branch does not
incorporate or modify their work. Exact validated source/publication identities
are recorded in [PUBLICATION.json](PUBLICATION.json).

[PRESERVATION.json](PRESERVATION.json) verifies all **363 production files** against
the reference, all 37 previously frozen economic sources, and 23 corrected/21
prior capture files against their original manifests. The 29 captured source
hashes match published integration commit
`510b61d1950ae54c8b0435b7b7cae3aad0bcc1fe`. Seven already approved reference repairs
postdate that capture; their identities are recorded separately. No capture label
is promoted to new economic authority.

The original `$500` PAPER epoch remains `paper-1791089005190643467`, with approved
policy SHA-256
`e87385900145e53956df18956ee2390f0d95787e6ffc44243251f9b147eb65f2`.
Current entry/exit, independent Survivor qualification, five-percent family
sizing, realized-equity compounding, shared reservations, tail bridge, right-tail
protection, staged winner scaling, native journals/reconciliation and Model B
startup/recovery are byte-identical. Meteora and Ramses remain paused.
`combined_position_and_candidate_provider_latency_not_certified` remains intact.

The corrected tape retains **50,330,766 application bytes**. Its original meter
charged **50,331,681 bytes**; the final **915 bytes** were charged but not captured.
That unknown frame cannot be classified, filtered retroactively or granted
canonical authority. Framing, TLS, NIC bytes and actual billed usage are not
measured. Compressed capture size is not streaming delivery.

| Corrected component | Application bytes | Packets |
| --- | ---: | ---: |
| PumpSwap successful logs | 27,538,305 | 9,819 |
| PumpSwap failed logs | 13,400,141 | 6,967 |
| Pump successful logs | 4,521,806 | 1,246 |
| Pump failed logs | 3,041,169 | 4,352 |
| Candidate native statuses | 1,673,692 | 16,352 |
| Shared block metadata | 72,165 | 345 |
| Universal Pump account scout | 63,669 | 263 |
| Shared finalized slots | 11,288 | 345 |
| Candidate metadata | 7,304 | 35 |
| Candidate finalized slots | 1,147 | 35 |
| WS acknowledgements | 80 | 2 |
| Charged but uncaptured | 915 | Unknown |
| Total charged application payload | **50,331,681** | |

Failed WS delivery is **16,441,310 bytes**, 33.90% of WS payload. Removing these
bytes is attractive only if a supported acquisition path avoids their delivery.
The 96,052 exact duplicate WS bytes represent about 0.198% of WS traffic.
All native statuses, including 927,338 failed-status bytes, remain required.
The 1,548,879 status bytes below the requested replay floor and other native
prefix bytes were actually delivered. Local floor rejection does not save them.
No corrected reconnect/rebuild occurred. Full attribution, per-subscription
payload and original HTTP receipts are in [BASELINE.json](BASELINE.json).

The previous tape independently contains 67,105,406 captured bytes, including
57,920,465 WS and 9,184,941 native bytes, plus 9,691 uncaptured charged bytes.
It includes additional scoped position interests and 16 native RPC streams, so
its rate must not be compared as a controlled steady-state configuration.
[PRIOR_CAPTURE.json](PRIOR_CAPTURE.json) retains that distinction.

| Alternative examined | Documented boundary capability | Decision |
| --- | --- | --- |
| Current `logsSubscribe` | One `mentions` address; commitment; all/allWithVotes | Retain. No success-only parameter or log-field selection is documented. |
| Yellowstone successful PumpSwap transactions | `failed=false`, `vote=false`, account include/exclude/required | Supported schema; account/payload/equivalence experiment needed before adoption. |
| Native status plus narrower economics | Compact status, signature, index, error and matching filter labels | Preserve both success and failure statuses. They cannot supply missing successful logs or seal history alone. |
| Universal scout plus selected pool/body feeds | Sliced account locators; exact account-based subscriptions | Useful wakeups, insufficient exact launch/migration/ordered economics; no early weak-candidate suppression or population cap is permitted. |
| Status plus targeted HTTP bodies | Existing `getTransaction` and paginated `getTransactionsForAddress` | Preserve recovery exception path. Universal replacement increases requests substantially and has no proven deadline/latency bound. |
| Native account slicing | `accounts_data_slice` | Already used for 56-byte scouts; it does not project transaction logs. |
| WS `blockSubscribe` | Streaming endpoint; scoped program, full/accounts/signatures/none, omit rewards | Full messages are unmeasured; reduced detail omits required economic logs. No supported success-only/log projection established. |
| Native filtered blocks | Account include; transaction/account/entry inclusion controls | Full transaction payload unmeasured; excluding transactions loses required logs. No justified reduction. |
| Combined program interests/deduplication | Native include supports a union; WS standard mention supports one address | Potential small duplicate savings; successful full-body cost dominates and overlap must preserve both scopes. |
| Smaller reconnect replay / removing repeated acquisition | Existing `from_slot`, checkpoints and stable shards | Corrected tape has no rebuild. Delivered prefix suppression is unproved; shortening necessary continuity is unsafe. |
| Deshred, account snapshots or extracted event-only messages | No committed execution logs/status in pre-execution data; account state coalesces economics | Cannot substitute for required ordered committed evidence. No provider switch or purchase proposed. |

Alchemy documents `account_include` as matching any listed account,
`account_exclude` as excluding a transaction with any listed account, and
`account_required` as requiring every listed account. These filters combine;
`failed=false` selects successes and unset `failed` preserves both outcomes.
Full transaction updates include instructions and metadata with logs, balances
and other fields. Their larger payload must be counted. The repository's pinned
14.0.1 protocol and native error/index/bank checks remain unchanged.
[Alchemy transaction filters](https://www.alchemy.com/docs/reference/yellowstone-grpc-subscribe-transactions)
and [upstream protocol](https://github.com/rpcpool/yellowstone-grpc/tree/fb1aaf67cb8b50802d8b59b58a1ac4b274f4acc4).

The standard WS method supplies mention/commitment filtering, with no documented
failure switch or field mask.
[Solana logsSubscribe](https://solana.com/docs/rpc/websocket/logssubscribe).
Account slicing and transaction-status maps are separate request features.
[Alchemy request schema](https://www.alchemy.com/docs/reference/yellowstone-grpc-subscribe-request).
Block detail selection is supported at the streaming WS endpoint, but does not
provide the requested success-only economic-log stream.
[Alchemy blockSubscribe](https://www.alchemy.com/docs/reference/block-subscribe).

Provider documentation conflicts on replay: the historical guide describes
432,000 slots/about 48 hours, while the request reference still describes 6,000
slots/about 40 minutes. Existing client recovery retains its conservative 6,000
slot contract; this task does not assert the larger window is admitted on the
account. Both windows are shorter than Survivor's existing seven-day eligibility.
Account replay availability, history completeness and physical prefix behavior
require verification. An initially weak pool therefore cannot safely lose its
history on the assumption that native replay can always restore it later.
[Historical replay guide](https://www.alchemy.com/docs/reference/yellowstone-grpc-historical-replay),
[request reference](https://www.alchemy.com/docs/reference/yellowstone-grpc-subscribe-request).

The audited scout carries curve locators, reserve/development hints and complete
flags, explicitly `economic_event=false` and `history_complete=false`. It does
not carry every original launch identity, participant, trade, liquidity event or
authenticated migration. Current rejection cannot terminate Survivor retention.
The existing durable history, activity wakeups, retained economic reservoir and
deadline-aware work scheduler remain in place. Promotion/position filters and
the existing independent position feeds are not removed. No top-N or artificial
candidate-population limit is introduced.

The corrected traffic implies a **4,169.31-byte mean native-success ceiling** for
replacing the entire PumpSwap WS interest while retaining existing native status
and continuity bytes. Required logs/signature/slot alone give a serialized
**25,541,710-byte lower bound** over 9,819 successes, leaving only
**15,396,736 bytes**, about **1,568.06 per success**, for transaction, metadata,
index, label, timestamp and recovery overhead. The missing native transaction
fields were not fabricated or passed to authority. The lower bound is not an
available provider projection. If full native delivery exceeds the break-even
total, the switch fails the bandwidth objective even if its tariff is cheaper.
Pump alone has a different 6,069.80-byte threshold; it is not substituted for the
PumpSwap threshold. Prior-tape PumpSwap threshold is 4,578.55 bytes, showing
traffic-mix sensitivity.

| Metric | Reference actual / known | Retained production path | Hypothetical alternative |
| --- | --- | --- | --- |
| WS application payload | 48,501,501 B | Same path; no new acquisition | If PumpSwap WS replaced: 7,563,055 B before new session/recovery effects |
| Yellowstone payload | 1,829,265 B | Same path | 1,829,265 B plus **unmeasured full native success delivery** |
| Charged total | 50,331,681 B | No verified change | Not measurable from this tape; 915 B stays unknown |
| Verified streaming savings | 0 | **0 B** | **UNVERIFIED** |
| Hypothetical failed-packet omission | Not supported by WS | No suppression | 16,441,310 B removed from replay only; full replacement native cost absent |
| HTTP | 12 successful Solana request envelopes, 12 method elements, 210 published method CU | Same path | All PumpSwap successes via HTTP would add 9,819 elements/392,760 CU in this capture |
| Combined prior proof RPC estimate | 120 Robinhood elements plus 12 Solana; 12,210 planning CU | Unchanged | Kept separate from Solana tariffs and actual invoices |
| Failure/complete-input parity | 658 committed failed witnesses in 1,215 native witnesses | Same | Exact conditional replay parity; missing statuses remain incomplete |
| Canonical economics | 287 complete canonical events | Same | Same 287; no complete-market claim |
| Retained identities | 169 observed candidate locators | Same | Same 169; exact eligible market population not certified |
| Streaming pressure | 3 native Subscribe RPCs on one configured channel, 1 WS connection, 2 WS subscriptions | Same | Candidate full-success filter adds one filter to the existing RPC; no extra connection proposed |
| Deadlines / funded positions | Complete live sample unavailable | Preserved code/fixtures | Native full-payload and held-position acceptance still unproved |

The native stream peak is a measured RPC-stream count, not a TCP socket count or
an account admission guarantee. Corrected total native filters are 1 scout + 2
control + 4 candidate; the proposed request would change the candidate request
to 5 filters. Existing position/continuation groups can add their own WS/native
interests; they remain independent and byte-charged in both configurations.
Corrected native admission errors were zero, but the short tape cannot clear the
earlier RESOURCE_EXHAUSTED/combined-latency blocker.

All 5,211 decoded successful source economic events are audited before selection:
7 creates, 917 Pump trades, 1 decoded migration and 4,286 PumpSwap trades.
[PARITY.json](PARITY.json) compares the full original ordered capture through the
actual join, canonical owner, rolling history, lifecycle and CandidateHistory.
The baseline matches the published reference canonical digest and all 11 prior
durable projections. The failed-WS-omission hypothesis matches all canonical
rows and native witness tuples: true indices, original event indices, bodies,
hashes, ordering, first-seen clocks and every candidate/history row. It preserves
658 committed failures with zero failed economic trades. Missing evidence stays
explicit: 10,210 successful log facts remain unwitnessed in both replays.

Across the full tape, 413 Pump and 538 PumpSwap failed log facts have matching
native statuses; 3,939 Pump and 6,429 PumpSwap failures do not. Those 951 matches
are not all complete finalized intervals. Scope-specific successful status
matches likewise exceed the canonical economic subset; they are not completeness
authority. There is no canonical migration, full qualification window or funded
position sample in this tape. The conditional omission result does not validate
actual success-only native full-transaction replacement or full-market recall.

The added frozen fixture is only 3,556 compressed bytes and contains 14 authentic
source records, with original packet digests and ordinals. It tests success/fail
identity contradictions, true-index conflicts, late/missing statuses, large
duplicate-failure delivery, retained full successful logs, explicit byte budgets,
older scoped position interests and supported request fields. It is explicitly
not a complete interval. [VALIDATION.md](VALIDATION.md) records the affected,
FAST/OPERATIONAL suites and baseline-failure dispositions; [COVERAGE.md](COVERAGE.md)
maps strategy/safety adversarial requirements to actual evidence and limitations.
No economic test expectation was changed.

Affected modules passed 136 tests and the final audit class passed nine. FAST ran
856 tests with one failure; OPERATIONAL ran 2,276 with two failures, two errors
and 33 existing skips. The source-freeze failure and two archived-startup IPC
errors reproduce on the untouched reference. The suite-only generation failure
remains unresolved despite passing both isolated comparisons, both full-module
reruns and 20 diagnostic checks per branch. One full-module rerun separately hit
the unchanged simultaneous-debt fixture's 12-second timeout; isolated comparison
passes on both branches and the concurrent Pons publication reports the same
unchanged-source timeout. Full suites are not green. No safety deadline or test
expectation was weakened to make them pass.

The profiled serial replay measured 8.012 CPU/9.819 wall seconds for full reference
delivery and 8.236 CPU/10.151 wall seconds for the omission hypothesis, both
110,196 KiB peak RSS, 8,440 SQLite changes and 87,232,512 process write bytes.
The hypothesis still inspects the preserved failed frames to select them and
both runs include profiler/host contention. These are engineering costs, not
production CPU improvements, WAL totals or billed traffic. No production CPU/RAM
or durable-write saving is claimed. Original steady candidate/position latency
remains unmeasured; retained fixture deadlines are not live capacity proof.

Published Solana WS pricing is **0.0002 CU per byte**, Yellowstone **$75 per TB**,
and `getTransaction`/`getTransactionsForAddress` are **40/100 CU**.
The generic 0.04 CU/byte subscription tariff and diagnostic `ceil(bytes/512)`
are not used for Solana billing.
[Alchemy CU costs](https://www.alchemy.com/docs/reference/compute-unit-costs).
Published PAYG compute is **$0.525 per million CU**; throughput capacity is priced
separately. No upgrade, credit, free allowance or account-specific discount is
assumed. The app's actual contract, billing unit for TB, throughput entitlement
and invoice remain unverified offline.
[Alchemy pricing](https://www.alchemy.com/pricing).

[COST_MODEL.json](COST_MODEL.json) is a full **MODELED** 30-day sensitivity model
with source links, exact Decimal values, separate WS/native/HTTP charges,
startup prefix, reconnect history, candidate reactivation costs and independent
open-position maintenance. Traffic rates are explicit scenario assumptions,
not extrapolated from the capture's 2.379-second post-release tail. Baseline and
retained production path have the same modeled cost. Native success sizes below
are assumptions including full envelopes, not measured deliveries.

| 30-day scenario | Baseline WS / native GB | WS / native / HTTP USD | Retained total USD | Native success 3,000 / 4,200 / 6,000 B total USD |
| --- | ---: | ---: | ---: | ---: |
| Quiet | 21.77 / 4.07 | 2.29 / 0.31 / 0.27 | 2.86 | 1.98 / 2.45 / 3.15 |
| Normal | 242.61 / 13.98 | 25.47 / 1.05 / 2.72 | 29.24 | 17.79 / 22.46 / 29.45 |
| Busy | 1,595.99 / 80.28 | 167.58 / 6.02 / 27.22 | 200.82 | 104.29 / 127.61 / 162.61 |
| High-volume stress | 11,478.03 / 615.63 | 1,205.19 / 46.17 / 108.86 | 1,360.23 | 450.65 / 543.96 / 683.93 |
| Normal, reconnects and reactivation history gaps | 242.61 / 14.03 | 25.47 / 1.05 / 3.89 | 30.42 | 18.98 / 23.64 / 30.65 |
| Normal, one held position | 288.92 / 17.33 | 30.34 / 1.30 / 29.94 | 61.57 | 50.12 / 54.79 / 61.78 |

Quiet assumes Pump success/failure 0.2/0.2 per second and PumpSwap 2/1; normal
2/2 and 20/15; busy 10/15 and 100/150; stress 40/120 and 400/1,600.
Scout and HTTP rates, independent position 5-success/2-failure-per-second
delivery, startup and all recovery assumptions are in the machine-readable
model. Recovery assumes 30 reconnects with 60-second gaps plus 30 exceptional
reactivation histories, each 216 archive pages for an assumed six-hour history
at one transaction/second and 100 transactions/page. Already complete retained
history needs no such refetch. These labels are workload sensitivities, not
predictions, and do not certify restoration before original deadlines. The 4,200-byte
alternative increases quiet streaming bytes by 2.25 GB even though its tariff
cost is lower. Cost reductions alone cannot meet the bandwidth directive.
Status plus HTTP for every successful PumpSwap transaction models about
$1,094.77/month in the normal scenario and has unverified HTTP response bytes
and admission latency. Selecting only currently strong tokens cannot make that
cost comparison legitimate; future Survivor history must remain available.

The next action is the separately authorized finite experiment in
[EXPERIMENT.md](EXPERIMENT.md), after its finite executor and shutdown bounds
pass offline checks. Within the disposable probe, both paths use three native
RPC streams and one WS connection; the candidate request replaces the reference
request on that topology. Concurrent production connections would be additional
account pressure and require established headroom through existing shared
admission before starting. Its actual full-success payload, suppression, independent
witnesses, overlap and error receipts decide whether a controlled configuration
switch is justified. Until then retain universal successful PumpSwap logs,
negative statuses, complete candidate retention, exact recovery and independent
position monitoring. No current production or combined-capacity acceptance is
implied by this publication.
