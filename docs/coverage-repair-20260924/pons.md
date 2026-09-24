# Pons coverage diagnosis — preserved hourly run 35935431384

Read-only diagnosis of frozen runtime `c6b924bb3b90f0e6ee8721d3b8ab44c8f3099b66`. No market/provider requests or runtime edits were made by the diagnosing agent. This report does not change block admission: the predecessor remains censored.

## Evidence and frozen authority

- Original artifact: `10785439707`, `four-lane-hourly-35935431384-1`, 633,092,120 bytes; SHA-256 `1729982afa710db37dc401b0d515125f7cd7d5c6fd2d8a43fafaf334a86e326c`.
- Verified derivative: `repair-evidence/coverage-native/`, with original archive identity and selected-file hashes in `provenance.json`; extraction declares zero market requests.
- Full candidate result: `repair-evidence/hourly-review/complete-review.json` → `pons_complete`; agrees with native `candidate-rows.jsonl` and `opportunity-pipeline.sqlite` under `coverage-native/certification-native/hourly/pons/pons-selective-continuation-v1-cohort/`.
- Raw transport: `coverage-native/certification-hourly/pons/rpc-evidence.jsonl.gz`; queue terminals: native `queue-terminal.jsonl`; authenticated range and header summaries: `hourly-review/pons-discovery-range-rows.json` and `pons-authenticated-header-rows.json`.
- Focused structural decoding output: `repair-evidence/pons-structural-attribution.json`. It binds each structural candidate to the raw request interval using `evidence_started_monotonic`, transport start time, and the unchanged original deadline, then replays `factory_record` and `authenticate_curve`. The deadline alone cannot join candidates: queued siblings share an observation clock and deadline.
- Pons source commit `3de3d376847531ccb90e260cfcc96c37587ccb23`, composed with the four frozen declared overlays. Verified original source diff SHA-256: `8a9d0818606e9c9c8e3ca76ce07f85fe0902aaf761d3de8042b1dd3ff2dd8238`.
- Policy hash: `19e2f4e51be263718ec520b1d315153e04bd216819fcacb3f74e9d9acfecba84`; strategy `pons-selective-continuation-v1/profitability-v1-profit-protection-v2`.

Frozen target: native-quote Pons curves in the 50–85% progress, 120–600 second age, and 20–90 second graduation-ETA domain, plus authenticated graduation/re-entry modes and existing-position lifecycle scope. Broad source observability is all authenticated Pons V2 buy/sell logs; those source rows are not a target-market denominator. Current-state code/factory/header/receipt identity, trajectory, 60-second flow evidence, economics and the unchanged local five-second acquisition deadline remain mandatory for qualification.

Frozen acquisition schedule: 60 chain-second tape warmup; this run covered 65 chain seconds in 65.020 wall seconds. Discovery runs 3,600 seconds after warmup. Poll coalescing uses up to four contiguous ten-block log ranges within the existing 0.5-second poll clock. Candidate screening is at most once per curve per two wall seconds; queue deadline is five seconds, with the existing one-second dispatch reserve. Eight workers concern admitted lifecycles; candidate evidence acquisition is serial.

## Exact funnel and loss accounting

There were 8,589 discovered event identities: 4,320 buys and 4,269 sells. Only buy nominations enter the current-state queue. The existing per-curve reevaluation rule leaves 2,171 screened/enqueued event identities. These are neither 8,589 target curves nor 2,171 distinct target opportunities.

| Scheduled-candidate outcome | Count |
| --- | ---: |
| Intentional current-state strategy rejection | 942 |
| Intentional trajectory strategy rejection | 155 |
| Complete vector, intentional final strategy rejection | 2 |
| `natural_non_native_quote_not_supported` | 609 |
| `invalid_current_snipe_bps` | 140 |
| `curve_factory_disagreement` | 4 |
| Expired/insufficient remaining queue time | 264 |
| Dispatched acquisition timing failure | 45 |
| Provider exception boundary | 10 |
| **Total** | **2,171** |

The native database confirms exact per-identity stage counts and no unclassified remainder in this partition. `strategy_rejection` has 2,196 transition rows but only 1,099 unique identities because both `prospect_screened` and `rejected` record the same outcome. Do not add transition rows as opportunities.

Of 1,907 dispatched evaluations, 1,126 completed current-state authentication: 942 were deliberately rejected there and 184 entered trajectory acquisition. Those 184 split into **155 deliberate trajectory rejections + 27 timing failures + 2 complete vectors**. All candidates passing the trajectory screen reached complete 60-second receipt-window evidence. That window took 0.120 and 0.206 seconds for the two full vectors. Both vectors then failed frozen economic/demand rules; no qualifier or natural lifecycle occurred.

The published 2/184 completion ratio therefore includes 155 intentional early strategy stops in its denominator. It does not establish a 99% reconstruction failure rate. The reporting correction belongs in the external historical audit; preserve historical telemetry and admission.

## Structural labels resolved from native responses

All 753 generic `reconstruction_incomplete` boundaries now have narrower evidence-backed attribution:

| Native label | Native-response finding | Interpretation |
| --- | --- | --- |
| Non-native quote, 609 rows | 74 distinct curves; all deployment/factory identity checks replay successfully; all pair tokens are nonzero | Intentional exclusion from the frozen native-quote scope |
| Invalid snipe, 140 rows | 140 distinct curves; all deployment/factory identity checks replay; every raw snipe value is exactly 9,900; 121 native quote and 19 non-native quote | Deterministic failure of the unchanged zero-snipe qualification gate; the 19 non-native observations also fail scope |
| Factory disagreement, 4 rows | Four distinct curves; all queried factory records have zero curve identity; the frozen authenticator reproduces `curve_factory_disagreement` | Intentional identity failure, not demonstrated infrastructure reconstruction loss |

The narrower non-overlapping structural interpretation is **628 non-native-scope observations + 121 native observations with nonzero snipe + 4 unproven factory identities**. Do not relax snipe bounds, authenticate absent factory membership, or fabricate full vectors for these observations. Native RPC code 3 errors are separate: their failed batch results do not preserve individual response members, so their exact failing methods remain unknown.

## Discovery capture versus timeliness

- 4,274 successful broad-discovery ranges cover every block **70935553–70971901**: 36,349 unique blocks, zero internal holes, zero overlaps. The final range reaches the final sequencer sequence 70971901. This proves capture over the recorded cursor interval, not an independent external target universe.
- All **15 HTTP 429 batches / 33 exact failed ranges** have subsequent successful same-range observations, recovering **85 logs**. Delay to successful observation was 0.258–0.907 seconds. These are recovered provider rate limitations, not fifteen lost opportunities.
- There were 2,133 successful physical poll observation times, 113 inter-observation gaps over five seconds, three over ten seconds, and maximum gap 11.715 seconds. Recorded range-end/header matches show maximum chain timestamp lag 27.455 seconds. Serial acquisition delays observation even when it ultimately captures every range.
- The published `discovered_too_late=264` is the queue-terminal count. It is not proof of 264 distinct opportunities discovered after their target window.
- External never-observed count and absolute target denominator remain unavailable; retain `coverage_unknown`. There is no demonstrated internal authenticated range gap to repair in this block.

## Real timing and capacity losses

- Queue terminal count 264 = **191 dropped below the unchanged one-second dispatch reserve + 73 already expired**. Maximum queue depth was ten, below the 4,096 bound. No queue-capacity, observation-capacity, or local-budget exhaustion occurred.
- These 264 events span 128 distinct curves. At least 67 events on 22 curves had earlier in-block authenticated non-native-quote identity, before those events' first observation. Retain their historical infrastructure classification; disclose that the target-membership denominator differs from raw queue events.
- Dispatched timing loss 45 = **19 `evidence_deadline_before_transport` + 15 `provider_shared_admission_deadline` + 11 `stale_evidence_acquisition`**. The latter two groups together are the reported 26 stale-during-evidence cases. Never add the 15 admission failures again.
- Eighteen dispatched failures occurred during current-state authentication; 27 occurred after current state passed, during trajectory acquisition. Those 27 split into 17 direct evidence deadlines and ten shared-admission deadlines.
- Median queue wait for all dispatched candidates: 0.616 seconds; p95 3.416 seconds; maximum 3.992 seconds. Median queue wait for dispatched timing losses: **3.425 seconds**. Forty-two of 45 already waited at least two seconds before evidence started.
- Candidate-attributed shared-provider wait summed to 273.340 seconds; median 0.041 seconds, p95 0.508 seconds, maximum 1.177 seconds. Across all Pons scopes, admission recorded 546.314 seconds of wait and maximum 9.274 seconds. These scopes differ; they are not additive measures.
- Pons had 15 failed shared admissions: three connectivity, five current-state, seven trajectory. All Pons physical admissions were priority ten. These demonstrate contention but do not by themselves prove that changing lane priorities is necessary or safe.
- The ten provider exceptions are nine whole-batch RPC-code-3 boundaries and one transport failure. The nine RPC failures occurred before current-state authentication completed and span four observed curve addresses. Their exact per-member causes are not captured; preserve uncertainty instead of labelling every method as independently failed.
- Successful numeric-header responses were 8,778 over 8,616 unique blocks: 162 repeated successful block reads, maximum two per block. Complete/public candidate rows contain 1,099 observations over 220 curves, with zero repeated `(curve, block)` pairs. Repeated observations at new blocks are legitimate mutable-state work and must not be collapsed as duplicate opportunities.

## Demonstrated engineering repairs

### 1. Cached launch-age rejection before trajectory reconstruction

Of 155 completed trajectory rejects, 137 fail the frozen 120–600 second age gate. At least 123 have a prior completed trajectory for the same curve; they consumed **209.897 seconds** of redundant later trajectory work. All 137 age rejects consumed 236.579 seconds. The run retained only 15 immutable launch identities, below the existing cache bound.

Use the already authenticated cached launch time with the freshly authenticated candidate timestamp, after current-state authentication and prospect screening but before `_trajectory`. Preserve the current cold-cache path, exact inclusive boundaries, and subsequent reevaluation of young curves. No new read or provider capacity is needed. This removes known unnecessary work from the serial queue.

Do not call `strategy_trajectory_preflight(candidate, [], launch)` for the fast path: that would invent a `trajectory_history` failure for intentionally unrequested work. Emit only the demonstrated `token_age` rejection, with explicit not-acquired trajectory metadata and `complete=False`; retain the existing trajectory-screen output contract so cohort classification stays correct. Validate `0 <= launch <= candidate timestamp`. Do not return qualification authority or permanently exclude a curve.

### 2. HTTP transport honors remaining original deadline

Candidate sequence 301 entered at monotonic 569.7616 after only 0.0189 seconds queue wait. Its raw failing transport started at 569.8148 with deadline 574.7426: **4.9279 seconds remained**, but the request lasted **10.0646 seconds**. Candidate-attributed transport time totaled 10.2705 seconds. The default ten-second socket timeout exceeds the consumer's useful remaining life.

Cap single and batch native HTTP timeout to `min(configured timeout, original deadline - monotonic now)` immediately before `urlopen`, after provider pacing/admission. Reject nonpositive remaining time without transport, preserve normal timeout when no evidence deadline exists, and never mutate the shared session timeout or extend/reset the original deadline. Reject a body that returns after deadline before exposing/caching it. An inactivity socket timeout is not a strict total-time cancellation guarantee for arbitrary trickle responses; do not overclaim.

Five queued followers expired while sequence 301 hung, all with its exact five-second deadline. Two were already known non-native. A timeout cap avoids roughly five seconds of useless serial overrun, but cannot honestly claim those same-deadline followers would be rescued by the timeout cap alone.

### 3. Seed request-shaping identity hints after successful identity authentication

All 609 non-native rows missed the factory hint and issued a separate factory-record batch; those rounds consumed 286.985 seconds. They include 535 repeated observations of the same 74 curves. Looking across earlier invalid-snipe identity successes as well, **602 later observations** already had an authenticated curve/token identity but still used `factory_record_in_first_batch=False`: **553 later non-native rows + 49 later current-state/full rows**. Their separate factory rounds consumed **283.659 seconds**.

The cause is precise: `remember_candidate()` seeds `factory_hints` only after `_authenticate_candidate()` completely returns. Non-native and invalid-snipe exceptions occur after successful compiled curve/factory authentication but before that return, discarding a valid request-shaping hint.

Add a bounded helper to remember curve/token identity immediately after `authenticate_curve()` succeeds and before those structural/economic gates. Subsequent requests still read current `token()`, current factory record, code, header, receipt and mutable state; the existing token-hint equality check decides whether the already-returned factory record can be used. A changed/mismatching token must use the existing second-round fallback. Four factory identity failures must never seed a hint. No negative eligibility cache, permanent curve exclusion, mutable-state reuse, threshold or throughput change is needed.

Measured saved-work durations are causal workload observations, not a prediction that the same number of new opportunities will complete. Validate scheduling improvement with deterministic pressure tests and the next prospective block's original admission logic.

## Source locations and focused regressions

All paths here are relative to the verified prepared `lane-worktrees/pons/` tree; root owns runtime implementation and tests.

- `robinhood_research/pons_selective_acquisition.py`: `ImmutableEvidenceCache.launch`/`remember_launch` (original lines 115/121); `SelectiveEvidenceContext.factory_token_hint`/`remember_candidate`; `_trajectory` (562), cached launch lookup (577), launch hydration (621), `strategy_trajectory_preflight` (774), `evaluate_candidate` (810; trajectory acquisition around 900).
- `robinhood_research/pons_natural_observation.py`: `_authenticate_candidate`; factory authentication precedes invalid-snipe/non-native boundaries. Preserve mandatory current identity validation.
- `robinhood_research/provider.py`: `_http` (45, timeout at 49), `_http_batch` (121, timeout at 128). `provider_topology.py` (227/239) adds pacing/admission before these methods. `certification/worker.py` around 285 caps governor waiting only, not native HTTP timeout.
- `robinhood_research/pons_selective_cohort.py` around 643 drains the queue serially before discovery; around 720–728 selects `trajectory_preflight` only when `screened_stage == 'trajectory'` and records intentional strategy rejection.
- `robinhood_tests/test_strategy_prospect_admission.py`: existing `evaluate_candidate` authentication mock and trajectory/window spies demonstrate early-screen shape.
- `robinhood_tests/test_pons_market_scope_efficiency.py`: frozen age/ETA/acceleration boundary assertions.
- `robinhood_tests/test_pons_selective_continuation.py`: `SelectiveEvidenceThroughputTests.BatchContext` around 425 has real immutable cache and recorded deterministic batches; test around 494 proves trajectory and launch reuse. `state()`, `snapshots()`, `events()`, `vector()` near the top yield a genuinely qualifying frozen-policy fixture suitable for proving the repaired path still reaches unchanged downstream qualification.
- `robinhood_tests/test_provider.py`: `ProviderHeaderTests._Response` and existing single/batch tests verify default timeout and HTTP headers. Add remaining-time, already-expired, and late-body cases without network calls.
- `robinhood_tests/test_candidate_authentication_deadline.py`: existing initial session authentication, rotation, original deadline and priority invariants.
- `robinhood_tests/test_immutable_rpc.py`: expired misses do not transmit, block identity remains pinned, coalesced consumers retain independent deadlines.
- `robinhood_tests/test_pons_natural_observation.py` around 79–130: captured-shaped authentication batch fixture and hint/no-hint cases; extend to identity-authenticated structural failure followed by fresh candidate, and identity disagreement/mismatching token controls.

Required focused behavior: repeated cached old/young age skips trajectory; ages exactly 120/600 and cold cache remain eligible for normal acquisition; a young curve later ages into normal qualification; pressure case shows avoidable old-age/factory rounds no longer delay a timely candidate; original deadline/queue reserve/provider ceilings remain unchanged; failed identity never seeds hints; recovered timely evidence still reaches unchanged qualification; expired evidence fails closed explicitly.

Read-only review of root's draft implementations found no blocker. A standalone synthetic regression was supplied at `repair-evidence/test_pons_factory_hint_reuse.py`; it executes native `_authenticate_candidate` with the real bounded hint store and mocked deterministic read batches. **Five tests passed** against the draft: two non-native observations use batch lengths 11/1 then 12; fresh mutable snipe rejection remains active; changed token forces a current-token factory round; failed factory authentication seeds no hint; an existing hint cannot bypass current factory/header failure. The draft's separate seven-case acquisition regression was inspected but not rerun by this agent. Its mocked qualification-vector case proves downstream invocation, while an actual qualifying frozen-policy fixture would provide the stronger recovered-evidence proof.

## Preservation and remaining limits

No strategy economics, target market, state-age/hold timing, provider ceilings, provider topology, retry allowance, evidence authority, paper accounting, or profitability criteria may change. Do not add alternate providers, finality use, forced activity, or live execution.

Absolute external coverage remains unknown. Queue/deadline losses remain historically real even where some candidates are later proven outside target scope. Nine RPC-code-3 member causes remain unavailable. No full certificate, successor launch, profitability, or prospective repair effectiveness is claimed by this diagnosis. Historical narrowed classification must not rewrite the preserved predecessor block or promote its Pump lifecycle into accepted economics.
