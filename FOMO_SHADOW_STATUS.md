# Inactive Fomo shadow intelligence scaffold

## Purpose

Add a provider-neutral, research-only Fomo intelligence boundary without changing the active Solana strategy, candidate authority, execution, or DLMM state.

This scaffold is intentionally inactive. It is not imported by `meme_machine.engine`, does not nominate tokens, does not alter `continuation-v1`, cannot reserve capital, and cannot enable DLMM.

## Current source adapter

The first adapter is compatible with the currently documented FomoScan v2 token leaderboard surfaces:

- `/v2/leaderboard/tokens/trending`
- `/v2/leaderboard/tokens/most-held`
- `/v2/leaderboard/tokens/graduated`

The vendor documentation was reviewed on 2026-09-17. These endpoints require a keyed API plan. No key is stored in this repository, no plan is purchased, and CI performs zero Fomo/FomoScan network requests.

FomoScan is an independent data product and is not treated as execution authority or as equivalent to FOMO itself. The internal normalized book is deliberately provider-neutral so a different authorized Fomo data source can replace the adapter later.

## Normalized point-in-time evidence

`meme_machine/fomo_shadow.py` normalizes a leaderboard row into:

- Solana mint;
- board (`trending`, `most-held`, or `graduated`);
- rank;
- provider sample timestamp;
- local observation timestamp;
- source identifier.

Malformed token identity, duplicate token rows, future timestamps, unsupported boards, and time regression fail closed. State is bounded to 256 tokens and eight snapshots per board by default.

## Research-only v0 scores

The scaffold publishes two deterministic integer scores from 0-100:

1. `directional_attention_score`
   - trending-rank strength: 60%;
   - most-held rank strength: 20%;
   - improving trending rank: 20%.

2. `dlmm_flow_score`
   - trending-rank strength: 30%;
   - most-held rank strength: 30%;
   - improving trending rank: 20%;
   - presence on the graduated board: 20%.

These are transparent instrumentation weights only. They are **not calibrated**, are not a prediction of return, and have no threshold that can authorize an order or liquidity position. Scores older than 120 seconds are unavailable rather than carried forward.

The eventual purpose of the DLMM score is only to answer whether Fomo attention may justify *further direct Meteora pool research*. Actual DLMM qualification must use direct pool identity, liquidity distribution, fees, volume, volatility, inventory risk, and executable paper economics. DLMM remains disabled in the allocator.

## Provider-spend guard

`FomoScanClient` is read-only but defaults to `enabled=false`. Even with a key supplied by a future task, construction with live polling enabled fails unless `provider_spend_authorized=true` is separately supplied. No environment variable automatically activates it.

This prevents an installed key or later secret from silently creating paid API usage.

## Verification target

Normal CI must prove:

- deterministic leaderboard normalization;
- Solana-only token identity;
- point-in-time/future-data rejection;
- bounded history;
- deterministic directional/DLMM research scores;
- stale scores become unavailable;
- no live client activity without explicit spend authority;
- `meme_machine.engine` has no Fomo dependency;
- allocator still returns `dlmm_disabled`.

No live Fomo ingestion, scoring comparison, strategy change, merge, or deployment is authorized by this scaffold.
