# Ramses coverage diagnosis — preserved run 35935431384

Read-only analysis of runtime `c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66` and its composed Ramses tree. No market requests or runtime edits were made by this lane. The predecessor hour remains censored.

**A demonstrated engineering defect prevents preentry history authentication for both otherwise screened qualifiers.** It is separate from the five pools with genuinely unavailable bounded cost routes, and from the latest-scan denominator defect.

## Authority and evidence

- Ramses source: `5dd003b45a60a73e19bf1162f81e4f1ccd2b4ef2` plus the ordered Ramses overlays in `The-Meme-Machine/certification/sources.json`; declared composed diff `fb970b518446b807fb4e2aeba87743cd383ef5cb45132839d009e0b7293c78c4`.
- Policy: Active Wide Maker v3, `bf75a70fcdf68cf231dd354eab7cb56879bc4c16184553db5c121ea0fdc5d4ef`.
- Frozen target: authenticated USDG pools with one or two swaps in the preceding 1,800 finalized-chain seconds; full factory inventory and economic log census remain acquisition scope. Exactly eight maximum wide-state candidates, radius 100, and existing liquidity/range/cost rules remain unchanged.
- Cadence: finalized frontier polling every 15 seconds; new-frontier scans with the existing 60-second minimum scan interval. Complete authoritative state, receipt/header history, costs and executable unwind are required before entry. Existing seven-day maximum hold and 210-second rebalance decision deadline remain unchanged.
- Original artifact `10785439707`, SHA256 `1729982afa710db37dc401b0d515125f7cd7d5c6fd2d8a43fafaf334a86e326c`. Verified derivative artifact `10786398294` from extraction run `35945640187`, ZIP SHA256 `b2f9a2e3dc41efbb080b6ccb11ebcdd33b53172ca4984ed9243a1a038a3baee3`.
- Extract root: `/workspace/scratch/90828f6d88ca/repair-evidence/coverage-native/`; original-file hashes are in `provenance.json`.
- Key files: `certification-hourly/ramses/telemetry.sqlite`, `certification-hourly/ramses/rpc-evidence.jsonl.gz`, and `certification-native/hourly/ramses/robinhood-ramses-extended-market-report.json` / `robinhood-ramses-continuation.json` / native pipeline SQLite.

## Quantified funnel

| Observation | Count | Interpretation |
|---|---:|---|
| Completed finalized scans | 10 | Nine frontier advances; 67 duplicate-frontier polls skipped |
| Acquired economic-log pages | 180/180 | 18 complete pages per scan; no censored census scan |
| Quiet pool/frontier observations | 25 | Includes overlapping pools across scans |
| Intentional non-USDG exclusions | 3 | Existing scope applied; not a narrowed denominator |
| Intended USDG state attempts | 22 | Pool/frontier observations, not distinct opportunities |
| Complete state screen rows | 21 | One state acquisition failed |
| Missing-cost screen rows | 15 | Five distinct pools; all bounded routes genuinely unavailable |
| Qualified screen rows | 6 | Two distinct pools; screening is not entry authority |
| Completed preentry acquisition attempts | 5 | Both pools reproduce the metadata mismatch defect |
| Preentry census stopped by HTTP 429 | 1 | Sixth attempt; remaining pages were never acquired |
| Unique discovered/screened IDs in native pipeline | 7 | Native union excludes the failed state row at that frontier |

The terminal latest scan has zero USDG targets, while the block union has seven. Do not divide seven by zero or otherwise use this latest scan as the block denominator. Existing reporting candidate `cd52852c2817887f1cd91667ce9b196ab8ad4f46` correctly suppresses that unsupported ratio. Keep block-wide absolute discovery coverage unknown unless an independently reconstructed same-window universe is supplied. These reporting semantics must not erase the losses below.

## Preventable preentry reconstruction defect

In composed `robinhood_research/ramses_all_pool_lifecycle.py:171`, `_canonical_preentry_history` still performs raw `event not in receipt["logs"]` membership at line 244. Public logs annotate `blockTimestamp="0x0"`; corresponding authoritative receipt logs contain the real timestamp. Every other log field matches, and the matching block header/receipt checks succeed. The existing `abi.receipt_log_matches` at line 88 already permits only that optional annotation difference; earlier overlays applied it to native replay but missed this preentry path.

Captured completed attempts:

| Pool | Public swap-log RPC sequences | Exact event identity |
|---|---|---|
| `0x544c010194d904a152524455fd9f3de59bbac034` | 104, 282 | transaction `0x95486fd158e48f01ca14f4efcece4bbcaa60624241de333f07717a9348ccac0f` |
| `0xe5c549d30eb7ac99dcaaddd4a7fec48c5d523a31` | 584, 1031, 1360 | transaction `0xc731330b2d8ec5b1c0f2261e13cde368a9458725aa74ed2b36361a16ff7c25a8` |

All five captured completed attempts deterministically reproduce `qualifier_history_receipt_header_disagreement` in the original composed function. Ignoring only the optional timestamp annotation authenticates the exact same canonical history. The sixth attempt acquired the same swap at sequence 1581 but failed on the next census request; its incomplete history cannot be promoted retroactively.

Smallest candidate: import the existing strict matcher and replace only the membership predicate with `not any(receipt_log_matches(event, log) for log in receipt["logs"])`. Keep duplicate checking, payload matching, receipt success/identity and header checks unchanged. No new provider request, retry, route, finality source, strategy threshold or timing change is needed.

Reviewable files are alongside this report:

- `ramses-preentry-candidate.patch` — applies cleanly to the exact composed lane (`git apply --check` passed).
- `ramses-regression/test_ramses_preentry_metadata.py` and `ramses-regression/fixtures/ramses_preentry_35935431384.json` — exact captured two-pool excerpts with original provenance.
- Baseline: five tests run; two positive tests fail with four subtest errors, while three negative-control tests pass.
- Exact candidate evaluated in memory only: **5/5 pass**, including real identity, payload, unknown metadata, receipt, header and conflicting-duplicate failures.

The repair recovers the preentry history stage. Full unwind evidence was not captured after the historical failure; no natural entry, settlement, profitability or repaired future coverage is inferred.

## Genuine bounded cost-route unavailability

All 15 `reconstruction_incomplete` screen rows have `cost_evidence.reason=no_executable_bounded_wnative_quote_route`, not provider transport/budget failure. All seven populated scans had a valid native gas model. Across them, six authenticated direct WNATIVE/USDG pools returned `amount_in_left=input`, `amount_out=0` (42 direct quote results). Four candidate bridge tokens had no factory pair. The fifth had two authenticated first-hop pools, both returning zero output at both relevant frontiers.

| Pool | Failed screen rows | Candidate bridge finding |
|---|---:|---|
| `0xa2e87f0c416e41c803370141ef337c5bd7545f71` | 5 | No WNATIVE/bridge pair |
| `0xfccb663cdbd8c84930c462df2365ee4684ef93f0` | 5 | No WNATIVE/bridge pair |
| `0x6d3e31fd6f61c4d51c3526700a648b409cd48424` | 1 | No WNATIVE/bridge pair |
| `0xb881bb80658a190fcf1b8feaba1c3781039cce69` | 2 | No WNATIVE/bridge pair |
| `0xe4780e0d0d5f51f9497b14afedd9c176815cf5dc` | 2 | Two first-hop pools; neither executable |

Implementation authority: `ramses_costs.py:255,338,394`. Do not broaden to another candidate's bridge/general routing or invent a cost. These remain visible fail-closed reconstruction limitations. The existing `test_ramses_costs.py` covers absent executable first-hop behavior; the proposed preentry patch does not alter costs.

## Separate provider and observability losses

1. **One state acquisition failure:** telemetry checkpoint sequence 827 records `pool_prestate_failed` for `0xe5c549...` at frontier 70938724, `pools_attempted=2`, `pools_completed=1`, `pools_failed=1`; the completed scan ends at 3 attempted/2 completed. RPC sequence 701 is an eight-member pinned-state batch with `provider_rpc_-32000`. Its response is null because the native transport raises before returning the response body; the underlying provider message cannot be established. `ramses_capture._batch_chunk` retries rate errors only. There is no evidence supporting a generic retry or revised error interpretation.
2. **One provider rate limitation during preentry:** RPC sequence 1582 stops the public lifecycle census for the same pool. `ramses_lifecycle_log_census.py:37` intentionally sets `rate_retries=0`; successful prefixes are cached, but the absent remaining pages cannot be reconstructed from this attempt. No additional existing retry allowance is demonstrated. Final continuation state is inactive, has `error=provider_http_429`, and no open position.
3. **Reporting loss:** native pipeline records discoveries only from successful state rows (`ramses_extended_test.py:681`), so the state failure does not appear in `unique_provider_failed`. Async lifecycle errors update a mutable continuation state/proxy (`certification/lifecycle_timing.py:564`) after compact lifecycle copies are archived; all six archived lifecycle rows remain `continuation_active`, and earlier async errors are superseded by later attempts. An external audit must retain the five reproducible metadata failures plus both provider losses. Do not interpret native `unique_provider_failed=0` as no provider loss.

Provider summary: 1,710 requests, 9,701 logical calls; zero failed admission requests; maximum admission wait 8.261 seconds; aggregate raw queue wait 659.906 seconds; aggregate transport time 722.461 seconds. Scan duration ranges 18.546–545.461 seconds. No Ramses deadline, capacity, stale-before/during-evidence or permanently starved source segment is established by this block. Continuous-time never-discovered opportunities remain unknown.

Recommended action: implement the isolated preentry matcher patch with its captured regression; retain all cost-route and provider limitations in the post-block audit; independently keep the same-window reporting correction. Certify only the final integrated exact SHA. Never rewrite the predecessor observation.
