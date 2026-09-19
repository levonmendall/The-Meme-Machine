"""Independent Pump.fun -> PumpSwap directional paper-signal strategy.

pump-alpha-v1 does not import or call continuation-v1, Engine, market-native
priority, Fomo, or DLMM.  Inputs must be point-in-time normalized observations.
Prices are always TOKEN/actual-QUOTE ratios.  This module can emit paper signals but
has no shared allocator, signing, submission, deployment, or live-money authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json
from typing import Iterable, Mapping, Optional

STRATEGY_ID = "pump-alpha-v1"
POLICY = {
    "strategy_id": STRATEGY_ID,
    "revision": 1,
    "curve": {
        "lookback_seconds": 30, "recent_seconds": 10,
        "min_progress_bps": 7000, "max_progress_bps": 9999,
        "min_recent_velocity_bps_per_second": 20,
        "min_acceleration_bps_per_second": 8,
        "min_independent_buyers": 5, "min_buyer_growth": 1,
        "min_net_demand_target_bps": 50,
        "max_concentration_bps": 3500, "max_extension_bps": 12000,
        "max_observation_age_seconds": 5,
    },
    "wallet_confirmation": {
        "min_history_trades": 10, "min_historical_roi_bps": 1,
        "min_skilled_clusters": 2,
        "min_unrelated_buyers_after_skill_entry": 2,
    },
    "creator_confirmation": {
        "min_prior_launches": 5, "min_prior_graduations": 1,
        "min_prior_graduation_rate_bps": 500,
    },
    "postgrad": {
        "min_age_seconds": 3, "max_entry_age_seconds": 120,
        "recent_seconds": 10, "lookback_seconds": 30,
        "min_independent_buyers": 4, "min_buyer_growth": 1,
        "min_net_demand_target_bps": 25,
        "min_price_vs_graduation_bps": 0, "max_pullback_bps": 1200,
        "min_volume_acceleration_bps": 0, "min_buy_size_growth_bps": 0,
        "max_early_holder_sell_share_bps": 3500,
        "max_concentration_bps": 3500, "graduation_carry_grace_seconds": 15,
    },
    "second_leg": {
        "breakout_window_seconds": 5, "min_age_seconds": 35,
        "min_pullback_bps": 1000, "max_pullback_bps": 4000,
        "min_consolidation_seconds": 20, "min_breakout_bps": 150,
        "min_new_independent_buyers": 3,
        "min_net_demand_target_bps": 20,
        "max_early_holder_sell_share_bps": 3500,
    },
    "exit": {"hard_stop_bps": -1000, "trailing_drawdown_bps": 800, "max_hold_seconds": 300},
    "authority": {
        "paper_signal_authority": True, "shared_allocator_authority": False,
        "signing_authority": False, "submission_authority": False,
        "live_money_authority": False, "automatic_strategy_promotion": False,
    },
}
POLICY_HASH = hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def policy_snapshot():
    return json.loads(json.dumps(POLICY))


def _time(e): return int(e.get("market_time", e.get("time", 0)))
def _wallet(e): return str(e.get("wallet") or "")
def _profile(w, profiles): return (profiles or {}).get(w) or {}
def _cluster(e, profiles):
    p = _profile(_wallet(e), profiles)
    return str(e.get("cluster") or p.get("cluster") or _wallet(e))
def _funding(e, profiles):
    p = _profile(_wallet(e), profiles)
    return str(e.get("funding_group") or p.get("funding_group") or "")
def _creator_related(e, profiles):
    p = _profile(_wallet(e), profiles)
    return bool(e.get("creator_related") or p.get("creator_related"))
def _amount(e): return int(e.get("quote_amount", e.get("amount", 0)))
def _price(e):
    q, t = _amount(e), int(e.get("token_amount", e.get("tokens", 0)))
    return None if q <= 0 or t <= 0 else Fraction(q, t)
def _window(events, start, end):
    return sorted((e for e in events if int(start) <= _time(e) <= int(end)),
                  key=lambda e: (_time(e), int(e.get("slot", 0)), int(e.get("index", 0))))
def _ret(start, end): return int((end / start - 1) * 10_000)
def _dd(peak, current): return max(0, int((1 - current / peak) * 10_000))
def _median(values):
    xs = sorted(int(x) for x in values)
    if not xs: return 0
    n = len(xs); return xs[n//2] if n % 2 else (xs[n//2-1] + xs[n//2]) // 2


def _stats(rows, target, profiles=None):
    if int(target) <= 0: raise ValueError("invalid_graduation_quote_target")
    buys, sells, buyer_clusters = [], [], set()
    early = 0
    for e in rows:
        if not _wallet(e) or _creator_related(e, profiles): continue
        a = _amount(e)
        if a <= 0: continue
        if bool(e.get("buy")):
            buys.append(a); buyer_clusters.add(_cluster(e, profiles))
        else:
            sells.append(a)
            if e.get("early_holder"): early += a
    buy, sell = sum(buys), sum(sells); net = buy - sell
    return {
        "independent_buyers": len(buyer_clusters), "buyer_clusters": sorted(buyer_clusters),
        "gross_buy_quote": buy, "gross_sell_quote": sell, "net_demand_quote": net,
        "net_demand_target_bps": net * 10_000 // int(target),
        "median_buy_quote": _median(buys),
        "early_holder_sell_share_bps": 0 if sell <= 0 else early * 10_000 // sell,
    }


def demand_features(events, now, target, profiles=None, lookback=30, recent=10):
    events = list(events)
    full_rows = _window(events, now-lookback, now)
    recent_rows = _window(events, now-recent, now)
    prior_rows = _window(events, now-lookback, now-recent-1)  # disjoint by design
    full, new, old = _stats(full_rows, target, profiles), _stats(recent_rows, target, profiles), _stats(prior_rows, target, profiles)
    growth = new["independent_buyers"] - old["independent_buyers"]
    new_clusters = set(new["buyer_clusters"]) - set(old["buyer_clusters"])
    if old["gross_buy_quote"] <= 0:
        vol_accel = 10_000 if new["gross_buy_quote"] > 0 else 0
    else:
        prior_seconds = max(1, lookback-recent)
        vol_accel = new["gross_buy_quote"]*prior_seconds*10_000//(old["gross_buy_quote"]*recent)-10_000
    if old["median_buy_quote"] <= 0:
        size_growth = 10_000 if new["median_buy_quote"] > 0 else 0
    else:
        size_growth = new["median_buy_quote"]*10_000//old["median_buy_quote"]-10_000
    prices = [p for p in (_price(e) for e in full_rows) if p is not None]
    current = prices[-1] if prices else None
    return {
        "full": full, "recent": new, "prior": old, "buyer_growth": growth,
        "new_recent_buyer_clusters": sorted(new_clusters),
        "volume_acceleration_bps": vol_accel, "buy_size_growth_bps": size_growth,
        "quote_relative_strength_bps": None if not prices else _ret(prices[0], current),
        "extension_bps": None if not prices else _ret(min(prices), current),
        "current_price": current, "peak_price": None if not prices else max(prices),
    }


def curve_trajectory(points, now, lookback=30, recent=10):
    rows = sorted(({"market_time": int(p["market_time"]), "progress_bps": int(p["progress_bps"])}
                   for p in points if now-lookback <= int(p["market_time"]) <= now), key=lambda p:p["market_time"])
    cut = now-recent
    prior, fresh = [p for p in rows if p["market_time"] <= cut], [p for p in rows if p["market_time"] >= cut]
    def slope(xs):
        if len(xs) < 2: return None
        dt = xs[-1]["market_time"]-xs[0]["market_time"]
        return None if dt <= 0 else (xs[-1]["progress_bps"]-xs[0]["progress_bps"])//dt
    pv, rv = slope(prior), slope(fresh)
    return {
        "progress_bps": None if not rows else rows[-1]["progress_bps"],
        "prior_velocity_bps_per_second": pv, "recent_velocity_bps_per_second": rv,
        "acceleration_bps_per_second": None if pv is None or rv is None else rv-pv,
    }


def skilled_wallet_convergence(events, now, wallet_profiles, lookback_seconds=30, policy=POLICY):
    gate, rows = policy["wallet_confirmation"], _window(list(events), now-lookback_seconds, now)
    net, first = {}, {}
    for e in rows:
        if not _wallet(e) or _creator_related(e, wallet_profiles): continue
        p = _profile(_wallet(e), wallet_profiles)
        as_of = int(p.get("as_of", 0)); sample = int(p.get("historical_trades", 0))
        roi = int(p.get("historical_roi_bps", 0)); pnl = int(p.get("historical_net_pnl_quote", 0)); a = _amount(e)
        if not as_of or as_of >= _time(e) or sample < gate["min_history_trades"] or roi < gate["min_historical_roi_bps"] or pnl <= 0 or a <= 0: continue
        group = _funding(e, wallet_profiles) or _cluster(e, wallet_profiles)
        net[group] = net.get(group, 0) + (a if e.get("buy") else -a)
        if e.get("buy"): first[group] = min(first.get(group, _time(e)), _time(e))
    skilled = {g for g,v in net.items() if v > 0 and g in first}
    t0 = min((first[g] for g in skilled), default=None); followers = set()
    if t0 is not None:
        for e in rows:
            if not e.get("buy") or _time(e) <= t0 or _creator_related(e, wallet_profiles): continue
            group = _funding(e, wallet_profiles) or _cluster(e, wallet_profiles)
            if group not in skilled: followers.add(group)
    return {
        "confirmed": len(skilled) >= gate["min_skilled_clusters"] and len(followers) >= gate["min_unrelated_buyers_after_skill_entry"],
        "skilled_clusters": len(skilled), "skilled_cluster_ids": sorted(skilled),
        "first_skilled_entry_time": t0, "unrelated_buyers_after_skilled_entry": len(followers),
        "unrelated_cluster_ids": sorted(followers),
    }


def creator_confirmation(profile, now, policy=POLICY):
    gate, p = policy["creator_confirmation"], profile or {}
    as_of, launches, grads = int(p.get("as_of",0)), int(p.get("prior_launches",0)), int(p.get("prior_graduations",0))
    valid = bool(as_of and as_of < now and launches > 0 and 0 <= grads <= launches)
    rate = grads*10_000//launches if valid else 0
    return {
        "confirmed": valid and launches >= gate["min_prior_launches"] and grads >= gate["min_prior_graduations"] and rate >= gate["min_prior_graduation_rate_bps"],
        "history_valid": valid, "prior_launches": launches if valid else 0,
        "prior_graduations": grads if valid else 0, "prior_graduation_rate_bps": rate,
    }


def _decision(mode, now, quote, reasons, score, features, **extra):
    return {"strategy_id": STRATEGY_ID, "policy_hash": POLICY_HASH, "entry_mode": mode,
            "observed_at": now, "quote_asset": quote, "eligible": not reasons,
            "reasons": reasons, "score_bps": max(0,min(10_000,int(score))), "features": features,
            "paper_signal_authority": True, "shared_allocator_authority": False,
            "live_money_authority": False, **extra}


def evaluate_late_curve(*, curve_points, events, now, graduation_quote_target, concentration_bps,
                        quote_asset="SOL", wallet_profiles=None, creator_profile=None,
                        curve_complete=False, observed_at=None, policy=POLICY):
    c = policy["curve"]; observed_at = now if observed_at is None else int(observed_at)
    curve = curve_trajectory(curve_points, now, c["lookback_seconds"], c["recent_seconds"])
    demand = demand_features(events, now, graduation_quote_target, wallet_profiles, c["lookback_seconds"], c["recent_seconds"])
    wallet = skilled_wallet_convergence(events, now, wallet_profiles, c["lookback_seconds"], policy)
    creator = creator_confirmation(creator_profile, now, policy); reasons=[]; p=curve["progress_bps"]
    if observed_at > now or now-observed_at > c["max_observation_age_seconds"]: reasons.append("stale_or_future_observation")
    if curve_complete: reasons.append("curve_complete")
    if p is None or not c["min_progress_bps"] <= p <= c["max_progress_bps"]: reasons.append("curve_not_late")
    if curve["recent_velocity_bps_per_second"] is None or curve["recent_velocity_bps_per_second"] < c["min_recent_velocity_bps_per_second"]: reasons.append("insufficient_curve_velocity")
    if curve["acceleration_bps_per_second"] is None or curve["acceleration_bps_per_second"] < c["min_acceleration_bps_per_second"]: reasons.append("insufficient_curve_acceleration")
    if demand["full"]["independent_buyers"] < c["min_independent_buyers"]: reasons.append("insufficient_independent_buyers")
    if demand["buyer_growth"] < c["min_buyer_growth"]: reasons.append("buyer_growth_not_positive")
    if demand["full"]["net_demand_target_bps"] < c["min_net_demand_target_bps"]: reasons.append("insufficient_net_demand")
    if concentration_bps > c["max_concentration_bps"]: reasons.append("excess_concentration")
    if demand["extension_bps"] is None or demand["extension_bps"] > c["max_extension_bps"]: reasons.append("excess_extension")
    # Score ranks passers; it never overrides hard gates.
    score = (
        min(1500, max(0, (p or 0)-c["min_progress_bps"]))
        + min(2000, max(0, curve["recent_velocity_bps_per_second"] or 0) * 20)
        + min(1500, max(0, curve["acceleration_bps_per_second"] or 0) * 25)
        + min(1000, demand["full"]["independent_buyers"] * 125)
        + min(1000, max(0, demand["buyer_growth"]) * 250)
        + min(1500, max(0, demand["full"]["net_demand_target_bps"]) * 5)
        + min(750, wallet["skilled_clusters"] * 250)
        + min(500, creator["prior_graduation_rate_bps"] // 4)
        + min(750, max(0, demand["quote_relative_strength_bps"] or 0) // 4)
        - concentration_bps // 4
        - max(0, (demand["extension_bps"] or 0)-4000) // 4
    )
    features={"curve":curve,"demand":demand,"wallet_confirmation":wallet,"creator_confirmation":creator,"concentration_bps":int(concentration_bps),"quote_asset":str(quote_asset)}
    return _decision("late_curve_acceleration", now, str(quote_asset), reasons, score, features,
                     wallet_confirmed=wallet["confirmed"], creator_confirmed=creator["confirmed"])


def evaluate_postgrad_continuation(*, events, now, graduated_at, graduation_price, graduation_quote_target,
                                   concentration_bps, quote_asset="SOL", wallet_profiles=None, policy=POLICY):
    p=policy["postgrad"]; age=now-graduated_at
    d=demand_features(events,now,graduation_quote_target,wallet_profiles,p["lookback_seconds"],p["recent_seconds"])
    cur,peak=d["current_price"],d["peak_price"]; vs=None if cur is None else _ret(graduation_price,cur); pull=None if cur is None or peak is None else _dd(peak,cur); r=[]
    if not p["min_age_seconds"] <= age <= p["max_entry_age_seconds"]: r.append("outside_postgrad_entry_window")
    if d["recent"]["independent_buyers"] < p["min_independent_buyers"]: r.append("insufficient_postgrad_buyers")
    if d["buyer_growth"] < p["min_buyer_growth"]: r.append("postgrad_buyer_growth_not_positive")
    if d["recent"]["net_demand_target_bps"] < p["min_net_demand_target_bps"]: r.append("insufficient_postgrad_net_demand")
    if vs is None or vs < p["min_price_vs_graduation_bps"]: r.append("below_graduation_reference")
    if pull is None or pull > p["max_pullback_bps"]: r.append("postgrad_pullback_too_deep")
    if d["volume_acceleration_bps"] < p["min_volume_acceleration_bps"]: r.append("postgrad_volume_not_accelerating")
    if d["buy_size_growth_bps"] < p["min_buy_size_growth_bps"]: r.append("postgrad_trade_size_not_growing")
    if d["recent"]["early_holder_sell_share_bps"] > p["max_early_holder_sell_share_bps"]: r.append("early_holder_distribution_too_high")
    if concentration_bps > p["max_concentration_bps"]: r.append("excess_concentration")
    score=2500+max(0,d["recent"]["net_demand_target_bps"])*20+max(0,d["volume_acceleration_bps"])//4+max(0,d["buy_size_growth_bps"])//4+max(0,vs or 0)//2-int(pull or 0)//2
    return _decision("postgrad_continuation",now,str(quote_asset),r,score,{"age_seconds":age,"price_vs_graduation_bps":vs,"pullback_bps":pull,"demand":d,"concentration_bps":int(concentration_bps)},graduated_at=int(graduated_at))


def evaluate_second_leg(*, events, now, graduated_at, graduation_quote_target, wallet_profiles=None,
                        quote_asset="SOL", policy=POLICY):
    s=policy["second_leg"]; rows=_window(list(events),graduated_at,now); priced=[(e,_price(e)) for e in rows if _price(e) is not None]
    r=[]; age=now-graduated_at; floor=now-s["breakout_window_seconds"]; pre=[x for x in priced if _time(x[0]) < floor]
    pull=breakout=None; consolidation=0; trough_time=None
    if age < s["min_age_seconds"]: r.append("second_leg_too_early")
    if len(pre) < 4 or not priced: r.append("insufficient_second_leg_price_history")
    else:
        i=max(range(len(pre)),key=lambda j:pre[j][1]); peak=pre[i][1]; after=pre[i+1:]
        if not after: r.append("missing_post_rally_pullback")
        else:
            te,tp=min(after,key=lambda x:x[1]); trough_time=_time(te); pull=_dd(peak,tp)
            cons=[x for x in pre if _time(x[0]) >= trough_time]; consolidation=floor-trough_time
            breakout=_ret(max(p for _,p in cons),priced[-1][1]) if cons else None
            if not s["min_pullback_bps"] <= pull <= s["max_pullback_bps"]: r.append("pullback_outside_second_leg_band")
            if consolidation < s["min_consolidation_seconds"]: r.append("insufficient_consolidation")
            if breakout is None or breakout < s["min_breakout_bps"]: r.append("no_second_leg_breakout")
    recent=_stats(_window(rows,now-10,now),graduation_quote_target,wallet_profiles)
    older={_cluster(e,wallet_profiles) for e in rows if e.get("buy") and _time(e)<now-10 and not _creator_related(e,wallet_profiles)}
    fresh={_cluster(e,wallet_profiles) for e in rows if e.get("buy") and _time(e)>=now-10 and not _creator_related(e,wallet_profiles)}-older
    if len(fresh)<s["min_new_independent_buyers"]: r.append("insufficient_new_second_leg_buyers")
    if recent["net_demand_target_bps"]<s["min_net_demand_target_bps"]: r.append("insufficient_second_leg_net_demand")
    if recent["early_holder_sell_share_bps"]>s["max_early_holder_sell_share_bps"]: r.append("early_holder_distribution_too_high")
    features={"age_seconds":age,"pullback_bps":pull,"consolidation_seconds":consolidation,"breakout_bps":breakout,"new_independent_buyers":len(fresh),"new_buyer_clusters":sorted(fresh),"recent_demand":recent,"trough_time":trough_time}
    return _decision("second_leg_breakout",now,str(quote_asset),r,4000+max(0,breakout or 0)*4+len(fresh)*500+max(0,recent["net_demand_target_bps"])*20,features)


def evaluate_exit(*, events, now, entry_time, entry_price, graduation_quote_target, wallet_profiles=None, policy=POLICY):
    rows=_window(list(events),entry_time,now); prices=[p for p in (_price(e) for e in rows) if p is not None]
    if not prices: return {"exit":True,"reasons":["missing_executable_price"],"return_bps":None,"drawdown_bps":None}
    current,peak=prices[-1],max(prices+[entry_price]); ret,draw=_ret(entry_price,current),_dd(peak,current)
    d=demand_features(rows,now,graduation_quote_target,wallet_profiles,30,10); x=policy["exit"]; r=[]
    if ret<=x["hard_stop_bps"]: r.append("hard_stop")
    if peak>entry_price and draw>=x["trailing_drawdown_bps"]: r.append("trailing_drawdown")
    if now-entry_time>=x["max_hold_seconds"]: r.append("max_hold")
    if d["recent"]["net_demand_quote"]<=0: r.append("net_demand_reversed")
    elif d["buyer_growth"]<=0 and d["volume_acceleration_bps"]<0: r.append("demand_deceleration")
    return {"exit":bool(r),"reasons":r,"return_bps":ret,"drawdown_bps":draw,"features":d}


@dataclass
class PumpAlphaLifecycle:
    mode: str="flat"; entry_mode: Optional[str]=None; entry_time: Optional[int]=None
    graduated_at: Optional[int]=None; last_transition: Optional[str]=None; history: list[dict]=field(default_factory=list)
    def _record(self, at, transition):
        self.last_transition=transition; self.history.append({"at":int(at),"transition":transition,"mode":self.mode}); self.history[:]=self.history[-32:]
    def open_curve(self, decision, at):
        if self.mode!="flat" or not decision.get("eligible") or decision.get("entry_mode")!="late_curve_acceleration": return False
        self.mode="pregrad_open"; self.entry_mode="late_curve_acceleration"; self.entry_time=int(at); self._record(at,"enter_pregrad"); return True
    def graduate(self, at):
        if self.mode!="pregrad_open": return False
        self.mode="graduation_pending"; self.graduated_at=int(at); self._record(at,"canonical_pumpswap_graduation"); return True
    def apply_postgrad(self, decision, at, policy=POLICY):
        if self.mode=="graduation_pending":
            if decision.get("eligible"): self.mode="postgrad_carry"; self._record(at,"hold_through_graduation"); return "hold"
            if self.graduated_at is not None and int(at)-self.graduated_at>=policy["postgrad"]["graduation_carry_grace_seconds"]: self.mode="exit_required"; self._record(at,"exit_failed_postgrad_continuation"); return "exit"
            return "wait"
        if self.mode=="flat" and decision.get("eligible"):
            self.mode="postgrad_open"; self.entry_mode="postgrad_continuation"; self.entry_time=int(at); self.graduated_at=int(decision.get("graduated_at",at)); self._record(at,"enter_postgrad"); return "enter"
        return "none"
    def open_second_leg(self, decision, at):
        if self.mode!="flat" or not decision.get("eligible") or decision.get("entry_mode")!="second_leg_breakout": return False
        self.mode="second_leg_open"; self.entry_mode="second_leg_breakout"; self.entry_time=int(at); self._record(at,"enter_second_leg"); return True
    def apply_exit(self, decision, at):
        if self.mode not in {"pregrad_open","graduation_pending","postgrad_carry","postgrad_open","second_leg_open","exit_required"}: return False
        if self.mode!="exit_required" and not decision.get("exit"): return False
        self.mode="exited"; self._record(at,"exit"); return True
