# Robinhood PAYG implementation and handoff

Outcome: **OPTIMIZED_OFFLINE_READY**, subject to the final validation record in
[validation.json](validation.json). Runtime status: **PROVIDER_VALIDATION_REQUIRED**.
The existing `combined_position_and_candidate_provider_latency_not_certified`
blocker remains. This work does not claim OPERATIONAL_PROVEN.

The dedicated branch is `engineering/robinhood-payg-optimization-20261008` in
`levonmendall/The-Meme-Machine`. Its starting commit is
`f8d4e9ec33ee557152fad9aca90fe1991919b45c`, containing the published scout
`842c99c462f42dda582d9211b16242ae12dff225` and forward Survivor improvements.
The original economic comparison reference remains
`b1f215edd3dc079b623401c7e09e9c91a380e6a0`. The final source and publication
identities are recorded in the Git commits and deployment handoff.

No provider workload, subscription, deployment, service restart, credential or
billing change was performed. The persistent volume, `$500` inception,
portfolio identity and epoch `paper-1791089005190643467` were not changed.
Pump production code and settings were not edited. Ramses and Meteora remain
paused; no paused-family provider work was dispatched.

## Account and capability reconciliation

The owner's latest connectivity update supersedes the earlier administrative
403 and app mismatch findings. The correct PAYG account exposes Pump app
`9bin99s96t7ga5e9` and Pons app `v5h0vqr0wpp9zscj`, with approximately
1.73M CU and $0.91 reported usage value. The owner can see app, network,
request-type and method breakdowns. The reported Solana drivers are address
history and WebSocket logs. These are account observations supplied by the
owner, not a measurement from this branch's offline replay.

Read-only reconciliation of `/etc/meme-machine/paper.env` validates both
configured hosts and records credential-domain fingerprints in
[credential-reconciliation.json](credential-reconciliation.json). It emits no
key or key suffix and changes nothing. The owner has confirmed the Droplet
credentials and app binding. An independent comparison with administrative
key metadata remains unmeasured in this agent session: its advertised Alchemy
tools return MCP `-32001 Unknown tool`, rather than the old paid-plan HTTP 403.
This is a session tool-binding failure, not evidence that PAYG entitlement or
owner administrative connectivity is unavailable. Do not rotate the keys or
repeat the upgrade on that basis.

The approximate effective value is $0.526 per million CU, consistent with the
current published flat $0.525 rate. The supplied rounded total lacks its
billing window, credit/tax details and numeric per-app series. It cannot
establish exact invoice tariff, Pons consumption per day, or savings caused by
this implementation. Older $0.45/$0.40 pricing assumptions and assertions
that billing breakdowns are unavailable must not drive the new forecast.
[Alchemy pricing](https://www.alchemy.com/pricing)

| Feature | Evidence now | Operational treatment |
| --- | --- | --- |
| Correct PAYG team and two apps | Owner verified; identifiers above | Use these IDs for subsequent administrative exports |
| Droplet hosts / authority domain | Independently inspected offline; exact app mapping owner confirmed | Protected read-only comparison utility; no credential change |
| Robinhood chain ID 4663 | Owner's successful direct RPC test | No additional chain test dispatched here |
| Ten-block filtered logs | Previous bounded provider work and existing implementation; new code tested offline | Remains safe default |
| Wider PAYG logs | Robinhood documentation says unlimited range, subject to 150MB response limit | Not tested on updated endpoint; explicit authorization required |
| Filtered `eth_subscribe` logs | Alchemy address/topic filtering documented; Robinhood Alchemy WSS endpoint documented | Account/network method support, completeness, rates and billed bytes untested |
| PAYG capacity | Published 300 RPS / 10,000 throughput CU/s; account-wide metering | Actual shared account ceiling unverified; governor remains two physical RPS |
| HTTP batches and topic combinations | Documented; existing bounded native batches and exact filters retained | Members are individually billed; batching reduces transport overhead |
| Stateful log filters | Robinhood API catalogue documents filter methods | Lifecycle/expiry/restart behavior untested; no deployment |
| Block receipts / call batching / debug or trace | Some enhanced methods documented; existing receipt chooser remains capability gated | No extra acquisition; no demonstrated benefit over selective receipts for this workload |
| Actual CU usage analytics | Available to owner in restored account | Independent numeric series not returned by this session; do not replace it with estimated CU |
| Alchemy enhanced mined/pending feeds | Listed supported networks exclude Robinhood in reviewed subscription documentation | No broad pending feed or enhanced-feed assumption |

The machine-readable [capability matrix](capability-matrix.json) separates
owner verification, documented support, previous provider evidence and work
requiring new authorization. Documentation is not an account capability test.
[Robinhood getLogs](https://www.alchemy.com/docs/chains/robinhood-chain/robinhood-chain-api-endpoints/eth-get-logs),
[subscription API](https://www.alchemy.com/docs/reference/subscription-api),
[logs filters](https://www.alchemy.com/docs/reference/logs),
[Robinhood connections](https://docs.robinhood.com/chain/connecting/),
[throughput](https://www.alchemy.com/docs/reference/throughput),
[batch requests](https://www.alchemy.com/docs/reference/batch-requests).

## Chosen architecture and exact scope

Choose **A: the existing shared public MarketScout, followed by selective
canonical Alchemy evidence**. Keep the existing Nitro sequencer observation
clock in production. Do not add a paid log stream, worker, candidate registry
or per-strategy observer. Public and canonical data keep their existing
different authorities: public activity retains and promotes opportunities;
canonical reconstruction alone supplies economic decision evidence.

The common discovery filter contains the authenticated factory's exact ABI
TokenLaunched and PoolGraduated topics plus
`CurveBuy(address,address,uint256,uint256,uint256,uint256)` and the matching
CurveSell signature. Pons factory identity is
`0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e`. Dynamic curve contracts require
topic filtering without a factory-only address restriction. Factory events
are accepted as nominations only from the authenticated factory. The shared
V4 observer uses the authenticated PoolManager, exact canonically identified
Pons pool IDs, and Swap, ModifyLiquidity, Donate and ProtocolFeeUpdated topics.
It never observes the entire shared V4 manager as though every pool were Pons.
Graduation authentication still reconstructs Initialize, token/curve/hook/pool
lineage and the original launch. Economic hydration uses the exact Swap topic
and the necessary canonical state/history paths, not an arbitrary event subset.
Exact checked-ABI signatures, topic hashes and filter relationships are retained
in [filters.json](filters.json).

The existing Candidate/Evidence Plane, durable nomination journals, Pons
History, immutable RPC cache and shared provider governor remain the owners
of their respective state. Current outcomes cannot delete Survivor enrollment.
Weak, improving and capital-denied opportunities remain independently
eligible. No top-N identity cap was introduced. Limits on 64-work cohorts,
four range elements, response acquisition and retries bound one turn, while
durable fair scheduling retains the population and original deadlines.

| Model | Assessment | Decision |
| --- | --- | --- |
| A: public scout + canonical hydration | Already integrated and validated offline; avoids paying for broad observation; public sustainability still requires runtime proof | Selected |
| B: all strategy-scoped paid HTTP discovery | Complete topic/pool filters possible; wider windows reduce empty reads, but continuous observation adds billed work already supplied by the scout | Retained as scoped canonical fallback, not duplicate market observation |
| C: filtered paid logs + fixed HTTP reconciliation | Sparse event delivery can beat paid continuous polling; introduces delivered-byte cost and unverified reconnect/filter lifecycle | Not enabled |
| D: filtered paid logs + adaptive HTTP reconciliation | Improves C recovery; cannot demonstrate superiority to an effective existing public source with current evidence | Not enabled |

Robinhood documents the Alchemy WSS hostname, but this does not prove
`eth_subscribe` behavior for the upgraded credential. If public reliability
fails the bounded comparison, reassess B first with measured demand. A paid
stream requires a separately reviewed complete filter and recovery lifecycle:
one shared bounded manager, durable identities/cursors, removed-log handling,
reorganizations, gap repair and byte metering. There is no new paid subscription
manager in this branch, so its account-specific stream/HTTP reconciliation is
explicitly untested. Existing Nitro feed failure/recovery tests are not a
substitute for a paid log-subscription integration test.

## Implemented changes

* [log_windows.py](../../meme_machine/lanes/pons/log_windows.py) implements
  credential- and filter-scoped capability admission, durable density hints,
  bounded batching, conservative window growth, exact ten-block fallback,
  deterministic range and topic-OR subdivision, response saturation detection,
  exact ordered deduplication and mixed-fork rejection. A single saturated
  pool/event that cannot be subdivided remains a visible gap. Attempt/event
  limits fail the turn; they never publish a shortened complete history.
* [pons_selective_v4.py](../../meme_machine/lanes/pons/pons_selective_v4.py),
  [pons_survivor_runtime.py](../../meme_machine/lanes/pons/pons_survivor_runtime.py)
  and [pons_natural_observation.py](../../meme_machine/lanes/pons/pons_natural_observation.py)
  integrate the planner into shared candidate economic acquisition and
  canonical scout fallback. Sparse proved ranges can increase history progress
  up to a bounded 160-block turn; discovery retains its existing forward turn
  timing. Public requests remain at ten blocks. No live capability file has
  been created or installed.
* Economic event headers are read by block number and matched to the event
  hash. An immutable cached hash body cannot certify that an orphaned block is
  currently canonical. The comparison probe applies the same membership check.
* [pons_historical.py](../../meme_machine/lanes/pons/pons_historical.py) now
  uses an identity-checked standard receipt's `from` for verified transaction
  sender. Missing `from` retains the transaction-body fallback; malformed
  sender evidence fails. This avoids a cold transaction-body read worth 20
  diagnostic CU per applicable transaction. Swap.sender remains insufficient
  for buyer independence. The earlier scout already made this optimization
  in the selective V4 collector; its savings are not claimed as new here.
* [provider.py](../../meme_machine/lanes/pons/provider.py) classifies range
  rejection without recording provider error text. Hard range/response/auth/
  rate/envelope/deadline failures do not produce unchanged automatic retries.
  Adaptive subdivision counts every attempt separately.
* [provider_usage.py](../../meme_machine/runtime/robinhood/provider_usage.py)
  and [provider_admission.py](../../meme_machine/lanes/pons/provider_admission.py)
  expose bounded rolling physical RPS, logical methods, diagnostic billing and
  throughput CU separately, arrival/service rates, oldest waits and original
  deadline remaining. Unpriced methods and missing older instrumentation are
  explicit unknowns. These metrics do not assert actual account capacity.
* [proof.py](proof.py), [capability.py](capability.py), [identity.py](identity.py),
  [replay.py](replay.py) and [cost_model.py](cost_model.py) provide the bounded
  executable handoff, protected reconciliation and reproducible offline data.

The original Current canonical-window implementation and all nine approved
strategy changes retain their source pins. Mutable state, quotes, freshness,
execution qualification, exits, stops, realizations, trailing behavior, right
tail and staged scaling rules were not loosened. Funded work keeps priority
zero; the 0.5-second provider admission interval and worker count are unchanged.
No mandatory seven-day startup scan was reintroduced. Explicit historical
research remains optional; prospective operation starts forward.

## Evidence and measured efficiency

[efficiency.json](efficiency.json) runs the original, published scout and final
collectors against identical synthetic ABI-shaped tapes through real native
RPC encoding and response accounting. It compares every normalized economic
output, including exact swaps, transaction senders, buyer groups, flows and
price indices. Recall and complete economic-tape equality are 1.0 in all three
cohorts. Fixture forty-block capability records prove no live account support.

| Cohort / blocks | Original HTTP / logical / diagnostic CU | Scout and final ten-block HTTP / logical / CU | Conditional forty-block HTTP / logical / CU |
| --- | --- | --- | --- |
| 8 / 20 | 12 / 290 / 5,800 | 6 / 155 / 3,160 | 6 / 154 / 3,100 |
| 32 / 40 | 48 / 1,626 / 32,400 | 24 / 834 / 16,720 | 24 / 831 / 16,540 |
| 64 / 40 | 50 / 1,698 / 33,840 | 25 / 870 / 17,440 | 25 / 867 / 17,260 |

The approximately halved transport/CU demand against the original is primarily
the already published scout work, preserved here. Against that scout, a
forty-block sparse query removes three log elements / 180 diagnostic CU from
the forty-block cohort; receipt hydration still dominates, and physical
transports stay unchanged. Final ten-block behavior adds stricter canonical
membership without inventing new CU savings.

For 32 candidates, original response payload is 2,027,045 bytes versus
1,781,835 at ten blocks and 1,781,712 with the fixture forty-block query.
CPU values are measured offline and retained per run in efficiency.json;
network latency and billed Pons CU remain unmeasured. A 160-block empty recovery
uses five physical attempts / seventeen logical elements / 960 diagnostic CU
at ten blocks, versus two / five / 240 at forty, including chain verification.
A dense 1,200-event forty-block interval instead receives 1,163,110 bytes with
the initial saturated wide request and subdivision, versus 581,681 bytes with
ten-block pages. The wide case uses 180 versus 240 diagnostic CU but more bytes
and one more transport. This is why density and saturation affect selection.

[decisions.json](decisions.json) exercises native chronological Survivor
history, qualification, real quote decoding, shared capital and PAPER book
paths against the frozen original. All nonexecution economic features match;
fully eligible decisions and position quotes match exactly. Quiet candidates
skip seven unnecessary quote sizes, remain retained and later qualify after
improvement. Concentrated-buyer rejection preserves exact buyer evidence.
Capital denial preserves qualification, and returned capital opens one native
position idempotently. The unchanged warm funded Survivor turn costs 152
diagnostic CU / three HTTP attempts in the synthetic unchanged-head case;
new swaps and conditional exits/scaling add work. This is not a genuine funded
runtime latency sample and does not clear the combined guard.

Authentic retained protocol/lineage fixtures and original accounting tests are
included in OPERATIONAL. Full chronological activity and resource-pressure
fixtures are synthetic and labeled as such. SQLite page stocks, WAL behavior,
test CPU/RSS, queue fairness and deadline regressions are offline evidence,
not thirty-day disk, billing or autonomy certification. Exact test results and
prior failures are retained in [validation.json](validation.json).

The full FAST suite passed **1,003 tests** (361.995 seconds; peak RSS 234,472
KiB). OPERATIONAL passed **2,424 tests** (860.486 seconds; peak RSS 239,036
KiB), with 33 existing archived MODEL A skips. The final focused suite passed
**61 tests**, including the engineering executor's final governor/scout/cache
measurements, WAL accounting and final-report size protection. The full suites
cover the final production code; those last executor-only additions were
validated by the focused run. No production code changed after the full suites
began. The original strategy source pins and maintenance assertions pass.

## Cost comparison

[cost-projections.json](cost-projections.json) and the executable model provide
24-hour and 30-day ranges for A/B/C/D at both the current ten-block fallback
and conditional forty-block support. These are comparable modeled subtotals
plus a clearly unmeasured Current allowance, not complete production invoices.
They include separate reconstruction, authenticated nomination, qualification,
warm funded maintenance, observation, subscription bytes and missing-interval
repair terms. Named unmeasured additions include Current position work,
conditional exits/scaling, extra mutable state and liquidity evidence,
throttling/retries, reorg churn and fallback duration.

The model uses the retained 9.897-block/second header pair, not a fresh network
measurement. Quiet/normal/high scenarios assume 4/48/480 discovered candidates
per day, 1/8/80 fully qualified candidates, differing active cohort durations,
event rates and funded occupancy. Recovery adds one hour of missing blocks.
Current's 4,000–12,000 CU per attempt allowance is a replaceable scenario
assumption, not a measured cost or safe upper bound. Full assumptions and
blended unit ratios are in the JSON; none is an acquisition cap.

Conditional forty-block modeled USD, before the named unmeasured additions:

| Scenario | A 24h / 30d | B 24h / 30d | C 24h / 30d | D 24h / 30d |
| --- | --- | --- | --- | --- |
| Quiet | 0.23–0.33 / 6.90–9.93 | 2.03–2.13 / 60.78–63.80 | 0.24–0.34 / 7.08–10.10 | 0.24–0.34 / 7.08–10.10 |
| Normal | 1.58–2.79 / 47.52–83.81 | 3.38–4.59 / 101.39–137.68 | 1.82–3.03 / 54.53–90.81 | 1.82–3.03 / 54.53–90.81 |
| High activity | 11.90–24.00 / 357.04–719.92 | 14.37–26.47 / 431.11–793.99 | 16.36–28.46 / 490.88–853.76 | 16.36–28.46 / 490.88–853.76 |
| Recovery | 1.61–2.82 / 48.36–84.65 | 3.41–4.62 / 102.24–138.52 | 1.93–3.14 / 57.89–94.18 | 1.85–3.06 / 55.37–91.66 |

Selected A at the **currently enabled ten-block fallback** projects
$0.31–0.41 / $9.17–12.19 quiet, $2.04–3.25 / $61.13–97.42 normal,
$15.53–27.63 / $465.90–828.78 high, and $2.15–3.36 / $64.50–100.78 recovery.
Actual billed consumption is the owner's account total only; these figures
are diagnostic projections. Per-hour coverage and blended candidate/qualified
opportunity ratios use assumed complete coverage and scenario denominators;
they are not measured marginal unit prices. The warm synthetic funded-position
coefficient is 182,400 CU per occupied position-hour, approximately $0.09576.
An hour of missing logs at the retained block rate costs 213,840 diagnostic CU
at ten blocks or 53,460 at forty, before canonical witness/hydration additions.

EVM log subscriptions are priced at **0.04 CU per delivered byte**. Solana
subscriptions are separately listed at **0.0002 CU per byte**. Applying the EVM
rate to Pump would overestimate that coefficient by 200 times. The model uses
87 authentic retained curve/factory log bodies with a synthetic subscription
envelope (mean approximately 941 bytes), and 141 explicitly synthetic V4 Swap
bodies (approximately 1,039 bytes). Delivered framing, duplicates and the
provider meter remain unmeasured. Subscription notifications never replace
canonical economic evidence. [CU schedule](https://www.alchemy.com/docs/reference/compute-unit-costs)

The modeled high-activity A demand exceeds two physical RPS **before Current
and retries**. A published PAYG ceiling cannot prove the smallest sustainable
capacity. Record real shared Pump/Pons demand, oldest wait, original deadlines,
method-weighted throughput, retries and position latency before proposing a
tested governor increase. Do not increase workers or relax completeness to fit
an aspirational 10M CU/month. [spending-alerts.example.json](spending-alerts.example.json)
prepares owner-selectable alert thresholds only; no alert is installed, no
hard production cutoff is introduced, and billing settings are unchanged.

## Maintenance repair and integration

The real maintenance timeout causes were fixture construction inside the
unchanged twelve-second service deadline and wall-clock idle cadence inside a
controlled-clock harness. The approved workload's SQLite seeding now happens
before that timer, followed by a genuine native service reopen. Only idle
turns with no unfinished worker advance the synthetic clock. Unfinished native
workers still await real completion. Held readers, archive/retirement work,
requested turns, table assertions and the original timeout are preserved.
No maintenance assertion was deleted or weakened. This repairs an offline
fixture, not production Pump acquisition or provider behavior.

The harness import is byte-identical to the independently repaired maintenance
worktree at the recorded SHA in [maintenance-import.json](maintenance-import.json).
That worktree's ongoing proof changes were not overwritten or merged.
The separately published Pump branch `engineering/pumpswap-provider-bandwidth-20261008`
at `874e94a9` is preserved. Final integration must reconcile its exact committed
scope with this Pons branch; do not merge its older Pons tree over the new
scout/Survivor implementation. See [HANDOFF.md](HANDOFF.md) for the remaining
bounded proof and safe path to autonomous PAPER operation.
