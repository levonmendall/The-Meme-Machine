# Build status / continuation

## Repository and authority

Repository: `levonmendall/The-Meme-Machine` (public). Authorized minimal `main`
initialization remains `54712c4c6470cc4dc267888f934bd693aac030d0`.
Implementation branch: `feat/pump-directional-paper`; PR #1 remains open and unmerged.
Do not merge, deploy, purchase services, enable signing/submission/live money, add
DLMM/other venues, or alter predecessor repositories/services without separate
authorization.

Latest **code-bearing verified SHA**:
`e1153a9617931c5be4bc6a39e39a7ad02d115ff3`.
Final push workflow: `35169737512`; both `test` and `live-diagnostic` passed.
Documentation-only commits after this SHA do not replace that code proof.

## Implemented directional boundary

The sole implemented venue remains Pump.fun on Solana mainnet. The paper lifecycle is:
wallet scouting -> independent `continuation-v1` qualification -> shared $500 allocator
-> reservation -> delayed finalized quote/fill -> independent monitoring -> exit ->
settlement -> restart reconciliation. DLMM remains disabled.

Ordinary native-SOL and native-SOL Mayhem curves are supported. Cashback and
non-native quote assets remain fail-closed. The disclosed Mayhem agent wallet cannot
scout or count as independent-demand corroboration. No `continuation-v1` economic
threshold, sizing rule, exit rule, event-cap rule, or portfolio rule changed during
this work.

## Point-in-time history boundary

The complete 60-second pool-history problem remains solved by one finalized
Pump-program `logsSubscribe` stream with a bounded in-memory tape. A full uninterrupted
60-second warmup is required before any scout trade gains nomination authority.
Disconnect, parse loss, capacity loss, or time inconsistency removes coverage and
requires fail-closed recovery. The stream has observation authority only.

Previous exact live proof produced two natural post-warmup nominations with complete
60-second windows containing 14 and 109 decoded Pump trades. That established history
coverage without weakening the 60-second requirement. The 109-event candidate also
shows a possible later `evidence_capacity` boundary (>100 events); do not alter that
cap unless it becomes the actual next blocker.

## Concentration retrieval repair

The public RPC's `getTokenLargestAccounts` method repeatedly returned HTTP 429 during
natural stream-covered candidate evaluation. A first attempt to use a separate free
PublicNode endpoint was rejected after hosted CI received HTTP 403 during mainnet
verification. It is therefore not a default dependency and no paid or credentialed
provider was added.

The current concentration path instead stays on the already-authorized primary RPC
and first uses one compact finalized `getProgramAccounts` scan against the mint's token
program:

- mint memcmp filter at token-account offset 0;
- `dataSlice` of only the 8-byte token amount at offset 64;
- `withContext=true`, `commitment=finalized`, and `minContextSlot` tied to the
  candidate snapshot;
- curve custody excluded exactly as before;
- top five remaining account balances divided by the same validated actual mint
  supply;
- stale/invalid/wrong-network evidence fails closed;
- original `getTokenLargestAccounts` remains a fallback.

This changes only how the existing concentration input is retrieved. The <=35%
`continuation-v1` threshold is unchanged.

## Live concentration proof

A one-mint, no-order-authority probe was run on naturally nominated Mayhem mint
`DnRCpeTggn8qp5w42Kv82agMTS5tD3p9B1GhNdEApump` in workflow `35169426338` on code
containing the same concentration implementation.

The compact program scan succeeded:

- source: `program_scan`;
- snapshot slot: `447666436`;
- concentration slot: `447666440` (fresh, four slots later);
- measured probe-time concentration: `5002` bps;
- program-scan RPC: 2 requests total (network verification + account scan), 0
  failures, 0 retries;
- primary snapshot path: 3 requests, 0 failures, 0 retries;
- provider spend: $0; infrastructure spend: $0;
- orders=0, positions=0, paper trades=0.

The `5002` bps value is **only the concentration at this later probe time**. It must not
be retroactively applied to the earlier nomination and is not a strategy result.

The temporary automatic probe workflow job was removed after establishing this proof;
`tests/concentration_live_probe.py` remains available for explicit diagnostics.

## Exact current verification

Final code-bearing SHA `e1153a9617931c5be4bc6a39e39a7ad02d115ff3` passed:

- **62/62 deterministic tests**;
- bounded synthetic workload: 2,000 frames / 240,000 submitted events;
- SQLite DB: 1,261,568 bytes;
- WAL: 708,672 bytes;
- peak RSS: 26,412 KiB;
- synthetic connected entry -> monitoring -> exit -> settlement.

Its final live diagnostic also stayed healthy for the full bounded stream session:
60-second coverage was reached, final warm duration was 170 seconds, with 0 stream
gaps, 0 parse failures, 0 capacity losses, 70,600 Pump notifications and 8,148
decoded trades. No admitted scout happened to nominate during that particular run, so
it did not re-exercise concentration prospectively. There were 0 HTTP failures and no
orders, positions, or paper trades.

## Current evidence boundary

The **concentration retrieval mechanism is now technically proven live, read-only,
bounded, and free on the same public RPC**. The remaining prospective proof is not
another concentration redesign: wait for a naturally nominated, stream-covered
candidate to use this path, obtain a final snapshot, and reach unchanged
`Engine.qualify`.

When that occurs, report the exact `continuation-v1` result. If it is `concentration`,
`independent_demand`, `extended_price`, `roundtrip_cost`, `evidence_capacity`, or
another declared rule, preserve that result. Do not change thresholds or the >100-event
cap merely to force a qualification.

A shadow `qualified` result would still not be a paper trade. Actual market-driven
entry -> monitoring -> exit -> settlement still requires durable resumable state; the
CI diagnostic has no order/reservation authority.

## Reproduce

```sh
python -m pip install -r requirements.txt
python -m unittest discover -v
python -m tests.resource_check
python -m tests.make_tape
python -m meme_machine --mode synthetic --config config.synthetic.json --db /tmp/meme-fresh.db --tape tests/fixtures/synthetic_lifecycle.jsonl
```

Bounded finalized-stream shadow qualification:

```sh
python -m tests.prospective_stream_qualification
```

Explicit one-mint read-only concentration diagnostic:

```sh
python -m tests.concentration_live_probe
```
