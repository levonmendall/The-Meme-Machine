# Evidence reconstruction repair and single-campaign boundary

Candidate branch: `repair/evidence-reconstruction-20260924`. This document describes
the candidate tree, not a passing exact-SHA certificate or a launched market run.
The final runtime identity is the commit that receives the full non-market
certificate. Do not execute market work from an intermediate candidate.

The owner instruction received during this repair authorizes **exactly one** new
prospective market workflow, only after the repairs and required verification pass.
Smoke and hourly observation may occur inside that same workflow. Successors,
replacement runs, reruns, retry campaigns, and separate position-continuation
workflows are prohibited. A failed/censored/incomplete single run consumes the
authorization. Preserve unresolved paper positions as unresolved; never force a
settlement or change a holding period to reach a clean stop.

## Immutable primary evidence

- Accepted run: `35949285193`, runtime
  `1c6da29d08bfbe42e39ea1c8068933aae6b15cdb`.
- Original hourly artifact: `10790448432`, SHA-256
  `698dcc65131bdc972f0be3176f8b29d276f8f054c77c86aa780a2bcd237dda6a`.
- Existing complete review: `10790443455`, SHA-256
  `7f0a625a4ee2148ac8e97e93ec68cb5f609d4d81e4dca2429db656b41aeef141`.
- Additional immutable projection: workflow `35959153525`, artifact `10791522985`,
  SHA-256 `916ec872959f58dcbfe650305a0aafd93f46bb4d7e28e619dbe2093286238a71`.
  It verified the original artifact digest, copied 75 files byte-for-byte and
  projected selected read-only SQLite tables. It made no provider requests.

The prior successor `35956802640` was observed cancelled when the owner supplied
the single-run restriction. Its previous durable program was already `HALTED`.
This repair did not cancel that run. Historical admissions and evidence remain
unchanged. No incompatible runtime revisions may be combined in the new cohort.

## Causal findings

| Lane | Required evidence and outcome | Demonstrated repair |
| --- | --- | --- |
| Pons | All 86 nominal full attempts were valid age rejections: 8 completed trajectories, 78 cached age vetoes, zero required receipt-window reconstructions. Of 693 screened observations, 691 have authoritative early rejection and two retain unknown full-evidence necessity after provider/deadline failure. | Separate current-state/trajectory/full-evidence stages; authenticate and classify 193 non-native and 46 nonzero-snipe boundaries; stop redundant cold history after the existing age veto. |
| Ramses | All 17 observations across seven pools reproduced a valid negative bounded cost-route check; all 81 captured route quotes had zero executable output. Full canonical reconstruction required/requested/completed: 0/0/0. | Preserve structural cost rejection; report genuine reconstruction request/completion only at authenticated canonicalization; retain incomplete/provider negative controls. |
| Pump | 25 mints required decision histories; 500 window requests produced 239 supported window decisions. One full concentration vector completed. There were 342 genuine incomplete window/second-leg episodes across 25 mints. | Remove false reconstruction labels for pre-admission uncertainty, normal expiry and absent shapes in complete history. Preserve every genuine missing-history failure and the existing lifecycle. |
| Meteora | Of 56 legacy attempts, 23 reached the pre-entry reserve cutoff and 14 had no authenticated trigger observed. The 19 authenticated-trigger obligations partition into 5 complete economic vectors, 9 verified zero-swap early rejections, and 5 genuine failures (including the lost authenticated trigger). | Retain authenticated triggers during finalized-state catch-up, retain recovery until reconnect/hydration succeeds, and correct trigger completion/supersession bookkeeping. |

The small full-vector denominator is not evidence of complete coverage. Early
history requirements and failed candidate states remain separately reported;
an earlier rejection of a token does not excuse missing evidence for a later state.
New assurance summarizes explicit required observations, requests, completions,
failures, authoritative early rejections, superseded states and pending work.
Legacy artifacts without requirement markers remain unmeasured by that new summary.
Cumulative stream interruptions do not prove a current outage or complete recovery
of events missing during the historical gap.

## Frozen admission audit

Finding **A**: the existing admission implementation matches the pre-existing
specification. Commit `f24811098a39745ccc8734203bef46992949a704` explicitly keeps
numerical infrastructure censoring separate from coverage diagnostics. No admission
threshold or historical classification is changed. Any additional numerical
required-evidence/stream-loss gate needs a separately frozen future owner policy.
See [the authority audit](block-admission-audit.md).

## Unchanged boundaries and remaining limitations

Strategy economics, target scopes, provider throughput/capacity, evidence freshness
and requirements, portfolio/accounting semantics, and paper-only authority remain
unchanged. No live-money path exists in these repairs.

Pump's genuine body-acquisition demand remains above available timely capacity for
many observations. No safe cache defect was demonstrated in the preserved missing
body samples, and provider rates are unchanged. Meteora retains its frozen transaction
capacity and fails closed on mutations without validated replay support. These limits
must remain visible after the repairs; green tests cannot establish complete market
coverage or profitability.

## Verification and execution handoff

Lane-focused tests and affected lane suites are recorded in the individual reports.
Final integrated tests, exact source-diff identities, full hosted certificate, and
single authorized workflow ID must be recorded before a completion claim. The
one-shot controller must consume dispatch intent durably before the only dispatch,
verify no competing market run in any nonterminal status, reject reruns, and prevent
every successor path. At terminal, report evidence/economics and confirm zero
successor market runs active or queued, then stop.
