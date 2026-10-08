"""Bounded allocation evidence derived from realized, attributed ledger samples.

No price prediction or trading signal is invented. Missing/compacted evidence
remains neutral. A score never creates cash, changes a trade size or exits a lot.
"""
from fractions import Fraction

from .model import REGIMES, ZERO, money, ratio_bps, exact


@exact
def _window(samples):
    if not samples:
        return dict(count=0, expectancy_bps=0, return_bps=0, profit_factor_bps=10000,
                    drawdown_bps=0, downside_bps=0, tail_capture_bps=0,
                    efficiency_bps_per_day=0, capital_seconds="0", costs="0", score_bps=0)
    capital = sum((money(s["capital_deployed"]) for s in samples), ZERO)
    pnl = sum((money(s["pnl"]) for s in samples), ZERO)
    seconds = sum((money(s["capital_seconds"]) for s in samples), ZERO)
    wins = sum((max(ZERO, money(s["pnl"])) for s in samples), ZERO)
    losses = -sum((min(ZERO, money(s["pnl"])) for s in samples), ZERO)
    costs = sum((money(s["costs"]) for s in samples), ZERO)
    # Equal-position expectancy, capital-weighted return and capital-time
    # efficiency each answer a different question. Gross trade count/P&L cannot
    # win priority merely through turnover or duration.
    expectancy = sum((Fraction(money(s["pnl"])) / Fraction(money(s["capital_deployed"]))
                      for s in samples), Fraction(0)) / len(samples)
    running = peak = drawdown = ZERO
    for s in samples:
        running += money(s["pnl"])
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
    tail = sum((max(ZERO, money(s["pnl"])) for s in samples
                if ratio_bps(money(s["pnl"]), money(s["capital_deployed"]), limit=1000000) >= 10000), ZERO)
    exp_bps = max(-2000, min(2000, int(expectancy * 10000)))
    ret = ratio_bps(pnl, capital, limit=2000)
    pf = 20000 if wins and not losses else ratio_bps(wins, losses, limit=20000) if losses else 10000
    dd = ratio_bps(drawdown, capital, limit=2000)
    downside = ratio_bps(losses, capital, limit=2000)
    capture = ratio_bps(tail, wins)
    efficiency = ratio_bps(Fraction(pnl) * 86400, seconds, limit=2000)
    # Right-tail contribution is recognized but cannot erase downside/drawdown.
    raw = (2 * exp_bps + ret + (pf - 10000) // 10 + efficiency
           + capture // 20 - 2 * dd - downside) // 6
    return dict(count=len(samples), expectancy_bps=exp_bps, return_bps=ret,
                profit_factor_bps=pf, drawdown_bps=dd, downside_bps=downside,
                tail_capture_bps=capture, efficiency_bps_per_day=efficiency,
                capital_seconds=str(seconds), costs=str(costs),
                score_bps=max(-2500, min(2500, raw)))


@exact
def evidence_score(samples, policy, at):
    long = [s for s in samples if at - policy["reference_seconds"] <= s["at"] <= at]
    recent = [s for s in long if s["at"] >= at - policy["recent_seconds"]]
    reference, short = _window(long), _window(recent)
    count_confidence = Fraction(len(long), len(long) + policy["confidence_trades"])
    observed = Fraction(money(reference["capital_seconds"])) / 86400
    time_confidence = observed / (observed + policy["confidence_capital_days"])
    confidence = min(count_confidence, time_confidence)
    # A short streak cannot dominate the longer window. Inconsistency further
    # shrinks evidence, including a formerly strong lane currently deteriorating.
    inconsistent = bool(short["count"] and reference["score_bps"] * short["score_bps"] < 0)
    if inconsistent:
        confidence /= 2
    raw = (3 * reference["score_bps"] + short["score_bps"]) // 4
    delta = int(raw * confidence)
    multiplier = max(policy["multiplier_min_bps"], min(policy["multiplier_max_bps"], 10000 + delta))
    return dict(multiplier_bps=multiplier, confidence_bps=int(confidence * 10000),
                inconsistent_windows=inconsistent, recent=short, reference=reference)


@exact
def update_budgets(state, at):
    policy, allocation = state["policy"], state["allocation"]
    scores = {r: evidence_score(state["samples"][r], policy, at) for r in REGIMES}
    if not policy["adaptive"]:
        allocation["scores"] = scores
        return
    for r in REGIMES:
        old = allocation["multipliers"][r]
        target = scores[r]["multiplier_bps"]
        if at - allocation["updated_at"][r] < policy["cooldown_seconds"]:
            continue
        if abs(target - old) < policy["hysteresis_bps"]:
            continue
        step = max(-policy["maximum_step_bps"], min(policy["maximum_step_bps"], target - old))
        allocation["multipliers"][r] = old + step
        allocation["updated_at"][r] = at
        allocation["changes"].append(dict(at=at, regime=r, before=old, after=old + step))
        allocation["changes"] = allocation["changes"][-policy["max_samples"]:]
        allocation["change_count"] += 1
    allocation["scores"] = scores


@exact
def request_score(state, request, flow_count, exposures, risk_base):
    r = request["regime"]
    performance = state["allocation"]["multipliers"][r] - 10000 if state["policy"]["adaptive"] else 0
    # Optional native quality is copied from verified qualification; missing data
    # has neutral priority. No requirement or threshold is added to qualification.
    quality = 0 if request["native_quality_bps"] is None else (request["native_quality_bps"] - 5000) // 10
    capacity = min(money(request["liquidity_capacity"]), money(request["execution_capacity"]))
    capacity_score = min(250, max(0, ratio_bps(capacity, money(request["requested_basis"])) // 40))
    flow = min(250, 250 * flow_count // (flow_count + 5))
    concentration = ratio_bps(exposures["regime"][r], risk_base) // 10
    # Expected duration is used only when strategy evidence already supplies it;
    # its small bounded effect cannot overwhelm return per unit capital-time.
    duration = request["expected_holding_seconds"]
    lockup = 0 if duration is None else min(100, duration * 100 // (duration + 86400))
    return 10000 + performance + quality + capacity_score + flow - concentration - lockup
