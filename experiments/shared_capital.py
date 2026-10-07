"""Deterministic controlled economics using the production capital reducer.

python -m experiments.shared_capital --output feature_validation/shared-capital/economics.json

The tapes contain already-qualified native opportunities and after-cost outcomes,
not predictive signals or market acceptance. No parameter fitting occurs here.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import statistics
import tempfile

from meme_machine.exact_money import exact
from meme_machine.shared_capital import CapitalAuthority, CapitalError, REGIMES, RiskPolicy
from meme_machine.shared_capital.authority import capital_view, risk_view, _size_equity
from meme_machine.shared_capital.model import FAMILIES, ZERO, amount, canonical, digest, money, scaled, wire
from tests.shared_capital_support import Harness

STEP_SECONDS = 86400
MODELS = ("A_HARD_SLEEVES", "B_SHARED_FIXED", "C_SHARED_ADAPTIVE")


class ReducerReplay(CapitalAuthority):
    """Offline speed harness around exactly the production reducer.

    Durability/concurrency are tested separately against real SQLite, including
    process death. This class is never exported as a funding API or imported by
    operational code. A tape has one deterministic event order, no worker races.
    """
    def __init__(self, plan, model="B_SHARED_FIXED"):
        self.current = None; self.operations = {}; self.fault = None; self._replaying = False
        self.model = model
        self.install_migration(plan)

    @contextmanager
    def _transaction(self, *, write):
        yield

    def _read(self):
        return self.current

    @exact
    def _write(self, operation_id, action, at, data):
        event = wire(dict(operation_id=operation_id, action=action, at=at, data=data))
        prior = self.operations.get(operation_id)
        if prior:
            if prior[0] != digest(event): raise CapitalError("conflicting_operation_identity")
            return prior[1]
        self.current, result = self._apply(self.current, event)
        self._reconcile(self.current)
        result = wire(result)
        self.operations[operation_id] = digest(event), result
        return result

    def snapshot(self, *, at=None):
        return dict(ledger=self.current, capital=capital_view(self.current))

    def close(self):
        pass

    def _decision(self, state, request, at):
        decision = super()._decision(state, request, at)
        if self.model != "A_HARD_SLEEVES" or decision["status"] != "RESERVED":
            return decision
        family = FAMILIES[request["regime"]]
        equity = money(state["family_sizing_genesis"][family]) + sum(
            (money(state["realized"][r]) for r in REGIMES if FAMILIES[r] == family), ZERO)
        held = sum((money(p["basis"]) for p in state["positions"].values()
                    if p["status"] == "OPEN" and FAMILIES[p["regime"]] == family), ZERO)
        held += sum((money(h["total"]) for bucket in (state["reservations"], state["commitments"])
                     for h in bucket.values() if FAMILIES[h["regime"]] == family), ZERO)
        if money(decision["total"]) > equity - held:
            return dict(status="QUALIFIED_BUT_CAPITAL_UNAVAILABLE", reason="HARD_SLEEVE_CAPITAL", basis="0", total="0")
        return decision


@dataclass(frozen=True)
class Opportunity:
    uid: str
    slot: int
    regime: str
    asset: str
    outcome_bps: int
    hold_slots: int = 2
    quality_bps: int | None = 5000
    capacity_bps: int = 10000


def scenario(name):
    rows = []
    def offer(slot, r, count, ret, hold=2, quality=5000, capacity=10000, correlated=False):
        for i in range(count):
            uid = f"{name}:{slot}:{r}:{i}"
            asset = f"asset:correlated:{slot}:{i}" if correlated else "asset:" + uid
            rows.append(Opportunity(uid, slot, r, asset, ret, hold, quality, capacity))
    for slot in range(0, 10, 2):
        if name == "one_lane_dominates":
            offer(slot, "pump_current", 50, 800)
        elif name == "leadership_rotates":
            r = "pump_current" if slot < 4 else "pons_survivor" if slot < 8 else "meteora"
            offer(slot, r, 50 if "_" in r else 14, 700, hold=2 if "_" in r else 3)
        elif name == "several_lanes_strong":
            for i, r in enumerate(REGIMES): offer(slot, r, 12, 600 + i * 100)
        elif name == "weak_lane_recovers":
            offer(slot, "pump_current", 30 if slot < 6 else 6, 600)
            offer(slot, "pons_current", 12 if slot < 6 else 50, -800 if slot < 6 else 1600, quality=5000 if slot < 6 else 9000)
        elif name == "small_sample_winning_streak":
            offer(slot, "pump_current", 2 if slot == 0 else 40, 4000 if slot == 0 else -500)
            offer(slot, "pons_survivor", 35, 500)
        elif name == "strong_lane_drawdown":
            offer(slot, "pump_current", 50, 1000 if slot < 4 else -1800)
            offer(slot, "ramses", 8, 350, hold=3)
        elif name == "correlated_arrivals":
            for r in REGIMES: offer(slot, r, 12, 600, correlated=True)
        elif name == "liquidity_constrains_leader":
            offer(slot, "pump_current", 50, 1500, capacity=10000 if slot < 4 else 5000)
            offer(slot, "pons_survivor", 25, 600)
            offer(slot, "meteora", 6, 500, hold=3)
        elif name == "prolonged_idle":
            if slot == 0: offer(slot, "pump_current", 8, 400, hold=1)
            if slot == 8: offer(slot, "pons_survivor", 50, 600)
        elif name == "rare_right_tail":
            for r in REGIMES: offer(slot, r, 2, 250, hold=2 if "_" in r else 4)
            if slot == 0:
                rows.append(Opportunity("rare:winner", slot, "pump_survivor", "asset:rare-winner", 240000, 9))
        else:
            raise ValueError("unknown_scenario")
    return rows


SCENARIOS = ("one_lane_dominates", "leadership_rotates", "several_lanes_strong", "weak_lane_recovers",
             "small_sample_winning_streak", "strong_lane_drawdown", "correlated_arrivals",
             "liquidity_constrains_leader", "prolonged_idle", "rare_right_tail")


@exact
def run_tape(tape, model, *, sizing_basis="effective_family_equivalence"):
    policy = RiskPolicy(adaptive=model == "C_SHARED_ADAPTIVE", sizing_basis=sizing_basis)
    with tempfile.TemporaryDirectory() as td:
        h = Harness(td, policy)
        h.authority.close(); h.authority = ReducerReplay(h.plan, model)
        state = h.authority.current
        positions = {}; granted = unfunded = 0; requested_sum = ZERO; turnover = ZERO
        utilization = []; stranded = []; nav_history = []; peak_exposure = ZERO; peak_marked_exposure = ZERO
        peak_concentration = peak_asset_concentration = peak_nav_concentration = Fraction(0)
        capital_time = ZERO; cash_time = ZERO; allocations = []
        lane_granted = {r: 0 for r in REGIMES}; lane_denied = {r: 0 for r in REGIMES}
        failure_reasons = {}
        end = max(o.slot + o.hold_slots for o in tape) + 1
        for slot in range(end + 1):
            h.at = slot * STEP_SECONDS
            for life, (op, q) in list(positions.items()):
                p = state["positions"][life]
                if slot >= op.slot + op.hold_slots:
                    proceeds = scaled(money(p["basis"]), 10000 + op.outcome_bps)
                    h.realize(q.regime, life, amount(proceeds), included_cost=amount(scaled(money(p["basis"]), 10)))
                    turnover += proceeds
                    del positions[life]
                else:
                    progress = (slot - op.slot) * op.outcome_bps // op.hold_slots
                    h.mark(q.regime, life, amount(scaled(money(p["basis"]), 10000 + progress)))
            opportunities = [o for o in tape if o.slot == slot]
            round_id = "economic-round:" + str(slot)
            h.authority.open_round(operation_id="open:" + round_id, round_id=round_id, at=h.at, cutoff=h.at)
            requests = []
            for op in opportunities:
                r = op.regime
                basis = scaled(max(ZERO, _size_equity(state, r)), 500) if "_" in r else money("25")
                capacity = scaled(basis, op.capacity_bps)
                strategy_cap = basis
                requested_sum += basis
                q = h.prepare(r, round_id=round_id, request_id=op.uid, candidate=op.uid, asset=op.asset,
                    requested=amount(basis), liquidity_capacity=amount(capacity), execution_capacity=amount(capacity),
                    strategy_capacity=amount(strategy_cap), native_quality_bps=op.quality_bps,
                    expected_holding_seconds=op.hold_slots * STEP_SECONDS)
                h.authority.submit(q, at=h.at)
                requests.append((op, q))
            h.finish_round(round_id, [q for _, q in requests])
            result = h.authority.allocate(round_id=round_id, at=h.at)
            for op, q in requests:
                d = result["decisions"][q.request_id]
                if d["status"] == "RESERVED":
                    life, _ = h.fill(q, included_cost=amount(scaled(money(d["basis"]), 10)))
                    positions[life] = op, q; granted += 1; lane_granted[q.regime] += 1
                    turnover += money(d["basis"])
                else:
                    unfunded += 1; lane_denied[q.regime] += 1
                    reason = "HARD_SLEEVE_CAPITAL" if model == "A_HARD_SLEEVES" and d["reason"] == "STRATEGY_CAPACITY" else d["reason"]
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            c, risk = capital_view(state), risk_view(state, h.at)
            eq, dep = money(c["realized_equity"]), money(c["deployed_basis"])
            utilization.append(float(Fraction(dep) / Fraction(eq)) if eq else 0)
            nav_history.append(float(risk["marked_equity"]))
            peak_exposure = max(peak_exposure, dep)
            peak_marked_exposure = max(peak_marked_exposure, risk["exposure"]["portfolio"])
            peak_concentration = max(peak_concentration, Fraction(max(risk["exposure"]["regime"].values())) / Fraction(eq) if eq else Fraction(0))
            peak_asset_concentration = max(peak_asset_concentration, Fraction(max(risk["exposure"]["asset"].values(), default=ZERO)) / Fraction(eq) if eq else Fraction(0))
            peak_nav_concentration = max(peak_nav_concentration, Fraction(max(risk["exposure"]["regime"].values())) / Fraction(risk["marked_equity"]) if risk["marked_equity"] else Fraction(0))
            idle_sleeve_cash = ZERO
            if model == "A_HARD_SLEEVES":
                active_families = {FAMILIES[o.regime] for o in opportunities}
                for family in set(FAMILIES.values()) - active_families:
                    family_equity = money(state["family_sizing_genesis"][family]) + sum(
                        (money(state["realized"][r]) for r in REGIMES if FAMILIES[r] == family), ZERO)
                    held = sum((money(p["basis"]) for p in state["positions"].values() if p["status"] == "OPEN" and FAMILIES[p["regime"]] == family), ZERO)
                    idle_sleeve_cash += max(ZERO, family_equity - held)
            stranded.append(float(idle_sleeve_cash))
            if slot < end:
                capital_time += dep * STEP_SECONDS
                cash_time += eq * STEP_SECONDS
            allocations.append(dict(slot=slot, multipliers=deepcopy(state["allocation"]["multipliers"])))
        final = capital_view(state)
        returns = [nav_history[i] / nav_history[i - 1] - 1 for i in range(1, len(nav_history))]
        high = 500.0; drawdown = 0.0
        for nav in nav_history:
            high = max(high, nav); drawdown = max(drawdown, (high - nav) / high)
        average_request = float(Fraction(requested_sum) / len(tape))
        output = dict(model=model, sizing_basis=sizing_basis, opportunities=len(tape), granted=granted,
            qualified_unfunded=unfunded, utilization_pct=round(100 * statistics.mean(utilization), 4),
            stranded_idle_sleeve_usd=round(statistics.mean(stranded), 4),
            realized_return_pct=round(100 * (float(money(final["realized_equity"])) / 500 - 1), 4),
            drawdown_pct=round(drawdown * 100, 4), volatility_pct=round(statistics.pstdev(returns) * 100, 4),
            downside_pct=round((statistics.mean(min(0, r)**2 for r in returns) ** .5) * 100, 4),
            peak_deployed_usd=round(float(peak_exposure), 4), peak_regime_exposure_pct=round(float(peak_concentration) * 100, 4),
            peak_marked_risk_exposure_usd=round(float(peak_marked_exposure), 4),
            peak_asset_exposure_pct=round(float(peak_asset_concentration) * 100, 4),
            peak_regime_exposure_nav_pct=round(float(peak_nav_concentration) * 100, 4),
            turnover_usd=round(float(turnover), 4), capital_time_utilization_pct=round(float(Fraction(capital_time) / Fraction(cash_time)) * 100, 4),
            realized_usd_per_capital_day=round(float(Fraction(money(final["realized_equity"]) - 500) * 86400 / Fraction(capital_time)), 6) if capital_time else 0,
            average_requested_position_usd=round(average_request, 6), allocation_changes=state["allocation"]["change_count"],
            maximum_multiplier_change_bps=max((abs(c["after"] - c["before"]) for c in state["allocation"]["changes"]), default=0),
            lane_realized_pnl={r: float(money(state["realized"][r])) for r in REGIMES},
            lane_costs={r: float(money(state["costs"][r])) for r in REGIMES},
            lane_granted=lane_granted, lane_unfunded=lane_denied, denial_reasons=failure_reasons,
            allocation_path=allocations, conservation=True, terminal_free_cash=final["free_cash"])
        return output


def evaluate():
    results = {}
    for name in SCENARIOS:
        tape = scenario(name)
        models = {model: run_tape(tape, model) for model in MODELS}
        models["B_SHARED_PORTFOLIO_SIZING"] = run_tape(tape, "B_SHARED_FIXED", sizing_basis="shared_realized_equity")
        results[name] = dict(tape_sha256=digest([o.__dict__ for o in tape]), results=models)
    aggregate = {}
    for model in MODELS + ("B_SHARED_PORTFOLIO_SIZING",):
        rows = [results[n]["results"][model] for n in SCENARIOS]
        aggregate[model] = dict(mean_utilization_pct=round(statistics.mean(r["utilization_pct"] for r in rows), 4),
            mean_stranded_idle_sleeve_usd=round(statistics.mean(r["stranded_idle_sleeve_usd"] for r in rows), 4),
            qualified_unfunded=sum(r["qualified_unfunded"] for r in rows), granted=sum(r["granted"] for r in rows),
            mean_realized_return_pct=round(statistics.mean(r["realized_return_pct"] for r in rows), 4),
            worst_drawdown_pct=max(r["drawdown_pct"] for r in rows),
            peak_regime_exposure_pct=max(r["peak_regime_exposure_pct"] for r in rows),
            mean_capital_time_utilization_pct=round(statistics.mean(r["capital_time_utilization_pct"] for r in rows), 4),
            allocation_changes=sum(r["allocation_changes"] for r in rows),
            mean_requested_position_usd=round(statistics.mean(r["average_requested_position_usd"] for r in rows), 6))
    # Conservative predeclared recommendation gate, no scenario parameter fitting.
    fixed, adaptive = aggregate["B_SHARED_FIXED"], aggregate["C_SHARED_ADAPTIVE"]
    improves = adaptive["mean_utilization_pct"] > fixed["mean_utilization_pct"] + 0.5
    improves = improves and adaptive["mean_realized_return_pct"] >= fixed["mean_realized_return_pct"]
    stable = adaptive["worst_drawdown_pct"] <= fixed["worst_drawdown_pct"] + 1
    stable = stable and adaptive["peak_regime_exposure_pct"] <= fixed["peak_regime_exposure_pct"] + 5
    no_starvation = all(not (a["lane_granted"][r] == 0 and b["lane_granted"][r] > 0)
        for name in SCENARIOS for r in REGIMES
        for a, b in [(results[name]["results"]["C_SHARED_ADAPTIVE"], results[name]["results"]["B_SHARED_FIXED"])])
    recommended = "C_SHARED_ADAPTIVE" if improves and stable and no_starvation else "B_SHARED_FIXED"
    return dict(schema="meme-machine-shared-capital-economics-v1", paper_only=True, synthetic=True,
        policy=RiskPolicy().value(), parameters_fitted=False,
        method="Identical qualified tapes and after-cost native outcomes; production reducer; A adds exact $125-family hard funding ceilings to the same risk/execution controls. This controlled capital comparison is not a historical alpha backtest.",
        scenario_results=results, aggregate=aggregate, recommendation=recommended,
        recommendation_gate=dict(utilization_and_return_improve=improves, drawdown_and_concentration_bounded=stable, no_new_lane_starvation=no_starvation),
        default_sizing="effective_family_equivalence", activation_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(dict(aggregate=result["aggregate"], recommendation=result["recommendation"]), indent=2))


if __name__ == "__main__": main()
