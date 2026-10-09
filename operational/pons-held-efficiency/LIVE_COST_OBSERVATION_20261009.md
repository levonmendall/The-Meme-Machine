# Pons live cost observation — 2026-10-09 UTC

**Disposition: LIVE_FILTER_COMPONENT_VERIFIED / END_TO_END_SAVINGS_NOT_PROVEN**

The owner asked for live verification *before* completion or activation of the Pons event-driven holding redesign. This read-only test used the connected Robinhood Alchemy application, not a deployed Meme Machine process. No PAPER or real position was purchased/sold, no deployment/configuration/provider entitlement was changed, no signing/funding was enabled, and no production controller used the candidate adapter.

## Identity and bounds

- Network: Robinhood mainnet, Alchemy Robinhood app selected (app ID `v5h0vqr0wpp9zscj`).
- Historic proven Pons V2 -> Uniswap V4 pool ID: `0x2075abed94de15d218a27b4da93541a974e23e131f1d2da32177b33634ac8da7`.
- PoolManager: `0x8366a39CC670B4001A1121B8F6A443A643e40951`.
- Pons hook: `0xE5e702641Ea86F4ae6cC3cDaeD2B886f976Be044`.
- Authentic lineage transaction: `0x1d49a28a0e27ecdd952094c4aaa9de2105253a2d62924ec36e761c13e43493c9`, at block `0x363f617`.
- Native quoter: `0x8dc178efb8111bb0973dd9d722ebeff267c98f94`. Exact-input quote simulation was for 10^18 held-token units, not an actual wallet position.
- All reads were bounded to explicit block ranges and an existing account. No automatic retries, subscriptions, archive sweep or long-running market service was started.

## A. Live 40-block provider filter parity

Same fixed 40 blocks were compared with four disjoint ten-block queries. Canonical event identity included block hash, transaction hash, log index and raw event data.

| Authenticated nonempty filter | One 40-block query | Four 10-block queries | Exact parity |
| --- | ---: | ---: | --- |
| V4 PoolManager Initialize | 1 event | 1 event total | PASS |
| Pons Hook PoolRegistered | 1 event | 1 event total | PASS |
| V4 PoolManager Swap | 1 event | 1 event total | PASS |
| Pons HookFeeCollected | 1 event | 1 event total | PASS |

One 40-block call versus four 10-block calls saves **3 of 4 eth_getLogs elements (75%) for each tested filter**. Alchemy method accounting uses **60 CU per eth_getLogs request**, so this is 240 -> 60 modeled/billable-method CU per filter, or 180 CU fewer per filter. Across the four equivalent queries it is 960 -> 240, or 720 CU saved under the same method tariff. This is a real endpoint/filter capability observation, **not** a 75% reduction to the entire Pons machine bill. Production code already batches ten-block logical queries into one HTTP request when possible; do not count four-to-one physical HTTP savings from this direct-tool sequential experiment.

The single filtered nonempty 40-block requests completed in approximately 0.35-0.78 seconds; the four sequential ten-block calls took approximately 1.58-2.05 seconds in the same connector. These are connector timings, not latency guarantees on the existing Pons governor or the 3-second Survivor safety loop.

No demonstrated busy/high-cardinality 40-block equivalence, response saturation ceiling, block gap recovery or full manager+hook filter-union parity was established. The code's authenticated capability-file preconditions must not be bypassed.

## B. Live quiet-pool / native quote comparison

A separate contiguous **160-block** numeric interval `0x4ff8103` through `0x4ff81a2` was queried on Robinhood mainnet.

- Filtered native PoolManager pool-ID events: 0.
- Filtered Pons hook pool-ID events: 0.
- Filtered 10 global Pons hook control event topics: 0.
- Headers at block `0x4ff8102`, `0x4ff8152` and `0x4ff81a2` reported chain timestamps **2026-10-09 03:48:54, 03:49:02, 03:49:10 UTC**, so the sampled horizon was **16 seconds**, not 72 hours.
- Native V4 quoter was read-only queried at blocks +0, +40, +80 and +160. All four responses returned the identical output amount **1,124,082,281 wei** and quote simulation gas **68,729**, for the same 10^18 held-token input.
- This establishes **sampled exact-quantity quoter output stability** in one event-quiet Pons pool window. It does NOT establish static gas price, every token/fee invariant, native historical position profitability, no missed WebSocket message or production exit correctness.

The four quote samples show up to 3 of 4 simulations *could* have been omitted **in hindsight** without changing those particular returned values. This is not proof that a scheduler would have known safely in advance, nor a 75% all-in cost saving: certified event coverage and canonical headers themselves cost provider CU and physical attempts.

## C. Account usage cross-check

Alchemy Robinhood-app hourly method usage was consulted. A partial snapshot with data through `2026-10-09T03:53:00Z` reported `eth_getLogs: 1200 CU`, `eth_call: 52 CU`, `eth_getTransactionReceipt: 20 CU`, `eth_blockNumber: 30 CU`. This supports the method-cost order of magnitude, but the partial app/hour bucket includes unknown unrelated requests and reporting lag. **It is not an exclusive invoice delta for this experiment.** Separate WebSocket delivered-byte billing was not measured.

## Decision for implementation

**Verified:** At least this paid app accepted exact nonempty 40-block filters; 40 vs four 10-block elements for four authentic pool/hook event categories had exact identity/payload parity; one actual Pons pool had unchanged native quote outputs across an observed 16-second quiet interval.

**NOT verified:** The forecast **70-95% all-in Pons long-hold saving**, a complete event subscription or all-mutator coverage producer, 3-second/5-second protective-exit noninferiority, a multi-day held-position portfolio, actual bill reduction, high-activity adaptive fallback and extension affordability.

**Gate:** Continue to keep new quote-skipping and price-only extension policy inactive. Do not merge/deploy or enlarge budgets on this evidence. A subsequent separately bounded live shadow comparison on an active Pons pool is required: side-by-side actual baseline and candidate quote demand, complete canonical manager/hook/fee/token coverage, delivered WS bytes or actual HTTP consumption, busy-market/reorg/reconnect cases, cost by method and any loss of protective-exit timing. Only then implement/activate the event-driven controller if both cost reduction and exit equivalence are supported.

The in-branch `held_event_coverage.py` is a standalone candidate and **is not connected to production controllers**. Earlier 147 focused/current-survivor tests ran before that new file was added; no claim that this new adapter has passed its own tests is made.
