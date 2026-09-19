"""Deep, fail-closed reconstruction for profitable DLMM operator candidates.

This module is intentionally downstream of the frozen all-pool census and operator
ranking. It authenticates LP transaction structure, execution costs and entry/
management behavior. Unsupported or incomplete mutation histories are surfaced as
unavailable rather than approximated into the final capital-efficiency ranking.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import statistics
import struct
import time

from meme_machine import dlmm, pump
from meme_machine.dlmm_tape import (
    EVENT_CPI, ADD_LIQUIDITY_EVT, REMOVE_LIQUIDITY_EVT, SWAP, SWAP2,
    _keys, _ordered_instructions, _un58_data,
    decode_add_liquidity, decode_remove_liquidity,
)
from tests import dlmm_alchemy_provider as solana_provider
from tests import dlmm_profitable_operator_discovery as op

DEFAULT_RANKING=Path("DLMM_PROFITABLE_OPERATOR_RANKING_V1.json")
OUT=Path("dlmm-profitable-operator-deep-reconstruction.json")

ADD=bytes([181,157,89,67,143,182,52,72])
ADD2=bytes([228,162,78,28,70,219,116,115])
STRATEGY=bytes([7,3,150,127,148,40,61,200])
STRATEGY2=bytes([3,221,149,218,111,141,118,213])
STRATEGY_ONE_SIDE=bytes([41,5,238,175,100,225,6,205])
WEIGHT=bytes([28,140,238,99,231,162,21,149])
WEIGHT2=bytes([209,59,63,91,111,200,153,228])
ONE_SIDE=bytes([94,155,103,151,70,95,220,165])
PRECISE_ONE_SIDE=bytes([161,194,103,84,171,71,250,154])
PRECISE_ONE_SIDE2=bytes([33,51,163,201,117,98,125,231])
REBALANCE=bytes([92,4,176,193,119,185,83,9])
REMOVE_RANGE2=bytes([204,2,195,145,53,145,145,205])
REMOVE_ALL=bytes([10,51,61,35,112,105,24,85])
CLAIM_FEE2=bytes([112,191,101,171,28,144,127,187])
REBALANCING_EVT=bytes([0,109,117,179,61,91,199,200])

STRATEGY_TYPES=(
    "spot_one_side","curve_one_side","bid_ask_one_side",
    "spot_balanced","curve_balanced","bid_ask_balanced",
    "spot_imbalanced","curve_imbalanced","bid_ask_imbalanced",
)


def _dec(value,default=0.0):
    try:
        return float(Decimal(str(default if value is None else value)))
    except (InvalidOperation,ValueError,TypeError):
        return float(default)


def _corr(xs,ys):
    if len(xs)<3 or len(xs)!=len(ys):
        return None
    mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
    dx=[x-mx for x in xs];dy=[y-my for y in ys]
    den=math.sqrt(sum(x*x for x in dx)*sum(y*y for y in dy))
    return None if den==0 else sum(x*y for x,y in zip(dx,dy))/den


def classify_distribution(distributions,active_bin):
    rows=[r for r in distributions if (r.get("weight") or 0)>0]
    if not rows:
        return "unknown"
    weights=[float(r["weight"]) for r in rows]
    mean=sum(weights)/len(weights)
    if mean>0 and len(weights)>1 and statistics.pstdev(weights)/mean<=0.20:
        return "spot_like"
    distances=[abs(int(r["bin_id"])-int(active_bin)) for r in rows]
    relation=_corr(distances,weights)
    if relation is not None and relation<=-0.35:
        return "curve_like"
    if relation is not None and relation>=0.35:
        return "bid_ask_like"
    return "custom"


def decode_strategy(raw):
    if len(raw)<105 or raw[:8] not in (STRATEGY,STRATEGY2):
        raise ValueError("dlmm_operator_strategy_shape")
    amount_x,amount_y=struct.unpack_from("<QQ",raw,8)
    active,max_slippage,min_bin,max_bin=struct.unpack_from("<iiii",raw,24)
    strategy_index=raw[40]
    if min_bin>max_bin or strategy_index>=len(STRATEGY_TYPES):
        raise ValueError("dlmm_operator_strategy2_values")
    name=STRATEGY_TYPES[strategy_index]
    return dict(
        instruction=("add_liquidity_by_strategy2" if raw[:8]==STRATEGY2
                     else "add_liquidity_by_strategy"),
        amount_x=amount_x,amount_y=amount_y,
        observed_active_bin=active,max_active_bin_slippage=max_slippage,
        lower_bin_id=min_bin,upper_bin_id=max_bin,
        width_bins=max_bin-min_bin+1,
        strategy_type=name,
        strategy_family=("spot" if name.startswith("spot") else
                         "curve" if name.startswith("curve") else "bid_ask"),
        one_sided=(amount_x==0) != (amount_y==0),
        two_sided=amount_x>0 and amount_y>0,
    )


def decode_add(raw):
    if len(raw)<32 or raw[:8] not in (ADD,ADD2):
        raise ValueError("dlmm_operator_add_shape")
    amount_x,amount_y,count=struct.unpack_from("<QQI",raw,8)
    if not 1<=count<=70 or len(raw)<28+8*count:
        raise ValueError("dlmm_operator_add2_distribution")
    rows=[];offset=28
    for _ in range(count):
        bid,dx,dy=struct.unpack_from("<iHH",raw,offset);offset+=8
        if dx>10000 or dy>10000:
            raise ValueError("dlmm_operator_add2_weight")
        rows.append(dict(bin_id=bid,distribution_x=dx,distribution_y=dy,
                         weight=dx+dy))
    bins=[r["bin_id"] for r in rows if r["weight"]>0]
    return dict(
        instruction=("add_liquidity2" if raw[:8]==ADD2 else "add_liquidity"),
        amount_x=amount_x,amount_y=amount_y,
        lower_bin_id=(None if not bins else min(bins)),
        upper_bin_id=(None if not bins else max(bins)),
        width_bins=(None if not bins else max(bins)-min(bins)+1),
        one_sided=(amount_x==0)!=(amount_y==0),
        two_sided=amount_x>0 and amount_y>0,
        distributions=rows,
    )


def _strategy_fields(raw,amount_x,amount_y,base_offset,instruction):
    active,max_slippage,min_bin,max_bin=struct.unpack_from("<iiii",raw,base_offset)
    strategy_index=raw[base_offset+16]
    if min_bin>max_bin or strategy_index>=len(STRATEGY_TYPES):
        raise ValueError("dlmm_operator_strategy_values")
    name=STRATEGY_TYPES[strategy_index]
    return dict(
        instruction=instruction,amount_x=amount_x,amount_y=amount_y,
        observed_active_bin=active,max_active_bin_slippage=max_slippage,
        lower_bin_id=min_bin,upper_bin_id=max_bin,width_bins=max_bin-min_bin+1,
        strategy_type=name,
        strategy_family=("spot" if name.startswith("spot") else
                         "curve" if name.startswith("curve") else "bid_ask"),
        one_sided=(amount_x==0)!=(amount_y==0),
        two_sided=amount_x>0 and amount_y>0,
    )


def decode_strategy_one_side(raw):
    if len(raw)<97 or raw[:8]!=STRATEGY_ONE_SIDE:
        raise ValueError("dlmm_operator_strategy_one_side_shape")
    amount=struct.unpack_from("<Q",raw,8)[0]
    result=_strategy_fields(
        raw,amount,0,16,"add_liquidity_by_strategy_one_side")
    result["amount"]=amount
    result["amount_x"]=None;result["amount_y"]=None
    result["one_sided"]=True;result["two_sided"]=False
    result["single_side_token_from_accounts"]=True
    return result


def decode_weight(raw):
    if len(raw)<36 or raw[:8] not in (WEIGHT,WEIGHT2):
        raise ValueError("dlmm_operator_weight_shape")
    amount_x,amount_y=struct.unpack_from("<QQ",raw,8)
    active,max_slippage=struct.unpack_from("<ii",raw,24)
    count=struct.unpack_from("<I",raw,32)[0]
    if not 1<=count<=70 or len(raw)<36+6*count:
        raise ValueError("dlmm_operator_weight_distribution")
    rows=[];offset=36
    for _ in range(count):
        bid,weight=struct.unpack_from("<iH",raw,offset);offset+=6
        rows.append(dict(bin_id=bid,weight=weight))
    bins=[r["bin_id"] for r in rows if r["weight"]>0]
    return dict(
        instruction=("add_liquidity_by_weight2" if raw[:8]==WEIGHT2
                     else "add_liquidity_by_weight"),
        amount_x=amount_x,amount_y=amount_y,observed_active_bin=active,
        max_active_bin_slippage=max_slippage,
        lower_bin_id=(None if not bins else min(bins)),
        upper_bin_id=(None if not bins else max(bins)),
        width_bins=(None if not bins else max(bins)-min(bins)+1),
        one_sided=(amount_x==0)!=(amount_y==0),
        two_sided=amount_x>0 and amount_y>0,distributions=rows,
    )


def decode_one_side(raw):
    if len(raw)<28 or raw[:8]!=ONE_SIDE:
        raise ValueError("dlmm_operator_one_side_shape")
    amount=struct.unpack_from("<Q",raw,8)[0]
    active,max_slippage=struct.unpack_from("<ii",raw,16)
    count=struct.unpack_from("<I",raw,24)[0]
    if not 1<=count<=70 or len(raw)<28+6*count:
        raise ValueError("dlmm_operator_one_side_distribution")
    rows=[];offset=28
    for _ in range(count):
        bid,weight=struct.unpack_from("<iH",raw,offset);offset+=6
        rows.append(dict(bin_id=bid,weight=weight))
    bins=[r["bin_id"] for r in rows if r["weight"]>0]
    return dict(
        instruction="add_liquidity_one_side",amount=amount,
        observed_active_bin=active,max_active_bin_slippage=max_slippage,
        lower_bin_id=(None if not bins else min(bins)),
        upper_bin_id=(None if not bins else max(bins)),
        width_bins=(None if not bins else max(bins)-min(bins)+1),
        one_sided=True,two_sided=False,distributions=rows,
        single_side_token_from_accounts=True,
    )


def decode_precise_one_side(raw):
    if len(raw)<20 or raw[:8] not in (PRECISE_ONE_SIDE,PRECISE_ONE_SIDE2):
        raise ValueError("dlmm_operator_precise_one_side_shape")
    count=struct.unpack_from("<I",raw,8)[0]
    if not 1<=count<=70 or len(raw)<12+8*count+8:
        raise ValueError("dlmm_operator_precise_one_side_bins")
    rows=[];offset=12
    for _ in range(count):
        bid,amount=struct.unpack_from("<iI",raw,offset);offset+=8
        rows.append(dict(bin_id=bid,compressed_amount=amount,weight=amount))
    multiplier=struct.unpack_from("<Q",raw,offset)[0];offset+=8
    max_amount=None
    if raw[:8]==PRECISE_ONE_SIDE2:
        if len(raw)<offset+8:
            raise ValueError("dlmm_operator_precise_one_side2_max_amount")
        max_amount=struct.unpack_from("<Q",raw,offset)[0]
    bins=[r["bin_id"] for r in rows if r["weight"]>0]
    return dict(
        instruction=("add_liquidity_one_side_precise2"
                     if raw[:8]==PRECISE_ONE_SIDE2
                     else "add_liquidity_one_side_precise"),
        decompress_multiplier=multiplier,max_amount=max_amount,
        lower_bin_id=(None if not bins else min(bins)),
        upper_bin_id=(None if not bins else max(bins)),
        width_bins=(None if not bins else max(bins)-min(bins)+1),
        one_sided=True,two_sided=False,distributions=rows,
        single_side_token_from_accounts=True,
    )


def decode_remove_range2(raw):
    if len(raw)<18 or raw[:8]!=REMOVE_RANGE2:
        raise ValueError("dlmm_operator_remove_range2_shape")
    lower,upper,bps=struct.unpack_from("<iiH",raw,8)
    if lower>upper or not 1<=bps<=10000:
        raise ValueError("dlmm_operator_remove_range2_values")
    return dict(instruction="remove_liquidity_by_range2",
                lower_bin_id=lower,upper_bin_id=upper,bps=bps)


def decode_rebalance(raw):
    if len(raw)<80 or raw[:8]!=REBALANCE:
        raise ValueError("dlmm_operator_rebalance_shape")
    active=struct.unpack_from("<i",raw,8)[0]
    max_slippage=struct.unpack_from("<H",raw,12)[0]
    claim_fee=bool(raw[14]);claim_reward=bool(raw[15])
    min_wx,max_dx,min_wy,max_dy=struct.unpack_from("<QQQQ",raw,16)
    shrink_mode=raw[48]
    return dict(
        instruction="rebalance_liquidity",observed_active_bin=active,
        max_active_bin_slippage=max_slippage,should_claim_fee=claim_fee,
        should_claim_reward=claim_reward,min_withdraw_x_amount=min_wx,
        max_deposit_x_amount=max_dx,min_withdraw_y_amount=min_wy,
        max_deposit_y_amount=max_dy,shrink_mode=shrink_mode,
    )


def decode_rebalancing_event(raw,pool):
    if len(raw)<188 or raw[:8]!=REBALANCING_EVT:
        raise ValueError("dlmm_operator_rebalancing_event_shape")
    if pump.b58(raw[8:40])!=pool:
        raise ValueError("dlmm_operator_rebalancing_event_pool")
    position=pump.b58(raw[40:72]);owner=pump.b58(raw[72:104])
    active=struct.unpack_from("<i",raw,104)[0]
    amounts=struct.unpack_from("<QQQQQQ",raw,108)
    old_min,old_max,new_min,new_max=struct.unpack_from("<iiii",raw,156)
    return dict(
        position=position,owner=owner,active_bin=active,
        x_withdrawn=amounts[0],x_added=amounts[1],
        y_withdrawn=amounts[2],y_added=amounts[3],
        x_fee=amounts[4],y_fee=amounts[5],
        old_min_bin=old_min,old_max_bin=old_max,
        new_min_bin=new_min,new_max_bin=new_max,
    )


def _swap_fee_bps(raw,pool):
    if raw[:8]==SWAP and len(raw)==137 and pump.b58(raw[8:40])==pool:
        return int.from_bytes(raw[113:129],"little")
    if raw[:8]==SWAP2 and len(raw)==155 and pump.b58(raw[8:40])==pool:
        return int.from_bytes(raw[81:97],"little")
    return None


def transaction_features(tx,pool,position):
    if not tx or not tx.get("meta") or tx["meta"].get("err"):
        raise RuntimeError("dlmm_operator_failed_transaction")
    meta=tx["meta"];message=(tx.get("transaction") or {}).get("message") or {}
    keys=_keys(meta,message)
    required=int((message.get("header") or {}).get("numRequiredSignatures",0))
    if not keys or required<1:
        raise RuntimeError("dlmm_operator_fee_payer_missing")
    fee_payer=keys[0]
    actions=[];entry=None;actual_add_active=None
    rebalances=[];remove_events=[];swap_fees=[]
    for outer,inner,ix in _ordered_instructions(meta,message):
        pi=ix.get("programIdIndex")
        if type(pi) is not int or not 0<=pi<len(keys) or keys[pi]!=dlmm.PROGRAM:
            continue
        raw=_un58_data(ix.get("data") or "")
        accounts=ix.get("accounts") or []
        if raw[:8]==EVENT_CPI:
            payload=raw[8:]
            if payload[:8]==ADD_LIQUIDITY_EVT:
                try:
                    ev=decode_add_liquidity(payload,pool)
                    if ev["position"]==position:
                        actual_add_active=ev["active"]
                except (ValueError,KeyError):
                    pass
            elif payload[:8]==REMOVE_LIQUIDITY_EVT:
                try:
                    ev=decode_remove_liquidity(payload,pool)
                    if ev["position"]==position:
                        remove_events.append(ev)
                except (ValueError,KeyError):
                    pass
            elif payload[:8]==REBALANCING_EVT:
                try:
                    ev=decode_rebalancing_event(payload,pool)
                    if ev["position"]==position: rebalances.append(ev)
                except (ValueError,KeyError):
                    pass
            else:
                fee=_swap_fee_bps(payload,pool)
                if fee is not None: swap_fees.append(fee)
            continue
        spec=op.LP_MUTATIONS.get(raw[:8])
        if spec is None: continue
        action,pool_i,position_i,signer_i=spec
        needed=max(pool_i,position_i,signer_i)
        if len(accounts)<=needed or any(type(accounts[i]) is not int or
                not 0<=accounts[i]<len(keys) for i in (pool_i,position_i,signer_i)):
            continue
        if keys[accounts[pool_i]]!=pool or keys[accounts[position_i]]!=position:
            continue
        detail=dict(action=action,order=[outer,inner],signer=keys[accounts[signer_i]])
        if action in (
            "add_liquidity_by_strategy_one_side","add_liquidity_one_side",
            "add_liquidity_one_side_precise","add_liquidity_one_side_precise2"
        ) and len(accounts)>5 and type(accounts[5]) is int and 0<=accounts[5]<len(keys):
            detail["single_side_token_mint"]=keys[accounts[5]]
        try:
            if raw[:8] in (ADD,ADD2):
                detail.update(decode_add(raw))
            elif raw[:8] in (STRATEGY,STRATEGY2):
                detail.update(decode_strategy(raw))
            elif raw[:8]==STRATEGY_ONE_SIDE:
                detail.update(decode_strategy_one_side(raw))
            elif raw[:8] in (WEIGHT,WEIGHT2):
                detail.update(decode_weight(raw))
            elif raw[:8]==ONE_SIDE:
                detail.update(decode_one_side(raw))
            elif raw[:8] in (PRECISE_ONE_SIDE,PRECISE_ONE_SIDE2):
                detail.update(decode_precise_one_side(raw))
            elif raw[:8]==REBALANCE:
                detail.update(decode_rebalance(raw))
            elif raw[:8]==REMOVE_RANGE2:
                detail.update(decode_remove_range2(raw))
            elif raw[:8]==REMOVE_ALL:
                detail.update(instruction="remove_all_liquidity",bps=10000)
            elif raw[:8]==CLAIM_FEE2:
                detail.update(instruction="claim_fee2")
        except ValueError:
            detail["decode_complete"]=False
        actions.append(detail)
        if entry is None and action.startswith("add_liquidity"):
            entry=detail
    if entry is not None and actual_add_active is not None:
        entry=dict(entry);entry["actual_active_bin"]=actual_add_active
        if entry.get("distributions"):
            entry["distribution_shape"]=classify_distribution(
                entry["distributions"],actual_add_active)
        lower=entry.get("lower_bin_id");upper=entry.get("upper_bin_id")
        if isinstance(lower,int) and isinstance(upper,int):
            entry["lower_active_offset_bins"]=lower-actual_add_active
            entry["upper_active_offset_bins"]=upper-actual_add_active
            entry["center_active_offset_bins"]=(lower+upper)/2.0-actual_add_active
            entry["range_asymmetry_bins"]=(upper-actual_add_active)-(
                actual_add_active-lower)
    return dict(
        slot=int(tx.get("slot") or 0),block_time=tx.get("blockTime"),
        network_fee_lamports=int(meta.get("fee") or 0),fee_payer=fee_payer,
        actions=actions,entry=entry,rebalances=rebalances,
        remove_events=remove_events,
        swap_fee_bps_observed_in_transaction=swap_fees,
    )


def infer_event_sol_price(event):
    for side in ("x","y"):
        if event.get("token_"+side)!=dlmm.WSOL:
            continue
        amount=event.get("amount_"+side)
        usd=float(event.get("amount_"+side+"_usd") or 0)
        try: raw=float(Decimal(str(amount)))
        except (InvalidOperation,ValueError,TypeError): continue
        if raw<=0 or usd<=0: continue
        candidates=[usd/raw,usd/(raw/1_000_000_000.0)]
        valid=[x for x in candidates if 1.0<=x<=10000.0]
        if len(valid)==1:
            return valid[0]
    return None


def exact_position_capital(position,history,features_by_signature):
    lower=position.get("lower_bin_id");upper=position.get("upper_bin_id")
    if not isinstance(lower,int) or not isinstance(upper,int):
        return dict(exact=False,reason="missing_position_range")
    basis=0.0;capital_seconds=0.0;last=None;segments=[]
    for event in history:
        ts=event.get("block_time")
        if not isinstance(ts,int) or ts<=0:
            return dict(exact=False,reason="missing_event_time")
        if last is not None and ts>last and basis>0:
            capital_seconds+=basis*(ts-last)
            segments.append(dict(start=last,end=ts,capital_usd=basis))
        kind=event.get("event_type")
        feature=features_by_signature.get(event.get("signature")) or {}
        actions=feature.get("actions") or []
        if kind=="add":
            relevant=[a for a in actions if a.get("action","").startswith("add_liquidity")]
            if len(relevant)!=1:
                return dict(exact=False,reason="unresolved_add_instruction")
            basis+=max(0.0,float(event.get("total_usd") or 0))
        elif kind=="remove":
            remove=[a for a in actions if a.get("action","").startswith("remove")]
            if len(remove)!=1:
                return dict(exact=False,reason="unresolved_remove_instruction")
            action=remove[0]
            if action.get("instruction")=="remove_all_liquidity":
                basis=0.0
            elif (action.get("instruction")=="remove_liquidity_by_range2" and
                  action.get("bps")==10000 and
                  action.get("lower_bin_id")<=lower and action.get("upper_bin_id")>=upper):
                basis=0.0
            else:
                return dict(exact=False,reason="partial_remove_requires_bin_basis")
        elif kind in ("claim_fee","claim_reward"):
            pass
        last=ts
    if abs(basis)>1e-9:
        return dict(exact=False,reason="residual_basis_after_closed_history")
    return dict(exact=True,capital_hours_usd=capital_seconds/3600.0,
                exposure_segments=segments)


def exact_simple_twr(positions,histories,network_cost_by_position=None):
    """Exact deployed-capital TWR for simple, non-overlapping position lifecycles.

    This is deliberately narrow. Every position must have one add, one terminal
    remove, no intermediate fee/reward cash flow, positive deposit USD and no temporal
    overlap with another measured position. Under those conditions each closed
    position is one external-flow-bounded subperiod and can be chain-linked exactly.
    More complex portfolios require event-boundary marks and remain unavailable.
    """
    network_cost_by_position=network_cost_by_position or {}
    periods=[]
    for p in positions:
        address=p.get("position")
        rows=sorted(
            histories.get(address) or [],
            key=lambda e:(int(e.get("block_time") or 0),
                          int(e.get("slot") or 0),int(e.get("ix_index") or 0)))
        flows=[e for e in rows if e.get("event_type") in
               ("add","remove","claim_fee","claim_reward")]
        adds=[e for e in flows if e.get("event_type")=="add"]
        removes=[e for e in flows if e.get("event_type")=="remove"]
        claims=[e for e in flows if e.get("event_type") in ("claim_fee","claim_reward")]
        if len(adds)!=1 or len(removes)!=1 or claims:
            return dict(available=False,reason="complex_external_cash_flow")
        start=adds[0].get("block_time");end=removes[0].get("block_time")
        if not isinstance(start,int) or not isinstance(end,int) or end<=start:
            return dict(available=False,reason="invalid_position_time")
        deposit=float(p.get("deposit_usd") or 0.0)
        pnl=float(p.get("pnl_usd") or 0.0)
        cost=network_cost_by_position.get(address)
        if cost is None:
            return dict(available=False,reason="network_cost_usd_unavailable")
        if deposit<=0:
            return dict(available=False,reason="nonpositive_deposit")
        periods.append((start,end,address,(pnl-float(cost))/deposit))
    periods.sort()
    for prior,current in zip(periods,periods[1:]):
        if current[0]<prior[1]:
            return dict(available=False,reason="overlapping_positions")
    factor=1.0
    for _start,_end,_address,r in periods:
        if r<=-1.0:
            return dict(available=False,reason="subperiod_return_below_minus_one")
        factor*=1.0+r
    return dict(
        available=True,
        twr=factor-1.0,
        subperiods=len(periods),
        methodology="chain_linked_after_network_cost_simple_nonoverlapping_positions",
    )


def wallet_deep_metrics(wallet_row,tx_features):
    positions=wallet_row.get("positions") or []
    histories=wallet_row.get("histories") or {}
    exact=[];entry=[];rebalance_count=0;action_counts=Counter()
    unique_signatures=set()
    price_by_signature={}
    for position in positions:
        address=position.get("position")
        history=histories.get(address) or []
        for event in history:
            sig=event.get("signature")
            if sig: unique_signatures.add(sig)
            price=infer_event_sol_price(event)
            if sig and price is not None: price_by_signature[sig]=price
        result=exact_position_capital(position,history,tx_features)
        exact.append(dict(position=address,**result))
        for event in history:
            feature=tx_features.get(event.get("signature")) or {}
            for action in feature.get("actions") or []:
                action_counts[action.get("action")]+=1
            rebalance_count+=len(feature.get("rebalances") or [])
        adds=[
            tx_features.get(e.get("signature"),{}).get("entry")
            for e in history if e.get("event_type")=="add"
        ]
        adds=[a for a in adds if a]
        if adds: entry.append(dict(position=address,entry=adds[0]))

    network_lamports=sum(
        int(tx_features[s].get("network_fee_lamports") or 0)
        for s in unique_signatures if s in tx_features)
    network_cost_usd=0.0;missing_price=[]
    for sig in unique_signatures:
        feature=tx_features.get(sig)
        if not feature: continue
        price=price_by_signature.get(sig)
        if price is None:
            missing_price.append(sig);continue
        network_cost_usd+=feature["network_fee_lamports"]/1_000_000_000.0*price

    capital_exact=all(x.get("exact") for x in exact)
    capital_hours=(sum(x.get("capital_hours_usd",0.0) for x in exact)
                   if capital_exact else None)
    gross=float(wallet_row.get("api_realized_pnl_usd") or 0)
    cost_complete=not missing_price
    after=(gross-network_cost_usd if cost_complete else None)
    return dict(
        wallet=wallet_row["wallet"],capital_at_risk_exact=capital_exact,
        exact_position_capital=exact,capital_hours_usd=capital_hours,
        network_execution_cost_lamports=network_lamports,
        network_execution_cost_usd=(network_cost_usd if cost_complete else None),
        network_cost_usd_complete=cost_complete,
        unpriced_network_fee_signatures=missing_price,
        after_network_cost_pnl_usd=after,
        after_cost_pnl_per_capital_hour=(
            None if after is None or capital_hours is None or capital_hours<=0
            else after/capital_hours),
        fee_income_usd=float(wallet_row.get("fee_income_usd") or 0),
        inventory_token_price_pnl_usd=float(
            wallet_row.get("inventory_token_price_pnl_usd") or 0),
        entry_features=entry,action_counts=dict(action_counts),
        rebalance_count=rebalance_count,
        fee_payers=sorted({
            tx_features[s]["fee_payer"] for s in unique_signatures
            if s in tx_features and tx_features[s].get("fee_payer")
        }),
    )


def cluster_fleets(wallets):
    """Merge only direct coordination evidence; behavioral similarity is diagnostic."""
    parent={w["wallet"]:w["wallet"] for w in wallets}
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    def union(a,b):
        a=find(a);b=find(b)
        if a!=b: parent[max(a,b)]=min(a,b)
    payer_to_wallets=defaultdict(set)
    for row in wallets:
        for payer in row.get("fee_payers") or []:
            if payer!=row["wallet"]:
                payer_to_wallets[payer].add(row["wallet"])
    for members in payer_to_wallets.values():
        members=sorted(members)
        for other in members[1:]: union(members[0],other)
    groups=defaultdict(list)
    for row in wallets: groups[find(row["wallet"])].append(row["wallet"])
    return [
        dict(cluster_id=min(members),wallets=sorted(members),
             independent_evidence_unit=True,direct_shared_fee_payer=(
                 len(members)>1))
        for members in sorted(groups.values(),key=lambda x:min(x))
    ]
