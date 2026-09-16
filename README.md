# The Meme Machine

Fresh, paper-only research application. Wallets scout; independent contemporaneous
market evidence authorizes a paper entry. Profitability is an untested hypothesis.
One shared portfolio starts once at **$500**, allocated to simulated SOL on Solana
mainnet using an explicit recorded starting USD/SOL valuation. It is not $500 per
strategy. Cash benchmark is holding that initial SOL balance; current USD value is
unknown without a fresh conversion mark. No signing, transaction submission, paid
services, deployment, predecessor imports, or automatic policy optimization.

## Milestone and contract

Pump.fun **standard SOL bonding curves** are the sole implemented surface. The
read-only RPC adapter decodes real accounts and successful Pump invocation logs.
Integer constant-product quotes use contemporaneous on-chain dynamic fee tiers,
real reserve bounds, exact proposed size, and conservative fee rounding. This is a
versioned hypothetical execution model, not a promise that a transaction lands.
Token-2022 metadata-only mints are supported. Transfer hooks/taxes, freeze/mint authorities, mayhem/cashback, custom
quote assets and completed curves fail explicitly. Graduation retains mint identity
but an unavailable bonding-curve exit remains unresolved; it never becomes a
fictional PumpSwap fill.

| Target | Status |
| --- | --- |
| Pump.fun standard SOL bonding curve | Implemented offline; live evidence in BUILD_STATUS.md |
| PumpSwap and Raydium | Planned, no adapters |
| FOMO application/feed and underlying pool | Planned; identity must be verified; not a chain or sentiment score |
| Robinhood Chain on-chain pools | Planned; chain/network/contracts/providers must be verified |
| Solana Meteora DLMM | Planned; liquidity-position interface only, allocation disabled |
| Robinhood Chain Ramses DLMM candidate | Planned; offering/deployment must be verified, allocation disabled |

No legacy code was copied. There is no v5.2 equivalence claim. The uploaded mandate
is the broader product contract; this branch deliberately implements only its first
directional experiment. Live operational acceptance and profitability are separate
from liveness, data readiness, fixture correctness and captured mainnet evidence.

## Fixed policy: continuation-v1

These uncalibrated research defaults are declared before evaluating outcomes:

- At most eight explicitly configured public scout addresses, with seed provenance.
  A scout buy within 60 seconds nominates a mint. No wallet skill or sizing bonus.
- Require a complete bounded 60-second pool window. Exclude scout/creator and known
  related groups from demand; require three distinct remaining groups and net buys
  of at least 1 SOL. Unknown common ownership remains a stated uncertainty.
- Top-five token-account concentration excluding verified curve custody <=35% of
  supply. This is account concentration, not proof of beneficial-owner independence.
- Require >=10 SOL real exit liquidity; current price <=120% of observed scout
  transaction price; exact-size round-trip loss including modeled fees <=5%.
- Fixed entry budget 5% of initial SOL, four concurrent positions/reservations
  maximum; one mint and one creator/related group at a time. Preserve 10% gas/cash
  reserve. No scale-in, leverage, averaging down, re-entry or partial exits/runners.
- Quote age <=20 seconds; minimum execution delay 2 seconds; require a later
  finalized slot and post-delay market timestamp. Entry slippage limit 1%; cancel
  unavailable/stale attempts. A delayed finality quote waits up to 60 seconds.
- Model 50,000 lamports network/priority cost per attempted transaction; actual
  future inclusion fee is uncertain. Reserve 2,100,000 refundable ATA rent (conservative reserve for SPL/Token-2022); release
  it only with the modeled full exit/account closure. These assumptions are not
  RPC transaction simulation or a measured fill. Protocol fees are charged once.
- Monitor every 5 seconds, independent of scouts. Full exit at net +15%, -10%,
  15-minute timeout, or real SOL liquidity below 5 SOL. An exit intent remains
  active until a later valid mark settles it. Failed exits retain inventory; stale
  or missing marks are unknown, including when a curve graduates.
- No threshold changes to obtain a trade. No positive-skill promotion. Partial
  wallet episodes and observed trades are not validated wallet performance.

## Run

Use **CPython 3.12.14**, the same exact version as CI; standard library only, zero
third-party Python dependencies. Linux/macOS file locking is required. Use a durable
local directory for real experiments. Never put runtime databases or credentials
in Git. One process owns the SQLite writer.

```sh
python -m unittest discover -v
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-synthetic.db --tape tests/fixtures/synthetic_lifecycle.jsonl
```

For a budgeted prospective session, copy `config.example.json` locally; enter actual
public scout addresses and provenance plus the initial SOL/USD valuation and its
source. Empty seeds explicitly mean no scouting; never substitute synthetic seeds.
`MM_SOLANA_RPC_URL` is the only optional credential-bearing variable; public RPC is
the default. A private provider URL, if needed, must support read-only finalized
`getGenesisHash`, `getSignaturesForAddress`, `getTransaction`, `getMultipleAccounts`,
`getBlockTime`, and `getTokenLargestAccounts`. Never supply a wallet private key.

```sh
python -m meme_machine --mode prospective --config config.local.json --db /path/to/state/paper.db --seconds 60
```

Local read-only endpoints: `http://127.0.0.1:8080/live`, `/ready`, `/status`.
Status cannot place orders or fetch market history. Session duration is bounded
(1..3600 seconds); do not leave positions unattended after a session ends. Restart
with the same database/config to resume. Provider budget is 120 calls/session by
default (hard maximum 240), with 40 reserved for monitoring; at most 2 requests/sec,
no hidden retries, shared two-second cache and bounded responses. These are request
budgets, not proof of a particular vendor's monthly allowance.

## Architecture, authority and persistence

`provider.py` owns RPC retrieval and budgeting; `pump.py` decodes and quotes;
`engine.py` scouts, qualifies, allocates and manages paper lifecycle; `store.py`
is the sole durable writer. Replay and live use the same Engine and Store. SQLite
FULL-sync transactions atomically persist action journal and authoritative state.
Intents/reservations survive a crash; repeated settled order IDs cannot spend twice.
Finalized observations reduce reorganization exposure; history is not rewritten to
invent a recovered trade. Contradictory evidence is a failure, not an overwrite.

| Dataset | Owner/purpose | Retention and bound |
| --- | --- | --- |
| State checkpoint | Store; current authority | One hashed row; <=4 active positions; <=100 entries per experiment |
| Orders + embedded entry/exit evidence | Engine; reproduce economics | Keep all experiment orders; cap experiment at 100 entries; no automatic deletion |
| Dedup IDs | Scout; reject duplicate/conflicting observations | 120 seconds, <=1,000; expired events cannot qualify |
| Decisions | Engine; explicit zero-trade reasons | Latest 100 plus aggregate counts |
| Gaps | Provider/scout; visible loss markers | Latest 20; no fabricated continuity |
| Journal | Store; atomic audit events | Append for bounded session/experiment; 32 MiB admission pressure boundary |
| Provider cache | RPC; shared retrieval | Memory only, <=128 responses / 8 MiB encoded payload, 2-second reuse; <=2 MB/response |
| Raw research captures | Tests/research | Small public redacted fixtures, separate from prospective authority |

Pressure stops discretionary entries before monitoring, including <16 MiB filesystem free space. Open positions and orders
are never deleted to satisfy a size limit. Existing positions may require bounded
additional writes above the admission threshold. No rollover/copy/full-ledger scan
on startup or status. Startup checks checkpoint hash, journal tail and current
accounting invariants. `Store.verify_archive()` separately streams the complete
journal for audit; hashes detect accidental damage, not a malicious DB owner.
A hostile rewrite or old-checkpoint rollback requires external anchoring, deferred.
No cross-chain balance, gas conversion or liquidity-position allocation is implied.

Wallet shadow scorecards retain at most 32 token episodes per configured seed.
They record observed buys/sells, token inventory, costs and availability times;
unknown starting inventory, partial sells and transfers cannot become claimed
profit. Wallet protocol fees are observed; network-fee allocation across composite
transactions and complete balance boundaries remain unresolved. No follower return
is credited from the leader's earlier price. Budget-matched discovery-control and
wallet-informed/blind performance comparisons remain the next research layer;
this initial policy deliberately grants no wallet-skill influence.

A gap blocks further entries for that experiment while exits continue. Clearing a
gap is not automated: preserve evidence and review a new experiment or a specific
recovery repair. A rare contradiction in finalized history is a gap, not permission
to retroactively rewrite fills. No reorganization economics are fabricated.
