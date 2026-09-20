# Strategy Prospect Admission Audit

Revision: strategy-prospect-admission-v1

## Objective

Keep network observation broad enough for observability while ensuring each lane spends expensive evidence-acquisition and investment-evaluation capacity only on prospects defined by its frozen strategy.

This repair does not change any strategy threshold, freshness/finality rule, paper accounting rule, lifecycle rule, signing authority, or live-money authority. It changes only when a broadly observed market object becomes an investment prospect eligible for expensive strategy evidence.

## Pump

Finding: partially overbroad.

The lane already rejected pre-graduation mints below the frozen curve-progress floor before HTTP work, but every mint crossing that single floor could enter an RPC snapshot/evaluation path even when finalized Pump logs already proved its trajectory or independent demand could not satisfy the strategy.

Repair:
- retain all finalized Pump events for market observability;
- construct a cheap prospect vector from finalized Pump events only;
- apply the same frozen late-curve hard gates that are available in the stream: progress, velocity, buyer breadth, buyer growth, net-buy share, and extension;
- use concentration=0 only as an optimistic admission assumption because holder concentration requires RPC evidence;
- only a stream prospect that can still qualify is admitted to authoritative RPC snapshot and concentration acquisition;
- a screen failure is not permanent: every later fresh event can be reconsidered;
- the stream prospect screen has no order or trade authority.

Post-graduation and second-leg modes remain bounded to authenticated Pump graduations and their existing entry horizons.

## Pons

Finding: materially overbroad.

The selective-continuation cohort discovered every distinct Pons V2 CurveBuy and previously sent it through candidate authentication, trajectory reconstruction, and a 60-second authenticated market window before learning whether the curve was even inside the strategy's late-stage progress band.

Repair:
- retain broad authenticated Pons buy/sell log observation;
- after minimal authenticated current-state acquisition, apply a strategy-static prospect preflight;
- require the curve to be ungraduated, in the frozen progress band, with current snipe tax zero and creator tax inside the frozen ceiling;
- only those prospects proceed to trajectory/header reconstruction and 60-second market-window authentication;
- token age, velocity/ETA, buyer breadth, demand, concentration, friction, sizing and all remaining frozen gates stay in full qualification;
- a current screen failure does not permanently blacklist a curve; a later CurveBuy can be reconsidered.

This changes evidence scheduling, not the Pons strategy.

## Meteora

Finding: correctly strategy-shaped.

Broad Meteora discovery is used to identify SOL-paired DLMM inventory, but investment evaluation already requires:
- exactly one WSOL leg;
- nonblacklisted/mechanically supported pool;
- frozen volume and fee acceleration regime;
- then fresh authenticated swap trigger, exact warmup and economic reconstruction.

No admission behavior is changed.

## Ramses

Finding: correctly strategy-shaped.

The complete factory is enumerated to establish authenticated inventory. Investment state construction and Fee Pulse classification are restricted to a bounded cohort of pools with recent finalized swap activity. Full factory enumeration is therefore observation/inventory, not evaluation of every factory pool as an investment prospect.

No admission behavior is changed.

## Invariants

- Strategy thresholds unchanged.
- Execution-certification restrictiveness remains the previously frozen approximately 5/10 target.
- Broad observability is retained.
- No future data may influence admission.
- No admission screen grants allocation or fill authority.
- Freshness, finality and exact evidence authentication remain unchanged.
- Unsupported mechanics remain fail closed.
- Paper-only accounting and lifecycle reconciliation remain unchanged.
- No validation run is launched by this repair. Validation remains deferred until the Alchemy repairs are finalized.
