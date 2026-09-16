# Build status / continuation

## Repository and authority

Repository: `levonmendall/The-Meme-Machine` (public). Authorized minimal `main`
initialization remains `54712c4c6470cc4dc267888f934bd693aac030d0`.
Implementation branch: `feat/pump-directional-paper`; PR #1 is the review boundary.
Do not merge, deploy, purchase services, enable signing/submission/live money, or alter
predecessor repositories/services without separate authorization.

The reviewable implementation is branch HEAD. Resolve it with `git rev-parse HEAD`;
GitHub Actions attaches verification to the exact SHA. Do not substitute `main`.

## Implemented directional surface

The sole implemented venue remains Pump.fun on Solana mainnet. The paper lifecycle is:
wallet scouting -> independent continuation-v1 qualification -> shared $500 allocator
-> reservation -> delayed finalized quote/fill -> independent position monitoring ->
exit -> settlement -> restart reconciliation. DLMM allocation and all other venue
adapters remain disabled/deferred.

The Pump adapter now supports both ordinary native-SOL Pump bonding curves and
**native-SOL Mayhem Mode bonding curves** when `quote_mint` is the SOL/default value
and cashback is disabled. Mayhem does not change the constant-product reserve quote
used for our own hypothetical buy/sell, but it does change supply context. The model
therefore validates the real mint supply, uses that supply for dynamic fee-tier market
cap and concentration, and keeps the Mayhem agent inventory visible as genuine supply
and exit-overhang risk.

Cashback and non-native quote assets remain fail-closed. They require different
cash-flow/quote-capital accounting and were not enabled merely to increase candidate
coverage. Completed/graduated curves remain outside this first Pump bonding-curve
execution surface.

## What the rejected natural candidates actually were

A bounded read-only on-chain inspection classified ten naturally nominated mints that
had previously failed as `unsupported curve mode or quote asset`:

- all 10 had `is_mayhem_mode=true`;
- all 10 had native-SOL/default `quote_mint`;
- all 10 had `is_cashback_coin=false`;
- all 10 had 6-decimal mints;
- all 10 had curve `token_total_supply` of 1,000,000,000 tokens while observed mint
  supply was approximately 2,000,000,000 tokens, consistent with Mayhem's additional
  trading-agent inventory (two observations were one base unit below 2B);
- none of the inspected curves had a custom creator fee or holder-reward flag.

This established a concrete adapter-compatibility gap rather than a strategy
qualification failure. After native-SOL Mayhem support was added, natural nominations
advanced past `initial_snapshot`; the old mode rejection disappeared.

## Mayhem provenance correction

The original public buyer census had accidentally admitted
`BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s` as an unvalidated scout. Pump's public
Mayhem documentation identifies that address as the protocol's disclosed Mayhem
trading-agent wallet. It is now removed from `evidence/unvalidated_seed_watchlist.json`.
`Engine` rejects that address as a scout, and Mayhem qualification excludes its trades
from independent-buyer/net-demand corroboration. Its market trades still affect real
reserves and its token inventory remains visible in concentration. This is a source-
provenance correction, not a continuation-v1 threshold change.

## Current exact verification

Exact verified head: `ae602bcf4384c0d3aca3c445a07ea603572282f2`.
Exact push workflow: `35163710197`.

Both workflow jobs passed. The deterministic suite is **49/49 passing**. It includes
Mayhem reserve-math, Mayhem supply, actual-supply fee-tier selection, standard-supply
fail-closed behavior, system-wallet exclusion, independent-demand exclusion, cashback
and non-native-quote rejection, and bounded pool-window short-circuit regressions.

The same exact-head resource workload remained bounded at 2,000 frames / 240,000
submitted events, ~1.26 MB SQLite DB, ~0.71 MB WAL and 26,444 KiB peak RSS on the
GitHub runner. The connected synthetic lifecycle also completed entry -> monitoring ->
exit -> settlement. These remain software/resource proofs, not market profitability.

## Latest prospective evidence

On the exact verified head, admitted-scout shadow qualification observed 9 admissible
real events and produced 4 natural nominations. Two fresh unique Mayhem/native-SOL
candidates were inspected at about 22 and 33 seconds signal age. Both passed the new
Mayhem account/supply snapshot validation, then stopped with the explicit unchanged-
policy result `incomplete_market_window` because the bounded 40-signature pool tail did
not span the complete required 60-second evidence window.

That exact run used 18 public RPC requests with **0 failures, 0 retries and no HTTP
429s**. It created zero orders, reservations, positions or paper trades; shadow cash
was unchanged. Therefore the adapter-mode repair is proven to have moved the evidence
boundary from account compatibility to market-history completeness.

Earlier runs did encounter public-RPC HTTP 429 responses while attempting transaction-
heavy pool history. The provider now honors a bounded Retry-After delay, and required
pool-history reads short-circuit before fetching transaction bodies when their bounded
signature census already proves that the complete 60-second window is unavailable.
Open-position monitoring retains priority.

## Policy / safety status

`continuation-v1` economic thresholds, fixed 5% initial-SOL entry budget, concentration
limit, independent-demand threshold, liquidity threshold, price/chase guard,
round-trip-cost threshold, delay, take-profit, stop, timeout and portfolio limits have
not been loosened to obtain a result. Wallet skill still has zero sizing influence.

This branch remains paper-only. The GitHub shadow diagnostic may call qualification but
has no order/reservation authority; a shadow `qualified` result would not itself be a
paper trade. Operational acceptance and profitability evidence remain false until a
market-driven position can be durably entered, monitored, exited and reconciled.

## Exact continuation boundary

The observed curve-mode question is resolved: current natural nominations are
native-SOL Mayhem curves, and that mode is now explicitly supported with Mayhem-specific
supply/fee/provenance controls. Do not broaden to cashback, custom quote assets, DLMM,
PumpSwap or another venue to manufacture activity.

The next evidence boundary is **complete point-in-time pool history for a natural
nomination under the unchanged 60-second continuation-v1 window**. Continue bounded
prospective observation. If a candidate obtains a complete market window, run the
existing concentration/final snapshot and unchanged `Engine.qualify` path and record
its exact accept/reject reason. If active pools consistently exceed the bounded history
capacity or public RPC again prevents complete evidence, treat that as a read-only data
capacity/efficiency problem rather than changing strategy thresholds.

Do not create a paper position on an ephemeral Actions runner. A real paper entry must
use durable resumable state through monitoring and settlement.

Reproduce deterministic checks:

```sh
python -m unittest discover -v
python -m tests.resource_check
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-fresh.db --tape tests/fixtures/synthetic_lifecycle.jsonl
```

Bounded admitted-scout shadow diagnostic:

```sh
python -m tests.prospective_qualification
```

Optional one-off curve-mode inspection (diagnostic only; not part of every live run):

```sh
python -m tests.inspect_curve_modes
```
