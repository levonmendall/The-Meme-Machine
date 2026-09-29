# E27 preserved-evidence diagnosis before runtime changes

Date: 2026-09-29. Repository: levonmendall/The-Meme-Machine.

Runtime remains `9356068cc92f9cadbd35adead3c33b532cbd4268`; tree `b7fea73f83b29e569b9c8ffde47ae11ecb04cf1d`; parent `fdeee2721d2bb63e0ff3234328b06936257493b1`. Historical cohort `36525293113` remains FAILED. Continuation `36526139462` correctly stopped. Canonical branch remains `a775849c940d48bc8f809e99c075e421744bc53f`. No E28 candidate, canonical promotion, Phase F or market run is authorized by this document.

## Preserved evidence verified

Recovered aggregate artifact 11014743705 and source-history artifact 11014423081. Verified exact commit/tree/parent, clean worktree, Git object integrity, 24 aggregate manifest entries, all five original input ZIP digests and all 20 original contained files byte-for-byte against the aggregate. Frozen inputs and 20 runtime source fingerprint comparisons passed. Unmodified E27 aggregation and recovery assessment exactly reproduce the preserved failed results. Twelve read-only audit checks passed with no failures/errors/skips. These are not runtime certification results.

## ROOT CAUSE

Two observed failure mechanisms are established; the unique implementation-level cause is not yet established.

Combined-1's first held-reader window has six durable source frames and zero durable retirement records. The original lower-bound eligibility witness is false at both endpoints. Therefore `no_eligible_witness` and the historical rejection are valid. The original files do not establish whether retirement work was ineligible throughout the interval or became eligible but was not serviced inside it.

Recovery-1 accumulates archive-eligible hot debt after burst #2 and does not drain enough surplus before the frozen deadline. This is a hot-to-archive recovery deficit, not retained-evidence expiry: 4,445 frames, 1,200.15 source-seconds, zero failure frames, peak retained age 198.30694 seconds. The artifacts do not contain paired receipt/queue event order needed to attribute the deficit uniquely to a scheduling or compute/database mechanism.

## EVIDENCE

Combined-1 first/second reader windows retired 0/612 records while source advanced 6/7 frames. Combined-2 retired 512/877 with source 4/4; combined-3 retired 1107/256 with source 3/4. All held snapshots were preserved. Combined-2's first window had false eligibility at both endpoints despite 512 retirements: endpoint-negative lower-bound checks are not exhaustive no-work evidence.

Source `certification/combined_observer.py` arms one held-reader window on actual multi-frame source batching, consumes the phase before evaluating eligibility, and correctly requires positive durable source and retirement progress. Do not manufacture a witness by moving the reader window or changing runtime scheduling just to fit the measurement.

Recovery second-burst late-mean hot debt is Meteora 5341.3333 versus 2024 allowed, Pump 2164.8333 versus 1408, PumpSwap 3692.5 versus 1736. All retirement-stage and mature-tail recovery checks passed. Eventual recovery is not the 120-source-second acceptance requirement.

Lifecycle snapshots show, using actual monotonic wall intervals and debt-conservation-inferred eligible arrivals:

| Source interval | Wall seconds | Eligible arrivals/s | Archived/s | Net debt drain/s |
|---|---:|---:|---:|---:|
| 349.92-370.17 | 20.173 | 968.43 | 1048.93 | 80.50 |
| 385.56-408.78 | 20.255 | 1003.62 | 592.46 | -411.16 |
| 413.37-463.59 | 50.564 | 965.90 | 969.06 | 3.16 |
| 469.26-494.91 | 25.409 | 997.43 | 1062.60 | 65.17 |

The deficit interval adds 8328 records; the following 50.6 seconds remove only 160 net records. Late service shares are approximately Meteora 48.18%, Pump 19.40%, PumpSwap 32.43%, near workload proportions, not evidence of single-scope monopolization.

Recovery archive_commit_plan has 2220 pooled calls: queue mean 189.592 ms versus execution mean 49.057 ms. Those are not paired first-slice/inter-slice latencies. Worker wait is 378.85 ms/1000 reported records versus 383.34/383.10 in combined-2/3. The existing observer wall fraction is 0.8705%, below its 1% bound. Pooled owner, SQL, worker and checkpoint timers overlap and must not be added as disjoint time or treated as causal event order.

## WHY COMBINED-2/3 PASS BUT RECOVERY-1 FAILS

Combined trials run 2223 frames and evaluate interaction/resource conditions, without the extended lifecycle backlog observer or recovery assessment. Recovery runs 4445 frames and the additional hot-to-archive recovery gate. Passing combined controls do not show that their unmeasured recovery ceilings passed. They are proof/resource and pooled-cost controls only.

## WHY THE EXISTING E27 READY-RECEIPT RULE IS OR IS NOT SUFFICIENT

E27 defers new retention submissions after a receipt becomes ready and preserves one <=512-row slice per owner admission. The final slice already selects the next snapshot. It does not remove previously queued retention or older source/foreground work. These are possible blocking mechanisms, not established causes of this historical interval. The failed gate proves the existing rule alone is not sufficient certification evidence; missing event ordering prevents selecting a mechanism-backed runtime repair.

## SMALLEST REPAIR CLASS

No runtime repair is established. First close the demonstrated diagnostic observability gap outside the immutable candidate. One bounded non-authoritative trace uses the unchanged 4445-frame provider-free workload, original bursts, delays, observer and gates. It records snapshot selection, worker start/end/ready, owner submission/execution/errors, receipt-linked bounded commits, actual retirement slices/yield reasons, checkpoint handoffs, and existing reader observations without adding or moving readers.

Nine local diagnostic-observer safety tests passed, including spawn import, single native calls, priority/result/exception preservation and bounded recording. This control-only commit changes no runtime source, policy, workload or acceptance file. Diagnostic results have no qualification, promotion, canonical or market authority; no trial.json is produced, and no automatic retries occur. A successful diagnostic workflow means evidence collection, not Phase E success. Historical failures remain rejected.
