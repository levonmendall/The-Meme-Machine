# Pump finalized-log authority repair — 2026-09-24

## Scope

This repair changes PumpSwap trade-history evidence provenance only. It does not change
the Pump profitability strategy, policy hash, qualification thresholds, timing windows,
target market, provider throughput, provider identities, paper accounting, sizing,
exit policy, or paper-only authority.

## Root cause

Run 36020434038 showed healthy finalized Pump discovery with zero stream capacity loss,
but high-activity PumpSwap pools produced hundreds to more than one thousand genuine
target-pool trades in a 30-second decision window. The existing path attempted to
hydrate immutable transaction bodies for those signatures inside a four-second
decision deadline. Under the frozen shared Solana provider envelope that cannot
complete for the hottest pools, creating preventable
`incomplete_pumpswap_decision_window` classifications.

## Repair

A complete finalized candidate-pool PumpSwap `logsSubscribe` notification may now be
authoritative only for the exact TradeEvent fields emitted by the PumpSwap program:

- pool
- wallet
- buy/sell side
- quote amount
- base-token amount
- event market time
- pool base reserve
- pool quote reserve
- user quote amount
- slot
- event index

The evidence record retains signature and a SHA-256 digest of the complete finalized
log payload.

The path remains fail-closed. It requires immutable transaction-body hydration when
logs are missing, empty, truncated, malformed, contain unsupported PumpSwap program
data, or when any required evidence is not present in the program event. A stream gap
still invalidates current-window completeness until a fresh covered window exists.

No finalized log is used as authority for holder concentration, account state,
execution quotes, fill evidence, settlement, or any other evidence not emitted by the
PumpSwap TradeEvent.

## Proof

Focused diagnostic run: 36031835261

- captured finalized-log/body parity: 5/5 PASS
- focused Pump history/broker regressions: 41/41 PASS
- exact recomposed Pump diff:
  00b774af7ce78d1627e235adbe61ed1c4521b19aa0a45972bb38c2bc1ef9cd4f

The captured parity fixture is derived from retained run 36020434038 smoke evidence
and verifies exact equality of the strategy-relevant TradeEvent vector.

A new prospective cohort identity is frozen because evidence provenance changed:

`prospective-four-lane-v9-pump-finalized-log-authority-20260924`

No market run is authorized or dispatched by this repair.
