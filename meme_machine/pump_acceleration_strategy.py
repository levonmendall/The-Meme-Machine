"""Independent Pump.fun/PumpSwap late-curve acceleration strategy family.

This module is deliberately isolated from continuation-v1 and Engine.qualify.  It
contains only point-in-time feature construction, a frozen paper-policy definition,
qualification for three entry modes, and exit-state decisions.

Shared protocol decoders / market-data transports may feed this module, but no
existing strategy decision, threshold, score, wallet scout, or order can authorize
a decision here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


STRATEGY_ID = "pump-acceleration-independent-v1"
MODE_LATE_CURVE = "late_curve_acceleration"
MODE_POSTGRAD = "post_graduation_momentum"
MODE_SECOND_LEG = "pumpswap_second_leg"


def _clamp(value, low, high):
    return max(low, min(high, value))


def _value_or(value, default):
    """Preserve legitimate zero values; substitute only for missing evidence."""
    return default if value is None else value


def _points(value, low, high, maximum):
    if value <= low:
        return 0
    if value >= high:
        return int(maximum)
    return int((value-low)*maximum//(high-low))


@dataclass(frozen=True)
class FrozenPolicy:
    version: str = STRATEGY_ID + "-profitability-v1"
    entry_fraction_bps: int = 500

    # Late-curve structural gates.
    min_curve_progress_bps: int = 6000
    max_curve_progress_bps: int = 8500
    min_curve_velocity_bps_per_s: int = 10
    min_curve_acceleration_bps_per_s2: int = -10
    min_independent_clusters: int = 20
    min_buyer_growth: int = 4
    min_net_buy_share_bps: int = 5500
    max_concentration_bps: int = 2500
    max_extension_bps: int = 16000
    max_immediate_roundtrip_loss_bps: int = 600
    # Retained as an informational field for stable serialization. The old score
    # was not robustly discriminative and has no entry authority in profitability-v1.
    min_late_curve_score: int = 0

    # Historical confirmation inputs.  These can add score but never authorize
    # a trade on their own.
    wallet_min_history_trades: int = 5
    wallet_min_win_rate_bps: int = 5500
    wallet_min_realized_return_bps: int = 1
    creator_min_history_launches: int = 5

    # Immediate post-graduation momentum gates.
    min_postgrad_age_s: int = 5
    max_postgrad_entry_age_s: int = 180
    min_postgrad_independent_clusters: int = 8
    min_postgrad_buyer_growth: int = 2
    min_postgrad_price_vs_graduation_bps: int = 1
    min_postgrad_volume_acceleration_bps: int = 0
    max_postgrad_concentration_bps: int = 3500
    max_early_holder_sell_share_bps: int = 4000
    min_postgrad_score: int = 0

    # PumpSwap second-leg gates.
    min_second_leg_age_s: int = 30
    min_consolidation_s: int = 10
    min_pullback_depth_bps: int = 100
    max_pullback_depth_bps: int = 3500
    min_breakout_bps: int = 200
    min_second_leg_buyer_growth: int = 2
    min_second_leg_score: int = 0

    # Independent paper exit policy.
    hard_stop_bps: int = -800
    trailing_drawdown_bps: int = 1200
    demand_exit_score: int = 50
    late_curve_max_hold_s: int = 900
    postgrad_max_hold_s: int = 300
    second_leg_max_hold_s: int = 600
    postgrad_confirmation_grace_s: int = 30


POLICY = FrozenPolicy()


def policy_hash(policy=POLICY):
    body=json.dumps(asdict(policy),sort_keys=True,separators=(",",":"))
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass(frozen=True)
class WalletSkillRecord:
    cluster: str
    as_of: int
    total_trades: int
    profitable_trades: int
    realized_return_bps: int
    funding_group: str | None = None
    creator_related: bool = False


@dataclass(frozen=True)
class CreatorQualityRecord:
    creator: str
    as_of: int
    launches: int
    successful_launches: int

    @property
    def quality_bps(self):
        if self.launches <= 0:
            return 0
        return int(self.successful_launches)*10_000//int(self.launches)


@dataclass(frozen=True)
class SignalVector:
    mint: str
    observed_at: int
    surface: str
    phase: str
    quote_asset: str = "SOL"

    curve_progress_bps: int | None = None
    curve_velocity_bps_per_s: int | None = None
    curve_acceleration_bps_per_s2: int | None = None

    independent_buyer_clusters: int = 0
    buyer_growth: int = 0
    net_buy_share_bps: int = 0
    concentration_bps: int = 10_000
    extension_bps: int = 0
    immediate_roundtrip_loss_bps: int | None = None

    skilled_wallet_clusters: int = 0
    creator_quality_bps: int | None = None
    creator_history_launches: int = 0
    quote_relative_return_bps: int = 0

    graduated: bool = False
    seconds_since_graduation: int | None = None
    price_vs_graduation_bps: int | None = None
    volume_acceleration_bps: int | None = None
    early_holder_sell_share_bps: int | None = None

    pullback_depth_bps: int | None = None
    recovery_bps: int | None = None
    consolidation_seconds: int | None = None
    breakout_bps: int | None = None

    point_in_time: bool = True
    future_data_used: bool = False

    def validate(self):
        if not self.mint or self.observed_at < 0:
            raise ValueError("invalid_signal_identity")
        if self.surface not in ("pump.fun","pumpswap"):
            raise ValueError("unsupported_surface")
        if self.phase not in (MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG):
            raise ValueError("unsupported_strategy_phase")
        if not self.point_in_time or self.future_data_used:
            raise ValueError("non_point_in_time_signal")
        for name in ("net_buy_share_bps","concentration_bps"):
            value=int(getattr(self,name))
            if not 0 <= value <= 10_000:
                raise ValueError("invalid_bps")
        if self.early_holder_sell_share_bps is not None and not 0 <= int(self.early_holder_sell_share_bps) <= 10_000:
            raise ValueError("invalid_bps")
        if self.phase == MODE_LATE_CURVE and self.surface != "pump.fun":
            raise ValueError("late_curve_requires_pump_surface")
        if self.phase in (MODE_POSTGRAD,MODE_SECOND_LEG) and self.surface != "pumpswap":
            raise ValueError("postgrad_requires_pumpswap")
        return True


@dataclass(frozen=True)
class Qualification:
    strategy_id: str
    mode: str
    mint: str
    observed_at: int
    qualified: bool
    score: int
    reasons: tuple[str, ...]
    confirmations: tuple[str, ...]
    entry_fraction_bps: int
    policy_hash: str


@dataclass(frozen=True)
class ExitObservation:
    mode: str
    now: int
    opened_at: int
    return_bps: int
    peak_return_bps: int
    demand_score: int
    surface: str
    graduated: bool = False
    seconds_since_graduation: int | None = None
    postgrad_demand_confirmed: bool = False


def relative_return_bps(token_usd_return_bps, quote_usd_return_bps):
    """Return TOKEN/QUOTE performance from two same-window USD returns."""
    token_factor=10_000+int(token_usd_return_bps)
    quote_factor=10_000+int(quote_usd_return_bps)
    if token_factor <= 0 or quote_factor <= 0:
        raise ValueError("invalid_relative_return")
    return token_factor*10_000//quote_factor-10_000


def trajectory_metrics(points):
    """Compute latest curve velocity/acceleration from point-in-time progress samples.

    points: iterable of (unix_second, curve_progress_bps). The final sample is the
    decision-time state. Backward movement is valid signed market evidence: sells can
    reduce bonding-curve progress, yielding negative velocity and an ordinary frozen
    gate rejection rather than an evidence-integrity failure.
    """
    rows=sorted((int(t),int(p)) for t,p in points)
    if len(rows) < 2:
        raise ValueError("insufficient_curve_history")
    if any(t2 <= t1 for (t1,_),(t2,_) in zip(rows,rows[1:])):
        raise ValueError("non_monotonic_curve_time")
    # Progress is deliberately not required to be monotonic. A real sell can move
    # the curve backward; the frozen positive velocity/acceleration gates decide it.
    velocities=[]
    for (t1,p1),(t2,p2) in zip(rows,rows[1:]):
        velocities.append((p2-p1)//(t2-t1))
    latest=velocities[-1]
    acceleration=0
    if len(velocities) >= 2:
        dt=max(1,rows[-1][0]-rows[-2][0])
        acceleration=(velocities[-1]-velocities[-2])//dt
    return dict(
        curve_progress_bps=rows[-1][1],
        curve_velocity_bps_per_s=int(latest),
        curve_acceleration_bps_per_s2=int(acceleration),
        sample_count=len(rows),
        elapsed_seconds=rows[-1][0]-rows[0][0],
    )


def flow_metrics(events, now, cluster_map=None, excluded_clusters=()):
    """Compute independent demand metrics from already authenticated trade events."""
    now=int(now)
    cluster_map=cluster_map or {}
    excluded=set(excluded_clusters)
    accepted=[]
    for event in events:
        try:
            t=int(event["market_time"])
            amount=int(event["amount"])
            wallet=str(event["wallet"])
            buy=bool(event["buy"])
        except (KeyError,TypeError,ValueError):
            continue
        if amount <= 0 or not now-30 <= t <= now:
            continue
        cluster=str(cluster_map.get(wallet,wallet))
        if cluster in excluded:
            continue
        accepted.append((t,cluster,amount,buy))
    recent={c for t,c,_,buy in accepted if buy and now-10 <= t <= now}
    prior={c for t,c,_,buy in accepted if buy and now-30 <= t < now-10}
    buys=sum(a for _,_,a,b in accepted if b)
    sells=sum(a for _,_,a,b in accepted if not b)
    gross=buys+sells
    return dict(
        independent_buyer_clusters=len({c for _,c,_,buy in accepted if buy}),
        buyer_growth=len(recent)-len(prior),
        gross_buy=buys,
        gross_sell=sells,
        net_buy=buys-sells,
        net_buy_share_bps=0 if gross <= 0 else _clamp((buys-sells)*10_000//gross,0,10_000),
    )


def skilled_wallet_convergence(records, observed_at, policy=POLICY):
    """Count independently funded, pre-observation skilled wallet clusters."""
    observed_at=int(observed_at)
    best_by_funding={}
    for row in records:
        if int(row.as_of) > observed_at or row.creator_related:
            continue
        if row.total_trades < policy.wallet_min_history_trades:
            continue
        win_rate=int(row.profitable_trades)*10_000//max(1,int(row.total_trades))
        if win_rate < policy.wallet_min_win_rate_bps:
            continue
        if row.realized_return_bps < policy.wallet_min_realized_return_bps:
            continue
        funding=row.funding_group or row.cluster
        prior=best_by_funding.get(funding)
        rank=(row.realized_return_bps,win_rate,row.total_trades,row.cluster)
        if prior is None or rank > prior[0]:
            best_by_funding[funding]=(rank,row.cluster)
    return len({cluster for _,cluster in best_by_funding.values()})


def creator_confirmation(record, observed_at, policy=POLICY):
    if record is None or record.as_of > int(observed_at):
        return None
    if record.launches < policy.creator_min_history_launches:
        return None
    return record.quality_bps


def _late_score(s):
    """Profitability-v1 ranking.

    Rank broad, expanding independent demand and low concentration most heavily.
    Score remains diagnostic/ranking evidence only; the explicit structural gates
    below retain qualification authority.
    """
    score=0
    score+=_points(int(s.curve_progress_bps or 0),6000,8000,10)
    score+=_points(int(s.curve_velocity_bps_per_s or 0),10,60,10)
    score+=_points(int(s.curve_acceleration_bps_per_s2 or -10),-10,5,5)
    score+=_points(int(s.independent_buyer_clusters),10,30,25)
    score+=_points(int(s.buyer_growth),2,10,25)
    score+=_points(int(s.net_buy_share_bps),5500,8000,5)
    score+=20-_points(int(s.concentration_bps),1000,2500,20)
    score+=_points(int(s.skilled_wallet_clusters),0,3,3)
    if s.creator_quality_bps is not None and s.creator_history_launches >= POLICY.creator_min_history_launches:
        score+=_points(int(s.creator_quality_bps),5000,9000,1)
    score+=_points(int(s.quote_relative_return_bps),0,2000,1)
    return _clamp(score,0,100)


def _postgrad_score(s):
    score=0
    age=int(s.seconds_since_graduation or 0)
    if 5 <= age <= 60:
        score+=5
    score+=_points(int(s.independent_buyer_clusters),4,8,20)
    score+=_points(int(s.buyer_growth),1,5,15)
    score+=_points(int(s.net_buy_share_bps),6000,9000,20)
    score+=_points(int(s.price_vs_graduation_bps or 0),0,3000,15)
    score+=_points(int(s.volume_acceleration_bps or 0),0,5000,10)
    score+=_points(int(s.skilled_wallet_clusters),0,3,8)
    score+=_points(int(s.quote_relative_return_bps),0,2000,5)
    score+=_points(int(s.recovery_bps or 0),0,1500,7)
    score+=10-_points(int(s.early_holder_sell_share_bps or 0),0,3500,10)
    score-=_points(max(0,int(s.early_holder_sell_share_bps or 0)-2000),0,1500,15)
    score-=_points(max(0,int(s.concentration_bps)-2500),0,1000,10)
    return _clamp(score,0,100)


def _second_leg_score(s):
    score=0
    score+=_points(int(s.breakout_bps or 0),500,2500,20)
    score+=_points(int(s.independent_buyer_clusters),4,8,10)
    score+=_points(int(s.buyer_growth),1,5,15)
    score+=_points(int(s.net_buy_share_bps),6000,9000,15)
    score+=_points(int(s.recovery_bps or 0),500,2500,15)
    score+=_points(int(s.quote_relative_return_bps),0,2500,10)
    score+=_points(int(s.skilled_wallet_clusters),0,3,10)
    score+=_points(int(s.consolidation_seconds or 0),20,90,5)
    score+=_points(int(s.price_vs_graduation_bps or 0),0,3000,10)
    pullback_distance=abs(int(s.pullback_depth_bps or 0)-1200)
    score+=10-_points(pullback_distance,0,2300,10)
    score-=_points(max(0,int(s.early_holder_sell_share_bps or 0)-2000),0,1500,10)
    score-=_points(max(0,int(s.concentration_bps)-2500),0,1000,10)
    return _clamp(score,0,100)


def qualify(signal, policy=POLICY):
    signal.validate()
    reasons=[]
    confirmations=[]

    if signal.skilled_wallet_clusters >= 2:
        confirmations.append("skilled_wallet_convergence")
    if (signal.creator_quality_bps is not None and
            signal.creator_history_launches >= policy.creator_min_history_launches):
        confirmations.append("creator_quality")
    if signal.quote_relative_return_bps > 0:
        confirmations.append("quote_relative_strength")

    if signal.phase == MODE_LATE_CURVE:
        progress=int(signal.curve_progress_bps or 0)
        if progress < policy.min_curve_progress_bps:
            reasons.append("curve_not_late")
        if progress > policy.max_curve_progress_bps:
            reasons.append("curve_too_late")
        if int(signal.curve_velocity_bps_per_s or 0) < policy.min_curve_velocity_bps_per_s:
            reasons.append("curve_velocity")
        if int(signal.curve_acceleration_bps_per_s2 or 0) < policy.min_curve_acceleration_bps_per_s2:
            reasons.append("curve_deceleration")
        if signal.independent_buyer_clusters < policy.min_independent_clusters:
            reasons.append("independent_buyers")
        if signal.buyer_growth < policy.min_buyer_growth:
            reasons.append("buyer_growth")
        if signal.net_buy_share_bps < policy.min_net_buy_share_bps:
            reasons.append("net_demand")
        if signal.concentration_bps > policy.max_concentration_bps:
            reasons.append("concentration")
        if signal.extension_bps > policy.max_extension_bps:
            reasons.append("extension")
        if signal.immediate_roundtrip_loss_bps is None:
            reasons.append("executable_downside_unavailable")
        elif int(signal.immediate_roundtrip_loss_bps) > policy.max_immediate_roundtrip_loss_bps:
            reasons.append("executable_downside")
        score=_late_score(signal)
        threshold=policy.min_late_curve_score

    elif signal.phase == MODE_POSTGRAD:
        age=int(_value_or(signal.seconds_since_graduation,-1))
        if not signal.graduated:
            reasons.append("not_graduated")
        if age < policy.min_postgrad_age_s or age > policy.max_postgrad_entry_age_s:
            reasons.append("postgrad_age")
        if signal.independent_buyer_clusters < policy.min_postgrad_independent_clusters:
            reasons.append("independent_buyers")
        if signal.buyer_growth < policy.min_postgrad_buyer_growth:
            reasons.append("buyer_growth")
        if signal.net_buy_share_bps < policy.min_net_buy_share_bps:
            reasons.append("net_demand")
        if int(_value_or(signal.price_vs_graduation_bps,0)) < policy.min_postgrad_price_vs_graduation_bps:
            reasons.append("price_retention")
        if int(_value_or(signal.volume_acceleration_bps,-1)) < policy.min_postgrad_volume_acceleration_bps:
            reasons.append("volume_acceleration")
        if int(_value_or(signal.early_holder_sell_share_bps,10_000)) > policy.max_early_holder_sell_share_bps:
            reasons.append("early_holder_distribution")
        if signal.concentration_bps > policy.max_postgrad_concentration_bps:
            reasons.append("concentration")
        score=_postgrad_score(signal)
        threshold=policy.min_postgrad_score

    else:
        age=int(_value_or(signal.seconds_since_graduation,-1))
        if not signal.graduated:
            reasons.append("not_graduated")
        if age < policy.min_second_leg_age_s:
            reasons.append("second_leg_age")
        if int(_value_or(signal.consolidation_seconds,0)) < policy.min_consolidation_s:
            reasons.append("consolidation")
        pullback=int(_value_or(signal.pullback_depth_bps,0))
        if not policy.min_pullback_depth_bps <= pullback <= policy.max_pullback_depth_bps:
            reasons.append("pullback_shape")
        if int(_value_or(signal.breakout_bps,0)) < policy.min_breakout_bps:
            reasons.append("breakout")
        if signal.independent_buyer_clusters < policy.min_postgrad_independent_clusters:
            reasons.append("independent_buyers")
        if signal.buyer_growth < policy.min_second_leg_buyer_growth:
            reasons.append("buyer_growth")
        if signal.net_buy_share_bps < policy.min_net_buy_share_bps:
            reasons.append("net_demand")
        if int(_value_or(signal.early_holder_sell_share_bps,10_000)) > policy.max_early_holder_sell_share_bps:
            reasons.append("early_holder_distribution")
        if signal.concentration_bps > policy.max_postgrad_concentration_bps:
            reasons.append("concentration")
        score=_second_leg_score(signal)
        threshold=policy.min_second_leg_score

    return Qualification(
        strategy_id=STRATEGY_ID,
        mode=signal.phase,
        mint=signal.mint,
        observed_at=signal.observed_at,
        qualified=not reasons,
        score=int(score),
        reasons=tuple(dict.fromkeys(reasons)),
        confirmations=tuple(confirmations),
        entry_fraction_bps=policy.entry_fraction_bps,
        policy_hash=policy_hash(policy),
    )


def exit_decision(observation, policy=POLICY):
    if observation.mode not in (MODE_LATE_CURVE,MODE_POSTGRAD,MODE_SECOND_LEG):
        raise ValueError("unknown_strategy_mode")
    if observation.surface not in ("pump.fun","pumpswap"):
        raise ValueError("unsupported_surface")
    age=int(observation.now)-int(observation.opened_at)
    if age < 0:
        raise ValueError("time_regression")
    if observation.return_bps <= policy.hard_stop_bps:
        return "risk_stop"
    if (observation.peak_return_bps > 0 and
            observation.peak_return_bps-observation.return_bps >= policy.trailing_drawdown_bps):
        return "trailing_momentum_exit"
    if observation.demand_score < policy.demand_exit_score:
        return "demand_deceleration"

    if observation.mode == MODE_LATE_CURVE:
        if age >= policy.late_curve_max_hold_s:
            return "timeout"
        if observation.graduated:
            seconds=int(observation.seconds_since_graduation or 0)
            if seconds >= policy.postgrad_confirmation_grace_s and not observation.postgrad_demand_confirmed:
                return "graduation_without_continuation"
        return None

    if observation.mode == MODE_POSTGRAD and age >= policy.postgrad_max_hold_s:
        return "timeout"
    if observation.mode == MODE_SECOND_LEG and age >= policy.second_leg_max_hold_s:
        return "timeout"
    return None
