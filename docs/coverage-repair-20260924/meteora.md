# Meteora coverage diagnosis — preserved run 35935431384

This is a read-only diagnosis of the censored predecessor hour. It does not rewrite admission, infer a trade, or count later software as historical market evidence.

## Authority and evidence

- Runtime: `c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66`.
- Source manifest: Meteora source `ec0b96f999f460c35cb63b27cd0387c4f81f9898`, with the declared checkpoint, market-scope-efficiency, lifecycle-clock, public-fee-context and market-assurance overlays. Verified original combined source diff: `74ee2eaf30ef9df3b370cc6e311bd91d44f2fcf271f67c635d63db27277d9c64`.
- Frozen policy: `SOLANA_DLMM_INDEPENDENT_V1.json`; declared policy identity `90c711e5e3e521fb79f93bc386af5a3067d0a30c83ae3407c550f70db581f966`.
- Native evidence: `coverage-native/certification-native/hourly/meteora/solana-dlmm-independent-v1-live.json` and `.pipeline.sqlite`.
- Wire evidence: `coverage-native/certification-hourly/meteora/rpc-evidence.jsonl.gz`.
- Source-page proof: preserved hourly assurance and frozen/stable review; the derivative extraction did not include Meteora public telemetry.sqlite, so this analysis uses the already-verified source-page audit rather than inventing another census.

The target remains nonblacklisted Solana Meteora DLMM pools with exactly one WSOL leg. There is no minimum TVL or absolute-volume threshold. The frozen observable source schedule is three ordered sorts (`fee_tvl_ratio_5m:desc`, `volume_5m:desc`, `volume_30m:desc`), two pages each, 250 rows per page, recurring campaign census interval 60 seconds. Public HTTP minimum interval is 0.10 seconds. Economic-attempt capacity remains 48 per rolling 1,200 seconds. Entry still requires compatibility, a fresh authenticated finalized swap, the exact frozen warmup, full reconstruction and unchanged qualification.

The complete external target-pool inventory is unavailable. The API's global total 131,794 is not a strategy denominator. All full-target percentages remain unknown.

## Proven discovery starvation

Only fee-density descending page 1 was acquired. Five intended segments never received a request: fee-density page 2, both volume-5m pages and both volume-30m pages. No source-page error explains this.

The acquired page contained 250 raw rows, including 171 exactly-one-WSOL pairs. Of those pairs, 160 were discovered and 11 never reached candidate iteration before the observation deadline. The last admitted candidate was API raw rank 231. These are acquired-page facts, not a full-market coverage estimate.

The code path is causal: `_campaign_candidates()` delegates to `_iter_acceleration_candidates()`; that generator reads one page, yields one candidate, and cannot request another row/page until `run_live()` finishes synchronous compatibility, trigger waiting, warmup and reconstruction. The census timer is reached only when the entire generator drains. Accordingly, expensive evidence work consumed the hour inside the first source page, and no second campaign census ran.

Native timing reinforces this cause:

- 31 candidates actually entered trigger waiting; their recorded trigger waits totaled **2,681.781911 seconds**.
- The 13 trigger-timeout attempts occupied **1,564.651323 seconds** between evidence request and terminal classification.
- All 58 evidence-attempt intervals together occupied **3,288.406792 seconds**; stages are serial here, so these intervals do not overlap.
- Discovery advanced from epoch 1790209011.067338 to 1790212606.979689 even though all candidates came from the same page acquired at 1790209011.051830.
- There were 160 completed-bucket history reads and zero discovery history errors. They were individual context reads, not duplicate reads of the same candidate.

This is real source-observation loss and consumer starvation. It is not fixed by changing the denominator to acquired pages or by increasing provider limits.

## Exact disjoint candidate accounting

| Stage or terminal outcome | Distinct pool count | Meaning |
| --- | ---: | --- |
| Acquired first-page WSOL pairs | 171 | Known acquired source subset only |
| Never iterated within that page | 11 | Observation-window/source-iteration loss |
| Discovered | 160 | Native pool identities |
| Public completed-bucket fee context measured zero | 38 | Preserved intentional preflight rejection |
| Compatibility screened | 122 | 160 minus 38 |
| Unsupported Token-2022 behavioral extension | 36 | Intentional structural rejection |
| Unsupported fee mode | 17 | Intentional structural rejection |
| Freeze authority unsupported | 11 | Intentional structural rejection |
| Evidence requested/admitted | 58 | 122 minus 64 structural rejections |
| Campaign pre-entry reserve exhausted | 27 | Observation-window/evidence-admission loss |
| Fresh authenticated swap timeout | 13 | No authentic activity within the frozen trigger window |
| Verified zero-swap warmup | 7 | Intentional no-activity rejection |
| Complete evidence; strategy rejects | 7 | Successful evidence completion, unchanged economics |
| Genuine warmup reconstruction failure | 4 | Two capacity overflows, one mint-supply projection defect, one unsupported rebalance reconstruction |

The last five rows partition all 58 attempts exactly. The seven complete decisions are the only full economic vectors. Evidence-completion latency among them: p50 90.493311 seconds, p95 147.003094 seconds, maximum 147.733116 seconds. These are acquisition metrics, not profitability evidence.

## Reporting and overlapping identities

The final pipeline has **46** `reconstruction_incomplete` rows and 46 distinct identifiers, but those identifiers combine pool addresses with synthetic `pool:trigger_slot` IDs. It does not establish 46 lost pool candidates.

Exact decomposition:

- 27 pool identities: `campaign_window_insufficient_preentry_time`.
- Four pool identities: actual warmup reconstruction errors.
- Eight synthetic trigger identities: `superseded_before_fresh_state`, belonging to only three pools. Seven overlap the two pressure-failed pools; one belongs to a pool that subsequently completed and received a strategy rejection.
- Seven synthetic trigger identities: `campaign_shutdown_unresolved_trigger`. All seven correspond exactly to pools with complete evidence and recorded qualification rejection. `run_live()` writes the qualification terminal directly through `pipeline.record()` rather than the `progress()` path that clears `active_triggers`, so shutdown mislabels those completed triggers.

The native JSON checkpoint shows 39 because it precedes the seven shutdown terminal rows; the final SQLite pipeline shows 46. Preserve both artifacts. Correct the external audit attribution without changing runtime merely to fix this reporting artifact. Preserve superseded-trigger operational counts, but do not add them to unique pool losses.

## Four genuine reconstruction failures

1. Pool `ovtwEHG1eLuqagpSz8QXxfwrsUNKx58hejKjhWjxoeD`: `solana_dlmm_transaction_pressure_overflow`, interval slots 449869024→449869037. Preserved signature responses show 25 successful transactions, including **18 in slot 449869037 alone**. The frozen per-interval verifier bound is 16. This failure cannot be removed by pretending a slot can be split or by dropping transactions.
2. Pool `GYqytuXSiX3GaPuCkLMY4jeRR3mAtyAuQqhD32d45g5y`: same overflow, interval slots 449873418→449873449, 25 successful transactions. This interval spans the previous reconstruction latency; it remains a known bounded-evidence limitation. No capacity expansion or omission is proposed.
3. Pool `FtwzPjTqoFuy8aF8bMBi7QF7UxpdYN5n9YUH6R7DcHjB`: `dlmm_rebalance_liquidity_requires_position_state:449865040`, after four verified warmup chunks. The observed instruction requires position-state evidence outside the captured pool-only reconstruction model. Remain fail-closed; do not treat it as a strategy rejection or an already-repaired case.
4. Pool `EjTLLhayt7s5F9iA143PsCbb9UzvzqG7Q3Q1KJTiLmWh`: terminal mint-info mismatch after five verified chunks. This is a demonstrated preventable projection defect, detailed below.

### Supply-only mismatch reproduced from captured wire evidence

Paired mint: `98kfF7rmsg1QDUEoCqNE7g7M1FdrTt92TEp2CLzypump` (metadata-only Token-2022).

| Field | Start | End |
| --- | --- | --- |
| Endpoint slot | 449870963 | 449870974 |
| Chain time | 1790211048 | 1790211051 |
| Raw transport ID | `d67b348d-26e0-4fed-9c4c-fc7d8f744d46:669` | `d67b348d-26e0-4fed-9c4c-fc7d8f744d46:672` |
| Global mint supply | 956208555432374 | 956207960807047 |
| Decimals | 6 | 6 |
| Mint authority present | false | false |
| Freeze authority present | false | false |
| Extensions | 18, 19 | 18, 19 |

Both raw mint accounts are 390 bytes. Their only differing bytes are offsets 36–39 inside the supply field. All pool fields, reserves, fees and bins match exactly. The retained native signature prefix contains zero successful pool transactions in the interval; its lower-bound witness is at slot 449870908. Reconstructing these exact authenticated endpoint snapshots with that retained prefix and the original verifier reproduces `dlmm_terminal_state_disagrees_with_forward_reconstruction:token_x_mint_info`.

This focused reproduction does not independently prove a complete signature census through the ending snapshot. The final retained raw signature transport is `:671` at 1790211058.472, preceding end-account transport `:672` at 1790211060.006 and block-time transport `:673` at 1790211060.462. The native provider has a two-second response cache, and the census call did not force a fresh transport. No missing transaction is inferred, but no fresh post-endpoint signature read is fabricated. The final replay script explicitly reports this retained-prefix limitation. Supply-only endpoint comparison remains proved, and the historical hour remains censored.

Total mint supply can change through an external burn that never mentions this pool. It is not an input to Meteora pool swap math, LP entitlement, fee calculation, position sizing, executable liquidation or qualification. The separate per-bin LP supply remains an essential input and must stay strictly verified. Searches of `dlmm.py`, `dlmm_tape.py`, `dlmm_paper.py` and the native strategy confirm that paired mint metadata consumers use only program/extensions/authority context; all mechanical supply arithmetic uses bin LP supply.

Scratch proposal `meteora-mint-supply.patch` excludes only the `supply` field inside the two decoded mint-info dictionaries from terminal equality. It retains every other mint field and every pool/bin/vault field, and retains the actual authenticated supply in the terminal state, terminal hash and raw-evidence lineage. `test_meteora_mint_supply.py` contains four focused regressions. Executing the proposed patched module only in memory passes all four, including unchanged swap events, qualification vectors/decisions, virtual position state and executable marks, and negative cases for mint authorities/program/decimals/extensions and bin/vault changes. Runtime files were not edited by this diagnosis agent.

## Provider and reconstruction limits

There were 1,162 physical Meteora RPC transports, 1,637 logical calls and no provider HTTP, JSON-RPC or method errors. RPC latency p50/p95/p99 was 0.126297/0.203078/0.242890 seconds. Public history had no recorded errors. The shared broker records 16 deadline-expired body consumers across two interests, overlapping successfully completed interests; they are not 16 lost pool opportunities. Shared-provider failure counters elsewhere in the broker snapshot are cross-lane and must not be attributed wholesale to Meteora.

Neither no-activity timeouts nor the four warmup failures should be hidden by source acquisition repair. The two capacity failures and rebalance evidence gap remain visible. A repaired supply comparator cannot restore the rest of the abandoned historical 12-second warmup: uncaptured future evidence stays unavailable, so this predecessor remains censored.

## Scheduler draft review and regressions

The root agent's draft `meme_machine/dlmm_discovery.py` separates public page scheduling from expensive history/evidence, uses an on-disk invocation-scoped FIFO spool, and preserves provider pacing and attempt/strategy limits. Review found a publish-before-discovery callback race; root corrected it by holding the spool lock and transaction until the direct pipeline callback finishes. No report/checkpoint calls should run in the source producer.

Remaining review considerations sent to root:

- Preserve original same-sort failure behavior or explicitly document why an intended later page is still requested; never mark page failure as exhaustion.
- Index `(invocation, consumed, sequence)` and avoid repeated full-spool scans becoming a lock bottleneck.
- Preserve a fatal producer's final queue/segment snapshot before propagating the exception.
- Use source receipts to distinguish late responses from timely acquisition in the external source audit.
- Surface pending candidates and oldest queue wait as known operational gaps even when all six source pages are observed. `coverage_unknown` for the external denominator must not hide this backlog.
- Test blocked evidence consumer across all segments and a second census; immediate first-candidate handoff; first-sighting order and deduplication; short pages, page failure, late response, early close, fatal producer and callback publication order.

The repair can prove removal of the scheduling defect and the supply-only projection defect. Only the successor natural block can measure resulting timely evidence throughput under the unchanged frozen capacity. No coverage-complete or profitability claim follows from deterministic tests.
