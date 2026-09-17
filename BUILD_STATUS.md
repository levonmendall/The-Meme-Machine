# Build status / continuation

## Repository and authority

Repository: `levonmendall/The-Meme-Machine` (public). Authorized minimal `main`
initialization remains `54712c4c6470cc4dc267888f934bd693aac030d0`.
Implementation branch: `feat/pump-directional-paper`; PR #1 remains open and unmerged.
Do not merge, deploy, purchase services, enable signing/submission/live money, add
DLMM/other venues, or alter predecessor repositories/services without separate
authorization.

The latest **code-bearing verified SHA** is
`9d815bd93568600cdd9f72a37ce6ef2462f9bc58`. Subsequent documentation-only commits
may move branch HEAD; do not substitute a docs-only SHA for the code-bearing proof.

## Implemented directional boundary

The sole implemented venue remains Pump.fun on Solana mainnet. The paper lifecycle is:
wallet scouting -> independent `continuation-v1` qualification -> shared $500 allocator
-> reservation -> delayed finalized quote/fill -> independent position monitoring ->
exit -> settlement -> restart reconciliation. DLMM remains disabled.

The adapter supports ordinary native-SOL Pump bonding curves and native-SOL Mayhem
Mode curves. Cashback and non-native quote assets remain fail-closed. Mayhem uses the
same reserve-based paper quote path but validates its distinct mint-supply boundary,
uses actual mint supply for fee-tier market cap and concentration, and excludes the
disclosed Mayhem agent wallet from scouting and independent-demand corroboration.

No `continuation-v1` economic threshold, sizing rule, exit rule, or portfolio rule was
changed during the history-capacity work.

## Why retrospective pool reconstruction was replaced

Natural Mayhem nominations exposed a data-acquisition problem rather than a strategy
problem. A bounded 40-signature tail was too short. Increasing the census to the
Solana RPC maximum of 1,000 signatures still could not guarantee that a hot pool's
result reached strictly before the required 60-second cutoff. Fetching transaction
bodies after nomination also created bursty fan-out and public-RPC 429/provider errors.

The final proof path therefore does not reconstruct a hot pool after the signal. It
maintains one read-only finalized Pump-program `logsSubscribe` stream and a bounded
in-memory tape. The tape is warmed for the complete 60 seconds **before** any scout
event gains nomination authority. Thus the prior 60 seconds already exist when a
post-warmup scout buy occurs.

Stream safety rules are fail-closed:

- commitment is `finalized`;
- no pre-warmup scout trade may nominate;
- a disconnect or parse loss removes continuity and requires a fresh 60-second warmup;
- a capacity loss invalidates coverage for the affected window;
- future-time inconsistencies invalidate coverage rather than rewriting timestamps;
- retention is 75 seconds, with a 50,000 decoded-trade in-memory bound;
- the stream has observation authority only. The CI diagnostic calls `Engine.qualify`
  but cannot reserve capital, open a position, fill, monitor, or settle.

HTTP remains necessary for contemporaneous curve/mint/fee snapshots and token-holder
concentration once a fresh candidate exists.

## Exact deterministic verification

Code-bearing SHA: `9d815bd93568600cdd9f72a37ce6ef2462f9bc58`.
Push workflow: `35165757445`.
Both `test` and `live-diagnostic` jobs passed.

The deterministic suite is **55/55 passing**. Added coverage includes finalized stream
notification decoding, exact 60-second warmup authority, disconnect re-warm,
capacity-loss fail-closed behavior, secure WSS endpoint derivation, dense HTTP history
fallback batching, and strict unknown-timestamp/incomplete-window handling.

The exact-head bounded synthetic resource workload remained:

- 2,000 frames / 240,000 submitted events;
- SQLite DB: 1,261,568 bytes;
- WAL: 708,672 bytes;
- peak RSS: 26,284 KiB;
- no real provider calls in the synthetic workload.

The synthetic connected lifecycle still completes entry -> monitoring -> exit ->
settlement. These are software/resource proofs, not market profitability evidence.

## Exact live finalized-stream evidence

The exact-head live diagnostic used `finalized_logsSubscribe` and ran without order
or reservation authority.

Timeline:

- stream start: Unix `1789604101`;
- complete coverage became eligible: `1789604161`, exactly 60 seconds later;
- diagnostic ended: `1789604186`;
- final warm duration: 85 seconds.

Stream health at the evidence boundary:

- `connected=true` and `covered=true`;
- **0 gaps, 0 parse failures, 0 capacity losses**;
- 27,484 Pump-program notifications observed;
- 3,550 decoded Pump trade events;
- 2,642 retained decoded events at end;
- last observed finalized slot: `447656453`.

After the warmup, the admitted scout produced 3 real observed seed events and 2
natural nominations. Both had complete point-in-time 60-second market history:

1. `FtawywwXbE4MPHqPwjJcuA3J5CHEpBAXZPnZgyo3pump`
   - signal age about 11 seconds;
   - `market_window_covered=true`;
   - **14** decoded Pump trades in its exact 60-second window;
   - history snapshot slot `447656379`.
2. `CCLFcaHz4tMmzLm6wAoTv9NEvqzUsacmqDX53u8Ypump`
   - signal age about 15 seconds;
   - `market_window_covered=true`;
   - **109** decoded Pump trades in its exact 60-second window;
   - history snapshot slot `447656418`.

Both then stopped at the next independent evidence stage: `concentration`. Public HTTP
`getTokenLargestAccounts` calls were rate-limited. Across the diagnostic, HTTP used 9
logical/physical requests, recorded 4 HTTP 429 failures and 2 bounded retries.

No order, reservation, position, or paper trade was created. Shadow cash was unchanged.

**Conclusion: the requested complete 60-second point-in-time pool-history problem is
now proven solved for natural hot Mayhem candidates without weakening the 60-second
requirement.** The current immediate blocker is public-HTTP concentration evidence,
not pool history.

## Important remaining limits

This does **not** establish a complete `evidence_stage=complete` economic qualification,
a market-driven paper entry, operational acceptance, or profitability. The two live
candidates failed before concentration could be obtained.

The second candidate's complete window contained 109 market events. If concentration
later succeeds, unchanged `Engine.qualify` currently returns `evidence_capacity` when
more than 100 market events are presented. Do not raise that cap or silently aggregate
away evidence merely to obtain a qualification; treat it as a separate bounded-evidence
question if it becomes the next actual blocker.

The finalized stream is currently proven in the no-order-authority prospective shadow
diagnostic. The durable `python -m meme_machine --mode prospective` runtime still uses
its earlier HTTP history path. Do not claim authoritative long-running stream-backed
paper operation until the stream acquisition path is deliberately integrated into the
durable runtime with restart/reconciliation behavior preserved.

## Exact next boundary

Stop modifying the 60-second window: it is now demonstrated complete under the
finalized stream. The next narrow engineering question is whether concentration can be
obtained reliably and efficiently without new provider cost. If public RPC repeatedly
429s the required concentration query, treat that as the read-only RPC-capacity
boundary rather than modifying strategy thresholds.

If a later stream-covered candidate obtains concentration and final snapshot evidence,
run unchanged `Engine.qualify` and report its exact reason. A shadow `qualified` result
still is not a paper trade.

Reproduce deterministic checks:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m tests.resource_check
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-fresh.db --tape tests/fixtures/synthetic_lifecycle.jsonl
```

Bounded finalized-stream shadow proof:

```sh
python -m tests.prospective_stream_qualification
```
