"""Research-only point-in-time DLMM strategy replay.

This module never opens Store state and has no allocation authority. It takes a
verified finalized prestate, applies an ex-ante one-sided SOL distribution, replays
only verified real swaps through the same integer DLMM mechanics used by PR #4,
then withdraws and liquidates the residual token leg back to SOL.

Live mode uses a verified warmup interval to build pre-entry regime features, then
a separate verified outcome interval for counterfactual strategy replay. No outcome
data is available to the strategy selector.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import statistics
import time

from meme_machine import dlmm
from meme_machine.dlmm_paper import CAPITAL, ENTRY_COST, EXIT_COST
from meme_machine.dlmm_tape import (VerifiedTape,apply_external_adjustment,ordered_tape_actions,replay_swap_event)
from meme_machine.postgrad import PoolScanRPC
from meme_machine.provider import Unavailable
from meme_machine.store import digest
from tests import dlmm_alchemy_provider as alchemy_provider

KNOWN_POOLS = (
    "Cqc2v6yhK5NBgmhNoYBFYmUA5WR1UriYANa3wf7ijN7C",
    "J8a3ZKcDZA8HSinuCyjJggU8hnDgwkZKmwH8qDZ9nUcY",
)
DISCOVERY_STEPS = (10, 25, 50)
WIDTHS = (2, 4, 8, 16, 32)
STRATEGIES = ("foundation_spot", "sdk_bidask")
MAX_POOLS = 4
MAX_CYCLES = 3
MAX_WINDOW_SECONDS = 20
REPORT = Path(os.environ.get("MM_DLMM_STRATEGY_REPORT", "dlmm-strategy-report.json"))


def _range_ids(state, width):
    # The legacy shadow grid remains WIDTHS=(2,4,8,16,32), but the economic
    # research candidate may choose any integer width in the same bounded envelope
    # so equivalent price-distance placements can be compared across different
    # bin_step pools.
    if type(width) is not int or not 2 <= width <= max(WIDTHS):
        raise ValueError("dlmm_research_width")
    sol_y = state["y"] == dlmm.WSOL
    active = state["active"]
    ids = list(range(active - width, active)) if sol_y else list(range(active + 1, active + width + 1))
    if any(str(bid) not in state["bins"] for bid in ids):
        raise Unavailable("dlmm_research_missing_range_bin")
    return ids


def _foundation_spot_amounts(state, ids, capital=CAPITAL):
    """Exact generalized form of PR #4's verified SpotOneSide test placement."""
    sol_y = state["y"] == dlmm.WSOL
    weights = [
        dlmm.Q if sol_y else dlmm.Q * dlmm.Q // dlmm.price(bid, state["step"])
        for bid in ids
    ]
    total = sum(weights)
    if total <= 0:
        raise ValueError("dlmm_research_weight")
    amounts = [capital * w // total for w in weights]
    return amounts, capital - sum(amounts)


def _bidask_bps(active, ids):
    """Pinned SDK calculateBidAskDistribution semantics for one-sided ranges."""
    if not ids:
        raise ValueError("dlmm_research_empty_range")
    smallest, largest = min(ids), max(ids)
    if smallest <= active <= largest:
        raise ValueError("dlmm_research_bidask_requires_one_side")
    mean = smallest if active < smallest else largest
    std = (largest - smallest) / 4
    variance = max(std * std, 1.0)
    # The gaussian normalization constant cancels after inverse-pdf normalization.
    raw = [math.exp(((bid - mean) ** 2) / (2 * variance)) for bid in ids]
    total = sum(raw)
    bps = [int(v / total * 10_000) for v in raw]
    loss = 10_000 - sum(bps)
    # Pinned helper assigns precision loss to the farthest bin.
    bps[-1 if active < smallest else 0] += loss
    if min(bps) < 0 or sum(bps) != 10_000:
        raise ValueError("dlmm_research_bidask_bps")
    return bps


def _sdk_bidask_amounts(state, ids, capital=CAPITAL):
    bps = _bidask_bps(state["active"], ids)
    amounts = [capital * b // 10_000 for b in bps]
    return amounts, capital - sum(amounts)


def _deposit(state, strategy, width, capital=CAPITAL):
    ids = _range_ids(state, width)
    if strategy == "foundation_spot":
        amounts, idle = _foundation_spot_amounts(state, ids, capital)
    elif strategy == "sdk_bidask":
        amounts, idle = _sdk_bidask_amounts(state, ids, capital)
    else:
        raise ValueError("dlmm_research_strategy")
    v = deepcopy(state)
    sol_y = state["y"] == dlmm.WSOL
    shares, fee_start = {}, {}
    for bid, amount in zip(ids, amounts):
        b = v["bins"][str(bid)]
        if b["x" if sol_y else "y"]:
            raise Unavailable("dlmm_research_non_sol_side_composition")
        x, y = (0, amount) if sol_y else (amount, 0)
        share = dlmm.deposit_share(b, x, y)
        if share <= 0 or share + b["supply"] > dlmm.U128:
            raise Unavailable("dlmm_research_invalid_share")
        shares[str(bid)] = share
        fee_start[str(bid)] = {"x": b["fee_x"], "y": b["fee_y"]}
        b["x"] += x
        b["y"] += y
        b["supply"] += share
    return dict(
        strategy=strategy,
        width=width,
        lower=min(ids),
        upper=max(ids),
        shares=shares,
        fee_start=fee_start,
        virtual=v,
        idle_sol=idle,
        entry_active=state["active"],
        entry_slot=state["slot"],
        entry_time=state["time"],
    )


def _replay(position, tape):
    if not isinstance(tape, VerifiedTape):
        raise TypeError("dlmm_research_verified_tape_required")
    v = deepcopy(position["virtual"])
    for kind,item in ordered_tape_actions(tape):
        if kind=="swap":
            v,_ = replay_swap_event(v,item)
        else:
            v = apply_external_adjustment(v,item,counterfactual=True)
        v["slot"] = item["cursor"][0]
    v["slot"] = tape.terminal["slot"]
    v["time"] = tape.terminal["time"]
    position = deepcopy(position)
    position["virtual"] = v
    return position


def _withdraw(position):
    state = deepcopy(position["virtual"])
    assets = {"x": 0, "y": 0, "fee_x": 0, "fee_y": 0}
    for bid, share in position["shares"].items():
        b = state["bins"][bid]
        x = dlmm.withdraw_amount(share, b["x"], b["supply"])
        y = dlmm.withdraw_amount(share, b["y"], b["supply"])
        start = position["fee_start"][bid]
        fx = dlmm.claim_fee(share, b["fee_x"] - start["x"])
        fy = dlmm.claim_fee(share, b["fee_y"] - start["y"])
        assets["x"] += x
        assets["y"] += y
        assets["fee_x"] += fx
        assets["fee_y"] += fy
        b["x"] -= x
        b["y"] -= y
        b["supply"] -= share
    return state, assets


def _liquidation_value(state, token_amount, sol_side, timestamp):
    if token_amount <= 0:
        return 0
    _, quote = dlmm.swap(state, token_amount, sol_side == "y", timestamp)
    return quote["output"]


def evaluate(start, tape, strategy, width, capital=CAPITAL):
    """Counterfactual after-cost return; strategy and range are fixed before tape."""
    if tape.start_hash != digest(start):
        raise Unavailable("dlmm_research_tape_start_mismatch")
    position = _replay(_deposit(start, strategy, width, capital), tape)
    state, assets = _withdraw(position)
    sol_side = "x" if start["x"] == dlmm.WSOL else "y"
    token_side = "y" if sol_side == "x" else "x"
    sol = assets[sol_side] + assets["fee_" + sol_side] + position["idle_sol"]
    tokens = assets[token_side] + assets["fee_" + token_side]
    base_tokens = assets[token_side]
    try:
        full_liq = _liquidation_value(deepcopy(state), tokens, sol_side, tape.terminal["time"])
        base_liq = _liquidation_value(deepcopy(state), base_tokens, sol_side, tape.terminal["time"])
    except (Unavailable, ValueError) as exc:
        return dict(
            strategy=strategy, width=width, resolved=False, reason=str(exc),
            entry_active=position["entry_active"], lower=position["lower"], upper=position["upper"],
        )
    sol += full_liq
    fee_value = assets["fee_" + sol_side] + max(0, full_liq - base_liq)
    costs = ENTRY_COST + EXIT_COST
    pnl = sol - capital - costs
    return dict(
        strategy=strategy,
        width=width,
        resolved=True,
        pnl_lamports=pnl,
        pnl_bps=pnl * 10_000 / capital,
        gross_fee_value_lamports=fee_value,
        fixed_cost_lamports=costs,
        ending_sol_lamports=sol,
        token_liquidation_lamports=full_liq,
        token_inventory=assets[token_side],
        fee_token_inventory=assets["fee_" + token_side],
        fee_sol_inventory=assets["fee_" + sol_side],
        entry_active=position["entry_active"],
        ending_active=position["virtual"]["active"],
        lower=position["lower"],
        upper=position["upper"],
        range_hit=any(
            position["lower"] <= event["observed"]["start"] <= position["upper"]
            or position["lower"] <= event["observed"]["end"] <= position["upper"]
            for event in tape.events
        ),
    )


def _to_sol(state, amount, token, bin_id):
    if amount <= 0:
        return 0
    if token == dlmm.WSOL:
        return amount
    p = dlmm.price(bin_id, state["step"])
    if state["y"] == dlmm.WSOL:
        return amount * p // dlmm.Q
    return amount * dlmm.Q // p


def regime_features(state, tape):
    events = list(tape.events)
    local_liquidity = 0
    for bid, b in state["bins"].items():
        if not b["supply"]:
            continue
        local_liquidity += _to_sol(state, b["x"], state["x"], int(bid))
        local_liquidity += _to_sol(state, b["y"], state["y"], int(bid))
    direction_volume = {True: 0, False: 0}
    total_volume = total_fee = total_travel = 0
    for event in events:
        bid = event["observed"]["start"]
        input_token = state["x"] if event["for_y"] else state["y"]
        volume = _to_sol(state, event["amount"], input_token, bid)
        fee = _to_sol(state, event["observed"]["fee"], input_token, bid)
        direction_volume[event["for_y"]] += volume
        total_volume += volume
        total_fee += fee
        total_travel += abs(event["observed"]["end"] - event["observed"]["start"])
    net_drift = abs(events[-1]["observed"]["end"] - events[0]["observed"]["start"]) if events else 0
    balance = 0.0 if not total_volume else 2 * min(direction_volume.values()) / total_volume
    return dict(
        warmup_swaps=len(events),
        warmup_volume_sol_lamports=total_volume,
        warmup_fee_sol_lamports=total_fee,
        local_liquidity_sol_lamports=local_liquidity,
        turnover_bps=0.0 if not local_liquidity else total_volume * 10_000 / local_liquidity,
        fee_density_bps=0.0 if not local_liquidity else total_fee * 10_000 / local_liquidity,
        direction_balance=balance,
        bin_travel=total_travel,
        net_bin_drift=net_drift,
        drift_ratio=0.0 if not total_travel else net_drift / total_travel,
        current_fee_bps=dlmm.total_fee(state) * 10_000 / dlmm.FEE_PRECISION,
        active_bin=state["active"],
        bin_step=state["step"],
    )


def _summary(results):
    groups = {}
    for row in results:
        groups.setdefault((row["strategy"], row["width"]), []).append(row)
    stats = []
    for (strategy, width), rows in sorted(groups.items()):
        resolved = [r for r in rows if r.get("resolved")]
        pnl = [r["pnl_bps"] for r in resolved]
        stats.append(dict(
            strategy=strategy,
            width=width,
            observations=len(rows),
            resolved=len(resolved),
            mean_pnl_bps=None if not pnl else statistics.fmean(pnl),
            median_pnl_bps=None if not pnl else statistics.median(pnl),
            profitable_rate=None if not pnl else sum(x > 0 for x in pnl) / len(pnl),
            range_hit_rate=None if not resolved else sum(bool(r["range_hit"]) for r in resolved) / len(resolved),
            total_fee_value_lamports=sum(r.get("gross_fee_value_lamports", 0) for r in resolved),
        ))
    ranked = [s for s in stats if s["resolved"]]
    ranked.sort(key=lambda x: (
        x["median_pnl_bps"] if x["median_pnl_bps"] is not None else -1e99,
        x["mean_pnl_bps"] if x["mean_pnl_bps"] is not None else -1e99,
    ), reverse=True)
    return stats, ranked[0] if ranked else None


def _discover(adapter, now):
    addresses = list(KNOWN_POOLS)
    errors = []
    for step in DISCOVERY_STEPS:
        try:
            for address in adapter.pool_addresses(step, now):
                if address not in addresses:
                    addresses.append(address)
                if len(addresses) >= MAX_POOLS:
                    break
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            errors.append(dict(step=step, reason=str(exc)))
        if len(addresses) >= MAX_POOLS:
            break
    states, rejections = {}, []
    for address in addresses[:MAX_POOLS]:
        try:
            snap = adapter.snapshot(address, int(time.time()), True)
            states[address] = dlmm.validate(snap, snap["available_time"], "real")
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            rejections.append(dict(pool=address, reason=str(exc)))
    return states, errors, rejections


def _advance(adapter, states, wait_seconds):
    time.sleep(wait_seconds)
    advanced, tapes, errors = {}, {}, []
    for address, start in list(states.items()):
        try:
            end_snapshot = adapter.snapshot(address, int(time.time()), True)
            now = int(time.time())
            tape = adapter.swap_history(
                start,
                [start["slot"], 2**31 - 1, 2**31 - 1],
                end_snapshot=end_snapshot,
                now=now,
                priority=True,
            )
            advanced[address] = tape.terminal
            tapes[address] = tape
        except (Unavailable, ValueError, KeyError, TypeError) as exc:
            errors.append(dict(pool=address, reason=str(exc)))
    return advanced, tapes, errors


def run_live(cycles=MAX_CYCLES, window_seconds=18):
    if not 1 <= cycles <= MAX_CYCLES or not 5 <= window_seconds <= MAX_WINDOW_SECONDS:
        raise ValueError("dlmm_research_live_bounds")
    rpc = PoolScanRPC(alchemy_provider.rpc_url(), limit=240)
    adapter = dlmm.Adapter(rpc)
    states, discovery_errors, discovery_rejections = _discover(adapter, int(time.time()))
    report = dict(
        kind="dlmm_point_in_time_strategy_replay_v1",
        base="pr4_verified_simulator",
        research_rpc_provider=alchemy_provider.PROVIDER_LABEL,
        research_rpc_provider_host=alchemy_provider.ALCHEMY_SOLANA_MAINNET_HOST,
        research_rpc_fallback_allowed=False,
        allocation_authority=False,
        prospective_allocation_enabled=False,
        capital_lamports=CAPITAL,
        fixed_cost_lamports=ENTRY_COST + EXIT_COST,
        strategies=list(STRATEGIES),
        widths=list(WIDTHS),
        cycles=cycles,
        window_seconds=window_seconds,
        point_in_time=True,
        selector_uses_outcome_data=False,
        started=int(time.time()),
        discovery_errors=discovery_errors,
        discovery_rejections=discovery_rejections,
        initial_pools=sorted(states),
        opportunities=[],
        results=[],
        interval_errors=[],
    )
    for cycle in range(cycles):
        mid_states, warmups, warm_errors = _advance(adapter, states, window_seconds)
        report["interval_errors"].extend(dict(cycle=cycle, phase="warmup", **e) for e in warm_errors)
        end_states, outcomes, out_errors = _advance(adapter, mid_states, window_seconds)
        report["interval_errors"].extend(dict(cycle=cycle, phase="outcome", **e) for e in out_errors)
        for address in sorted(set(warmups) & set(outcomes)):
            warm = warmups[address]
            outcome = outcomes[address]
            entry = mid_states[address]
            features = regime_features(states[address], warm)
            report["opportunities"].append(dict(
                cycle=cycle,
                pool=address,
                warmup_start_slot=states[address]["slot"],
                entry_slot=entry["slot"],
                end_slot=end_states[address]["slot"],
                warmup_lineage=warm.lineage,
                outcome_lineage=outcome.lineage,
                outcome_swaps=len(outcome.events),
                features=features,
            ))
            for strategy in STRATEGIES:
                for width in WIDTHS:
                    try:
                        result = evaluate(entry, outcome, strategy, width)
                    except (Unavailable, ValueError, KeyError, TypeError, OverflowError) as exc:
                        result = dict(strategy=strategy, width=width, resolved=False, reason=str(exc))
                    result.update(
                        cycle=cycle,
                        pool=address,
                        entry_slot=entry["slot"],
                        end_slot=end_states[address]["slot"],
                        warmup_swaps=features["warmup_swaps"],
                        outcome_swaps=len(outcome.events),
                        turnover_bps=features["turnover_bps"],
                        fee_density_bps=features["fee_density_bps"],
                        direction_balance=features["direction_balance"],
                        drift_ratio=features["drift_ratio"],
                    )
                    report["results"].append(result)
        states = end_states
        if not states:
            break
    stats, best = _summary(report["results"])
    pools = {o["pool"] for o in report["opportunities"]}
    nonempty = sum(o["outcome_swaps"] > 0 for o in report["opportunities"])
    pilot_adequate = len(report["opportunities"]) >= 8 and len(pools) >= 3 and nonempty >= 4
    repeatability_adequate = len(report["opportunities"]) >= 200 and len(pools) >= 20
    report.update(
        ended=int(time.time()),
        strategy_stats=stats,
        best_observed_variant=best,
        distinct_pools=len(pools),
        opportunity_count=len(report["opportunities"]),
        nonempty_outcome_count=nonempty,
        pilot_sample_adequate=pilot_adequate,
        repeatability_sample_adequate=repeatability_adequate,
        conclusion=(
            "pilot_complete_repeatability_not_established"
            if pilot_adequate
            else "insufficient_point_in_time_sample_for_pilot"
        ),
        rpc_calls=rpc.calls,
        rpc_http_requests=rpc.http_requests,
        rpc_failures=rpc.failures,
        rpc_retries=rpc.retries,
        provider_failure_kinds=rpc.failure_kinds,
    )
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(dict(
        conclusion=report["conclusion"],
        pools=report["distinct_pools"],
        opportunities=report["opportunity_count"],
        nonempty_outcomes=report["nonempty_outcome_count"],
        best=best,
        rpc_failures=rpc.failures,
    ), sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=MAX_CYCLES)
    parser.add_argument("--window-seconds", type=int, default=18)
    args = parser.parse_args()
    try:
        run_live(args.cycles, args.window_seconds)
    except Exception as exc:
        failure = dict(
            kind="dlmm_point_in_time_strategy_replay_v1",
            allocation_authority=False,
            prospective_allocation_enabled=False,
            conclusion="experiment_failed_before_valid_sample",
            error=str(exc)[:160],
            ended=int(time.time()),
        )
        REPORT.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n")
        print(json.dumps(failure, sort_keys=True))
        raise


if __name__ == "__main__":
    main()
