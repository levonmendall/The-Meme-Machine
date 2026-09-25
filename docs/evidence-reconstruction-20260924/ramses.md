# Ramses accepted-block reconstruction diagnosis

Primary immutable run: `35949285193`; runtime `1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`.
Native hourly artifact `10790448432`, SHA-256
`698dcc65131bdc972f0be3176f8b29d276f8f054c77c86aa780a2bcd237dda6a`.
Digest-verified local projection: `evidence/native`, derivative artifact
`10791522985`, obtained by read-only workflow `35959153525`.
Historical artifacts and admission classifications remain unchanged.

## What the historical 0/7 means

The lane completed 10 universe scans and produced 17 pool/frontier screening
rows for seven unique pools. Every row's sole frozen strategy reason was
`cost_evidence_unavailable`; every row's precise cost boundary was
`no_executable_bounded_wnative_quote_route`.

This was a completed negative structural cost-route check. It was not missing
historical pool state, a failed bin reconstruction, a missing gas sample, or a
provider deadline. The native report retained eight authenticated gas-receipt
samples (eight unwind observations; the unchanged conservative proxy handles the
other operation categories).

Replayed the existing `quote_native_cycle` independently for all 17 cases using
285 exact captured request/response records pinned to their original block
hashes. Candidate and route clone identity checks ran during the replay. All 17
cases reproduced the precise no-route boundary. Every one of the 81 captured
`getSwapOut` responses returned the entire input as unconsumed, zero output, and
zero fee. Both the configured direct WNATIVE/USDG route and any available
candidate-token first-hop routes were unexecutable at those pinned frontiers.
There is no evidence-supported acquisition repair to make here without changing
the frozen cost-route boundary or inventing cost evidence.

Full receipt/header canonical pre-entry reconstruction runs only after a
qualified screen in `ramses_all_pool_lifecycle.run`. None of these 17 screens
qualified. Continuing their reconstruction was unnecessary after the proven
structural rejection. No missed profitable opportunity can be inferred.

| Pool | Screening attempts | Primary causal bucket |
|---|---:|---|
| `0xb1c3a6cf5f7c7cf2646e29378efc8b26c39a2eae` | 5 | valid early structural rejection |
| `0xe4780e0d0d5f51f9497b14afedd9c176815cf5dc` | 3 | valid early structural rejection |
| `0xb881bb80658a190fcf1b8feaba1c3781039cce69` | 2 | valid early structural rejection |
| `0xc063b607ebfa652d4fd5a8148a602ce4b57408de` | 3 | valid early structural rejection |
| `0x65efa1cc2fe2ebfc7dedb1d74c9e20d8c0c2a7bf` | 2 | valid early structural rejection |
| `0x43c70df87d7448ec5b605d1139d9e4fafaecc9ab` | 1 | valid early structural rejection |
| `0xa2e87f0c416e41c803370141ef337c5bd7545f71` | 1 | valid early structural rejection |

| Metric | Unique pools | Pool/frontier attempts |
|---|---:|---:|
| Screened | 7 | 17 |
| Full reconstruction actually required after screening | 0 | 0 |
| Full canonical evidence requested | 0 | 0 |
| Full canonical evidence completed | 0 | 0 |
| Full reconstruction unnecessary after valid structural rejection | 7 | 17 |
| Required candidate evidence failed / provider / deadline / pending | 0 | 0 |

The five transport-level HTTP 429s in lane telemetry were separate, recovered
observations. They do not explain these seven candidate outcomes. All other
candidate causal buckets in the requested taxonomy have zero primary cases.
The historical telemetry/classification defect affected all seven pools, as a
secondary defect rather than an additional disjoint candidate bucket.

## Implemented engineering correction

Historical code unconditionally emitted `admitted` and `evidence_requested` for
every screening row, then mapped any missing cost or construction reason to
`reconstruction_incomplete`. It never emitted `evidence_complete`, including
for genuinely completed downstream canonical reconstruction.

The correction preserves strategy decisions and records their causal meaning:

- Completed negative bounded cost routes become an explicit structural rejection
  with `evidence_not_required`; they never fabricate evidence completion.
- Missing/unproven cost metadata, provider errors, or incomplete wide state stay
  required evidence failures. An unavailable route label without the complete
  conversion result does not silently become a valid rejection.
- Screening qualification remains `screening_qualified`. Actual
  `evidence_requested`/`reconstruction_started` are emitted only when the
  connected lifecycle invokes canonicalization.
- `reconstruction_complete`/`evidence_complete` occur only after canonical
  receipt/header reclassification returns; a complete negative decision is
  included, while a thrown boundary stays incomplete.
- Native screen summaries retain exact required/not-required status and causal
  buckets, and the report exposes pool and pool/frontier denominators separately.
- A non-provider lifecycle boundary uses its actual failure class, avoiding a
  duplicate false provider-failure label.

Lane-owned files:

- `robinhood_research/ramses_evidence_coverage.py`
- `robinhood_research/ramses_extended_test.py`
- `robinhood_research/ramses_all_pool_lifecycle.py`
- `robinhood_tests/test_ramses_evidence_coverage.py`
- `robinhood_tests/fixtures/ramses_cost_routes_35949285193.json`

The parent owns dynamic `pipeline.py` stages/classes and preservation of
`evidence_status` in `certification.worker.compact_ramses_screen`; these are
required integration companions. No lane git commit, push, workflow action,
network market call, or historical rewrite was performed by this task.

## Verification

Python `3.12.14`. Focused causal, extended-market, continuous-campaign, and
connected-lifecycle suite passed 41 tests before the final extra wide-state
negative control. Initial complete affected lane suite passed 344 tests.
Final lane suite after the extra control passed **345 tests in 13.722 seconds**;
see `evidence/ramses-tests.log`. `git diff --check` also passed.
Eight new regressions cover all 17 captured cases, all 81 quotes, provider and
unproven absence, valid earlier policy rejection, missing wide state, separation
of screening from full evidence, a campaign with no unnecessary reconstruction,
and canonical successful/failed reconstruction promotion.

Active Wide Maker v3 policy bytes/hash, qualification and execution rules, target
scope, provider rate/capacity, evidence requirements, finality/timing, accounting,
and paper-only authority remain unchanged. No profitability claim.
