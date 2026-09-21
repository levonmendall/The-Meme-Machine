"""Exact Ramses quiet-entry counterfactual using public mint geometry.

This is the preregistered Branch-B diagnostic. It must be run only if the short
symmetric quiet-mint diagnostic fails its preregistered Branch-A condition.
The signal is unchanged; the only geometry input is the finalized public signal
mint itself, observed before our next-block paper entry.
"""
from __future__ import annotations
from collections import defaultdict
import gzip, hashlib, json, os
from pathlib import Path

from . import BoundaryError
from .abi import calldata
from .identity import load
from .ramses import (
    authenticate_pool, decode_ramses_event, mint_effect, paper_fee_capture,
    paper_outcome, paper_position, price, quote_value, state, total_fee, unpack,
    values,
)
from .ramses_capture import BoundedMultiRpc, _first_finalized_block_at_or_after
from .ramses_all_pool_lifecycle import _snapshot, _build_segment_replay, _unwind
from .ramses_historical_quiet_mint_counterfactual import (
    INDEX, MINT_FIELDS, POOL_FIELDS, USDG, addr, i, f, page, select_candidates,
    swap_times,
)

PROTOCOL=Path("RAMSES_DLMM_QUIET_ENTRY_ESCALATION_V1.json")
OUT=Path("ramses-quiet-mint-geometry-counterfactual.json")
HOLDS=(21600,86400,259200)
DEPTH_BPS=50
MAX_CANDIDATES=6
MAX_SIGNAL_BINS=192
ZERO="0x"+"00"*20

def add2(a,b): return [a[0]+b[0],a[1]+b[1]]

def one_freeze(proposal):
    body=dict(frozen=True,allocation_authority=False,hurdle_bps=None,proposals=[proposal])
    body["proposal_hash"]=hashlib.sha256(
        json.dumps(body["proposals"],sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    return body

def signal_geometry(receipt,pool):
    abi=load("ramses_pool_implementation")["abi"]
    rows=[]
    for event in receipt.get("logs") or []:
        if str(event.get("address") or "").lower()!=pool.lower(): continue
        decoded=decode_ramses_event(abi,event)
        if decoded["name"]=="DepositedToBins":
            rows.append(decoded["args"])
    if len(rows)!=1: raise BoundaryError("quiet_geometry_deposit_event_count")
    row=rows[0]
    ids=[int(x) for x in row["ids"]]
    amounts=[unpack(x) for x in row["amounts"]]
    if not ids or len(ids)!=len(amounts) or len(ids)>MAX_SIGNAL_BINS or len(set(ids))!=len(ids):
        raise BoundaryError("quiet_geometry_signal_shape")
    if any(not any(v) for v in amounts):
        raise BoundaryError("quiet_geometry_zero_signal_bin")
    return ids,amounts

def custom_proposal(pre, signal_ids, signal_amounts, target_capital, quote_side, entry_at):
    active=int(pre["active"]);step=int(pre["step"])
    if any(b not in pre["bins"] for b in signal_ids):
        raise BoundaryError("quiet_geometry_missing_entry_bin")
    values_by_bin=[
        quote_value(a,price(b,step),quote_side)
        for b,a in zip(signal_ids,signal_amounts)
    ]
    signal_value=sum(values_by_bin)
    if signal_value<=0: raise BoundaryError("quiet_geometry_signal_value")
    variable=list(pre["variable"])
    allocations=[];req=[0,0];deposit=[0,0];comp=[0,0];protocol=[0,0]
    for bid,signal_amount in zip(signal_ids,signal_amounts):
        requested=[
            max(0,int(signal_amount[0])*int(target_capital)//int(signal_value)),
            max(0,int(signal_amount[1])*int(target_capital)//int(signal_value)),
        ]
        if not any(requested):
            raise BoundaryError("quiet_geometry_scaled_zero_bin")
        b=pre["bins"][bid]
        effect=mint_effect(
            b["reserves"],b["supply"],requested,
            bin_id=bid,step=step,active_id=active,
            static=pre["static"],variable=variable,timestamp=entry_at,
        )
        variable=effect["variable_after"]
        allocations.append(dict(
            bin_id=bid,pre_reserves=list(b["reserves"]),pre_supply=int(b["supply"]),
            requested=requested,amounts_in=effect["amounts_in"],
            deposited=effect["deposited"],shares=effect["shares"],
            composition_fees=effect["composition_fees"],
            protocol_fees=effect["protocol_fees"],bin_price=price(bid,step),
        ))
        req=add2(req,effect["amounts_in"]);deposit=add2(deposit,effect["deposited"])
        comp=add2(comp,effect["composition_fees"]);protocol=add2(protocol,effect["protocol_fees"])
    spot=price(active,step);employed=quote_value(req,spot,quote_side)
    if employed<=0: raise BoundaryError("quiet_geometry_zero_employed")
    current_rate=total_fee(pre["static"],pre["variable"][0],step)
    proposal=dict(
        name="public_mint_geometry",mode="quiet_public_mint_follower",
        bins=list(signal_ids),active_bin=active,quote_side=quote_side,
        capital_requested=int(target_capital),capital_employed=int(employed),
        token_requirements=req,pool_deposit=deposit,
        composition_fees=comp,protocol_entry_fees=protocol,
        initial_inventory_mix=req,initial_spot_value=int(employed),
        allocations=allocations,
        base_fee=pre["static"][0]*step*10**10,
        dynamic_fee=max(0,current_rate-pre["static"][0]*step*10**10),
        protocol_share_bps=pre["static"][5],
        lp_share_bps=10000-pre["static"][5],
        signal_bin_count=len(signal_ids),
        signal_lower_bin=min(signal_ids),signal_upper_bin=max(signal_ids),
        signal_width_bins=max(signal_ids)-min(signal_ids)+1,
        public_signal_geometry=True,
    )
    return proposal

def main():
    protocol=json.loads(PROTOCOL.read_text())
    if protocol.get("status")!="preregistered_before_initial_quiet_counterfactual_result":
        raise RuntimeError("quiet_geometry_protocol_state")
    branch_b=protocol["branch_B_short_symmetric_fail"]["action"]
    if list(branch_b["holds_seconds"])!=list(HOLDS):
        raise RuntimeError("quiet_geometry_hold_protocol_mismatch")

    with gzip.open(INDEX,"rt",encoding="utf-8") as fh:index=json.load(fh)
    by_swaps,start,end=swap_times(index)
    mints=page("DLMMMint",MINT_FIELDS)
    pools=page("DLMMPool",POOL_FIELDS)
    candidates,selection=select_candidates(mints,pools,by_swaps,start,end)
    candidates=candidates[:MAX_CANDIDATES]
    if len(candidates)<3: raise RuntimeError("quiet_geometry_candidate_shortfall")

    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(
        endpoint,max_sessions=300,batch_size=16,batch_pause=.20,
        rate_retries=3,rate_cooldown=4.0,adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="quiet_geometry")
    factory=load("ramses_factory")["address"]
    results=[]

    for cand in candidates:
        pool=cand["pool"].lower()
        receipt=rpc.call("eth_getTransactionReceipt",[cand["transaction_hash"]],scope="quiet_geometry")
        if not receipt or int(receipt.get("status","0x0"),16)!=1:
            results.append(dict(candidate=cand,boundary="quiet_geometry_mint_receipt"))
            continue
        mint_block=int(receipt["blockNumber"],16);entry_block=mint_block+1
        try:
            signal_ids,signal_amounts=signal_geometry(receipt,pool)
            entry_header=rpc.call("eth_getBlockByNumber",[hex(entry_block),False],scope="quiet_geometry")
            if not entry_header or int(entry_header["number"],16)!=entry_block:
                raise BoundaryError("quiet_geometry_entry_header")
            entry_at=int(entry_header["timestamp"],16)
            member,code,active_raw,step_raw=rpc.batch([
                ("eth_call",[dict(to=factory,data=calldata("isPool(address)",pool)),hex(entry_block)]),
                ("eth_getCode",[pool,hex(entry_block)]),
                ("eth_call",[dict(to=pool,data=calldata("getActiveId()")),hex(entry_block)]),
                ("eth_call",[dict(to=pool,data=calldata("getBinStep()")),hex(entry_block)]),
            ],scope="quiet_geometry")
            if int(member,16)!=1: raise BoundaryError("quiet_geometry_not_factory_member")
            auth=authenticate_pool(code,factory_member=True)
            active=values(active_raw)[0];step=values(step_raw)[0]
            if step!=auth["bin_step"]: raise BoundaryError("quiet_geometry_step")
            quote_side="x" if auth["token_x"].lower()==USDG else "y" if auth["token_y"].lower()==USDG else None
            if quote_side is None: raise BoundaryError("quiet_geometry_non_usdg")

            snap_bins=sorted(set(signal_ids+[active]))
            raw=_snapshot(rpc,pool,entry_block,snap_bins,initial=True)
            pre=state(raw)
            active_liq=quote_value(pre["bins"][active]["reserves"],price(active,step),quote_side)
            range_liq=sum(
                quote_value(pre["bins"][bid]["reserves"],price(bid,step),quote_side)
                for bid in signal_ids
            )
            target=max(1,min(active_liq,range_liq)*DEPTH_BPS//10000)
            proposal=custom_proposal(pre,signal_ids,signal_amounts,target,quote_side,entry_at)
            freeze=one_freeze(proposal);decision={"freeze":freeze}
            out=dict(
                candidate=cand,mint_block=mint_block,entry_block=entry_block,
                entry_timestamp=entry_at,active_bin=active,bin_step_bps=step,
                quote_side=quote_side,active_liquidity_quote_raw=active_liq,
                signal_range_liquidity_quote_raw=range_liq,
                capital_quote_raw=proposal["capital_employed"],
                depth_fraction_bps=DEPTH_BPS,
                signal_geometry=dict(
                    bin_count=len(signal_ids),lower=min(signal_ids),upper=max(signal_ids),
                    width=max(signal_ids)-min(signal_ids)+1,
                ),
                holds=[],
            )
            for hold in HOLDS:
                selected,previous,reads=_first_finalized_block_at_or_after(
                    rpc,entry_block,frontier,entry_at+hold
                )
                exit_block=int(selected["number"],16);exit_at=int(selected["timestamp"],16)
                row=dict(
                    requested_hold_seconds=hold,exit_block=exit_block,
                    exit_timestamp=exit_at,actual_hold_seconds=exit_at-entry_at,
                    binary_search_reads=reads,
                )
                try:
                    _capture,replayed=_build_segment_replay(rpc,pool,decision,entry_block,exit_block)
                    unwind=_unwind(rpc,pool,decision,replayed,exit_block)
                    pos=paper_position(freeze,0)
                    fees=paper_fee_capture(pos,replayed)
                    outcome=paper_outcome(
                        pos,replayed["terminal_state"],unwind=unwind,costs={},
                        lp_fees_captured=fees,
                    )
                    employed=int(proposal["capital_employed"])
                    row.update(
                        terminal_equality=replayed.get("terminal_equality"),
                        event_count=replayed.get("events"),
                        transaction_count=replayed.get("transactions"),
                        fee_capture_quote=fees.get("quote_value"),
                        inventory_effect=outcome.get("inventory_effect"),
                        executable_slippage=outcome.get("executable_slippage"),
                        gross_result=outcome.get("gross_result"),
                        gross_return_bps=(None if outcome.get("gross_result") is None else
                                          int(outcome["gross_result"])*10000//employed),
                        unresolved_inventory=outcome.get("unresolved_inventory"),
                    )
                except BoundaryError as exc:
                    row["boundary"]=str(exc)
                out["holds"].append(row)
            results.append(out)
        except BoundaryError as exc:
            results.append(dict(candidate=cand,boundary=str(exc)))

    resolved=[h for r in results for h in r.get("holds",[]) if h.get("gross_return_bps") is not None]
    body=dict(
        kind="ramses_dlmm_quiet_public_mint_geometry_counterfactual_v1",
        research_only=True,allocation_authority=False,
        existing_strategy_policy_used=False,holdout_outcomes_read=False,
        protocol=protocol,selection=selection,candidates=results,
        summary=dict(
            selected_candidates=len(candidates),resolved_holds=len(resolved),
            positive_holds=sum(h["gross_return_bps"]>0 for h in resolved),
            median_gross_return_bps=(None if not resolved else
                sorted(h["gross_return_bps"] for h in resolved)[len(resolved)//2]),
        ),
        provider=rpc.telemetry(),
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps(dict(status="complete",**body["summary"]),sort_keys=True))

if __name__=="__main__":main()
