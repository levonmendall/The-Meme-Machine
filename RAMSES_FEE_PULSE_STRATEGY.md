# Ramses Fee Pulse Strategy

## Status

Implemented as a frozen, paper/research-only Robinhood Ramses DLMM strategy family.

Strategy policy: `ramses-fee-pulse-v1`.

The implementation does **not** sign, submit, allocate live money, or grant natural paper allocation authority. The existing Ramses 35-bps hurdle remains unchanged.

## Four-state classifier

Every evaluated pool is classified into exactly one of:

1. `fee_pulse` — neutral short-duration fee harvesting;
2. `anchor_pulse` — explicitly supplied external-reference convergence liquidity;
3. `directional_converter` — explicitly supplied independent directional conversion signal;
4. `no_trade` — fail-closed state when the required evidence is absent or a hurdle fails.

External-price and directional modes require fresh explicit signals. They are never inferred from Ramses flow alone.

## Fee Pulse frozen gates

The initial policy is frozen in `robinhood_research/ramses_strategy.py` and hashed into every decision.

- volume / active-liquidity percentile: >= 80th percentile;
- current fee-rate percentile: >= 70th percentile;
- volume acceleration: >= 2.0x;
- gross / net bin movement (chop): >= 3.0x;
- two-sided flow imbalance: <= 35%;
- estimated fee capture / modeled inventory-risk reserve: >= 1.5x;
- expected after-cost net / modeled costs: >= 2.0x;
- expected return must exceed the unchanged 35-bps cash hurdle;
- paper capital is capped at 10% of active-bin quote liquidity.

Missing cross-pool percentile evidence or missing cost evidence fails closed; the system does not fabricate either input to manufacture a qualification.

## Range construction

Fee Pulse uses an adaptive symmetric range derived only from pre-entry bin movement:

- core width: pre-entry 75th-percentile bin excursion;
- outer width: pre-entry 95th-percentile bin excursion;
- both are capped at three bins for v1;
- 70% of capital is concentrated in the core;
- 30% is placed in the outer buffer when a distinct buffer exists.

The complete proposal, owned paper shares, range, inputs, strategy version, and policy hash are frozen before any forward outcome is evaluated.

`anchor_pulse` and `directional_converter` use one-sided path ranges in the explicitly supplied direction. A directional signal must also identify the intended conversion side (`x` or `y`) so token ordering is never guessed.

## Event-driven management

The controller does not rebalance on a fixed timer.

It returns `hold`, `rebalance`, or `exit` from current bin displacement and economics:

- exit if the opportunity no longer qualifies;
- exit when estimated inventory loss is at least expected remaining fee capture;
- consider rebalance when the active bin reaches the outer quarter of the frozen range or leaves it;
- rebalance only when remaining expected edge exceeds 2x modeled rebalance cost;
- allow at most two rebalances;
- hard maximum holding period: 1,800 seconds.

## P&L attribution

Every evaluated paper position can be decomposed into:

- exact replay-derived LP fee P&L;
- inventory/directional P&L net of the fee component;
- execution/rebalance/unwind costs;
- gross result;
- after-cost result and bps return;
- unresolved inventory when an executable unwind is unavailable.

This prevents directional beta from being mistaken for DLMM fee skill.

## Prospective sample runner

`python -m robinhood_research.ramses_strategy_sample`

The runner uses the existing authenticated Ramses capture/replay path. It classifies from pre-entry state/history only. If the class qualifies, it constructs the strategy range, obtains an executable terminal unwind quote through the governed DLMM RPC, and produces separated paper P&L.

Optional evidence inputs are explicit JSON environment variables:

- `MM_ROBINHOOD_RAMSES_COSTS_JSON`
- `MM_ROBINHOOD_RAMSES_UNIVERSE_FEATURES_JSON`
- `MM_ROBINHOOD_RAMSES_ANCHOR_SIGNAL_JSON`
- `MM_ROBINHOOD_RAMSES_DIRECTIONAL_SIGNAL_JSON`

Absent optional evidence does not weaken the gates; it produces `no_trade` where required.

## Authority boundary

The strategy implementation is research/paper infrastructure only. Natural allocation remains disabled until a prospectively collected cohort demonstrates after-cost edge without threshold changes or hindsight range selection.
