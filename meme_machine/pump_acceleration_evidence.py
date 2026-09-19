"""Point-in-time evidence helpers for pump-acceleration-independent-v1.

These transforms are fixed before the first natural prospective outcome.  They do
not change strategy thresholds or scoring; they define how authenticated protocol
state is converted into the already-frozen SignalVector fields.
"""
from __future__ import annotations

import base64
import struct
from fractions import Fraction

from . import pump
from .postgrad import PUMPSWAP_PROGRAM
from .pump_acceleration_strategy import trajectory_metrics


PUMPSWAP_BUY_EVENT=bytes([103,244,82,31,44,245,119,119])
PUMPSWAP_SELL_EVENT=bytes([62,47,55,10,165,3,220,42])


def price_return_bps(first_num, first_den, last_num, last_den):
    values=tuple(int(x) for x in (first_num,first_den,last_num,last_den))
    if min(values) <= 0:
        raise ValueError("invalid_price")
    return values[2]*values[1]*10_000//(values[3]*values[0])-10_000


def curve_progress_bps(initial_real_token_reserves, real_token_reserves):
    initial=int(initial_real_token_reserves)
    real=int(real_token_reserves)
    if initial <= 0 or real < 0 or real > initial:
        raise ValueError("invalid_curve_progress")
    return (initial-real)*10_000//initial


def pump_price_parts_from_event(event):
    quote=int(event.get("virtual_quote_reserves",0))
    token=int(event.get("virtual_token_reserves",0))
    if min(quote,token) <= 0:
        raise ValueError("missing_pump_price_state")
    return quote,token


def pump_price_parts_from_curve(curve):
    if min(int(curve.sol),int(curve.token)) <= 0:
        raise ValueError("invalid_curve_price")
    return int(curve.sol),int(curve.token)


def late_curve_trajectory(creation, events, curve, snapshot_time):
    """Return absolute progress + recent velocity/acceleration + 10s extension.

    Absolute progress uses the exact initial real-token reserve emitted by the
    prospectively observed CreateEvent.  Velocity/acceleration use three distinct
    finalized states from the trailing 30 seconds.  Extension is current TOKEN/quote
    price versus the latest finalized trade at least 10 seconds earlier (or the
    earliest trailing-30s event when the token is younger than 10 seconds).
    """
    initial=int(creation["initial_real_token_reserves"])
    now=int(snapshot_time)
    rows=[]
    for event in events:
        try:
            t=int(event["market_time"])
            real=int(event["real_token_reserves"])
            if not now-30 <= t <= now:
                continue
            progress=curve_progress_bps(initial,real)
            pump_price_parts_from_event(event)
        except (KeyError,TypeError,ValueError):
            continue
        rows.append((t,progress,event))
    latest_progress=curve_progress_bps(initial,int(curve.real_token))
    latest_t=now
    rows.sort(key=lambda row:(row[0],int(row[2].get("slot",0)),int(row[2].get("index",0))))
    # Keep one terminal state per second so zero-duration event bursts cannot create
    # artificial infinite velocity.
    by_time={}
    for t,p,event in rows:
        by_time[t]=(p,event)
    states=[(t,p,event) for t,(p,event) in sorted(by_time.items()) if t < latest_t]
    if len(states) < 2:
        raise ValueError("insufficient_curve_trajectory")
    early=states[0]
    target=(early[0]+latest_t)//2
    middle=min(states[1:],key=lambda row:(abs(row[0]-target),row[0]))
    if middle[0] <= early[0] or middle[0] >= latest_t:
        raise ValueError("insufficient_curve_trajectory")
    trajectory=trajectory_metrics([
        (early[0],early[1]),
        (middle[0],middle[1]),
        (latest_t,latest_progress),
    ])

    baseline_candidates=[row for row in states if row[0] <= latest_t-10]
    baseline=(baseline_candidates[-1] if baseline_candidates else states[0])
    first_num,first_den=pump_price_parts_from_event(baseline[2])
    last_num,last_den=pump_price_parts_from_curve(curve)
    extension=price_return_bps(first_num,first_den,last_num,last_den)
    return dict(
        **trajectory,
        extension_bps=int(extension),
        quote_relative_return_bps=int(extension),
        extension_baseline_time=int(baseline[0]),
        absolute_progress_source="prospectively_observed_create_event",
        trajectory_window_seconds=30,
        extension_lookback_seconds=10,
    )


def _decode_pumpswap_event(raw):
    if len(raw) < 184:
        raise ValueError("short_pumpswap_event")
    disc=raw[:8]
    if disc not in (PUMPSWAP_BUY_EVENT,PUMPSWAP_SELL_EVENT):
        return None
    buy=disc==PUMPSWAP_BUY_EVENT
    offset=8
    timestamp=struct.unpack_from("<q",raw,offset)[0]; offset+=8
    base_amount=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    _limit_quote=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    _user_base=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    _user_quote=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    pool_base=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    pool_quote=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    quote_amount=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    _lp_bps=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    _lp_fee=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    _protocol_bps=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    _protocol_fee=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    _quote_with_fee=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    user_quote=struct.unpack_from("<Q",raw,offset)[0]; offset+=8
    pool=pump.b58(raw[offset:offset+32]); offset+=32
    user=pump.b58(raw[offset:offset+32]); offset+=32
    if min(base_amount,quote_amount,pool_base,pool_quote) <= 0:
        raise ValueError("invalid_pumpswap_event")
    return dict(
        pool=pool,wallet=user,amount=int(quote_amount),tokens=int(base_amount),buy=buy,
        market_time=int(timestamp),pool_base_reserve=int(pool_base),
        pool_quote_reserve=int(pool_quote),user_quote_amount=int(user_quote),
    )


def pumpswap_trade_events(tx):
    if not tx or not tx.get("meta") or tx["meta"].get("err"):
        return []
    stack=[];out=[]
    for index,line in enumerate(tx["meta"].get("logMessages") or []):
        if line.startswith("Program ") and " invoke [" in line:
            stack.append(line.split()[1])
        elif line.startswith("Program ") and (" success" in line or " failed:" in line):
            if stack:
                stack.pop()
        elif line.startswith("Program data: ") and stack and stack[-1]==PUMPSWAP_PROGRAM:
            try:
                raw=base64.b64decode(line[14:],validate=True)
                event=_decode_pumpswap_event(raw)
            except (ValueError,struct.error):
                continue
            if event is not None:
                event.update(index=index,slot=int(tx.get("slot",0)))
                out.append(event)
    return out


def postgrad_volume_acceleration_bps(events, now):
    now=int(now)
    recent=sum(int(e["amount"]) for e in events if now-10 <= int(e["market_time"]) <= now)
    prior=sum(int(e["amount"]) for e in events if now-30 <= int(e["market_time"]) < now-10)
    recent_rate=recent/10
    prior_rate=prior/20
    if prior_rate <= 0:
        return 10_000 if recent_rate > 0 else 0
    return int((recent_rate-prior_rate)*10_000/prior_rate)


def early_holder_sell_share_bps(events, early_wallets):
    early=set(early_wallets)
    sells=[e for e in events if not e.get("buy")]
    total=sum(int(e["amount"]) for e in sells)
    if total <= 0:
        return 0
    early_amount=sum(int(e["amount"]) for e in sells if e.get("wallet") in early)
    return max(0,min(10_000,early_amount*10_000//total))


def reserve_price_parts(base_reserve, quote_reserve):
    base=int(base_reserve);quote=int(quote_reserve)
    if min(base,quote)<=0:
        raise ValueError("invalid_reserves")
    return quote,base


def second_leg_shape(events, graduation_time, now, current_price_parts):
    """Pre-registered rally/pullback/consolidation/breakout transform.

    Historical peak must exist at least 20 seconds before the decision.  The trough
    must occur after that peak and at least 5 seconds before the decision.  The
    consolidation reference is the highest observed price from the trough through
    five seconds before the decision.  Breakout is current price over that reference.
    """
    now=int(now);graduation_time=int(graduation_time)
    points=[]
    for e in events:
        t=int(e.get("market_time",0))
        if not graduation_time <= t <= now:
            continue
        try:
            num,den=reserve_price_parts(e["pool_base_reserve"],e["pool_quote_reserve"])
        except (KeyError,ValueError,TypeError):
            continue
        points.append((t,Fraction(num,den),num,den))
    cnum,cden=current_price_parts
    points.append((now,Fraction(int(cnum),int(cden)),int(cnum),int(cden)))
    points.sort(key=lambda x:x[0])
    if len(points)<4:
        raise ValueError("insufficient_second_leg_history")
    peak_candidates=[p for p in points if p[0] <= now-20]
    if not peak_candidates:
        raise ValueError("missing_preconsolidation_peak")
    peak=max(peak_candidates,key=lambda x:x[1])
    trough_candidates=[p for p in points if peak[0] < p[0] <= now-5]
    if not trough_candidates:
        raise ValueError("missing_pullback")
    trough=min(trough_candidates,key=lambda x:x[1])
    consolidation=[p for p in points if trough[0] <= p[0] <= now-5]
    if not consolidation:
        raise ValueError("missing_consolidation")
    reference=max(consolidation,key=lambda x:x[1])
    pullback=-price_return_bps(peak[2],peak[3],trough[2],trough[3])
    recovery=price_return_bps(trough[2],trough[3],cnum,cden)
    breakout=price_return_bps(reference[2],reference[3],cnum,cden)
    return dict(
        pullback_depth_bps=max(0,int(pullback)),
        recovery_bps=int(recovery),
        consolidation_seconds=max(0,now-int(trough[0])),
        breakout_bps=int(breakout),
        peak_time=int(peak[0]),trough_time=int(trough[0]),
        breakout_reference_time=int(reference[0]),
    )
