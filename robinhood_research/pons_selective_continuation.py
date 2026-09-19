"""Frozen Robinhood-native Pons selective continuation research policy.

This policy is intentionally separate from continuation-v1-robinhood.  It studies
late-curve acceleration, independent demand, an optional point-in-time skilled-wallet
overlay, an authenticated Pons V2 -> Uniswap V4 continuation gate, asymmetric exits,
and a separate post-graduation breakout research signal.

All functions are deterministic and outcome-blind.  No signer or live-money authority.
"""
from __future__ import annotations

from collections import defaultdict

from . import BoundaryError
from .evidence import digest

POLICY = "pons-selective-continuation-v1"
ZERO = "0x0000000000000000000000000000000000000000"

ENTRY_THRESHOLDS = dict(
    min_curve_progress_bps=5500,
    max_curve_progress_bps=9200,
    max_token_age_seconds=900,
    max_graduation_eta_seconds=120,
    min_progress_15s_bps=800,
    min_independent_groups=5,
    min_new_independent_groups_15s=3,
    min_buy_sell_ratio_bps=20_000,
    max_largest_buyer_flow_bps=2500,
    max_top3_buyer_flow_bps=5500,
    max_creator_tax_bps=200,
    max_roundtrip_loss_bps=500,
    max_entry_impact_bps=300,
    capital_size_bps=25,          # 0.25% of strategy capital
    real_quote_size_bps=200,      # 2% of real quote liquidity
    independent_net_size_bps=1000,# 10% of independent net demand
    max_state_age_seconds=5,
    max_market_events=512,
)
POST_GRAD_THRESHOLDS = dict(
    min_observation_seconds=5,
    max_observation_seconds=30,
    min_price_retention_bps=9200,
    min_new_independent_buyers=3,
    min_buy_sell_ratio_bps=15_000,
    max_preholder_sell_share_bps=5000,
)
EXIT_POLICY = dict(
    risk_bps=-1000,
    first_profit_bps=2500,
    first_profit_sell_bps=5000,
    runner_trailing_drawdown_bps=1100,
    no_new_high_seconds=180,
    entry_delay_seconds=2,
    monitor_seconds=5,
    max_pregraduation_thesis_seconds=180,
)
BREAKOUT_THRESHOLDS = dict(
    allocation_authority=False,
    min_seconds_after_graduation=30,
    max_seconds_after_graduation=900,
    min_pullback_bps=500,
    min_new_independent_buyers_15s=3,
    min_buy_sell_ratio_bps=15_000,
)

POLICY_HASH = digest(dict(
    policy=POLICY,
    entry=ENTRY_THRESHOLDS,
    post_graduation=POST_GRAD_THRESHOLDS,
    exits=EXIT_POLICY,
    breakout=BREAKOUT_THRESHOLDS,
))


def _ceildiv(a, b):
    if b <= 0:
        raise BoundaryError("invalid_policy_denominator")
    return -(-a // b)


def curve_progress_bps(real_quote, graduation_threshold):
    real_quote = int(real_quote)
    graduation_threshold = int(graduation_threshold)
    if real_quote < 0 or graduation_threshold <= 0:
        raise BoundaryError("invalid_graduation_progress")
    return min(10_000, real_quote * 10_000 // graduation_threshold)


def _anchor(snapshots, target_at):
    rows = [
        row for row in snapshots
        if int(row["at"]) <= int(target_at)
    ]
    if not rows:
        return None
    return max(rows, key=lambda row: int(row["at"]))


def trajectory_metrics(snapshots, asof):
    """Measure progress/velocity/acceleration only from frozen prior snapshots."""
    rows = sorted(
        (dict(at=int(r["at"]), progress_bps=int(r["progress_bps"])) for r in snapshots),
        key=lambda r: r["at"],
    )
    if not rows or rows[-1]["at"] > int(asof):
        raise BoundaryError("invalid_trajectory_time")
    current = _anchor(rows, asof)
    p5 = _anchor(rows, int(asof) - 5)
    p15 = _anchor(rows, int(asof) - 15)
    if current is None or p5 is None or p15 is None:
        return dict(complete=False, reason="trajectory_history_incomplete")

    dt5 = current["at"] - p5["at"]
    dt10 = p5["at"] - p15["at"]
    if dt5 <= 0 or dt10 <= 0:
        return dict(complete=False, reason="trajectory_interval_incomplete")
    d5 = current["progress_bps"] - p5["progress_bps"]
    d10 = p5["progress_bps"] - p15["progress_bps"]
    progress15 = current["progress_bps"] - p15["progress_bps"]
    # Compare bps/second without float rounding.
    accelerating = d5 * dt10 > d10 * dt5
    velocity_num, velocity_den = d5, dt5
    remaining = max(0, 10_000 - current["progress_bps"])
    eta = None if velocity_num <= 0 else _ceildiv(remaining * velocity_den, velocity_num)
    return dict(
        complete=True,
        current_progress_bps=current["progress_bps"],
        progress_15s_bps=progress15,
        recent_progress_bps=d5,
        recent_seconds=dt5,
        prior_progress_bps=d10,
        prior_seconds=dt10,
        accelerating=accelerating,
        graduation_eta_seconds=eta,
    )


def normalized_trade(decoded, *, identity, event_at, group=None):
    name = decoded["name"]
    args = decoded["args"]
    if name == "CurveBuy":
        actor = str(args["buyer"]).lower()
        recipient = str(args["recipient"]).lower()
        return dict(
            identity=identity, side="buy", quote=int(args["quoteIn"]),
            tokens=int(args["tokensOut"]), event_at=int(event_at),
            actor=actor, recipient=recipient,
            group=str(group or recipient).lower(),
        )
    if name == "CurveSell":
        actor = str(args["seller"]).lower()
        recipient = str(args["recipient"]).lower()
        return dict(
            identity=identity, side="sell", quote=int(args["quoteOut"]),
            tokens=int(args["tokensIn"]), event_at=int(event_at),
            actor=actor, recipient=recipient,
            group=str(group or actor).lower(),
        )
    raise BoundaryError("unsupported_selective_event")


def demand_metrics(events, *, asof, creator_groups=()):
    if len(events) > ENTRY_THRESHOLDS["max_market_events"]:
        raise BoundaryError("selective_event_capacity")
    creator = {str(x).lower() for x in creator_groups if x}
    seen = {}
    valid = []
    for row in events:
        ident = row["identity"]
        body = (
            row["side"], int(row["quote"]), int(row["tokens"]), int(row["event_at"]),
            str(row["actor"]).lower(), str(row["recipient"]).lower(),
            str(row["group"]).lower(),
        )
        if ident in seen:
            if seen[ident] != body:
                raise BoundaryError("conflicting_market_event")
            continue
        seen[ident] = body
        if not int(asof) - 60 <= int(row["event_at"]) <= int(asof):
            raise BoundaryError("invalid_selective_market_window")
        if row["side"] not in ("buy", "sell") or int(row["quote"]) <= 0:
            raise BoundaryError("invalid_selective_trade")
        valid.append(row)

    cutoff15 = int(asof) - 15
    cutoff30 = int(asof) - 30
    groups_before = {
        str(r["group"]).lower() for r in valid
        if int(r["event_at"]) < cutoff15 and r["side"] == "buy"
        and str(r["group"]).lower() not in creator
    }
    independent_buy_flow = defaultdict(int)
    independent_groups = set()
    new_groups_15 = set()
    current_buy = current_sell = prior_buy = prior_sell = 0
    creator_sell = 0
    current_net_by_group = defaultdict(int)

    for row in valid:
        group = str(row["group"]).lower()
        quote = int(row["quote"])
        recent = int(row["event_at"]) >= cutoff15
        if group in creator or str(row["actor"]).lower() in creator:
            if row["side"] == "sell" and recent:
                creator_sell += quote
            continue
        if row["side"] == "buy":
            independent_groups.add(group)
            independent_buy_flow[group] += quote
            if recent and group not in groups_before:
                new_groups_15.add(group)
            if recent:
                current_buy += quote
                current_net_by_group[group] += quote
            elif int(row["event_at"]) >= cutoff30:
                prior_buy += quote
        else:
            if recent:
                current_sell += quote
                current_net_by_group[group] -= quote
            elif int(row["event_at"]) >= cutoff30:
                prior_sell += quote

    total_flow = sum(independent_buy_flow.values())
    ranked = sorted(independent_buy_flow.values(), reverse=True)
    largest = 0 if total_flow == 0 else ranked[0] * 10_000 // total_flow
    top3 = 0 if total_flow == 0 else sum(ranked[:3]) * 10_000 // total_flow
    current_net = current_buy - current_sell
    prior_net = prior_buy - prior_sell
    ratio = (
        100_000 if current_sell == 0 and current_buy > 0
        else 0 if current_buy == 0
        else current_buy * 10_000 // current_sell
    )
    return dict(
        independent_groups=len(independent_groups),
        new_independent_groups_15s=len(new_groups_15),
        independent_group_ids=sorted(independent_groups),
        current_buy_quote=current_buy,
        current_sell_quote=current_sell,
        current_net_quote=current_net,
        prior_net_quote=prior_net,
        buy_sell_ratio_bps=ratio,
        largest_buyer_flow_bps=largest,
        top3_buyer_flow_bps=top3,
        creator_sell_quote_15s=creator_sell,
        current_net_by_group=dict(current_net_by_group),
        recent_buy_groups=sorted(
            group for group,value in current_net_by_group.items() if value > 0
        ),
    )


def wallet_convergence(wallet_histories, recent_buy_groups, *, asof, candidate_related_groups=()):
    """Point-in-time overlay; never grants authority or bypasses the core policy."""
    recent = {str(x).lower() for x in recent_buy_groups}
    related = {str(x).lower() for x in candidate_related_groups}
    skilled = []
    for row in wallet_histories or ():
        group = str(row.get("group", "")).lower()
        if not group or group not in recent or group in related:
            continue
        cutoff = int(row.get("history_asof", -1))
        trades = int(row.get("completed_trades", 0))
        pnl = int(row.get("realized_after_cost_pnl", 0))
        profitable_tokens = int(row.get("profitable_tokens", 0))
        if cutoff > int(asof):
            raise BoundaryError("future_wallet_skill")
        if (
            bool(row.get("complete"))
            and trades >= 20
            and pnl > 0
            and profitable_tokens >= 2
            and not bool(row.get("candidate_related"))
        ):
            skilled.append(group)
    skilled = sorted(set(skilled))
    return dict(
        complete=wallet_histories is not None,
        skilled_independent_groups=skilled,
        convergence_count=len(skilled),
        converged=len(skilled) >= 2,
        qualification_authority=False,
    )


def _buy_price_impact_bps(state, amount):
    amount = int(amount)
    if amount <= 0:
        return None
    before_num = int(state.quote_reserve)
    before_den = int(state.token_reserve)
    quote = state.buy_with_snipe(amount, 0)
    if quote["refund"] or quote["ready_to_graduate"]:
        return None
    after_num = before_num + (quote["spent"] - quote["fee"] - quote["creator_tax"])
    after_den = before_den - quote["tokens_out"]
    if after_den <= 0 or before_num <= 0:
        return None
    # spot(after) / spot(before) - 1
    return max(0, _ceildiv(after_num * before_den * 10_000, after_den * before_num) - 10_000)


def max_size_for_impact(state, upper, max_impact_bps):
    lo, hi, best = 1, int(upper), 0
    if hi <= 0:
        return 0
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            impact = _buy_price_impact_bps(state, mid)
        except BoundaryError:
            impact = None
        if impact is not None and impact <= int(max_impact_bps):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def entry_size(state, *, strategy_capital_quote, independent_net_quote):
    caps = dict(
        capital=int(strategy_capital_quote) * ENTRY_THRESHOLDS["capital_size_bps"] // 10_000,
        real_quote=int(state.real_quote) * ENTRY_THRESHOLDS["real_quote_size_bps"] // 10_000,
        independent_net=max(0, int(independent_net_quote)) * ENTRY_THRESHOLDS["independent_net_size_bps"] // 10_000,
    )
    gross_cap = min(caps.values())
    impact_cap = max_size_for_impact(
        state, gross_cap, ENTRY_THRESHOLDS["max_entry_impact_bps"]
    )
    chosen = min(gross_cap, impact_cap)
    return dict(amount_quote=chosen, caps=caps, impact_cap_quote=impact_cap)


def roundtrip_loss_bps(state, amount_quote, lifecycle_gas_quote):
    try:
        buy = state.buy_with_snipe(int(amount_quote), 0)
        if buy["refund"] or buy["ready_to_graduate"]:
            raise BoundaryError("entry_graduation_boundary")
        sell = state.sell(buy["tokens_out"])
        loss = int(buy["spent"]) + int(lifecycle_gas_quote) - int(sell["quote_out"])
        return max(0, _ceildiv(max(0, loss) * 10_000, int(buy["spent"])))
    except (BoundaryError, ZeroDivisionError):
        return None


def relative_strength_bps(*, token_usd_start, token_usd_now, quote_usd_start, quote_usd_now):
    values = [int(x) for x in (token_usd_start, token_usd_now, quote_usd_start, quote_usd_now)]
    if min(values) <= 0:
        raise BoundaryError("invalid_relative_strength_price")
    token_return = values[1] * 10_000 // values[0] - 10_000
    quote_return = values[3] * 10_000 // values[2] - 10_000
    return token_return - quote_return


def qualification_vector(
    *, state, graduation_threshold, launch_at, snapshots, events,
    creator_groups, current_snipe_bps, lifecycle_gas_quote,
    strategy_capital_quote, asof, evidence_available_at,
    pair_token=ZERO, wallet_histories=None, creator_history=None,
    quote_relative_strength_bps=None,
):
    asof = int(asof)
    available = int(evidence_available_at)
    age = available - int(state.timestamp)
    progress = curve_progress_bps(state.real_quote, graduation_threshold)
    traj = trajectory_metrics(snapshots, asof)
    demand = demand_metrics(events, asof=asof, creator_groups=creator_groups)
    related = set(str(x).lower() for x in creator_groups if x)
    convergence = wallet_convergence(
        wallet_histories,
        demand["recent_buy_groups"],
        asof=asof,
        candidate_related_groups=related,
    )
    size = entry_size(
        state,
        strategy_capital_quote=strategy_capital_quote,
        independent_net_quote=demand["current_net_quote"],
    )
    friction = (
        None if size["amount_quote"] <= 0
        else roundtrip_loss_bps(state, size["amount_quote"], lifecycle_gas_quote)
    )

    rejections = []
    def reject(reason):
        if reason not in rejections:
            rejections.append(reason)

    if age < 0 or age > ENTRY_THRESHOLDS["max_state_age_seconds"]:
        reject("stale_state_after_evidence")
    if state.graduated:
        reject("already_graduated")
    if int(current_snipe_bps) != 0:
        reject("snipe_tax_nonzero")
    if not ENTRY_THRESHOLDS["min_curve_progress_bps"] <= progress <= ENTRY_THRESHOLDS["max_curve_progress_bps"]:
        reject("curve_progress")
    token_age = asof - int(launch_at)
    if token_age < 0 or token_age > ENTRY_THRESHOLDS["max_token_age_seconds"]:
        reject("token_age")
    if not traj.get("complete"):
        reject("trajectory_history")
    else:
        if traj["progress_15s_bps"] < ENTRY_THRESHOLDS["min_progress_15s_bps"]:
            reject("curve_velocity")
        if not traj["accelerating"]:
            reject("curve_acceleration")
        eta = traj["graduation_eta_seconds"]
        if eta is None or eta > ENTRY_THRESHOLDS["max_graduation_eta_seconds"]:
            reject("graduation_eta")
    if demand["independent_groups"] < ENTRY_THRESHOLDS["min_independent_groups"]:
        reject("independent_breadth")
    if demand["new_independent_groups_15s"] < ENTRY_THRESHOLDS["min_new_independent_groups_15s"]:
        reject("buyer_growth")
    if demand["buy_sell_ratio_bps"] < ENTRY_THRESHOLDS["min_buy_sell_ratio_bps"]:
        reject("buy_sell_flow")
    if demand["current_net_quote"] <= 0 or demand["current_net_quote"] <= demand["prior_net_quote"]:
        reject("net_demand_acceleration")
    if demand["largest_buyer_flow_bps"] > ENTRY_THRESHOLDS["max_largest_buyer_flow_bps"]:
        reject("largest_buyer_concentration")
    if demand["top3_buyer_flow_bps"] > ENTRY_THRESHOLDS["max_top3_buyer_flow_bps"]:
        reject("top3_buyer_concentration")
    if demand["creator_sell_quote_15s"] > 0:
        reject("creator_distribution")
    if int(state.creator_tax_bps) > ENTRY_THRESHOLDS["max_creator_tax_bps"]:
        reject("creator_tax")
    if creator_history is not None and bool(creator_history.get("adverse")):
        reject("creator_adverse_history")
    if size["amount_quote"] <= 0:
        reject("position_size_zero")
    if friction is None:
        reject("roundtrip_cost_unavailable")
    elif friction > ENTRY_THRESHOLDS["max_roundtrip_loss_bps"]:
        reject("roundtrip_cost")
    native_quote = str(pair_token).lower() == ZERO
    if not native_quote:
        reject("non_native_quote_allocation_disabled")

    complete = bool(
        traj.get("complete")
        and friction is not None
        and size["amount_quote"] > 0
    )
    return dict(
        policy=POLICY,
        policy_hash=POLICY_HASH,
        authority="frozen_policy_paper",
        qualification_authority=True,
        asof=asof,
        evidence_available_at=available,
        decision_state_age_seconds=age,
        thresholds=dict(ENTRY_THRESHOLDS),
        progress_bps=progress,
        token_age_seconds=token_age,
        trajectory=traj,
        demand=demand,
        wallet_convergence=convergence,
        creator_history=creator_history,
        current_snipe_bps=int(current_snipe_bps),
        proposed_size=size,
        roundtrip_loss_bps=friction,
        pair_token=str(pair_token).lower(),
        quote_relative_strength_bps=quote_relative_strength_bps,
        complete=complete,
        all_rejections=rejections,
        current_threshold_pass=bool(complete and not rejections),
        qualification=("qualified" if complete and not rejections else
                       (rejections[0] if rejections else "incomplete")),
    )


def pregraduation_exit_reason(
    *, elapsed_seconds, frozen_eta_seconds, trajectory, demand,
    after_cost_return_bps, creator_adverse=False,
):
    if int(after_cost_return_bps) <= EXIT_POLICY["risk_bps"]:
        return "risk"
    if creator_adverse or int(demand.get("creator_sell_quote_15s", 0)) > 0:
        return "creator_distribution"
    if trajectory.get("complete"):
        if int(trajectory.get("recent_progress_bps", 0)) <= 0:
            return "momentum_failure"
    if int(demand.get("current_sell_quote", 0)) > int(demand.get("current_buy_quote", 0)):
        return "flow_reversal"
    eta = max(1, int(frozen_eta_seconds or ENTRY_THRESHOLDS["max_graduation_eta_seconds"]))
    deadline = min(EXIT_POLICY["max_pregraduation_thesis_seconds"], eta * 2)
    if int(elapsed_seconds) > deadline:
        return "graduation_thesis_timeout"
    return None


def post_graduation_vector(
    *, observed_seconds, price_retention_bps, new_independent_buyers,
    buy_quote, sell_quote, net_quote, preholder_sell_quote,
    largest_buyer_flow_bps_before, largest_buyer_flow_bps_now,
):
    buy_quote, sell_quote = int(buy_quote), int(sell_quote)
    ratio = (
        100_000 if sell_quote == 0 and buy_quote > 0
        else 0 if buy_quote == 0
        else buy_quote * 10_000 // sell_quote
    )
    total_sell = max(0, sell_quote)
    preholder_share = (
        0 if total_sell == 0 else int(preholder_sell_quote) * 10_000 // total_sell
    )
    rejections = []
    def reject(reason):
        if reason not in rejections:
            rejections.append(reason)
    if not POST_GRAD_THRESHOLDS["min_observation_seconds"] <= int(observed_seconds) <= POST_GRAD_THRESHOLDS["max_observation_seconds"]:
        reject("post_grad_window")
    if int(price_retention_bps) < POST_GRAD_THRESHOLDS["min_price_retention_bps"]:
        reject("price_retention")
    if int(new_independent_buyers) < POST_GRAD_THRESHOLDS["min_new_independent_buyers"]:
        reject("second_wave_breadth")
    if ratio < POST_GRAD_THRESHOLDS["min_buy_sell_ratio_bps"]:
        reject("post_grad_buy_sell_flow")
    if int(net_quote) <= 0:
        reject("post_grad_net_flow")
    if int(largest_buyer_flow_bps_now) > int(largest_buyer_flow_bps_before):
        reject("post_grad_concentration_worsened")
    if preholder_share > POST_GRAD_THRESHOLDS["max_preholder_sell_share_bps"]:
        reject("preholder_sell_pressure")
    return dict(
        policy=POLICY,
        observed_seconds=int(observed_seconds),
        price_retention_bps=int(price_retention_bps),
        new_independent_buyers=int(new_independent_buyers),
        buy_quote=buy_quote,
        sell_quote=sell_quote,
        buy_sell_ratio_bps=ratio,
        net_quote=int(net_quote),
        preholder_sell_share_bps=preholder_share,
        largest_buyer_flow_bps_before=int(largest_buyer_flow_bps_before),
        largest_buyer_flow_bps_now=int(largest_buyer_flow_bps_now),
        continuation_pass=not rejections,
        all_rejections=rejections,
    )


def runner_action(
    *, tokens, partial_taken, after_cost_return_bps, high_water_return_bps,
    seconds_since_high, new_buyer_growth, buy_quote, sell_quote,
):
    tokens = int(tokens)
    current = int(after_cost_return_bps)
    high = max(int(high_water_return_bps), current)
    if tokens <= 0:
        return dict(action="none", reason="no_exposure", exit_tokens=0)
    if current <= EXIT_POLICY["risk_bps"]:
        return dict(action="full_exit", reason="risk", exit_tokens=tokens)
    if not partial_taken and current >= EXIT_POLICY["first_profit_bps"]:
        amount = max(1, tokens * EXIT_POLICY["first_profit_sell_bps"] // 10_000)
        return dict(action="partial_exit", reason="first_profit", exit_tokens=min(tokens, amount))
    if partial_taken:
        current_index = max(1, 10_000 + current)
        high_index = max(current_index, 10_000 + high)
        drawdown = (high_index - current_index) * 10_000 // high_index
        if drawdown >= EXIT_POLICY["runner_trailing_drawdown_bps"]:
            return dict(action="full_exit", reason="runner_trailing_stop", exit_tokens=tokens)
        if int(new_buyer_growth) <= 0 and int(sell_quote) > int(buy_quote):
            return dict(action="full_exit", reason="demand_failure", exit_tokens=tokens)
        if int(seconds_since_high) >= EXIT_POLICY["no_new_high_seconds"]:
            return dict(action="full_exit", reason="runner_time_exit", exit_tokens=tokens)
    return dict(action="hold", reason=None, exit_tokens=0)


def breakout_vector(
    *, seconds_after_graduation, pullback_bps, current_price_index,
    consolidation_high_index, new_independent_buyers_15s,
    buy_quote_15s, sell_quote_15s, previous_buy_quote_15s,
):
    """Separate research-only post-graduation breakout signal; never a re-entry authority."""
    rejections = []
    def reject(reason):
        if reason not in rejections:
            rejections.append(reason)
    if not BREAKOUT_THRESHOLDS["min_seconds_after_graduation"] <= int(seconds_after_graduation) <= BREAKOUT_THRESHOLDS["max_seconds_after_graduation"]:
        reject("breakout_time")
    if int(pullback_bps) < BREAKOUT_THRESHOLDS["min_pullback_bps"]:
        reject("settling_pullback")
    if int(current_price_index) <= int(consolidation_high_index):
        reject("no_breakout")
    if int(new_independent_buyers_15s) < BREAKOUT_THRESHOLDS["min_new_independent_buyers_15s"]:
        reject("breakout_breadth")
    sells = int(sell_quote_15s)
    buys = int(buy_quote_15s)
    ratio = 100_000 if sells == 0 and buys > 0 else (0 if buys == 0 else buys * 10_000 // sells)
    if ratio < BREAKOUT_THRESHOLDS["min_buy_sell_ratio_bps"]:
        reject("breakout_flow")
    if buys <= int(previous_buy_quote_15s):
        reject("breakout_demand_acceleration")
    return dict(
        strategy="pons-post-graduation-breakout-v1",
        allocation_authority=False,
        research_only=True,
        candidate=not rejections,
        all_rejections=rejections,
        buy_sell_ratio_bps=ratio,
    )
