Read-only provider compatibility review, checked 2026-10-10. Candidate code:
`e17d91fb1d95194774e94ae444b04cfe127d42ab`; runtime snapshot is the same frozen
source. The successor preserves original exit thresholds and adds bounded native
protective-return reporting and strict research-only shadow comparisons. The last
economic/helper repair is `bdecfeb34ce2082e9ef8848739c71d8762a14755`; capital-risk
policy preparation is `2a9b6f1797a7a3bc3ee38972fc950e76c13bc3b3`.
Owner-approved age-only exits are removed and new-epoch sizing uses total realized
portfolio equity. Original executable quantity, canonical, freshness and monetary
checks remain. No market-data endpoint requests, account changes,
credentials, subscriptions or deployments were performed.

The inactive new-epoch policy recommendation separately caps invested asset basis
at 7.5% and marked new-risk asset concentration at 10%; it needs owner approval.
Existing aggregate limits, native integer sizing and USD half-original add limits
remain. No production risk policy or governor has changed.

Prior core controller traces omit the native USD financial boundary. Its actual
source shapes are 10 cold/6 warm/8 oracle-refresh transports, zero on a valid original
cache hit; shared callers reuse one immutable unit price with independent amounts.
The new standalone canonical fence checks target and retained oracle blocks after
state acquisition. Basic provider validation must include USDG proxy/aggregator,
authenticated ETH→USDG router/factory/pool, route completion and original validity,
in addition to token buy/sell/add, gas, logs and receipts. Those static helpers are
Pons valuation references, not an activated Ramses consumer. Component 3/4/9-RPS
profiles do not prove complete protection including finance, entry and recovery.

Read-only administrative inspection is complete for the exposed interfaces.
Alchemy app/usage tools authenticate 1,740,125.5362 core CU in the partial October
billing period and $0.91 displayed core cost; Solana contributes 1,737,251.5362,
Robinhood 2,874. Solana gRPC delivery is separately reported as 0.0063307322 TB.
Neither core cost nor public tariff arithmetic is a complete invoice. Configured
credential-to-app binding, actual plan/allowance/tariff, shared throughput, physical
starts, logical method/batch/payload/in-flight limits, archive/failure charging and
spending controls remain unknown. Exposed administrative tools cannot establish
those entitlements; no market requests were made to fill the gaps.

The next comparison should first test the **configured Alchemy Pons endpoint**.
Optional Chainstack comparison is not prerequisite to existing-provider capacity
validation. Native exact-state quotation acceptance must include the new $50
directional target and eligible $25 staged-add size, with real gas, fee, liquidity
and USD/native conversion evidence. Offline sizing tests do not prove authentic
liquidity or quotation equivalence at those amounts. No operating $1,000 epoch is
needed for this read-only capability comparison.

The smallest candidate move remains **Pons standard RPC only**. Keep Alchemy's
Solana streams and enhanced address history. Use the existing `PacedRpc` diagnostic
role for any authorized comparison; it publishes no evidence into native trading.
A dependent decision retains one canonical acquisition authority. Wider Pump RPC
and streaming migration remain deferred until independently worthwhile.

| Requirement | Existing native/offline boundary | External proof still required |
|---|---|---|
| Chain and canonical state | Chain 4663; authenticated complete headers; ordered membership after dependent acquisition. | Exact endpoint chain, historical headers, hash/numeric references and canonical behavior. |
| Native executable quotations | Original buy/sell simulation, exact quantity, source code/manager, gas and fee arithmetic; no event-only approximation. | Both endpoints must read the same exact canonical state and request. Matching outputs at different blocks are insufficient. |
| Filtered logs and receipts | Strict identity/status/log/block/sender validation; immutable facts and independent obligations retained. | Required log filters, receipt completeness, missing sender/body behavior, payload and errors. |
| Complete block receipts | Existing density/resource/deadline selector and complete individual fallback. | Method support, authenticated block census, completeness, throughput and payload. Never buy full blocks blindly. |
| Archive | Original historical ranges, 900-second scaling history and recovery frontiers. | Endpoint archive depth, exact method/age classification, batch-member and failure charging. |
| Freshness and fork refusal | Original quote timestamps, source/session/activity generation and ordered fences; stale/partial/forked evidence refuses. | Node lag, reorganizations, timeout/429/partial batch behavior and original deadline envelope. |
| Current/Survivor owners | Separate native journals, quantities, simulations, risks, history acknowledgements and decisions. | Endpoints confer no execution/qualification authority. Native protection remains independent. |
| Protective capacity | Real-clock sleeping-mock traces in `CAPACITY_REPAIR_NATIVE.json`; default two RPS still fails twenty partial exits. | Authentic RTT, queue/throughput/payload, dense/cold history, account-wide Pump competition and CPU envelope. |
| Solana | PR126 fresh held consolidation preserved; native stream/history/account context and concentration remain. | No substitution prepared for streams or enhanced history. Later standard-RPC union/repair needs complete context parity. |

[Robinhood availability](https://chainstack.com/migrate-robinhood-chain-rpc-to-chainstack/)
is a documented offering, not authenticated endpoint proof. Offline exact-state
comparisons and the disabled envelope are in `operational/pons_rpc_equivalence.py`;
its per-response and aggregate byte limits are independently tested. No live runner
or production comparison activation is supplied by that module.

Public pricing checked October 10: Alchemy PAYG lists $0.525/million CU and
10,000 throughput CU/s (300 RPS), measured over ten seconds; extra 5,000 CU/s
capacity blocks are $160/month. The actual account contract/headroom is unknown.
[Alchemy pricing](https://www.alchemy.com/pricing).
Headers, code, gas, bodies and individual receipts cost 20 billed CU; `eth_call`
26; logs 60. Block receipts cost 20 billed CU but 500 throughput CU. Batch members
remain logical purchases. [Method weights](https://www.alchemy.com/docs/reference/compute-unit-costs).

Chainstack lists Growth at $49/month, 20 million RU, 250 RPS and archive access;
Developer has three million RU and 25 RPS, with archive availability unproved for
this endpoint. Overage is $15/million RU on Growth, $20 on Developer. Whole plan
charges stay in comparisons. [Chainstack pricing](https://chainstack.com/pricing/).
Global full reads are one RU and archive reads two; documented Robinhood-sensitive
reads at least 127 blocks behind the tip are archive. Actual batch/failure and
endpoint treatment must be authenticated. [Request-unit rules](https://docs.chainstack.com/docs/request-units).

`PROVIDER_PACKAGES.json` retains formula-driven sensitivities rather than an
operating forecast. Include the full additional subscription, actual archive
mix, charged failures, fallback/recovery, storage and operations; retained Alchemy
Solana/fixed charges remain on both sides. With no extra costs and enough included
RU, Growth needs more than 93.33 million *marginal* avoided Alchemy CU/month to
cover $49 at the public tariff. Unused existing allowances change that threshold.
The observed monthly distribution is unavailable, so net expected savings remain
null. Pro's earlier busy/extreme package values are owner-supplied hypotheses;
the research archive was not supplied or inspected.

The disabled capability preparation remains 60 seconds, **64 aggregate physical
starts across both endpoints**, 256 logical elements, 16 MiB delivered, 2,000,000
bytes per response/in flight, zero retries and the current two-RPS ceiling.
`PONS_RPC_COMPARISON_DISABLED.json` has null tariff, endpoint and monetary ceiling.
No requests are authorized by this file. Use only native required standard methods
with documented maximum billed cost at most 60 CU/element for the following bound.
The public Alchemy arithmetic is 256 × 60 × $0.525/1,000,000 = **$0.008064**.
For Growth, a conservative 512 RU at published overage gives **$0.00768**, plus
any full subscription charge; Developer's corresponding bound is **$0.01024**
and cannot establish archive equivalence. These are planning arithmetic, not
independently authenticated ceilings or authorization to buy a plan.

Before requesting dispatch approval, establish the actual account contract,
remaining allowance, archive/batch/failure charges and method ceilings without
market calls. A proposed $0.01 cap is valid only after that proof; use the smaller
of the approved ceiling and verified reservation. Stop before a start that would
exceed time/start/element/throughput/spend limits; stop on oversize response,
inconsistency, failure or timeout. No retry, discovery expansion, signing, native
state mutation, subscription, service startup or authority fallback is included.

A **distinct** higher-rate capacity probe would require explicit authorization
and authenticated headroom. Retain 60 seconds/64 starts/256 elements/16 MiB/zero
retries; require per-response 2 MB, at most two in-flight responses/4 MB total,
256 logical elements/s, 2,000 throughput CU/s, 50 elements/method/s, protected
reserves, and an independently verified monetary cap. Select three RPS for the
single-family warm partial-exit specimen first. Coincident mixed probes use four/eight;
bounded-phase staggered probes use three/twelve. Lower intermediate rates are
tested separately and do not establish general production settings. These remain offline
constructor profiles without a production enable path. A 64-start probe can
establish method behavior and sampled latency, not dependable P95/P99 tails or
full-market protective capacity. Bounded PAPER acceptance remains separately gated.

The 64-start comparison is a method/canonical/quote compatibility probe, not a
whole twenty-owner mixed-loop capacity test: a prior staggered 10+10 native
fixture used 69 physical starts, and the retained lowest passing specimen uses
66. Both exceed 64. A full-loop endpoint test needs its own
trace-sized element/payload/spend envelope and separate authorization. It cannot
silently exceed the retained comparison limits.

The completed native followups make separate envelopes necessary. One pending
partial plus nineteen ordinary owners needs four RPS in its 100-ms fixture;
ten independently staggered Current plus ten Survivor owners has a single
passing nine-RPS bounded-phase specimen, 66 starts/151 logical elements/3,732
modeled CU and 128,842 fixture response bytes. Eight has known misses. None is
authenticated capacity or sufficient P95/P99 evidence, and six dependent 600-ms
responses miss three seconds at any tested rate.

Prepared future envelopes, all **inactive and unauthorized**:

| Purpose | Proposed maximums | Monetary authority |
|---|---|---|
| Basic existing-Alchemy method/exact-state capability | 60 s; 64 aggregate HTTP starts; 256 logical elements; 16 MiB; 2 MB per response/in flight; 2 RPS; zero retries | Unknown actual tariff, no verified ceiling. Public $0.008064 is sensitivity only. |
| Four-owner warm protection capacity specimen | 60 s; 32 starts; 128 elements; 16 MiB; 2 MB response; two in flight/4 MB; 3 RPS; zero retries | Must be independently priced before authorization. |
| Core staggered 10-Current/10-Survivor specimen, excluding USD finance | 60 s; 80 starts; 256 elements; 16 MiB; 2 MB response; two in flight/4 MB; bounded phase at 9 RPS; zero retries | Must authenticate account-wide headroom and actual tariff before authorization. Its allowance does not yet bound the whole financial/protection loop. One loop cannot establish tail reliability. |

Higher-rate profiles additionally bound logical elements at 256/s, throughput at
2,000 modeled CU/s, methods at 50 elements/s and batches at 50 elements. They
reserve held/pending protection while retaining native decisions and provider
authority. Exact targets must be one authenticated canonical state with ordered
post-acquisition verification; archive/body/receipt fallbacks consume the same
finite envelope. Any size, time, throughput, spend, inconsistency, timeout or
failure stops the test; zero retry means no replacement starts. No comparison may
fund positions, submit transactions, alter active rate limits or change plans.

Sustained long-hold projections in `LONG_HOLD_RESOURCE_MODEL.json` demonstrate
that the existing finite allowance cannot support indefinite monitoring. They
contain no new provider authorization or restart grant. Required recurring
budget, actual market frequency, stream/redelivery and recovery demand remain
external readiness blockers. Removing a holding timer does not make protection
free; resource failure remains an operational condition, not a sell signal.
