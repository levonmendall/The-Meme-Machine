# Pump/Pons efficiency review candidate

The integrated code/test candidate is **d7cae26fce377db209daadbc478822382d003d9f**
on `integration/pump-pons-efficiency-rc-20261009`. Subsequent handoff commits
contain reports only. This candidate is for review; it is **not merged, deployed,
provider-certified or authorized for autonomous startup**. Full suite outcomes
and their exact tested identity are recorded in `TEST_RESULTS.json`.

## Actual source and existing engineering

| Source | Exact identity and disposition |
|---|---|
| Deployed checkout | `b577cc1c67f4d64f887b430f5e933f376b607dc2`; `/opt/meme-machine`, detached and unchanged. PAPER inactive, disabled, PID 0. |
| Repository operational ref | `operational/paper-v1`, `9f08f0db68fd3161c84bb955800db9a200a70f77`; newer repository lineage, not the deployed checkout. |
| Pro's published integration source | `2c826ddd0977871cfe66e3bd6d4c4d8eb7437629`, PR #128 head. |
| Preserved local successor / implementation parent | `cbfcb4137f10474ffc7fe0e19f0b8772f25c1563`; includes later isolation of Pons shadow work from protection. Original October 8 worktree remains clean at this identity. |
| Latest system-wide mandate arrival | `cd1c16c4e867b8121e6ff8a8b02b6759ca46bef2`; earlier efficiency/admission work already existed and was extended. |
| Final runtime implementation | `f8744148d30cc28d9e1e049eabe3e1d34f9cbb4b`; canonical-fixture commit `bb343fb5120bca0e486e8ea2b5a030114685854f`; final offline-fixture commit `d7cae26fce377db209daadbc478822382d003d9f`. Subsequent reports do not change runtime/test code. |
| Isolated Survivor count removal | `engineering/pons-survivor-count-removal-20261009`, `aa9fdcee23604ddacb740b454ca18c4909ca61d2`; included in this candidate. |

`BASELINE.json`, `PRIORITY_UPDATE_BASELINE.json`, `FINAL_ADDENDUM_BASELINE.json`
retain the pre-change observations. `SYSTEM_WIDE_SOURCE_RECONCILIATION.json`
classifies all 22 findings, distinguishes pre-existing work from new changes,
and lists every implementation commit and changed source path. No older remote
branch overwrote local work. Unrelated private checkpoints remain preserved and
are not integration inputs.

Pro's `Meme_Machine_Pro_Handoff.zip` and latest audit artifacts were **not supplied
to this workspace**. The reported `/mnt/data/` location belongs to its research
environment. The report, 27-category ledger, 104-row comparisons, workbooks and
30 reference tests were not inspected or reproduced. Owner-supplied findings
were reconciled against actual source and native offline fixtures.

| PR | Verified state | Candidate treatment |
|---|---|---|
| #120 | Open | Relevant later qualification/retention behavior preserved; head is not an ancestor. No claim of a complete merge. |
| #121 | Open, draft | Head is an ancestor; later compatible corrections retained. |
| #122 | Merged | Pump/Pons-only operation and paused-family accounting preserved. |
| #123 | Open, draft | Engineering storage admission and failure retention preserved; head is not an ancestor. Existing winner/continuation work comes from its separate engineering lineage. |
| #124 | Open, draft | Existing Pons held identity/reuse and acquisition foundations retained. |
| #125 | Closed, unmerged | Superseded; not revived or activated. |
| #126 | Open, draft | Pump held-position optimizations preserved. |
| #127 | Open, draft | Pons shadow preserved with the newer local protection-loop isolation. |
| #128 | Open | Integration head is an ancestor; this candidate continues its local successor. |

`PR_INTEGRATION.json` supplies exact PR head/base identities, current file hashes,
ancestry, differences and dependency dispositions. A changed file is not proof
that a PR's behavior was removed; native regression results accompany the matrix.

## Implemented changes

| Review commits | Changed implementation boundaries | Result |
|---|---|---|
| `4cfe8f5e` | `pons_quotes.py`, `pons_selective_paper.py`, `pons_survivor_runtime.py` | Numeric canonical membership is a genuine ordered post-acquisition read. It is never inferred from JSON-RPC batch ordering. Extra necessary transports are counted. |
| `22974c04`, `46c433be`, `c59313bb` | `pons_current_history.py`, `pons_selective_paper.py` | Existing durable Current history prepares the 900-second prefix before fresh execution evidence; subsequent requalification acquires only missing blocks. Source/canonical invalidation, restart and concurrent protection tested. |
| `31ce65b4`, `f8744148` | `pons_current_workers.py`, Current cohort/recovery/paper paths | Eight protected owner workers multiplex native owners at the original five-second idle wait. Eight separate entry workers transfer fills through existing durable handoff/recovery, retaining the authenticated RPC session and first monitor deadline. Worker pressure is retryable in durable candidate state. |
| `2b68ddba`, `c4be0417` | `pons_quotes.py`, `pons_survivor_runtime.py` | Conditional native Survivor sharing combines compatible heads, identity/gas and unioned history, with exact per-position simulations and independent native accounting. Actual endpoint resource proof is absent, so sharing is inactive there. Isolated fallback remains complete. |
| `49e61a76`, `41e4cb8d`, `22974c04` | `scaling_necessary_conditions.py`, `survivor_commit.py`, Current scaling | Original definitive necessities precede deep research. Uncertain observations take the original path. Failed prechecks are not cached as permanent eligibility decisions. |
| `07c4a911`, `41e4cb8d`, `dafd4c1f` | `source_artifacts.py`, Pons ABI/identity/event readers | Bounded immutable parsed artifacts and strict topic dispatch; explicit generation/content invalidation. Never substitutes for current chain state. |
| `cc76c9c6` | `survivor_commit.py` | Reuses verified risk folds under journal/owner/archive/source/mutation/recovery dependencies. Full native monetary replay remains on every read. |
| `377c7c16`, `c59313bb` | `pons_selective_v4.py`, `pons_selective_acquisition.py` | Adapts the existing dense receipt selector, validates complete transaction census/canonical membership/sender/status/logs, and returns existing receipt hits once. Capability, latency, payload and throughput proof required; otherwise original acquisition. |
| `25e17fa3`, `24996458`, `2ae04302` | Existing Robinhood Plane/cache and native consumer histories | Durable immutable receipt retention with separate obligations/acknowledgements, fork invalidation and busy-writer fallback. No second accounting authority. |
| `6132b17c`, `2ae04302` | `solana_candidate_join.py`, existing transaction repair | Conditional known-slot block repair with authenticated complete census, payload/deadline/economic bounds and original individual fallback. A known slot never proves an unknown interval. |
| `6463838a`, `e9e32f22`, `42e4a9d8`, `eea9e8cf`, `375d7496`, `f8744148` | Existing HTTP boundaries, `provider_purchases.py`, `provider_usage.py`, `provider_cost_attribution.py`, offline report | Bounded physical-purchase attribution distinguishes consumers, retries, failures, bytes and billed/throughput estimates; offline authenticated evidence/deadline/native-decision join. Old records' absent fields remain unknown. |
| `aa9fdcee`, `1c1cc59c`, `e2149bbb` | Survivor selection and Current broker/cohort | Removes the operative two-position veto and preserves retryable Current worker deferral. No replacement numerical Survivor cap. |
| `50732ef1`, `50f87cf9` | Existing native parity boundaries and diagnostic provider abstraction | Pump account-union parity and disabled RPC equivalence preparation. No provider substitution or competing acquisition engine activated. |

Full commit identities and per-commit files are in the source reconciliation.
`67705365` corrects stale offline fixture identity/source/schedule expectations
and checks the required separate canonical transport. The original monetary,
eligibility, completeness and risk assertions remain. `bb343fb5` updates the remaining Current entry fixtures to require the same
ordered canonical read. `d7cae26f` completes the Pump passive-diagnostic interfaces in offline fakes, isolates reservation context, strengthens priced-failure tariff assertions, and gives the unchanged kernel-write proof a fresh worker rather than the entire suite's lifetime writes. Twenty-five affected tests and the isolated write-budget proof pass. No risk, monetary or resource-budget assertion was relaxed. A baseline archive-decoder
fixture also hung after interval subtraction split its request: the corrected
fixture uses one missing interval and a timeout while retaining refusal/gap and
position-interest assertions. Storage tests isolate storage verification from
the separately tested NORMAL provider-capacity admission prerequisite.

Inherited acquisition savings are a separate baseline. PR #124's quoted-head reuse
avoids at most one redundant `eth_getBlockByNumber` per compatible held turn;
stale/missing heads still use the original call. PR #126's warm Pump method model
is 100 CU versus 20–40 CU, retained as the earlier sensitivity rather than a new
bill reduction. PR #127's held-event shadow omits zero mandatory executable
quotes; its projected suppression percentages are not savings. PR #128 integrates
these paths, so their hypothetical savings are not added to this branch's bundle
comparisons. The retained tapes do not attribute an actual count of billed
purchases eliminated by those PRs. The focused original held-reader tests remain
in both final suites; no old implementation was reintroduced.

## Current scaling history and freshness

Historical preparation uses the existing CurrentHistory and Plane tables, rolling
frontiers, range boundaries, receipts and recovery obligations. Complete retained
prefixes are reused; genuinely missing prefixes are prepared by one bounded,
lower-priority background worker. It cannot commit native capital. A blocked
preparation future does not block a real native mark and durable exit intent.
Pending exits/owner changes cancel preparation; races compare the existing
checkpoint before publication. No incomplete interval is certified.

Once preparation is complete, a fresh canonical target starts the execution
phase. Any small missing tail is acquired and authenticated, then the current
exact-quantity executable quote is obtained. A later sizing pass reads only the
new tail and fresh executable facts. Original acquisition timestamps are retained;
an old head cannot be relabeled to restart its five-second clock. Source generation
changes, missing legacy generation, conflicts and reorganizations refuse retained
authority. Missing history blocks an add, not a protective exit or future retry.

The native first realization, 2x qualification, 900-second persistence, one-add,
gross-high distance, capital/exposure, liquidity and execution safeguards remain.
Current/Survivor qualification and ownership remain independent.

The frozen before/after specimen has 25 decoded economic events in one occupied
event block. Native qualification, basis, high-water, realized and remaining
accounting agree. These counts describe the **history acquisition boundary**;
quote/sizing work is identically mocked and is not included as an avoided purchase.

| History pass | Mock physical transports | Logical elements | Estimated billed / throughput CU | Delivered bytes |
|---|---:|---:|---:|---:|
| Original full-window pass | 43 | 135 | 6,340 / 6,340 | 67,737 |
| Original second sizing/requalification pass | 43 | 135 | 6,340 / 6,340 | 67,737 |
| One-off missing prefix preparation | 25 | 93 | 5,500 / 5,980 | 66,658 |
| Retained first fresh pass, unchanged head | 3 | 3 | 60 / 60 | 9,198 |
| Retained final pass, unchanged head | 3 | 3 | 60 / 60 | 9,198 |
| Each one-block advancement | 4 | 5 | 140 / 140 | 6,711 then 1,115 |

Each advancing pass queries exactly its new block, with zero old receipts bought.
Warm reuse avoids 40 mocked transports and 6,280 estimated CU per unchanged pass.
Cold preparation plus two warm passes totals 31 transports rather than 86; its
dense receipt benefit overlaps the receipt model and must not be counted again.
Actual scaling-expiration rates and real network latency were not measured.
`SYSTEM_WIDE_EFFICIENCY.json` includes methods, ranges, bytes and local CPU/wall
samples; `test_pons_current_scaling_history` and native ongoing-scale tests prove
restart, missing-prefix refusal, fresh final deltas and actual native add integrity.

## Sharing, owner capacity and protection

Sharing is scoped to already-due compatible consumers, exact endpoint/source and
canonical identity, actual quantities and the original observation clock. It does
not wait to enlarge a batch. Independent simulations, stop/trailing/high-water,
capital, native decisions and history acknowledgements remain. Changed quantities,
missing resource proof, conflicts, partial responses and a pending protective exit
retain the original private acquisition/refusal behavior.

| Actual native Survivor `step()` replay | Isolated transports | Shared transports | Native simulations | Status |
|---|---:|---:|---:|---|
| Two quiet positions | 10 | 5 | 2 | Identical native money/risk; sharing resource profile is a fixture. |
| Twenty quiet positions | — | 5 | 20 | Twenty independent held owners; no count veto. |
| Two active positions, one shared transaction | 13 | 7 | 2 | Identical native money/risk; 478 -> 298 estimated CU. |
| Twenty active positions, one shared transaction | 121 | 7 | 20 | Identical native money/risk; 4,186 -> 766 estimated CU. |

These isolated paths already include the corrected ordered canonical fence;
they are not Pro's earlier four-transport-per-position assumption. Active receipts
are acquired once, authenticated and committed to independent native histories.
`SYSTEM_WIDE_EFFICIENCY.json` retains the full transport traces. Active bytes were
not measured and remain null. Complete conditional sharing in the owned Current
runtime is not claimed; its quotation component has parity preparation only.

The one-through-twenty native quotation component matrix has 160 specimens:
three/five-second deadlines, coincident/staggered timing, original/shared paths,
actual software admission with a virtual clock and injected HTTP. Twenty coincident
quotes reduce 61 transports to 4, preserving twenty exact simulations. Twenty
adversarially staggered quotes stay at 61; eighteen Survivor and seventeen Current
component deadlines miss. `CAPACITY.json` records P95/P99 waits/latencies, bytes,
method/CU counts and misses for every specimen. This is synthetic component proof,
not a real RTT or whole-loop capacity certificate.

Source and saved local provider limits both establish the unchanged 0.5-second
physical-start interval. Five quiet shared transports span at least two seconds,
leaving under one second for dependent response/processing within the Survivor
deadline. **Seven active transports span at least three seconds before the last
response; the active specimen cannot fit the original three-second requirement.**
Concurrent qualification/recovery can only add pressure. No ceiling was raised,
deadline relaxed or wait inserted to enlarge a batch. Whole-loop protective
latency is not certified. Headline provider RPS cannot resolve this
without endpoint latency, throughput, payload, CPU and monetary capacity evidence.

Twenty synthetic native Current entries transfer to durable protection ownership, and
twenty recovered fixture owners share eight protected threads. These tests run the
actual native ledger/controller against isolated synthetic books; they do not claim
that the original $500 can fund twenty positions independently of capital controls. Entry probes have their
own eight-worker pool, for a maximum of sixteen local threads; no provider limit
or hardware changes. Existing native handoff closes SQLite on the entry thread,
then full native recovery opens it on the protected thread. The authenticated raw
RPC session moves once, without a second provider factory/chain check. The test
retains twenty initial authentications for twenty new entries; no reduction versus
the original entry baseline is claimed for handoff itself. Ordinary
startup/crash recovery retains full verification. Original full qualification
vectors, entry delay, first monitor due time, basis, remaining quantities, realized
PnL and high-water state survive. Tests verify a blocked entry cannot occupy a due
protection worker and shutdown cannot strand an in-flight filled owner. This
one-off durable restore adds local work; it is not a free handoff or evidence of
full-loop throughput. The eight entry tickets bound entry processing, not
long-lived ownership. Deferred candidates remain durable and require genuine fresh
requalification after a missed deadline. Twenty simultaneously active full-loop
Current decisions are not deadline-certified. Entry-thread isolation does not
reserve extra RPC starts: the existing lifecycle `position_work` also gives entry
and filled-owner work native priority zero. Shared governor contention with entry
remains a measured-capacity requirement; the CPU-worker test does not certify it.

Survivor `select_entries` no longer checks position count. Its legacy descriptor
`POLICY.execution.max_open_positions=2` remains only to preserve the original
durable policy receipt/hash; there is no operative count gate. Tests select all
twenty qualified rows at counts 0/1/2/8/20 and reconcile twenty native reservations
after restart while refusing capital overflow. Every other policy/exit AST is
unchanged.

A final one-position active native replay also uses seven physical mock
transports, eleven logical elements and 272 estimated billed/throughput CU
on both original fallback and conditional paths. Native monetary/risk state
is identical. The same lower bound applies: three seconds from first to last
start before the last response and processing. This establishes a single-owner
active capacity constraint, not merely a failure of multi-position sharing.
The sanitized trace is in `SYSTEM_WIDE_EFFICIENCY.json` and `CAPACITY.json`.

## Local computation, durable evidence and costs

The captured strict Pons decode benchmark repeats 33 eligible captured events
1,000 times: template parses fall from 1,000 to two including the compiler dependency,
with CPU 1.04799 -> 0.22828 seconds. Peak Python allocations in 25 repeated decodes
fall 330,654 -> 71,086 bytes; the retained registry adds 491,928 bytes. These are
Python allocation measurements, not RSS or a free memory claim.

One hundred reads of an unchanged 258-event journal reduce verified risk folds
100 -> 1 and CPU 2.59460 -> 2.14310 seconds. All 100 full monetary verifications
remain. Full portfolio/book replay caching is not activated because a sufficient
invalidation proof is absent. Attribution adds measured local overhead: about
17.6 microseconds per mocked attempt, and 57.0 microseconds per existing SQLite
transaction in a 500-transaction fixture. No extra durability transaction is added. The final-source samples ran on this
two-CPU host alongside the full offline replays; process CPU is separate from
contended wall time. This does not prove a cheaper-server operating envelope.

The existing Plane, not another database, retains shared immutable receipts until
all required native consumers acknowledge publication. Bounds include 8,192 memory
entries, 32,768 reference obligations and a 64-MiB shared-cache admission budget;
required obligations are not silently evicted. Source/fork invalidation and restart
tests preserve native histories. Cache-full/busy cases use the original complete
path. A forced LRU eviction/restart specimen avoids 100 receipt refetches, two
mocked batched transports and 2,000 estimated CU. This overlaps shared-retention
savings in the dense workload and is not an additional monthly saving.

`HIGH_VOLUME.json` reproduces 32 authenticated synthetic blocks with 100 required
receipts and two independent consumers per block. Its matched acquisition bundle
reduces mocked transports 256 -> 160, elements 6,528 -> 160, estimated billed CU
133,120 -> 5,760, throughput CU 133,120 -> 21,120, and delivered bytes
14,804,096 -> 10,532,896. All 6,400 native economic events agree. Dense selection
and second-consumer retention are counted together once. A failed block purchase
can add 20 CU before complete fallback; no blanket retry multiplier is used.
An eight-transaction known-slot Pump fixture reduces eight requests to one and
320 -> 40 estimated CU while decoding a 171,786-byte complete block. Unknown
history intervals remain incomplete; the alternate short-deadline path is inactive.

Observed historical records are separate from those modeled workloads:

* `LOCAL_PROVIDER_USAGE.json` reads a consistent read-only local DB copy (SHA-256
  `4720d6db9881dfc8f1e30ff7bc83aa7e1944b43ee6fbf5360e6547d93a35ae0e`).
  Pons: 3,010 starts, 3,009 completions, 11,828 logical elements, zero recorded
  retries, 270,932 estimated CU. Dominant methods: 7,252 `eth_call`, 3,632 code
  reads, 471 headers, 467 chain checks, five log reads and one receipt.
* Its 4,096-start ring records six historical preparation starts; 1,413 records
  remain unassigned by operation, including 443 Pons `position_monitor` scope
  starts also used by `usd_valuation.py` without held positions. Another 2,677
  records are historical inactive-family work. The ring overlaps lifetime counters
  and is never added to them. Historical Ramses totals are separately reported;
  they do not mean Ramses resumed operation.
* The previously captured Pump mixed HTTP tape covers approximately 408 seconds:
  3,631 completed HTTP requests, 95,059,577 delivered bytes and 85,230 estimated CU;
  1,748 requests remain unassigned. Twelve unique missing transactions among
  seventeen retrievals include five repetitions whose avoidability is unproved.
* Retained provider-reported month-to-date aggregate is 1,740,125.5362 CU / $0.91
  at its partial capture time. Selected windows and stream bytes are kept in their
  original units; they overlap and are not added to this aggregate or the DB totals.

The old DB lacks payload sizes, authenticated evidence IDs, consumer-specific
deadlines and native decision links. Its 44 overall start/completion counter
difference is unresolved, not proof of charged failures. Neither audit rings nor
monotonic clocks establish a full billing month. The new bounded attribution/join
can capture available fields at existing boundaries; it makes no extra requests.
Unassigned demand remains explicitly unassigned. No old busy/extreme forecast or
blanket multiplier is retained as a production cost forecast.

At the frozen repository sensitivity rate $0.525/million CU:

| Hypothetical frequency, explicitly not observed | Conditional avoided variable cost |
|---|---:|
| 1,000 denied add prechecks/month, 46 CU each | $0.02415/month |
| 1,000 dense+reuse receipt bundles/month, 3,980 CU each | $2.0895/month |
| 10,000 such bundles/month | $20.895/month |
| 100,000 such bundles/month | $208.95/month |

Frequencies, paid marginal rate/allowances, response capability, retries and
deadline feasibility must be supplied before any forecast. These rows are
sensitivities, not additive savings across overlapping models. Warm scaling
6,280-CU avoidance per retained pass requires complete retained history and cannot
be multiplied by an invented attempt rate. CPU gains are not provider dollars.
**Actual deployed provider and infrastructure savings from this branch are zero.**

## Provider preparation and genuine blockers

`PROVIDER_COMPATIBILITY.md`, `PROVIDER_PACKAGES.json` and
`PONS_RPC_COMPARISON_DISABLED.json` prepare the owner's preferred Pons standard
RPC-only hybrid. Alchemy Solana streaming/enhanced history remain. No Chainstack
credential, plan, subscription, stream or migration was added.

The existing diagnostic abstraction compares identical chain/header/hash-pinned
requests and native quote results, including gas, historical/archive evidence,
missing/stale/forked responses and endpoint failures. Different chain states never
prove quote equivalence. It publishes no decision authority. Complete block
receipt capability and payload/latency guarantees still require endpoint proof.

Current public Growth pricing is a purchasing hypothesis: $49/month, 20 million
RU, $15/additional million. Full/archive RU, per-batch member and charged-failure
treatment must match the actual contract. The full Alchemy/Solana/stream plan
charges remain in both alternatives. Archive, fallback, storage and operations
costs are explicit inputs; a cheaper host/perfect sharing is not assumed.
See the [official pricing](https://chainstack.com/pricing/) and
[request-unit rules](https://docs.chainstack.com/docs/request-units).

If included RU suffice and there is no fallback or added operating cost, the
$49 package needs more than 93,333,333 avoidable Alchemy CU/month at the frozen
rate. Five million hypothetical 20-CU requests yield only $3.50 net before extras.
Unused existing allowances can make avoided variable dollars zero. The smallest
potentially worthwhile move is Pons RPC only **after** equivalent endpoint/deadline
proof and authenticated net spending justify its entire extra package cost.
A separate Current-history sensitivity assumes exactly 1,000 warm eligible
requalification passes per month: 6,280 avoided estimated CU per pass would mean
6.28 million CU and $3.297 at the same frozen variable rate. This is an explicit
workload assumption, not an observed frequency. Cold preparation, native quotes,
package allowances and failures are excluded. It overlaps the dense/shared
receipt model and must not be added to it.

Expected net monthly savings remain unknown. Pro's supplied $562/$1,183 versus
$339–432/$440–516 values are unreproduced hypotheses, not measured bills.

Remaining blockers are bounded and specific:

1. The active seven-transport Survivor specimen (also verified with one native
   position on the original fallback) and adversarial staggering exceed
   the existing two-RPS envelope. Full mixed qualification/recovery/protection
   capacity is unproved. No automatic governor increase or risk slowdown is safe.
2. The actual endpoint lacks authenticated dense-receipt/shared-quotation/Pump
   block-repair resource profiles. Those replacements retain complete fallback.
3. Complete owned-Current cross-position acquisition is not integrated; moving
   independent controllers across threads into a batch cannot delay protection.
4. Required host cgroup delegation is unavailable. The legacy USD valuation
   whole-source pin also fails on the preserved `cbfcb413` parent at `pons/evidence.py`.
   Assertions remain intact; full suite acceptance is blocked until the host proof
   and historical-pin conflict are resolved through the existing review workflow.
   Exact final counts and failures are in `TEST_RESULTS.json`; no host changes here.
5. Full-month method/archive/failure/fallback/allowance distributions and old
   consumer/deadline/byte attribution are missing. Monthly net savings are unknown.
6. Full monetary replay reuse, event-only HOLD quotation suppression, speculative
   receipt/header dispatch and exceptional holding extensions lack sufficient
   correctness/economic proof and remain inactive. Existing native continuation,
   tail bridging and fresh executable protection remain.

## Validation, safety and next bounded step

Use CPython 3.12.14 and the pinned validation environment. The repository driver
installs network refusal and isolated Scratch; it never starts PAPER. Reproduction:

```sh
python -m operational.tests FAST --verbose
python -m operational.tests OPERATIONAL --verbose
python -m engineering.proven_efficiency.system_wide --output /tmp/system-wide.json
python -m engineering.proven_efficiency.provider_snapshot --snapshot /path/to/consistent-offline-copy.sqlite --output /tmp/provider-usage.json
python -m engineering.proven_efficiency.cross_positions --output /tmp/cross-positions.json
python -m engineering.proven_efficiency.provider_packages --output /tmp/packages.json
```

The other benchmark/high-volume CLI arguments and actual commands are recorded
in `TEST_RESULTS.json` and each generator's `--help`. Raw snapshots and full logs
remain in the private workspace validation directory; no secret/state archive
was committed. Failed/unknown evidence is preserved. Report-only final commits
do not change the tested runtime/test tree.

The exact final code/test candidate is `d7cae26fce377db209daadbc478822382d003d9f`; runtime implementation remains `f8744148d30cc28d9e1e049eabe3e1d34f9cbb4b`. Both suites completed with identical source/test/engineering fingerprints before and after. Final outcomes:

- **FAST**: 1,374 tests in 3,131.812 seconds; 1 failure, 3 error entries, 0 skipped.
- **OPERATIONAL**: 2,795 tests in 3,468.059 seconds; 1 failure, 3 error entries, 33 skipped.

Three error entries require delegated CPU/memory/I/O cgroups unavailable on this host. The remaining failure is the inherited `b1f215ed` whole-source pin at `pons/evidence.py`, reproduced with the identical assertion on the preserved `cbfcb413` parent. These assertions remain intact. They block blanket acceptance. The stale Pump diagnostic fakes, reservation context, priced-repair expectation and full-suite write-counter fixture are corrected; the original resource budget and all native monetary/risk assertions remain. No additional native runtime failures appear in the final runs. The prior full receipts and failed evidence are retained in `TEST_RESULTS.json`, including their actual tested identities.

Final source/test/engineering SHA256: `e3c7ebf92e9c0591a77686ca506ed70aa89831f4ffdd42af2a2b0d3105364e41`. The receipt supplies the exact fingerprint recipe. Benchmark and detailed native measurement generators retain their actual `bb343fb5` measured source; the runtime is byte unchanged through final test-only `d7cae26f`.

Safety is evidenced by `SAFETY.json`, exact policy/source pins and native tests:
original $500 inception, portfolio/native monetary files, deployed checkout and
operational configuration unchanged. Original directional 5% allocation,
realized-equity compounding, first profit, stops/trailing/right-tail, creator,
concentration/liquidity, canonical completeness, Current-to-Survivor independence,
tail bridging, winner scaling, atomic commits and recovery remain. Meteora/Ramses
remain paused. No new service/provider workload, signing/funding/trading activation,
merge/deployment, plan/credential/limit change or host upgrade occurred. Offline
parity does not certify currently unproved live deadlines.

The next step is **not a PAPER restart**. First resolve valid source failures, run
the exact candidate's full offline suites in an already-authorized environment
with required cgroup delegation, and supply endpoint resource/tariff evidence.
The separately authorizable diagnostic capability envelope is at most 60 seconds,
64 HTTP starts, 256 logical elements, 16 MiB delivered, 2,000,000 bytes per response
and in flight, zero retries and the unchanged two-RPS ceiling. An independently
verified maximum charge is mandatory and currently null. Endpoint and runner are
absent; this handoff grants no dispatch authorization.

After those proofs and separate authorization, a bounded PAPER capacity/recovery
validation must retain the existing epoch and cover one-through-twenty positions,
coincident/staggered schedules, active/quiet markets, concurrent Current/Survivor
qualification, pending exits, restart/forks/gaps and long-held winners. Join each
physical purchase to authenticated native evidence, consumer, original deadline
and native decision. Record actual RTT/queue P95/P99, throughput, bytes, CPU and
spending; stop new optional admission on budget exhaustion while preserving native
protection. Do not admit a workload whose protective demand exceeds the proved
envelope, invent a satisfied deadline, impose a permanent strategy count veto or
liquidate merely to reduce cost. Any increased capacity requires its own supported
evidence and authorization. No such validation was executed here.
