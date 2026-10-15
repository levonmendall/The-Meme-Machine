# Indexed-retirement observation — 2026-10-15

**RECOVERY_REQUIRED. Original 300-second readiness FAIL; acceptance 0.**
Executed `bdc19709e7daad243b3e3e1c3d50874af79695c1` under standing owner
[issue134](https://github.com/levonmendall/The-Meme-Machine/issues/134), funding closed.
The controller stopped for `STARTUP_LIMITATION` and finished after **915.985 seconds**.
Its immutable raw result says `STOPPED_REVIEW_REQUIRED`, `drained=true` and
`recovery_required=false`. Those fields do not override actual native shutdown:
Pump received TERM, exceeded the existing 15-second lane wait, received SIGKILL
and exited **−9**. Final Pump `DISCOVERING/reconciled=true` health was stale before
the kill, not a graceful STOPPED record. Pons reached STOPPED/reconciled=true and
exited 0. Preserve the raw result and every prior failed outcome unchanged.

Native reconciliation first appeared at 197.435 seconds for Pons and 431.022
seconds for Pump. Combined readiness still failed within the separately allowed
900-second diagnostic startup. No original fatal file was present in the output;
the timeout and failed Pump cancellation remain real failures.

The 465.376-second interval after Pump first reported native reconciliation
measured these same-generation slot-head rates. CONTROL is receipt-side progress,
not independently measured provider emission. Slot units are not economic-event
counts, and overlapping Pump/PumpSwap progress must not be summed.

| Stage | Slot units/second |
| --- | ---: |
| CONTROL receipt | 4.188 |
| Joined | 1.811 |
| Prepared | 1.822 |
| Newest retained economics | 1.822 |
| Durable timing head | 1.814 |
| Fixed Pump program publication | 1.822 |

CONTROL-minus-stored grew **932→2,033 slots**, while stored-minus-fixed-publication
remained 4 slots. This demonstrates continuing pre-persistence accumulation after
native restoration, not merely a frontier-display delay. Required-history age,
complete proof eligibility and per-decision strategy-consumption rates remain
unavailable; newest heads do not establish complete preceding coverage. The
sampled cohort union observed 1,333 obligations, 1,303 authenticated receipts and
1,301 exact ACKs. Receipt `at` is original source receipt time, not independently
observed consumer-COMMIT completion. These samples are not population throughput.

The indexed planner **did execute and apply**: final durable retirement receipt
4014 records `indexed_hot_pages`, 64 metadata rows under a 64-row bound,
off-owner preparation and canonical-generation revalidation. Its latest turn took
1.948 seconds and retired zero records; that is not the run's retirement total.
The rolling-economic hot cursor and rotating-table key are present; the other
three exact hot-cursor keys are absent, not zero or proof their tables were
visited. CandidateHistory's `work_candidate_status` index is installed. This
post-stop evidence resolves the metrics analysis's explicitly unverified planner
applicability; it does not rewrite that earlier analysis or its stale interim
archive sample.

Current-process labelled retention completed 154 callbacks: 22.505 wall seconds,
2.244 thread-CPU seconds, peak 0.603 seconds. The earlier 53.806-second owner hold
did not recur in these labels. This uncontrolled observation is not a causal
whole-machine speedup comparison. During the post-reconciliation interval the
service used 1.696 CPU cores, with 26.413 cgroup throttled seconds; the actual
owner accumulated 102.344 CPU seconds and 200.269 kernel runnable-wait seconds.
Sampled page/journal waits show storage waiting without identifying one SQL
statement, lock holder, responsible device or hardware insufficiency. Actual
checkpoint handoff holds were 23.521 seconds in that interval, 50.007 over the
capture; overlapping checkpoint coroutine spans must not be added to those holds.
Peak sampled service memory was 3.190 GB. Minimum observed free storage was
12.073 GB root and 20.190 GB state volume.

Read-only post-review verified **$1,000 cash, zero eight-category monetary
obligations and exact head 9,660**. Only 320 indexed append events followed the
authenticated head-9,340 boundary; they were one admission, eight owner and 311
reporting publications. Historical $500 accounting, all four active v1 policy
bindings and financial genesis remain unchanged. The final current cohort has
five exact ACKs and 27 preserved pending records; both preceding 32-record cohorts
are fully ACKed. Older named pending witnesses remain. Owners are dead, both
historian/consumer leases inactive, writer lock unheld; source OFF, admission
closed/not failed, queue zero. These bounded consistency findings support existing
guarded recovery in their checked scope, not completed frame drainage, readiness
or permission to ignore the new Pump kill. No full-store integrity scan or replay
was repeated. A small private authenticated head-9,340 state is now retained for
subsequent bounded tail verification.

Usage was **416,448 accounted CU**, 11,409 logical elements (37 Solana / 11,372
Robinhood), and 3,043 physical starts **including** four native opens. Confirmed
accounted application bytes were 17,490,513 HTTP and 661,854,189 native; uncertain
exposure was 16,777,216 HTTP / 285,212,672 native bytes, not confirmed delivery.
New native failures were zero. Reservations and open accounting receipt/stream
rows are zero; new risk remains closed. Frozen modeled cost **$0.318077220405**;
provider invoices unavailable. Managed-Pons queue observations and flat operation
do not prove full quote/USD timing, provider suitability or held protection.

Compatible clean `66f85d61bf4d3ba9a01efdc0e9eb68949419bda8` source and the two
saved small overlays were restored at 03:21:44 UTC without database rewind,
counter reset or policy-history deletion. PAPER is inactive, disabled,
`Restart=no`, funding closed. Never launch the restored old finite diagnostic
overlay unchanged.

Next: diagnose the demonstrated Pump cancellation failure from its retained
operation/stack records, and use existing owner suboperation evidence to isolate
productive work versus runnable/storage waiting in candidate commits. Add only
the missing bounded discriminator if those records cannot identify a correction.
Do not repeat unchanged conditions or claim hardware insufficiency. Original
SQLite BUSY, Pons READONLY, managed held protection, native replay semantics and
backup/protection compatibility remain separate open issues. All approved six
opportunity-access changes, nine economic changes and volume-quality behavior
remain preserved. Prior focused validation is retained in the
[preceding repair handoff](STANDING_RETIREMENT_FAILURE_20261015.md); no additional
test campaign or application operation was performed to write this result.

Exact artifact locations, sizes and hashes are in
[the evidence index](evidence/standing-retirement-observation-20261015.json).
Private evidence remains in the existing `blocker-repair-20261011` sibling and
the original `/var/lib/meme-machine-diagnostics/20261015-standing-retirement-bdc19709-025742`
directory; no evidence databases or prior handoff trees were copied.
