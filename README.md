# The Meme Machine

Fresh, paper-only research application. Wallets scout; independent contemporaneous
market evidence decides whether anything remains executable. Profitability is an
untested hypothesis. One shared portfolio starts once at **$500**, allocated to
simulated SOL on Solana mainnet from an explicit recorded starting USD/SOL valuation.
It is not $500 per strategy. No signing, transaction submission, paid services,
deployment, predecessor imports, or automatic policy optimization.

## Current milestone

The only implemented trading surface is Pump.fun bonding-curve trading on Solana
mainnet. Both ordinary native-SOL curves and native-SOL **Mayhem Mode** curves are
supported. Cashback and non-native quote assets remain fail-closed. Completed curves
remain outside this first bonding-curve execution surface; graduation never becomes a
fictional PumpSwap fill.

The read-only adapter decodes real Pump accounts and successful Pump invocation logs.
Integer constant-product quotes use contemporaneous reserves, real-liquidity bounds,
actual mint supply where Mayhem requires it, dynamic protocol/creator fee tiers, exact
proposed size, and conservative fee rounding. Token-2022 metadata-only mints are
supported; transfer fees/hooks and other transfer-changing extensions are rejected.

Wallet scouting never grants purchase authority. The publicly disclosed Pump Mayhem
agent wallet is prohibited as a scout and excluded from independent-demand
corroboration, while its real reserve and inventory effects remain visible.

| Target | Status |
| --- | --- |
| Pump.fun native-SOL standard + Mayhem bonding curves | Implemented; prospective evidence in `BUILD_STATUS.md` |
| PumpSwap and Raydium | Planned, no adapters |
| FOMO application/feed and underlying pool | Planned; identity must be verified |
| Robinhood Chain on-chain pools | Planned; chain/contracts/providers must be verified |
| Solana Meteora DLMM | Planned; liquidity-position interface only, allocation disabled |
| Robinhood Chain Ramses DLMM candidate | Planned; must be separately verified, allocation disabled |

No legacy application code was copied and there is no v5.2-equivalence claim. Live
operational acceptance and profitability remain separate from liveness, data readiness,
fixture correctness, captured evidence, and shadow qualification.

## Fixed policy: continuation-v1

These research defaults remain unchanged while prospective evidence is gathered:

- at most eight provenance-recorded public scout addresses; a scout buy within 60
  seconds nominates a mint, with no wallet-skill sizing bonus;
- require a **complete point-in-time 60-second market window**; exclude scout, creator,
  known related groups, and the Mayhem system wallet where applicable; require at
  least three remaining independent groups and at least 1 SOL net buying;
- top-five token-account concentration excluding verified curve custody <=35% of
  actual mint supply;
- require >=10 SOL real exit liquidity, current price <=120% of scout transaction
  price, and exact-size modeled round-trip loss including protocol fees <=5%;
- fixed entry budget 5% of initial SOL, maximum four concurrent positions/reservations,
  one mint and one creator/related group at a time, with a 10% cash/gas reserve;
- quote age <=20 seconds, minimum execution delay 2 seconds, later finalized slot and
  post-delay timestamp required, 1% entry slippage limit;
- model 50,000 lamports per attempted transaction and reserve 2,100,000 refundable ATA
  rent until modeled full exit/account closure;
- monitor every 5 seconds independently of scouts; full exit at net +15%, -10%,
  15-minute timeout, or real SOL liquidity below 5 SOL;
- no leverage, averaging down, scale-in, re-entry, partial exits/runners, threshold
  changes to obtain a trade, or automatic positive-skill promotion.

## Point-in-time market evidence

Hot Mayhem pools exceeded retrospective bounded signature-history capacity. The
prospective shadow validator therefore maintains one finalized Pump-program
`logsSubscribe` stream and a bounded in-memory trade tape. A scout event receives no
nomination authority until the stream has been uninterrupted for the full 60 seconds.
Disconnect, parse loss, future-time inconsistency, or tape-capacity loss invalidates
coverage and requires a fresh warmup. The tape retains 75 seconds and at most 50,000
decoded trade events.

This stream has already demonstrated complete natural 60-second windows containing
14 and 109 Pump trades; see `BUILD_STATUS.md` for exact evidence. The recurring CI
shadow diagnostic has **no order/reservation authority**.

For the existing <=35% concentration gate, `concentration.py` first uses the same
primary read-only RPC to issue one finalized `getProgramAccounts` request against the
mint's token program, filtered by mint and sliced to only each token account's 8-byte
amount. It requires a context slot tied to the candidate snapshot, excludes verified
curve custody, and calculates the same top-five-account percentage over validated
actual mint supply. The old `getTokenLargestAccounts` call remains a fail-closed
fallback. No secondary provider, key, subscription, or new cost is required by default.

Important boundary: the finalized stream is currently wired into the shadow
prospective qualifier, not yet into the durable authoritative prospective runtime.
The durable runtime still uses its earlier HTTP history path. Do not interpret the
stream or concentration proof as a market-driven paper lifecycle.

## Runtime and dependencies

Use **CPython 3.12.14**, matching CI. The application is otherwise standard-library
focused and currently has one pinned third-party dependency, `websockets==17.1`, for
the finalized read-only log stream.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-synthetic.db --tape tests/fixtures/synthetic_lifecycle.jsonl
```

For a bounded prospective session, copy `config.example.json` locally and provide real
public scout addresses/provenance plus an explicit initial SOL/USD valuation. Empty
seeds mean no scouting. `MM_SOLANA_RPC_URL` is the optional credential-bearing primary
provider variable. `MM_SOLANA_CONCENTRATION_RPC_URL` is an optional read-only secondary
experiment only and is empty by default. Never provide a wallet private key.

```sh
python -m meme_machine --mode prospective --config config.local.json --db /path/to/state/paper.db --seconds 60
```

The durable runtime exposes local read-only `/live`, `/ready`, and `/status` endpoints.
One process owns the SQLite writer. Restart with the same database/config to preserve
cash, reservations, positions, and reconciliation state. Monitoring/open-position
work has priority over discretionary discovery.

The no-order-authority finalized-stream validator and explicit concentration probe can
be run separately:

```sh
python -m tests.prospective_stream_qualification
python -m tests.concentration_live_probe
```

## Architecture and bounded state

`provider.py` owns HTTP retrieval/budgets; `stream.py` owns the bounded finalized log
tape; `concentration.py` owns retrieval of the existing concentration input; `pump.py`
decodes and quotes; `engine.py` scouts, qualifies, allocates and manages paper
lifecycles; `store.py` is the sole durable writer. Replay and live execution use the
same Engine/Store accounting semantics.

SQLite FULL-sync transactions atomically persist action journal and authoritative
state. Intents/reservations survive a crash; repeated settled order IDs cannot spend
twice. Startup verifies the current checkpoint, journal tail and accounting invariants
without scanning all history. Full archive verification is separate.

| Dataset | Purpose | Bound |
| --- | --- | --- |
| State checkpoint | Current portfolio authority | one hashed row; <=4 active positions; <=100 entries/experiment |
| Orders + entry/exit evidence | Reproduce paper economics | bounded experiment, retained for audit |
| Dedup IDs | Reject duplicate/conflicting observations | 120 seconds, <=1,000 |
| Decisions | Explain rejects/zero-trade state | latest 100 + aggregate counts |
| Gaps | Preserve missing-data truth | latest 20 |
| Journal | Atomic audit events | bounded experiment; admission pressure at 32 MiB |
| HTTP cache | Reuse read-only provider results | <=128 responses / 8 MiB, two-second reuse |
| Finalized trade tape | Complete prospective 60-second windows | memory-only, 75 seconds, <=50,000 decoded events |
| Captured fixtures | Decoder/research regression | small public fixtures, no prospective authority |

Pressure stops discretionary entry work before monitoring. Open positions and orders
are never deleted to satisfy a resource limit. Missing observations or executable
marks remain unknown/fail-closed rather than being replaced by favorable estimates.

Wallet scorecards are shadow-only and bounded. Unknown initial inventory, transfers,
partial sells, and incomplete outcomes cannot become claimed wallet profit. The initial
policy grants wallet skill zero sizing influence. Budget-matched wallet-assisted versus
wallet-blind research remains a later milestone.

See `BUILD_STATUS.md` for the exact current verification SHA, live evidence, and next
engineering boundary.
