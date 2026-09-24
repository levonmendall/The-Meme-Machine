# Single authorized campaign: repair, verification and outcome

**Workflow 35962402406 completed successfully, attempt 1.** Smoke and hourly
engineering passed. The hourly economic block was censored by the unchanged Pons
infrastructure gate, and natural-lifecycle certification remains incomplete.
The one-market authorization is consumed and the durable controller is `HALTED`.
No retry, replacement, rerun, continuation or successor is authorized.

## Certified execution

The final repair and market execution SHA is
`029e7a851f122825e19343a9e8a79652a86f6bb4`. The execution ref is
`cert/single-market-evidence-reconstruction-20260924`. The source, policy,
implementation, protocol and configuration digests are recorded in
[final-execution-identity.json](final-execution-identity.json).

The repair preserves strategy economics, target markets, provider limits, evidence
freshness, portfolio and accounting rules, and paper-only authority. The frozen
admission audit found that the existing implementation matches its contract. No
numerical breadth threshold was added and no historical result was reclassified.

| Area | Repair |
| --- | --- |
| Meteora | Retain an authenticated trigger while finalized account state catches up; retain recovery until reconnect and hydration succeed; repair trigger completion, supersession and checkpoint identities. |
| Pons | Attribute authenticated early vetoes separately from required reconstruction; stop redundant cold history acquisition after the existing launch-age veto. |
| Ramses | Separate authenticated negative bounded cost-route checks from genuine canonical reconstruction requirements. |
| Pump | Separate pre-admission uncertainty, normal observation expiry and absent shapes in complete history from genuine missing-history failures. |
| Supervisor | Preserve dynamic pipeline fields and separate required observation episodes so later rejection or success cannot erase an earlier failure. |
| Campaign control | Consume one dispatch intent durably before the dispatch; reject duplicate claims, phase repeats and reruns; block all successor paths. |

## Verification before the only launch

The exact-SHA [non-market certificate](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35961549416)
passed all nine required gates: integration identity, exact-source offline tests,
historical exposure resolution, historical registry release, integrated current
policy, native crash matrix, production adapter connectivity, resource bounds and
restart safety. Supervisor tests passed **201/201**. Lane suites passed
**1,472 tests**: Pump 320, Pons 363, Meteora 444 and Ramses 345.
See [verification-receipt.json](verification-receipt.json).

Two local scratch-output integrated checks retained 10 of 12 governor grant records
despite all acquisition calls returning. Their failed results were retained. A
traced repeat, the unchanged gate in a temporary output directory and the exact
hosted gate each retained 12 of 12. No gate or threshold was weakened. This remains
a local verification limitation rather than evidence of a demonstrated production
failure.

The older run `35956802640` was externally cancelled and its previous durable
program was `HALTED`. Its native final evidence showed all four lanes flat and
reconciled. Immediately before dispatch, the controller found zero other market
runs in `in_progress`, `queued`, `waiting`, `pending` or `requested`.

## Single-run authority

The sole market workflow is
[35962402406](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35962402406),
attempt 1. A fresh 600-second smoke and 3,600-second hourly observation occur inside
that same workflow. Pump retains its existing 1,000-second native follow-up within
each phase; this is not a successor workflow or campaign block.

Authorization: `evidence-reconstruction-20260924-one-market-v1`.
Durable state ref: `cert/single-campaign-120002d402a7d838`.
The separate launcher `35962345309` consumed dispatch authority before its single
POST. Automatic program advancement, durable continuation, replacement, dispatch
retry, repeated phases and reruns are gated off. The certified runtime is unchanged
after launch. This report is a separate documentation-only commit.

## Smoke evidence

The smoke execution and artifact review passed. Concurrent overlap was
600.559821046 seconds; total native elapsed time was 1,604.57335488 seconds. All
four lanes ended flat and reconciled. There were no natural entries or settlements.
Smoke is excluded from prospective economic acceptance.

| Lane | Required full observations | Requested | Completed in time | Other evidence |
| --- | ---: | ---: | ---: | --- |
| Meteora | 2 | 2 | 1 | One unsupported replay primitive caused a genuine reconstruction failure. |
| Pons | 0 | 0 | 0 | 162 authoritative early rejections; three provider-failure observations retain unknown full-evidence necessity. |
| Pump | 0 | 0 | 0 | 49 decision-history requests, 16 supported history decisions and 40 genuine incomplete history episodes. |
| Ramses | 0 | 0 | 0 | Ten valid earlier rejections across two scans and five pools. |

These are separate observation scopes, not interchangeable denominators. A zero
full-obligation count does not establish complete acquisition coverage. Pump's
legacy `unscoped_full_requests=49` counts decision-history markers; it does not mean
49 required full concentration vectors. The exact assurance fields and native
accounting are preserved in [smoke-outcome-summary.json](smoke-outcome-summary.json).

No physical stream interruption was recorded during smoke. This does not prove
historical gap recovery or naturally exercise the reconnect repair. Meteora, Pons
and Pump retained degraded evidence coverage; Ramses' existing coverage diagnostic
was healthy.

## Defects and limits exposed after launch

Meteora ended an unauthenticated trigger wait at `experiment_runtime_deadline` and
classified it as `consumer_deadline`. The pool had `triggered=false`, no authenticated
trigger pending fresh state, four RPC calls, no provider failures and a 72.819741264
second wait. This is pending work at the fixed observation boundary, not a
demonstrated provider or consumer-queue deadline failure. It adds one false coverage
failure observation but creates or loses no required full-evidence obligation.
The native record is preserved unchanged in
[smoke-additional-findings.json](smoke-additional-findings.json).

The smoke's genuine Meteora failure was
`dlmm_partial_limit_order_or_output_fee_swap_unsupported`. Pump's timely body
acquisition limits and Meteora's frozen transaction capacity and unsupported replay
primitives remain visible. No provider rate, economic rule or freshness requirement
was relaxed. No runtime patch or additional market run was made in response to
post-launch findings.

## Hourly evidence and economic observations

The hourly execution and artifact review passed. Concurrent overlap was
**3,602.388362435 seconds** and total native elapsed time was **4,625.654479059
seconds**. There were no process restarts, unexpected exits, forced settlements,
open positions or unreconciled accounts. The archive is complete and uncancelled;
the review verified 76 file digests and reported no integrity failure.

| Lane | Full obligations | Recorded requests | Completed full vectors | Remaining evidence observations |
| --- | ---: | ---: | ---: | --- |
| Meteora | 25 | 25 | 6 | Ten became unnecessary after verified zero-swap vetoes; nine full obligations failed. Two additional decoder failures occurred before a full obligation could be authenticated. |
| Pons | 5 | 5 | 5 | 1,022 valid earlier rejections; six provider-failure, three `curve_runtime_length`, and two stale-in-queue observations remain outside the five completed full obligations. |
| Pump | 1 | 1 | 1 | 434 decision-history requests, 199 supported histories, 356 genuine incomplete history episodes, plus one misclassified economic entry cancellation. |
| Ramses | 1 | 0 | 0 | One pending obligation. The threaded progress-callback defect makes the recorded request/completion counters incomplete evidence of actual acquisition. |

The exact native counters are preserved in
[hourly-market-assurance.json](hourly-market-assurance.json); the causal audit is
[hourly-evidence-findings.json](hourly-evidence-findings.json). Pump's native 357
`reconstruction_incomplete` observations partition into 235 incomplete decision
windows, 121 incomplete second-leg histories, and one signal-decay cancellation.
Its legacy `unscoped_full_requests=434` again counts decision-history markers.
Native records were not relabeled. These windows differ from the historical
baseline, so these counts are not a controlled estimate of repair effectiveness.

Meteora's nine full-obligation failures comprise five frozen transaction-pressure
overflows and one each of external balance-delta mismatch, multiple liquidity
removals, unsupported partial-limit/output-fee swap, and unsupported non-swap
mutation. Two `dlmm_swap_event_without_ordered_call` failures preceded a scoped full
obligation. No physical stream gap was recorded in smoke or hourly observation;
the natural run therefore does not establish performance during a reconnection.

All four lanes had **zero natural entries, zero settlements and zero realized P&L
in their native accounting units**. Pump's one qualified candidate reserved an
entry and then correctly cancelled it because the frozen fill-persistence signals
had decayed. Ramses funded one native quote sleeve from a late qualified screen,
but recorded no position or trade. No unlike quote units were summed. No
profitability or natural-lifecycle success is established by this run.

Operational assurance was valid, but the authoritative prospective record has
`block_admission_passed=false`. Pons' unchanged gate computes a censoring fraction
of **1.0**, above the frozen **0.1** maximum: six unique provider-failure candidates
against five admitted candidates, capped at one. This fraction is a frozen
admission statistic; it does not mean the five completed full vectors failed.
Assurance's narrower `economic_performance.eligible=true` validity flag does not
override prospective block rejection. The full record is preserved in
[hourly-prospective-observation.json](hourly-prospective-observation.json).

## Additional defects found in the hourly evidence

1. **Pump cancellation classification.** The sole cancelled entry has complete
   decision evidence and an authenticated `entry_signal_decay` fill-persistence
   veto. The generic `_progress` cancellation path labels it
   `reconstruction_incomplete`. Its economic cancellation is correct; the extra
   reconstruction-failure label is wrong. The exact event, candidate and fill
   evidence are retained in the causal audit.
2. **Ramses callback propagation.** `ramses_extended_test.run` supplies
   `evidence_progress`, but the threaded measurement-window path in
   `certification/lifecycle_timing.py` calls `lifecycle.run` without forwarding it.
   Reconstruction-stage events can therefore be absent from the pipeline. Zero
   recorded requests cannot establish that no acquisition was attempted.
3. **Ramses pending-coverage label.** Assurance reports `coverage_healthy` while
   also recording one pending full obligation. The coverage label does not include
   pending required obligations. Treat this observation as incomplete.

Ramses' qualifying scan completed at 3,638.713731015 seconds, after the fixed
3,600-second observation boundary. Its saved pre-entry checkpoint has
`active=true`, no completed segment and zero native ledger positions. The initial
screen is preserved in the campaign archive. This checkpoint remains evidence of
unfinished work; it was not resumed or dispatched. The workflow controller is
`HALTED` and successor/continuation authority is false.

These findings, the smoke's Meteora deadline classification, and the continuing
capacity/replay limitations remain unresolved in the certified runtime. They were
diagnosed after launch. No post-launch runtime edit or replacement campaign was
made.

## Evidence preservation

The hourly native artifact is 747,077,698 bytes. Because that exceeds the download
limit, read-only workflow
[35971799680](https://github.com/levonmendall/The-Meme-Machine/actions/runs/35971799680)
verified the completed run and original artifact digest, then copied 34 selected
files byte-for-byte. It made **zero market/provider requests and zero workflow
dispatches** and had only `contents: read` and `actions: read` permissions. It did
not execute the market runtime. Its separate review SHA is
`f808c0027a5a29b2f2ac23ffee836ecca8f857ca`.

| Artifact | ID | SHA-256 |
| --- | --- | --- |
| Exact non-market certificate | 10792722573 | `d895c680e0eb6159e5088f53102ebe63e2296e93eafe9e7fedd8e91338e2b106` |
| Smoke native archive | 10793373825 | `dba44ddd09371377a77bddac4d95d89fa464c86e477322026edf2c9e9b63b337` |
| Smoke artifact review | 10794080248 | `4e9d2c18135b17da00a1eedcc22921ce93867540936303186a38c8e68b282459` |
| Hourly native archive | 10795922766 | `cd48383d331ded838128469f4a17138cc217fa7697b424e0e99b958b266400c2` |
| Hourly artifact review | 10796283282 | `eaea303e0a995f0113a6386f29b0e22b530cccc69d6d723047f9687f35bfec98` |
| Selected hourly native evidence | 10796830265 | `c7096583d7a4bb490560ffcbab4098c634df5c9f3110e7aa151b307b87cae285` |
| Single-campaign terminal handoff | 10796536595 | `6dcb48c5f263553027bcd078dd1f43d0a18e34e0638b53a2bbb82ca79839a8da` |

The complete receipt list is [artifact-receipts.json](artifact-receipts.json).
[hourly-projection-receipt.json](hourly-projection-receipt.json) binds each copied
file to its original digest. [single-run-receipt.json](single-run-receipt.json)
records the workflow, jobs, skipped continuation and durable control history.

## Terminal outcome and stop

The market workflow is terminal `success`, attempt 1. Smoke, hourly, both artifact
reviews and the terminal control job succeeded. Automatic durable continuation and
prospective program advancement were skipped. The durable state is `HALTED`, with
`retry_allowed=false`, `successor_allowed=false` and `continuation_allowed=false`.
The history contains one consumed authorization, one claimed workflow and one
entry into each permitted phase.

The final inventory in [final-run-inventory.json](final-run-inventory.json) records
zero `in_progress`, `queued`, `waiting`, `pending` and `requested` runs. No successor
market work is active or queued. All campaign progression has stopped. A new
explicit owner authorization is required before any further market run.
