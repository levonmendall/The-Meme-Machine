Read-only provider compatibility review, verified 2026-10-09. No subscription,
provider endpoint test, paid request, credential insertion or deployed configuration
change was performed. This document supersedes the earlier streaming-package
hypothesis with the owner's preferred **Pons standard RPC-only hybrid**.

Alchemy remains the sole existing canonical Pons acquisition authority. The
optional comparison uses the existing `PacedRpc` diagnostic role and publishes
no evidence into a trading decision. No production acquisition method is replaced
by this preparation. Solana streams and enhanced address-history acquisition
remain with Alchemy; neither a Chainstack streaming subscription nor a stream
migration is part of the next recommended move.

| Requirement | Native source boundary and offline proof | Chainstack evidence / remaining blocker |
|---|---|---|
| Chain identity and headers | `CHAIN_ID=4663`; complete numeric/hash/parent/timestamp header; fresh numeric membership fence. Wrong chain, fork and incomplete observations refuse. | Robinhood RPC availability is publicly documented; the exact candidate endpoint is untested. |
| Exact-state calls | Original `eth_call` and `eth_getCode` block parameters retained. Same-looking results at different canonical headers or different block references refuse comparison. | Exact EIP-1898 support, required numeric historical references and canonical fencing are unverified. |
| Native executable buy/sell quotes | Actual native V4 quote constructors, quantities, gas and exit decisions compared against identical frozen responses. Current CurveState execution-capacity comparisons included. | Quoter code/manager/source identity, archive availability and both buy/sell outputs must be authenticated on the candidate endpoint. No event-only substitute. |
| Gas and transaction costs | Original `eth_gasPrice`, gas-quote arithmetic and quantity validation preserved. | Gas state must be contemporaneous with the same canonical comparison; endpoint latency and response semantics unproved. |
| Filtered logs and individual receipts | Native strict ABI, transaction identity, sender, status, block/order/log membership; original missing-evidence refusal and transaction-body fallback retained. | Exact filtered `eth_getLogs`, `eth_getTransactionReceipt` and `eth_getTransactionByHash` behavior, byte limits and charged failures require endpoint proof. |
| Complete block receipts | Existing density selector integrated into V4, default original path without authenticated capability/resources. Sparse, partial, malformed, reorganized and failed fixtures retain refusal/fallback. | Generic RU method listings do not prove `eth_getBlockReceipts` support, census completeness or economical payloads on Robinhood. |
| Historical/archive reads | Original history intervals, canonical source identities and independent consumer cursors/acknowledgements retained. Exact old block reference included in offline comparisons. | Archive access, retention/depth, batch-member RU treatment and missing-state failure classification are not endpoint-verified. |
| Missing/stale/forked evidence | Offline comparisons refuse stale or reorganized observations and preserve distinct unavailable/failure outcomes. | 429, timeout, partial-batch, node lag and reorganization behavior must be measured within original deadlines. |
| Current/Survivor independence | Separate native qualification and position histories; shared acquisitions charge once; each consumer validates economics and retains its own obligation. | Provider transport confers no qualification or execution authority. A dependent decision must use one consistent canonical authority. |
| Protection deadlines | Three-second Survivor and five-second Current requirements unchanged. Native component matrix uses actual governor/admission with a virtual clock and injected HTTP. Twenty new entries and twenty recovered Current owners are tested with eight protected workers and eight separately bounded entry workers, maximum sixteen local threads, using native durable handoff. | No real RTT or whole-loop concurrent capacity certificate. Ownership multiplexing does not prove that twenty active protective decisions meet their deadlines. Public plan RPS is not a latency guarantee. |
| Later Pump standard RPC | Existing finalized account context, complete concentration, transaction repair and native quotations remain unchanged. `getBlock` is publicly documented. | Owner/variant/context parity, complete payloads and incremental net savings must justify this later move. |
| Solana discovery/history | Alchemy native filters, replay, gap repair and enhanced `getTransactionsForAddress` remain authoritative. | No Chainstack substitution is prepared or activated for these required functions. |

Robinhood availability: [official migration guide](https://chainstack.com/migrate-robinhood-chain-rpc-to-chainstack/).
Solana block method: [official getBlock reference](https://docs.chainstack.com/reference/solana-getblock).
These public pages establish documented offerings, not authenticated runtime capabilities.

| RPC package | Monthly base | Included RU | Extra million RU | Public RPS |
|---|---:|---:|---:|---:|
| Developer | $0 | 3 million | $20 | 25 |
| Growth | $49 | 20 million | $15 | 250 |
| Pro | $199 | 80 million | $12.50 | 400 |
| Business | $499 | 200 million | $10 | 600 |

Growth includes archive access in the published features; a free Developer test
cannot be assumed to establish archive equivalence. All figures are current list
prices, not an operating approval or invoice. See [official pricing](https://chainstack.com/pricing/).

Global Node full requests are modeled as one RU and archive requests as two.
For documented Robinhood archive-sensitive methods, reads at least 127 blocks
behind the head are archive reads. Exact batch-member and charged-failure treatment
must be verified for the chosen endpoint and contract. Do not convert Alchemy CU
into RU one for one. See [official request-unit rules](https://docs.chainstack.com/docs/request-units).

Streaming alternatives are deferred. The official Yellowstone guide documents
bounded filters/streams and approximately 100-slot replay; these do not establish
equivalence to the repository's 6,000-slot replay and separate candidate feeds.
Any later stream change would require its separate tier charge, full filter
coverage, RPC gap-repair costs, delivery/redelivery and protection proof. See
[official Geyser guide](https://docs.chainstack.com/docs/yellowstone-grpc-geyser-plugin).

`PROVIDER_PACKAGES.json` and `engineering.proven_efficiency.provider_packages`
contain Decimal sensitivities for the current optimized Alchemy architecture,
Pons RPC-only hybrid, a later standard-RPC hybrid and optional streaming alternatives.
They retain Alchemy's fixed plan, Solana and stream costs on both sides; add Growth's
full $49, RU overages, actual fallback, storage and operations. Actual unchanged
charges and full-month Pons method/archive distributions are unknown. Zero defaults
in illustrative sensitivities are explicitly supplied placeholders, not $0 bills.
No perfect-sharing multiplier, cheaper host, promotional discount or stream fee
removal is assumed.

If included Growth RU suffice and there is no fallback or added cost, replacing
Alchemy marginal CU at the frozen $0.525/million rate breaks even above
93,333,333.333... avoidable CU/month. At 5 million hypothetical 20-CU standard
requests this is only $3.50 net before fallback/storage/operations. Unused Alchemy
allowances can reduce the avoidable charge to zero. There is no supported expected
monthly net saving in retained evidence. The smallest independently worthwhile
candidate is Pons RPC-only **if** authenticated replacement spending exceeds its
full package and operating costs and all source/deadline proofs pass.

Pro's earlier matched busy/extreme values ($562/$1,183 for optimized Alchemy and
$339–432/$440–516 for alternative packages) remain unreproduced hypotheses. The
archive is unavailable here, and those streaming-era package assumptions are not
substituted for the owner's newer RPC-only preference.

The prepared capability-test configuration is `PONS_RPC_COMPARISON_DISABLED.json`.
It is disabled, contains no endpoint or credentials, and has no network runner.
The inactive configuration specifies at most 60 seconds, 64 HTTP starts, 256 logical
method elements, 16 MiB total delivered bytes, 2,000,000 bytes per response and
in flight, zero retries and the unchanged 2 physical starts/second. Offline reservations consume their maximum modeled charge even on failure.
Actual transport enforcement requires the separately authorized runner; none is implemented here. Monetary ceiling and throughput profile
remain `null`: no provider dispatch can be justified from this file.

Before a separately authorized capability test, authenticate the exact endpoint
and independently verify the selected plan's available units, archive/batch/failure
classification, throughput weights and maximum charge for all attempted methods.

Native active-market replay tightens the scheduling blocker. One active native
owner on the original fallback needs seven transports and eleven logical elements
(272 estimated billed/throughput CU); its native positions and risk remain equal.
Two held Survivors
use thirteen isolated transports versus seven shared transports; twenty use
121 versus seven in the synthetic single-transaction specimen. At two physical
starts/second, seven starts span at least three seconds before the last response
or local processing. This cannot fit the original three-second deadline.
`SYSTEM_WIDE_EFFICIENCY.json` preserves complete request traces and independent
native positions/risk state. The shared resource proof is a fixture, so actual
endpoint sharing remains inactive. Neither package headline RPS nor this reduction
certifies whole-loop capacity. Adversarial staggering also defeats sharing in the
native quotation component matrix; no wait was inserted to enlarge a batch.

The consistent offline provider copy independently records saved 0.5-second
intervals for two historical endpoint identities. `LOCAL_PROVIDER_USAGE.json`
records 3,010 Pons starts and 11,828 logical elements, estimated at 270,932 frozen
billed CU. Its timestamps/consumer identities cannot establish a full billing
month, quotation equivalence or current workload distribution. Paused Ramses
records are reported separately as historical data; no new workload was initiated.
Use the lesser of the owner's authorized monetary ceiling and that verified
worst-case reservation. Test only standard Pons RPC, pin both comparisons to one
canonical state, record start/element/byte/charge counters and stop on the first
budget or evidence boundary. No automatic retry, stream subscription, failover of
native authority, plan purchase or PAPER startup belongs in that test.

Capacity repair boundary: retain the existing `Admission`, position priority,
deadline queue and shared `PacedRpc`; batch only already-ready, same-state work,
with each native consumer simulation independent. Extend those established
boundaries with measured logical throughput weights, bounded in-flight bytes,
original protection reservations and ledger-derived monetary budgets after the
provider profile is authenticated. The native Survivor runtime now contains a
conditional quote union and unioned held history using the existing selector.
It requires authenticated endpoint resource bounds and remains inactive without
them; it introduces no wait to enlarge batches and no higher governor. Two quiet
native owners use five mock transports instead of ten, but staggered quote
components still miss deadlines under the unchanged governor. Current ownership
has separately been decoupled from its eight physical workers. Neither proof
certifies full-market concurrent history, execution, provider RTT or protection
capacity.
If complete original deadlines cannot be met within supported limits, keep the
configuration inactive and report the deficit; do not trade deadlines for savings.
