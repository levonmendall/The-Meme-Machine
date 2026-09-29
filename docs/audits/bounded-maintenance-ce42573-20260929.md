# Bounded archive/retirement correction: ce42573

Date: 2026-09-29. Repository: levonmendall/The-Meme-Machine.

This control-branch report preserves the causal comparison produced locally before the runtime edit, then records publication and verification. It does not change the runtime or grant qualification authority. The complete pre-runtime-change report has SHA256 6852648d94c674432511cecba60a542a9e07f39f9119e00b120f9700cc96e208 and is bound in the candidate request. Historical cohorts 36525293113 and 36594210589 remain rejected; diagnostic 36586266000 remains non-authoritative.

## Exact candidate and current checkpoint

- Commit: ce4257309cb1f6ec68e38d363320edf62d59db7f
- Tree: 276c6d83099cb56aabaaf558e8ad28add2b0529f
- Parent: 872360077cd36c415aff97a4c8d0e57a947c0875
- Publication-only run: 36599098485, succeeded.
- Original bundle SHA256: 9c9ed1fa35962247c2d6254c8a0bb6872ee4c9137d015da2b94e98354313aae5
- Publication artifact 11047697462, SHA256 384081ddb9c430d56ca6af71ac927f20dc5c485b7c84891087b98e948140b0f1. ZIP and all ten manifest entries independently verified.
- Prospective unchanged fixed cohort: 36599254413, attempt 1. In progress at this checkpoint; no acceptance claim.
- Frozen preflight artifact 11048281597, SHA256 161447bb73825ecdbfc7412224d8a94514e6c6423e2df6f7a30e3f25ef8edb92. Download independently hash-verified.

Publication restored the preserved Git bundle without recreating the commit. Remote commit/tree/parent match exactly. Frozen Python 3.12.14 / websockets 17.1 and complete native build passed. All 117 exact-SHA focused tests passed remotely, with zero failures/errors/skips. Local fresh restoration independently reproduced the clean commit/tree/parent and passed Git integrity. An initially malformed control-branch Base64 transport was corrected and its expected blob hash verified BEFORE publication; the original candidate bytes and SHA were never changed and no acceptance run used the malformed transport.

## ROOT CAUSE

The execution-entry guard closes the queued-retention readiness race, but supplies no compensating retirement entitlement. Every ordinary retention attempt can be rejected when the worker becomes READY before owner execution. The maintenance coroutine continues admitting archive slices without requiring any intervening retirement service. The rejected cohort contains direct positive-eligibility/no-retirement windows and sustained downstream debt growth. This establishes an admission-policy defect, not exclusive attribution of all runner timing differences or proof that one correction will satisfy every capacity gate.

## WHAT 8723600 FIXED

It prevents ordinary retention enqueued during preparation from executing after readiness changes. Parent diagnostic 36586266000 recorded 94 such starts with uncommitted archive work already submitted, occupying 8.888213389 seconds in its sampled post-burst window.

For the exact common sampled source interval 378.00-494.91, effective archival was 890.565 records/wall-second on parent versus 965.838 on rejected. All three second-burst hot-to-archive checks changed from failed to passed. These cross-run measurements are observations, not an isolated causal effect estimate.

## WHAT IT OVER-DEFERRED

| Trial | Owner retirement attempts | Actual native calls | Execution-time deferrals |
|---|---:|---:|---:|
| combined-1 | 1117 | 768 | 349 |
| combined-2 | 1090 | 771 | 319 |
| combined-3 | 1103 | 782 | 321 |
| recovery-1 | 1049 | 713 | 336 |

These represent approximately 29-32% of queued retirement opportunities. Additional READY-loop check counts 108762/112501/112482/116994 are check iterations, NOT independent queued opportunities, NOT measured elapsed durations, and NOT known consecutive streaks. Neither guard has a retirement-liveness escape.

## MAX RETIREMENT SERVICE DROUGHT

Exact rejected-candidate slice timestamps and consecutive execution-deferral streaks were not preserved. They cannot truthfully be reconstructed from cumulative totals. Sampled monotonic retired counters establish lower bounds: Meteora and Pump have at least 10.112769 seconds without durable retirement over source 384.48-397.44; sampled archived-pending debt rises 1408 to 4056 and 509 to 1479. PumpSwap has at least 10.088338 seconds over source 223.83-237.06, pending 597 to 2635. A separate 5.059769-second PumpSwap plateau has below-durable-floor debt 167 at both endpoints.

A sampled plateau alone does not prove all archived rows were eligible throughout. Three positive-eligibility held-reader windows independently demonstrate eligible work without service. Only the PARENT diagnostic has exact positive-slice events: 4402 slices; maximum global end-to-end gap 2.739567 seconds, median 0.044574; per-scope maxima Meteora 4.114881, Pump 4.364060, PumpSwap 4.228677 seconds. Those are not rejected-candidate timings. Its code has no finite bound on consecutive READY deferrals; deterministic tests demonstrate the structural defect without inventing production event history.

## ARCHIVE BENEFIT RETAINED

The correction keeps BOTH ordinary-retirement readiness guards unchanged. A READY receipt gets its bounded <=512-row archive slice before one earned retirement admission. It does not restore arbitrary queued ordinary cleanup ahead of initial READY work. Final-slice successor preparation starts before the earned retirement grant, preserving worker/cleanup overlap and one-worker semantics. Preservation of the observed hot-recovery performance remains a prospective acceptance requirement.

## RETIREMENT CAPACITY LOST

Over source 378.00-494.91, parent wall interval 116.438417 seconds and rejected 116.383867 seconds, retirement falls from 895.289 to 731.321 records/wall-second. Rejected archival exceeds retirement by 234.517/s and atomic stage-counter debt increases 27294. Over common late source 504.90-595.89, archival is 988.951/s versus retirement 873.095/s. Recovery stopped at 2219 accepted frames, so no unobserved sustained-tail behavior is asserted.

Matched combined-3 runs each accepted 2223 frames: native retirement calls 888 to 782; committed retirement transactions 2036 to 1857; retirement execution time 69.393770 to 66.796527 seconds; archive queue mean 194.642 to 166.539 milliseconds. Pooled timers are not disjoint occupancy or exact guard-caused service loss.

## WHY METEORA FAILED

In the common post-burst interval, archival 468.519/s exceeds retirement 309.046/s; stage-counter debt grows 18560. Final pending debt 27392, including 27264 below the durable floor. It receives service, but insufficient service, and contributes the largest deficit.

## WHY PUMPSWAP FAILED

Archival 310.644/s exceeds retirement 233.847/s; debt grows 8938. Final pending 11768, including 11343 below the durable floor. Its unchanged fixture has heavier continuity fanout than Pump. Aggregate data does not uniquely separate all index-cost, scope-rotation, queue and checkpoint contributions.

## WHY PUMP PASSED

Its smaller archival demand 186.675/s is met by retirement 188.428/s, decreasing stage debt by 204 in the common interval. Final pending debt is 458. Globally reduced retirement admission is amplified by unequal per-scope work; no new Pump exception or scope-rotation rewrite is supported.

## WHY COMBINED-3 REGRESSED

Parent reader windows retired 1107 and 256 records with source advances 3 and 4. Rejected windows retired zero and zero with source advances 6 and 7 despite positive eligibility at both endpoints. Both observations remain valid. The new guard admits source/archive activity without a mandatory intervening cleanup admission. Exact rejected in-window deferral/checkpoint events are unavailable, so no unique millisecond attribution is claimed.

## SMALLEST SUPPORTED REPAIR

After each successful bounded archive slice-and-plan callback, admit exactly ONE existing bounded ServiceState.retention() call through the same priority-4 owner before the next archive slice. Start final-slice successor preparation before this grant. Use the actual RetentionOutcome, including interrupted/unknown outcomes; never fabricate idle or completed work.

The existing <=512 archive-slice boundary and bounded native retirement grant provide a non-accumulating admission turn without new timers, tuned quotas, debt thresholds, scope rotation or transaction changes. This bounds maintenance admissions conditional on owner service; it is not an absolute wall-clock/deletion guarantee under arbitrary urgent saturation, pins or storage failures. Source/urgent priority and existing SQL interruption remain intact.

## Deterministic and build verification

Six new regressions cover sustained READY two-way admission, final-slice prefetch ordering, no earned grant after failed archival, actual interrupted outcomes, ordinary guard preservation, and real SQLite held-reader/all-scope retirement with source work queued during cleanup. Four fail on original 8723600; all six pass after correction. Existing ordinary queue-race/priority/outcome regressions remain. One older unit expectation now distinguishes unearned cleanup from the single earned bounded grant; no authoritative observer or workload changed.

The candidate changes exactly five tracked files: runtime service, existing archive-scheduling test module, two generated source/protocol identity manifests, and cohort request metadata. Ten runtime lines were added. Native policy objects match after excluding only their explicitly refreshed source fingerprints; frozen workload/observation plan hashes remain unchanged. Local and frozen-runner focused verification each pass 117 tests. Native build collection is not counted as test execution. No full machinery verification or canonical promotion has been dispatched at this checkpoint.

## Authority boundary

PAPER ONLY. No provider/market workload, signing, transaction submission, live money, Phase F, Render changes, deployment, strategy relaxation, acceptance-window change, threshold change, reduced intensity or trial retry. Only simultaneous all-four-green acceptance may unlock required full machinery verification and the established evidence-gated exact-SHA canonical path. Current cohort results are pending, not green.
