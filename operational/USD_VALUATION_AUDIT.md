# USD valuation

USDG/USD is verified on Robinhood Chain mainnet, chain ID **4663**. The runtime
uses proxy **`0x61B7e5650328764B076A108EFF5fa7282a1B9aD2`** exclusively through
the existing `MM_ROBINHOOD_READ_RPC_URL`. No new provider or credential is needed.

The identification source is [Chainlink's Reference Data Directory](https://reference-data-directory.vercel.app/feeds-robinhood-mainnet.json),
explicitly listed as the Robinhood mainnet source in
[Chainlink's own documentation source](https://github.com/smartcontractkit/documentation/blob/main/src/features/data/chains.ts#L623).
Its USDG/USD record identifies that exact primary proxy, aggregator
`0x8bEeE3503F6860D5dac4cE26b5eEe92982951c2e`, 8 decimals, an **86,400-second
heartbeat**, and 0.5% deviation threshold. The secondary SVR proxy is not a fallback.
Neither the abbreviated address nor a token symbol was used as authority.

Independent read-only RPC verification used the already-connected Robinhood
Production Read Alchemy application. At block **79,544,688** (`0x4bdc170`), hash
`0xc1428112e199645031d6d2026bd0b4648c1a9a39a5d93b3166372b0fbdbe514c`,
timestamp **2026-10-04T01:25:22Z**, direct contract reads returned:

| Read | Result |
| --- | --- |
| `eth_getCode(proxy)` | Deployed contract code; AggregatorV3 selectors present |
| `description()` | `USDG / USD` |
| `decimals()` | `8` |
| `aggregator()` | Exact aggregator address from Chainlink's directory |
| `version()` | `6` |
| Aggregator `typeAndVersion()` | `DualAggregator 1.0.0` |
| `latestRoundData().roundId` | `18446744073709551737` (phase 1, round 121) |
| `answer` | `100013961`, exactly **1.00013961 USD/USDG** |
| `startedAt` | `1791041989` |
| `updatedAt` | `1791042001`, **2026-10-03T15:40:01Z** |
| `answeredInRound` | `18446744073709551737`, equal to round ID |
| Frozen USDG token `decimals()` | `6` |

The observation was **35,121 seconds old** at the pinned block, within the
documented heartbeat; its validity ended at **2026-10-04T15:40:01Z**. The raw
readback and selected directory record are in [usdg-feed-readback.json](usdg-feed-readback.json).
The connected tool truncated the code response; its saved prefix proves code
presence and is explicitly recorded as a prefix, not a full bytecode identity.

Runtime `eth_call` validates the pinned chain/proxy, exact description, feed and
token decimals, deployed proxy/aggregator code, proxy interface, strict ABI lengths,
positive signed answer, uint80 round/phase semantics, ordered nonzero timestamps,
and freshness. Decimal normalization preserves the actual answer, including depeg.
Cached oracle observations are reused for at most 60 seconds and never beyond
their heartbeat validity. Provider failure, malformed rounds and stale/nonpositive
answers fail closed with `VALUATION_UNAVAILABLE`; no fixed-$1 substitute exists.

Pons native quote capital derives from its genuine **$125 family sleeve** using
native ETH→USDG executable conversion→this USDG/USD observation→USD. The reader
reuses the existing compiled router/factory authentication, WNATIVE identity,
factory membership, full pool authentication, hook exclusion and `getSwapOut`
capacity checks in `ramses_costs`. A bounded 0.001 ETH reference quote supplies a
conversion rate, without changing strategy quantity or entry/exit rules. The
conversion evidence retains the existing five-second execution window, bounded
also by oracle expiry. Historical fixed ETH/USD calibration grants no portfolio
valuation authority.

Ramses converts economic amounts from its frozen USDG quote token
`0x5fc5360d0400a0fd4f2af552add042d716f1d168` (6 decimals) through the same feed.
Other quote identities fail closed. Its entry, sizing, range, costs, rebalance,
exit and profitability rules are unchanged. Its existing unavailable mark behavior
still requires a valid liquidation quote before a USD mark can be published.

Pump/Meteora retain the existing authenticated Pyth SOL/USD decoder unchanged.
Robinhood oracle outages do not affect that reader. Existing positions and
pending durable facts remain intact during valuation failure; operations requiring
a new value stop, while the existing release/replay paths need no substitute price.

Offline validation: **31 focused**, **283 FAST**, **516 OPERATIONAL** tests passed
on CPython 3.12.14 / SQLite 3.53.1. All committed lane files and the nine-change
test module are byte-identical to `f05dcf09ebbded45e09aa7a95bfbe82c07b4fd38`;
the pre-change strategy comparison passes, including all 44 Ramses modules.
The earlier consolidation checks in `offline-validation.json` describe the prior
blocked commit; this repair resolves its sole valuation blocker.

Only read-only oracle verification occurred. No trades, deployment, genuine $500
epoch, CAPACITY, RECOVERY or AUTONOMY run occurred. PAPER only.
