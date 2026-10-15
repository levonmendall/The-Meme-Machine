The economic policies remain the operational policies at `5bd1a8b`. This is the
provider interface required by those policies. A discovery locator never grants
economic completeness. Unknown evidence remains unavailable.

| Lifecycle | Authoritative fields | Acquisition class |
|---|---|---|
| Pump universal discovery | Curve address, program owner, native slot, transaction signature, reserve/supply locator, complete flag | CONTINUOUSLY REQUIRED: server-sliced account scout; all identities retained |
| Pump development/reactivation | Actual creation/mint/curve lineage, initial reserves, ordered trader identity, side, token/quote quantity, native transaction index and event index | CANDIDATE-SPECIFIC: archive from actual creation, overlapping live log/status join |
| Pump Current qualification | Exact required ordered window, first-wallet prefix, creation lineage, curve/account/mint state, holders, concentration and quote reconstruction | QUALIFICATION-ONLY: complete scoped history and selective exact account/holder requests |
| Graduation/Current continuation | Canonical migration and pool lineage, ordered PumpSwap economics, exact executable pool reserves and fees | CANDIDATE-SPECIFIC; POSITION-ONLY after admission |
| Survivor qualification | Graduation, independent lane state, required reset/base/structure/demand history and buyer breadth, exact size/impact evidence | CANDIDATE-SPECIFIC history; QUALIFICATION-ONLY exact account state; funding follows durable qualification |
| Pump/PumpSwap open positions | Ordered price/demand/HWM/bridge/staged-add inputs, exact executable reserves, fees, confirmation and settlement identity | POSITION-ONLY with safety/position priority; shared Current/Survivor events acquired once |
| Meteora structural discovery | WSOL-paired pool identity/owner/filter lineage; bin header pool locator | CONTINUOUSLY REQUIRED; never substitutes for ordered swaps |
| Meteora development/reactivation | Authentic pool/bin activity locator; exact economics acquired before admission | CANDIDATE-SPECIFIC; locator is noncanonical economic evidence |
| Meteora warming/qualification | Account keys including loaded addresses, top-level and inner instructions, logs, pre/post token balances, error, native transaction index, exact pool/token/mint/bin snapshots and a real lower-bound signature witness | QUALIFICATION-ONLY exact 12-second reconstruction; incomplete warming fails closed |
| Meteora position/confirmation/settlement | Same required reconstruction vector, fresh exact accounts/bins, finality/confirmation ordering and settlement reconciliation | POSITION-ONLY; safety/settlement outranks qualification |
| All recovery | Durable content-before-checkpoint, original availability, signature/index dedup, overlapping scoped replay and exhaustive archive pagination, explicit gaps, pending jobs and qualified-unfunded outcomes | RECOVERY-ONLY; no unrelated global transaction/status census |

The selected interface is sliced discovery, conservative candidate activity,
candidate-scoped ordered history, selective hydration and exact positions. Native
status provides signature/slot/index/error; it does not provide missing account
keys or logs. Pump/PumpSwap log economics therefore require an independent order
witness. Archive `transactionDetails=full` still delivers rich bodies: local
projection saves CPU/storage, not the provider's bytes or call CU.

The integration remains disabled by `PRODUCTION_BLOCKERS` in
`solana_selective_source.py`. Specifically, cheap Meteora evidence does not yet
feed strategy promotion, activity does not yet drive reactivation, cold-cache
retirement is missing, the WS/replay handoff and candidate restart gaps need
certification, and combined position pressure and positive Meteora opportunity
parity have not been demonstrated. Removing that guard does not repair those
conditions. The candidate is unsuitable for merge or PAPER activation.
