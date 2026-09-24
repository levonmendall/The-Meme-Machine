# Pump coverage diagnosis — preserved hourly run 35935431384

## Decision

A narrowly scoped Pump reconstruction repair is justified. The existing public-log negative screen correctly identifies signatures with no trade for the candidate pool, but history hydration and completeness checks ignore that per-pool exclusion set. The recorded run both spent governed HTTP capacity on those signatures and rejected at least one otherwise complete current decision window because their bodies were pending.

Keep the repair in `meme_machine/pump_acceleration_history.py`. Reuse the existing negative classifications in history decoding and pending counts. Do not alter strategy qualification, windows, provider limits, authentication of positive economic evidence, entry/exit handling, or accounting. Broader Pump refactoring is not justified.

This establishes a preventable acquisition/completeness defect, not a claim that all remaining Pump coverage losses will disappear or that another trade should have occurred.

## Provenance and exact source

- Original run: `35935431384`, integration SHA `c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66`.
- Original artifact ID: `10785439707`; archive SHA-256 `1729982afa710db37dc401b0d515125f7cd7d5c6fd2d8a43fafaf334a86e326c`.
- Evidence root: `/workspace/scratch/90828f6d88ca/repair-evidence/coverage-native`.
- The root agent verified the original hosted archive, derivative archive, and selected extracted-file checksums. `coverage-native/provenance.json` records original file hashes and zero market requests for extraction.
- Pump source: `324fee081dd7664a30df4d88aaa1448d28e3033e`.
- Prepared source directory: `/workspace/scratch/90828f6d88ca/lane-worktrees/pump`.
- Independently verified prepared staged normalized diff SHA-256: `73382447eba168503b2c7dc909ecd3498cffabeaa116166c45a3af4c7b74836d`, equal to the manifest.
- Frozen policy hash: `b7718de9298e4c825616bed26c87731a65f43c4b12f152b14e1d574eb86eb8d5`.
- No runtime files were edited by this analysis. The shared DB was queried read-only; no live provider requests were made.

## Frozen observable scope

Authority is `certification/sources.json:lanes.pump.prospect_admission` and prepared `meme_machine/pump_acceleration_strategy.py:POLICY`.

| Dimension | Frozen authority and behavior |
|---|---|
| Target universe | Native-SOL Pump curves in the 60–85% late-curve domain, plus authenticated PumpSwap graduation/continuation modes. Existing positions retain their lifecycle scope. |
| Discovery | Continuous finalized public Pump logs; authenticated graduations establish candidate-specific PumpSwap subscriptions. |
| Scheduling | At least five seconds between curve evaluations for a mint; at least ten seconds between postgrad evaluations. These are existing scheduling intervals, not guarantees that provider work finishes within them. |
| Structural screening | Creation identity, native quote/surface, absolute reserve progress, trailing trajectory and independent demand are screened before expensive evidence. |
| Evidence | Point-in-time authenticated state and transaction bodies for relevant trades, unchanged concentration/executable evidence when an optimistic decision can qualify. Positive economics are never inferred from public hints. |
| Timing | Three distinct curve states including current state over the trailing 30 seconds; Pump tape has 60-second warmup and 75-second retention. Immediate postgrad entry age is 5–180 seconds; second-leg scope begins at 30 seconds and the runner retains candidates through its existing 600-second horizon. |
| External denominator | Absolute chain opportunity census is unavailable. Preserve coverage unknown; raw discovered creation/event counts are not a strategy-target denominator. |

Prepared source locations: `tests/pump_acceleration_natural_prospective.py:196,236,250,697,857,948,954`; `meme_machine/pump_acceleration_evidence.py:84,89`; `meme_machine/stream.py:12`.

## Quantitative reconstruction and intentional rejection

Primary sources are the native Pump report and `pump-acceleration-natural-prospective.pipeline.sqlite`, plus `pump-shared-attribution.json` and the original structured review.

| Classification | Native transitions | Unique mints | Interpretation |
|---|---:|---:|---|
| `incomplete_pumpswap_decision_window` | 180 | 26 | 170 transitions have unhydrated stream bodies; ten have a complete stream but pending historical signature rows. |
| `incomplete_pumpswap_second_leg_history` | 113 | 27 | 107 transitions have pending bodies; 62 lack the lower signature boundary; 56 have both. No capacity-loss or unknown-block-time flags in these 113 rows. |
| `insufficient_curve_trajectory` | 224 | 54 | Required distinct-second trailing states were unavailable. Artifacts do not establish whether each case was naturally sparse activity or local timeliness/retention loss. No curve-code repair is demonstrated. |
| `postgrad_entry_horizon_expired` | 40 | 40 | Frozen timing retirement; classification as generic reconstruction is a reporting defect. |
| Native `strategy_rejection` class | overlapping repeated observations | 79 | Intentional frozen curve-prospect rejection; retain. |

The union of actual PumpSwap window/history incompleteness is **34 mints** (`26 + 27 - 19`). All 34 also appear among horizon retirements. Seven of the 54 insufficient-trajectory mints overlap horizon retirement. Of the 87 native reconstruction-class identities, six are **horizon-expiry only**, 47 have only curve-trajectory insufficiency, and the others overlap these reason sets. Do not sum stage/class/reason counts as lost opportunities.

Additional overlap and timing facts:

- 22 of the 26 window-failure mints also reached a complete postgrad decision vector; four never did.
- 14 of the 27 second-leg-history-failure mints also reached a complete second-leg vector; 13 did not.
- Thirty mints reached a complete postgrad vector; nine reached those vectors only after the 180-second immediate-entry horizon.
- All 34 recorded postgrad candidates had an initial attempt inside that horizon: first age 5–135 seconds, median 70 seconds.
- Of the 180 window-failure transitions, 67 are at age <=180 seconds and 113 at ages 181–600, when second-leg observation remains relevant.
- The reported funnel is 2,051 broad discovered mints, 36 evidence-requested mints and one full-evidence-complete mint. This is not proof of 35 lost full qualifications. Requests are recorded before postgrad hydration; 230 postgrad and 113 second-leg optimistic rejections deliberately skip holder concentration because it cannot rescue a rejection. The two late-curve optimistic preflights also rejected under the frozen rules.
- Provider transport evidence records 27 local `certification_provider_queue_deadline` rejections and zero HTTP/RPC provider failures. There were no Pump 429s, tape gaps, parse failures, or tape capacity losses in the preserved final counters.
- Consumer counters are logical body interests, not candidate opportunities: `pump_window` has 40,519 expired and 12,934 complete interests; `research_history` has 477 expired and 3,737 complete interests. Among Pump-window expirations, 39,575 occurred before transport and 944 after transport began. These overlap mints and repeated observations.

The reporting defect is specifically `meme_machine/pipeline.py:67` (`censor_class` falls back to `reconstruction_incomplete`) combined with `tests/pump_acceleration_natural_prospective.py:697` (intentional horizon retirement). Correct that attribution externally/post-block; do not change runtime solely to improve the audit.

## Demonstrated redundant acquisition

`pump-shared-attribution.json` was generated by `repair-evidence/pump_shared_query.py`, opening the original shared evidence DB read-only. It compares same-pool negative log hints with each original consumer creation/transport time and acquired immutable body. It uses the exact existing pure PumpSwap decoder, whose SHA-256 is recorded in the result. Timestamp comparisons require the hint to precede the consumer/transport by an earlier integer second; same-second ordering is excluded.

| History consumer group | Interests with negative hint before registration | Interests reaching transport with an earlier negative hint | Acquired bodies confirming no candidate-pool trade |
|---|---:|---:|---:|
| `pump_window`, expired | 88 | 24 | 24 |
| `pump_window`, complete | 827 | 845 | 845 |
| `research_history`, expired | 230 | 38 | 38 |
| `research_history`, complete | 1,179 | 1,194 | 1,194 |
| Total consumer interests | **2,324** | **2,101** | **2,101** |

There are zero contradictory acquired trade-bearing bodies for these earlier negative hints. The totals are **consumer interests**, not a deduplicated union of signatures or HTTP requests. They do not establish that every one of these hints had already entered the in-memory exclusion set; the direct trace below does establish the defect for an actual observed window.

A single comprehensive read of the extracted Pump RPC evidence found 21,716 transported `getTransaction` members and **zero duplicate successful transport attempts for the same signature**. Immutable body reuse is functioning. The defect is history reacquiring facts already known from the allowed negative-only screening stage, not a broken transaction-body cache. All 20 signatures in the derivative's illustrative samples were found in successful raw requests across four physical batches.

## Direct historical failure trace

Candidate mint: `26z79ck4mfp89w3ja7XrndAshnPRbrmtmBr4hfGApump`.

Candidate pool: `8V9rDaKtkvD8vspbF7QKpqtrrXayKsqSgnBSQeZbipKU`.

1. A signature page at `1790209976.2049816`, raw request ID `c9ac60aa-24f4-44c8-82a5-75701378831b:1268`, already contained 16 of the sampled signatures with block times `1790209968–1790209973`.
2. Their nontrading public-log hints were retained at `1790209977–1790209982`, inside the next evaluation's stream query window.
3. At evaluation `1790209998` (candidate age 66 seconds), native history status records: `stream_complete=true`, `stream_pending_transactions=0`, `stream_prefiltered_signatures=25`, `signature_complete=true`, and **16 pending history transactions**. The runner therefore emitted `incomplete_pumpswap_decision_window` at `1790210002.3540955`.
4. Those 16 signatures had no prior authenticated bodies. The sampled bodies were only acquired around `1790210074.98`; each contains no PumpSwap trade. They are already excluded by the same predicate used in the earlier stream pass.
5. Example later transport: signature `2LVRUzRFrB2bAWDVZtvJj5jEwvmcPv89WrjYjPMfeJt9Kb96DzrPyssP3P52x6NRbLFNvh6Ag1o7cT8iQS81eLLb` in request `e4a0d21e-04c1-49f0-8376-92053e2df3c3:1403`, completed at approximately `1790210074.9723`.

The exact prepared source explains the result: `_ingest_stream_window` records the existing safe-negative set; `_decode_pending`, `decision_window_status`, and `pending_relevant` consider only `processed`/error/time and ignore that set. In particular, a covered current stream can skip `_decode_pending` but still fail the later decision check on already-negative history rows.

## Minimal fix and regression design for root implementation

Prepared source locations are `meme_machine/pump_acceleration_history.py:162` (negative screen), `:313` (decoder), `:376` (current pending count), and `:449` (historical pending count).

1. In those three pending/decoding loops, skip signatures already in this history object's `stream_prefiltered_signatures`, alongside the existing processed/error exclusions. Reuse the existing per-pool negative screen unchanged.
2. Do not insert negative-screened signatures into the immutable body cache or `processed`, fabricate trade events, or count them as authenticated/hydrated bodies. Keep broad raw observations intact.
3. Keep missing/empty/truncated/possible target-trade evidence fail-closed and subject to body authentication. Negative identity remains scoped to the candidate history/pool.
4. Do not increase provider throughput or evidence deadlines. No shared-broker redesign is required for this demonstrated case. Durable negative-hint reuse beyond the already-known set can be considered separately only with its own causal need; it is not necessary for the minimal fix.

Small regression cases:

- Reproduce the observed pattern: remember future-at-first-evaluation history signatures; then ingest the existing complete nontrading stream logs; advance into their decision window. With the stream covered and no real missing trades, current and historical pending counts become zero without any `getTransaction` call for those negative signatures.
- Include one real PumpSwap trade or an unknown/truncated/missing-log signature in the same history set. Only that signature requires a body; with a missing body completeness remains false. If acquired, the resulting trade events and decision inputs match the existing authenticated path exactly.
- Assert that negative-screened entries remain observed, are not added to authenticated-body/processed counts, and cannot suppress a distinct later relevant signature. Existing negative-admission tests already cover the basic ingress predicate.

An exact-source, in-memory, no-network reproducer already confirmed the bug: stream filtering produced zero requests and one known negative; after `_remember` inserted the same history signature, `_decode_pending` issued one `getTransaction`, producing zero events. This reproducer did not edit files or alter the frozen source.

After the repair, run focused history/negative-admission tests and affected Pump strategy, paper, natural-harness, campaign-tail-drain, and accounting tests. Root owns implementation and all final integrated/exact-SHA certification.

## Protected lifecycle and remaining limitations

The original natural lifecycle is preserved: one entry, two monitoring marks, natural `persistent_demand_deceleration` exit, and settlement. Native accounting is flat and exactly reconciled, with five replayed events and final journal hash `42d95ba8f9f7625e0d0c156ddb6f74f30f90c62feef01a14b6dca839fbfcb37b`. This is machinery/accounting evidence within a censored predecessor block; it must not be promoted into accepted economic statistics after repair.

Remaining limitations include genuine body-completion pressure, incomplete graduation-to-current history for some candidates, uncertain causality of sparse curve trajectories, and an unavailable absolute target denominator. The minimal repair removes demonstrated unnecessary work and false incompleteness; it does not establish retrospective recovery of missing economic evidence or future complete market coverage.

Strategy economics unchanged: yes. Target-market scope unchanged: yes. Provider limits unchanged: yes. Paper-only unchanged: yes. Predecessor censored block preserved: yes.
