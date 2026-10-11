# Alchemy acquisition efficiency execution report

Retain the existing Alchemy applications and selective acquisition architecture. No evidence supports buying Enterprise, dedicated infrastructure, a new webhook receiver or another stream. PAYG is the most suitable public product arrangement for the current combination, **conditional on confirming this account's actual plan and tariff**. Administrative tools expose historical consumption but do not establish those entitlements.

Two additional improvements are implemented on the isolated branch: authenticated Pons transaction senders survive independent consumers/restarts, and operational Pump curve scouts request 49 account bytes instead of 56. Native quotations, gas, canonical fences, financial validity, strategy decisions and provider limits are preserved. An additional immutable quoter getter optimization has offline equivalence proof and remains outside trading imports.

## Reconciled source and operating state

The base is PR #129 publication `030705397cf75766b5bffbea41abb8bf8db12104`, containing frozen tested source `5fa099edbce26a69b28503e893a961131feca57e` and trading runtime `e17d91fb1d95194774e94ae444b04cfe127d42ab`. GitHub still reports #129 **open and draft**. Its integration ancestry preserves #126–129; the other local integration checkout has no commits outside this ancestry. Concurrent Alchemy capacity preparation was inspected read-only and reused in the next-test specification.

Implementation commits: `34c7b6aaaa74fa596de510e46520ba356a5c35d6` (sender retention and scout slice) and `6e4b0a096d3cd45a580c5e956fb8024e098a73fb` (legacy domains retain sender metadata only in memory). Branch: [`efficiency/redundant-acquisition-20261011`](https://github.com/levonmendall/The-Meme-Machine/tree/efficiency/redundant-acquisition-20261011). Exact frozen-source checks are in [VALIDATION.json](VALIDATION.json). The candidate is not deployed. PAPER is inactive and disabled. The original $500 accounting, inactive $1,000 proposal, paused Meteora/Ramses and all capital/provider limits are unchanged.

The final committed implementation passed **322 focused checks in 118.030 seconds** on CPython 3.12.14 with offline providers. Coverage includes exact trailing boundaries, creator/liquidity safety, economic equivalence, reorganization, restart, cache pressure and long-duration winners. These are selected checks, not a new full-suite claim. Earlier fixture failures and storage refusals are retained and identified in the validation receipt.

## Authenticated account evidence and missing entitlements

[ACCOUNT_EVIDENCE.json](ACCOUNT_EVIDENCE.json) records authenticated Admin results through **2026-10-11 02:28 UTC**. October CU: **1,740,125.5362**, displayed compute value **$0.91**. Solana accounts for 1,737,251.5362 CU and Robinhood for 2,874. Solana HTTP contributes 1,154,900 CU; WebSocket delivery contributes 582,351.5362 CU. gRPC records zero compute CU and **0.0063307322 TB of separate delivery**. Both applications currently have zero webhooks.

These are retained development/observation usage, not a continuously protected-position sample. Applying public assumptions gives $0.91357 compute plus $0.47480 gRPC for this recorded window; **$1.38837 is not an invoice or monthly forecast**. No marginal rate, credit, remaining allowance, account throughput, replay entitlement or complete runtime-key binding is exposed. Successful filtered analytics proves that administrative capability, not a specific plan. Masked key suffixes cannot authenticate runtime binding.

[RETAINED_TRACE_SUMMARY.json](RETAINED_TRACE_SUMMARY.json) verifies an existing genuine October 7 mixed-provider capture against its manifest. It records 3,631 HTTP starts, 85,230 source-modeled CU, about 91.20 MB gRPC and 402.12 MB WebSocket application payload over startup, a planned 180-second steady window and drain. The public component value is about $0.09381 for that capture. Its older Pump/Meteora source, twenty-starts/s governor, 78 RPC errors and lack of a monetary controller prevent using it as current protection, billing or monthly-incidence proof. It shows why actual delivery/recovery needs measurement; differences from another period are not optimization savings.

The exact nonsecret owner export/support checklist is [ACCOUNT_AND_PRODUCTS.md](ACCOUNT_AND_PRODUCTS.md). No entitlement is inferred from public advertising.

## What the Pons monthly specimen actually buys

The old model repeats a one-event native specimen every three seconds: `864,000 × 232 CU = 200,448,000 CU`; at the frozen public $0.525/M assumption this is **$105.2352**, with 3,456,000 physical starts and 7,776,000 elements. It already includes PR #129's batching and same-turn head reuse. A batch reduces starts; its logical members remain separately priced.

| Specimen component | Elements | CU | 30 day component sensitivity |
|---|---:|---:|---:|
| Initial header and ordered target/previous checkpoint checks | 3 | 60 | $27.2160 |
| Current quoter code | 1 | 20 | $9.0720 |
| Manager relationship and exact remaining-token sell quote | 2 | 52 | $23.5872 |
| Gas price | 1 | 20 | $9.0720 |
| One incremental log window | 1 | 60 | $27.2160 |
| One newly relevant receipt | 1 | 20 | $9.0720 |

**Historical receipts are already conditional and cached.** Quiet holding does not buy one old receipt every tick. Removing that synthetic event assumption yields 212 CU, three starts, eight elements and $96.1632/30 days for a one-new-block quiet specimen. The $9.072 difference is an **8.62% model correction**, not a new billing saving from this branch. Repeated numeric membership checks protect still-unfinalized history; hash-keyed bodies cannot replace them.

The same old specimen also undercounts log work when several blocks advance. The actual source replay with 30 new blocks and ten-block windows buys 332 CU; 40 blocks buys 392 CU. Their uninterrupted core sensitivities are $150.5952 and $177.8112. A prior authenticated 160-block/16-second sample supports investigating this issue, but does not supply a month-long market distribution. Neither one block nor 30 blocks per tick is labeled ordinary activity here.

At one advancing block, 152 of the 232 CU are the currently retained fresh quote/code/gas/header graph, 60 CU are incremental history, and 20 CU are event-dependent receipt enrichment. Within that graph, the manager getter's 26 CU can be eliminated **only** under the inactive exact-runtime proof below. Dynamic code identity, hooks, token behavior, fees, gas and oracle/routes cannot be treated as unchanged because swaps are absent.

## Changes and same-evidence proof

| Change | Original purchase | Retained evidence and fallback | Demonstrated reduction |
|---|---|---|---|
| Pons sender reuse | Repeated `eth_getTransactionByHash` when a cached receipt lacks `from` | Validated sender plus transaction/block identity in the existing receipt cache, provider/source domain and fresh numeric membership; misses/forks/busy/full cache retain original requests | 100 repeated senders: 2,080→80 CU, 102→2 elements, 4→2 starts; $0.00105 public modeled saving per replay, 96.15% of that recovery specimen |
| Pump account slice | Seven unused bytes on each operational BondingCurve scout | Same full program/discriminator filter and all consumed bytes 0–48; full 56-byte slice when Meteora's locator is included; incomplete frames retain original rejection/repair | Seven account-data bytes per frame and seven serialized protobuf bytes in the measured fixture; $0.000525 per million frames at $75/TB, before provider byte-meter validation |
| Inactive immutable manager candidate | `poolManager()` call in native quote batch | Complete compiler input/runtime verification, four matching immutable offsets, fresh current code equality, unchanged gas/exact sell and final canonical fence | 26 CU/compatible cohort, zero starts on match; $11.7936/30-day single-owner continuous sensitivity; unknown code restores getter with **one extra start** |

Sender metadata shares the existing 8,192-record/16-MiB memory map and the existing durable receipt 8,192-record/64-MiB aggregate budget. It cannot displace receipts on admission and is evicted before receipts at pressure; outstanding receipt obligations remain protected. It stores only authenticated hash, block hash and sender. Optional retention uses the original nonblocking lock/zero busy timeout and never creates a new database or owner. Legacy qualification domains have memory-only sender reuse; they do not gain unbounded durable metadata. Normal receipts with `from` do not need the new lookup/store. New source/provider identity intentionally starts a cold domain; that one-time acquisition is not hidden as a recurring saving.

Files: [cache](../../meme_machine/lanes/pons/pons_selective_acquisition.py), [V4 consumer](../../meme_machine/lanes/pons/pons_selective_v4.py), [durable adapter](../../meme_machine/runtime/robinhood/pons.py), [receipt budget](../../meme_machine/runtime/robinhood/plane.py), [Pump scout](../../meme_machine/solana_selective_source.py), [focused regression](../../tests/test_redundant_acquisition.py), [inactive proof](../../engineering/redundant_acquisition/quoter.py), [measurement driver](../../engineering/redundant_acquisition/measure.py).

[REQUEST_NECESSITY.json](REQUEST_NECESSITY.json) classifies 35 purpose-specific acquisitions with their consumed fact, freshness, change trigger, cache/canonical requirements, failure behavior, public CU basis and disposition. A single method can serve multiple obligations; its classification never grants a blanket suppression rule.

The getter proof uses public Sourcify compiler/source material, not an authenticated current Alchemy quotation. It is **not activated**: changed-code fallback adds admission latency, requiring original three-second fault/partial-exit proof. Full executable quotes remain mandatory. Existing #126 Pump warm snapshots, immutable-slot time reuse, dense receipts, shared headers/cohorts, canonical history and addition necessary-condition checks are not credited as new changes.

## Minimum safe observation and acquisition path

1. Keep original three/five-second risk observations and the existing selective streams, health/gap monitoring and durable incremental history. Retain fresh mutable state/native net executable sell value wherever complete mutation coverage cannot prove it unchanged.
2. Reuse authenticated historical bodies and identity facts; acquire only uncovered log intervals/new receipts/senders. Wider exact-filter pages use the existing protected capability record, density/saturation bounds and ten-block fallback. Canonical checkpoints advance only after complete authenticated evidence.
3. Entry, additions, partial/full exits and recovery obtain every original required exact-quantity native, gas, canonical and USD fact. Same-turn reuse requires the existing identity/session/quantity/fence checks. Final Pons quotes and native USD routes retain their original five-second boundaries; oracle check/heartbeat rules remain unchanged.

No swap silence, untrusted stream timestamp, generic token price or cached block number proves unchanged sell value. Offline native replays without swaps still detect a price stop and a gas-only exit. The event-only wake planner and PAPER shadow remain inactive. Lost events, incompatible cohorts and provider inconsistencies retain native acquisition/repair or block new-risk admission; they supply no age-only sale authority.

## Workload and cost evidence

[OFFLINE_WORKLOADS.json](OFFLINE_WORKLOADS.json) executes identical market facts against published #129 and this candidate. It includes 18 native scenarios, cold/warm sender recovery, source-shaped USD freshness branches and the existing Pump modes. It reports physical/logical/CU/throughput counts, quote/receipt/header work, injected queue/latency, local time, action/ledger equivalence and explicit exclusions. Streaming/financial data injected by native fixtures are not claimed as observed market acquisitions. Missing cache/distribution metrics remain null.

| Native Survivor specimen, one cycle | Starts | Elements | CU | Result |
|---|---:|---:|---:|---|
| Quiet one block | 3 | 8 | 212 | HOLD |
| Quiet 30 / 40 blocks | 3 / 3 | 10 / 11 | 332 / 392 | HOLD |
| One new transaction | 4 | 9 | 232 | HOLD |
| Sharp price decline without swaps | 3 | 8 | 212 | Full exit |
| Gas change without swaps | 3 | 8 | 212 | Full exit |
| Partial realization | 6 | 12 | 298 | Correct fresh partial quantity |
| Full exit with event | 4 | 9 | 232 | Full exit |
| Missing new sender | 5 | 10 | 252 | Original sender fallback |
| Four compatible Survivor owners | 4 | 12 | 310 | Four independent native decisions |

2×, 5×, 10×, 25×, 50×, 100× and 1,000× initial winner observations preserve the original first realization; long-duration regressions preserve subsequent holding rules and identity. Failure/reorganization/restart/stream-gap behavior is covered by the focused original tests, without inventing successful fault decisions or fault frequencies. Synthetic two-RPS timing includes actual governor queueing and separately measured local time; it excludes injected financial acquisitions and **does not certify full provider capacity**.

The executable model supplies 24h, 72h, seven-day and 30-day **continuous component sensitivities**, plus activity/window/replacement formulas. Ordinary/high-activity event rates and expected total monthly utilization remain unknown. No fixture is multiplied into an observed market bill.

| Component only, public assumption | 24h | 72h | 7d | 30d |
|---|---:|---:|---:|---:|
| Old Pons Survivor one-event specimen | $3.5078 | $10.5235 | $24.5549 | $105.2352 |
| Pons quiet one-block current path | $3.2054 | $9.6163 | $22.4381 | $96.1632 |
| Pons quiet 30-block default window | $5.0198 | $15.0595 | $35.1389 | $150.5952 |
| Pump Survivor warm baseline quote | $0.9072 | $2.7216 | $6.3504 | $27.2160 |
| Existing opt-in Pump warm quote | $0.3629 | $1.0886 | $2.5402 | $10.8864 |
| Existing Pump exact local-slot time | $0.1814 | $0.5443 | $1.2701 | $5.4432 |

Pump Current additionally retains the 20-CU concentration element in the cited source shape: warm baseline $32.6592/30d versus existing opt-in $16.3296, excluding genesis, streaming, USD and other work. The historical model's rotation allowances yield $32.784822 Current and $27.320685 Survivor; rotations/local cache hits are not measured utilization.

Mandatory Pons USD is substantial. The original shared reader's synthetic advancing-block branches buy cold **420 CU/10 starts/19 elements**, warm expired-route **158/6/8**, or refreshed-oracle **354/8/16**; a valid intervening tick buys zero. With exactly one route, three-second sampling, six-second route refresh and inclusive sixty-second oracle cache, the 30-day component is **75,953,574 CU / $39.87562635**, 2,670,548 starts. That is a labeled source-shaped sensitivity, not a market forecast or new saving. Pool/route cardinality, completion delays, restarts and failures can increase it.

Eight hypothetical $25 positions, two per regime, fit the original $500 static portfolio/family/regime upper limits before additional admission constraints. They are a resource example, never funding authority. [COST_MODEL.json](COST_MODEL.json) includes one-owner, four-regime and eight-owner component projections, reproducibly derived by [derive_costs.py](../../engineering/redundant_acquisition/derive_costs.py). The four-regime table preserves Current Pons's original one-event specimen rather than inventing a quiet Current measurement. Its original and candidate core sums are identical: $228.25152/30 days; correcting only the Survivor quiet assumption gives $219.17952. Adopting the **existing inactive** Pump warm path conditionally gives $186.52032; none of these differences is new billing savings. Eight unshared owners double those core sums. Baseline discovery and compatible shared USD are counted once, while independent quote quantities remain necessary. Shared four-owner 310-CU event acquisition is **existing** offline capability-gated sharing, versus 928 CU for four private replicas; it is not a four-regime schedule proof.

Fixed host/storage costs are already present without the position and are excluded from marginal protection. Baseline discovery, authentic ongoing stream delivery, qualifications, SOL USD refresh distribution, settlement/recovery/failure frequencies, sustained reserves and combined latency remain unmeasured. Neither $96.16 nor $150.60 is a complete cost of safely protecting a $50 position. The 30-block core plus the conditional USD component is about $190.47/month **before** those exclusions; this does not establish economical $1,000 PAPER operation. Long winners retain legitimate market exits and unlimited permitted holding; cost pressure never becomes sale authority.

## Savings and activation disposition

| Component | Original | Candidate | Savings and proof status |
|---|---|---|---|
| Pons held core, same native evidence | 212 quiet / 232 one-event CU | Identical | No new recurring core saving; offline equivalent |
| Pons USD valuation | Original shared 5s route / 60s oracle reader | Identical | No new saving; authenticated capacity unproved |
| Pons history/senders, 100 replayed missing-from transactions | 2,080 CU / 4 starts | 80 CU / 2 starts | 2,000 CU / $0.00105, new offline proof; frequency unmeasured |
| Pump held core | Baseline 100 CU; existing opt-in 40/20 | Identical existing modes | Previous #126 saving; provider lifecycle validation pending |
| Shared acquisition | Existing eligible cohort machinery | Preserved | No double-counted saving |
| Streaming/discovery | 56-byte operational scout data | 49-byte data | Seven bytes/frame, new offline proof; actual meter delta unproved |
| Total incremental protection | Complete cost unknown | Complete cost unknown | No authenticated invoice reduction claimed |

Requires provider proof: wider Robinhood filters/ranges, full one-owner protection with USD, exact Pump optimized snapshots and stream meter effect. Offline candidate only: immutable getter and pre-existing `eth_callMany`/dense receipt product alternatives. Post-launch: economically justified event-history transport replacement or longer validated gRPC replay. Unsafe: swap-silence quote suppression, generic-price execution substitution, weaker oracle/canonical checks or clock/age-driven sales.

The new caches/scout need no diagnostic provider workload. Optional PAPER shadow purchases can cost more than the small metadata saving: one 232-CU diagnostic would consume the modeled benefit of over eleven 20-CU sender hits. Keep it off. [PASSIVE_MEASUREMENT_DISABLED.json](PASSIVE_MEASUREMENT_DISABLED.json) prepares a five-minute, 2-MiB, existing-counter/journal extraction with zero additional provider work during a separately authorized protected lifecycle. Replay the same retained facts offline; no additional live baseline stream or sampling service is introduced.

## First PAPER decision and smallest next test

Pump is the nearer engineering candidate because its warm state acquisition already has strong offline 100→40/20-CU equivalence. This is an engineering assessment, not authenticated readiness. It still needs actual combined discovery/position latency and financial/recovery acceptance. Unproved Pons improvements do not create a new Pump gate. Pons has a concrete capacity defect in the accepted envelope: its financial refresh adds six/eight dependent warm transports not included in passing core fixtures, and the unchanged two-starts/s governor has not demonstrated complete three-second protection when those refreshes coincide. Missing-sender partial acquisition already has a 3.18-second core counterexample. No price model or larger advertised plan resolves those timing gaps without exact-endpoint and complete native acceptance.

The next isolated component is the **existing** cold Pons USD check described in [NEXT_PROVIDER_TEST_DISABLED.json](NEXT_PROVIDER_TEST_DISABLED.json): 15 seconds, 12 maximum starts, 24 elements, conservative 1,440 CU, 4 MiB delivered, 2 MB response/in flight, two RPS, one in flight, zero retries/subscriptions/orders. Expected public CU value $0.0002205; conservative ceiling $0.000756. The owner dollar ceiling is **$0.01**, enforceable only after the applicable authenticated upper tariff and exceptional charges are supplied. Separate owner authorization is required by this assignment. The specification and harness remain disabled; no test was dispatched.

A successful component check does not authorize PAPER or prove complete first-owner protection. Activate clear cache/scout changes only as part of an exact reviewed candidate and actual capacity acceptance. Validate the existing Pump opt-in before adopting it; enable wider Pons windows only with protected exact-endpoint/filter evidence. Defer new products, quote suppression and substantial further engineering until the first properly protected position.

The lowest **demonstrated offline Pons core quiet specimen** is three starts/eight elements/212 CU at one advancing block; a complete authenticated sustained protection cost is unknown. Complete historical evidence is already not reconstructed each tick. Immutable source/ABI facts, validated nonproxy construction relationships, hash-keyed historical bodies/senders and exact finalized Solana slot times can persist with their existing identity/invalidation guarantees. Lightweight evidence safely reduces historical acquisition; it does not yet justify skipping fresh native protective quotations. No different Alchemy plan has demonstrated a better total cost for this machine.
