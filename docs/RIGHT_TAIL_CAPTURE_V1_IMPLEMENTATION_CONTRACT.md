# Right-Tail Capture v1 — implementation contract

This is a post-Stage-E PAPER implementation contract. It is not active trading authority.

## Pump Current trail

Replace the Current Pump fixed-return-point trail with two deterministic states.

Before high-water reaches +100%:

```
high_index = 10000 + high_water_return_bps
current_index = 10000 + current_return_bps
price_drawdown_bps = (high_index-current_index)*10000//high_index
exit if price_drawdown_bps >= 1400
```

At and after high-water +100%:

```
exit if current_return_bps <= high_water_return_bps*6000//10000
```

Do not calculate tail high-water from blended scale-in basis. The reference remains the original entry price/executable reference.

Pons Current and both Survivors keep their existing pre-arm proportional trail semantics, but use the same +100% tail state after arm.

## Same-lifecycle Current tail bridge

Add a durable lifecycle state `tail_bridge`.

A normal Current timeout may transition to it only when the frozen bridge gates in `right-tail-capture-v1.json` all pass. The transition must be append-only and preserve:

- lifecycle ID and original strategy identity;
- original opened_at;
- original entry reference;
- high-water and high timestamp;
- first-realization state;
- deterioration streak;
- held/reserved capital;
- all prior native economic events.

It must not create a second native book position, release/re-reserve capital, sell/rebuy, or grant a second regime simultaneous exposure.

Store `bridge_started_at` and a deterministic absolute deadline equal to original `opened_at + 129600`.

Survivor discovery/observation remains independent. Same-asset allocation must fail closed while Current bridge exposure exists.

## One bounded scale event

Extend the existing staged-winner-scaling machinery with one economic configuration:

- high-water trigger: +100%;
- first realization required;
- confirmation interval: 900 seconds after first trigger crossing;
- current price no more than 15% below original-entry high-water;
- add target: min(250 bps of realized sleeve equity, 50% of original committed basis);
- total original+added committed basis ceiling: 750 bps of realized sleeve equity;
- maximum scale sequence: 1.

All previously frozen scale safety semantics remain mandatory.

The add remains on the same lifecycle and is separately journaled with added quantity/basis/costs. The original-entry reference controls tail high-water. Aggregate economic accounting may use blended/lot basis, but risk state may not.

First realization must precede the scale. Therefore v1 introduces no new post-add partial realization. If a later revision adds one, it must reduce lots pro-rata unless a separately certified deterministic lot rule supersedes this requirement.

## Required failure behavior

- Missing or stale bridge evidence: take the existing Current timeout exit.
- Any safety failure: existing full-exit behavior wins over bridge/scale.
- Scale requalification failure: hold the unchanged original position; do not add.
- Reservation/capacity failure: hold the unchanged original position; do not add.
- Crash after incremental reservation but before native add commit: recover deterministically and either prove the add committed or release only the increment.
- Restart in bridge state: reconstruct the exact bridge deadline and original high-water; never restart the clock.

## Exact deterministic boundary vectors

Tail:
- high +10000, current +6000: exit boundary.
- high +10000, current +6001: no tail exit.
- high +40000 (5x), current +24000 (3.4x): exit boundary.
- high +90000 (10x), current +54000 (6.4x): exit boundary.
- high +240000 (25x), current +144000 (15.4x): exit boundary.
- high +490000 (50x), current +294000 (30.4x): exit boundary.

Pump pre-tail:
- high +5000 means high_index 15000; a 14% price drawdown boundary is current_index 12900, or current return +2900.

Bridge:
- timeout + first realization + high +5000 + every fresh safety gate => transition to tail_bridge.
- identical vector with high +4999 => original timeout exit.
- bridge absolute age 129600 seconds => full exit.
- bridge restart at any intermediate point => same deadline/high-water/state.

Scale:
- high +10000 before 900 seconds => no add.
- high +10000 at/after 900 seconds but >15% below high => no add.
- exact confirmation + fresh requalification + capacity => at most one add.
- duplicate scale event => idempotent/no second add.
- unrealized gain may satisfy the signal but never increases capital authority.

## Certification

Final composition must receive regenerated strategy/runtime identities, focused deterministic tests, shared-sleeve/accounting/restart tests and exact-SHA non-market certification before any PAPER market smoke. A fresh Pump/Pons profitability cohort is mandatory.
