"""Exact Branch B public-mint-geometry Ramses counterfactual.

Development and holdout share one implementation. Holdout evaluates only the
committed frozen rule and never computes alternative hold outcomes.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal
import gzip, hashlib, json, os
from pathlib import Path

from . import BoundaryError
from .abi import calldata
from .identity import load
from .ramses import (
    _add2, authenticate_pool, decode_ramses_event, mint_effect, paper_outcome,
    paper_position, price, quote_value, state, unpack, values,
)
from .ramses_all_pool_lifecycle import _snapshot, _unwind
from .ramses_capture import BoundedMultiRpc, _first_finalized_block_at_or_after
from .ramses_costs import _factory_direct_routes, _wnative
from .ramses_historical_quiet_mint_counterfactual import (
    INDEX, MINT_FIELDS, POOL_FIELDS, USDG, addr, i, page, swap_times, count_between,
)

PROTOCOL=Path("RAMSES_BRANCH_B_CERTIFICATION_V1.json")
FROZEN=Path("RAMSES_BRANCH_B_FROZEN_RULE_V1.json")
COST_ANCHOR=Path("ramses-branch-b-cost-anchor.json")\nCOST_FALLBACK=Path("ramses-branch-b-cost-route-fallback.json")
OUT=Path("ramses-branch-b-candidate.json")
CHAIN=4663
MAX_BINS=256
SIZE_SCHEDULE=(50,25,12,6,3,1)
DEV_HOLDS=(21600,86400,259200)
MAX_PER_POOL=4
CAP=24
PHASE_ENV="RAMSES_BRANCH_B_PHASE"
INDEX_ENV="RAMSES_BRANCH_B_CANDIDATE_INDEX"

def _txhash(v):
    raw=str(v or "").split(":")[-1]
    if not raw.startswith("0x") or len(raw)!=66:
        raise BoundaryError("branch_b_transaction_identity")
    return raw.lower()

def _selection(mints,pools,by_swaps,start,end,phase,maturity_cutoff):
    split=start+int((end-start)*.80)
    meta={addr(p.get("address")):p for p in pools}
    rows=[]
    for m in mints:
        pool=addr(m.get("pool"));ts=i(m.get("timestamp"))
        if not pool or ts<=0 or ts>maturity_cutoff:
            continue
        in_phase=(ts<split) if phase=="development" else (split<=ts<end)
        if not in_phase:
            continue
        pm=meta.get(pool)
        if not pm:
            continue
        x,y=addr(pm.get("tokenX")),addr(pm.get("tokenY"))
        if USDG not in (x,y):
            continue
        swaps=by_swaps.get(pool,[])
        pre30=count_between(swaps,ts-1800,ts)
        pre24=count_between(swaps,ts-86400,ts)
        if pre30>2 or pre24<10:
            continue
        tx=_txhash(m.get("transaction"))
        log_index=i(m.get("logIndex"))
        ids=[i(v) for v in (m.get("binIds") or [])]
        if not ids or len(ids)>MAX_BINS or len(set(ids))!=len(ids):
            continue
        ident=f"{pool}|{ts}|{tx}"
        rows.append(dict(
            pool=pool,symbol=pm.get("symbol"),token_x=x,token_y=y,
            timestamp=ts,transaction_hash=tx,log_index=log_index,
            indexed_bin_ids=ids,prior_30m_swaps=pre30,prior_24h_swaps=pre24,
            selection_hash=hashlib.sha256(ident.encode()).hexdigest(),
        ))
    rows.sort(key=lambda r:r["selection_hash"])
    selected=[];counts=defaultdict(int)
    for row in rows:
        if counts[row["pool"]]>=MAX_PER_POOL:
            continue
        counts[row["pool"]]+=1
        selected.append(row)
        if len(selected)>=CAP:
            break
    return selected,dict(
        phase=phase,history_start=start,split_timestamp=split,history_end=end,
        maturity_cutoff=maturity_cutoff,eligible_signals=len(rows),
        selected=len(selected),selected_pools=len({r["pool"] for r in selected}),
        max_per_pool=MAX_PER_POOL,candidate_cap=CAP,
    )

def _authenticate_public_mint(rpc,cand):
    receipt=rpc.call("eth_getTransactionReceipt",[cand["transaction_hash"]],scope="branch_b_mint")
    if not receipt or int(receipt.get("status","0x0"),16)!=1:
        raise BoundaryError("branch_b_mint_receipt")
    pool=cand["pool"].lower()
    abi=load("ramses_pool_implementation")["abi"]
    matches=[]
    for event in receipt.get("logs") or []:
        if event.get("address","").lower()!=pool:
            continue
        try:
            log_index=int(event.get("logIndex","0x0"),16)
        except (TypeError,ValueError):
            continue
        if log_index!=cand["log_index"]:
            continue
        decoded=decode_ramses_event(abi,event)
        if decoded["name"]=="DepositedToBins":
            matches.append((event,decoded))
    if len(matches)!=1:
        raise BoundaryError("branch_b_mint_event_identity")
    event,decoded=matches[0]
    args=decoded["args"]
    ids=[int(v) for v in args.get("ids") or []]
    packed=args.get("amounts") or []
    amounts=[unpack(v) for v in packed]
    if ids!=cand["indexed_bin_ids"] or len(ids)!=len(amounts):
        raise BoundaryError("branch_b_mint_geometry_identity")
    if not ids or len(ids)>MAX_BINS or len(set(ids))!=len(ids):
        raise BoundaryError("branch_b_mint_geometry_capacity")
    if any(not any(a) for a in amounts):
        raise BoundaryError("branch_b_zero_public_bin")
    return receipt,event,ids,amounts

def _sum2(rows):
    out=[0,0]
    for row in rows:
        out=_add2(out,row)
    return out

def _scaled_public_proposal(pre,ids,source_amounts,capital,quote_side,entry_at):
    step=pre["step"];active=pre["active"]
    weighted=0
    for bid,amount in zip(ids,source_amounts):
        weighted+=quote_value(amount,price(bid,step),quote_side)
    if weighted<=0:
        raise BoundaryError("branch_b_public_geometry_zero_value")
    requested=[]
    for amount in source_amounts:
        row=[int(amount[0])*int(capital)//weighted,int(amount[1])*int(capital)//weighted]
        if (amount[0] and row[0]==0) or (amount[1] and row[1]==0):
            raise BoundaryError("branch_b_geometry_scale_underflow")
        requested.append(row)
    allocations=[];variable=list(pre["variable"])
    req=[0,0];deposit=[0,0];comp=[0,0];protocol=[0,0]
    for bid,want in zip(ids,requested):
        if bid not in pre["bins"]:
            raise BoundaryError("branch_b_missing_entry_bin")
        b=pre["bins"][bid]
        effect=mint_effect(
            b["reserves"],b["supply"],want,bin_id=bid,step=step,active_id=active,
            static=pre["static"],variable=variable,timestamp=entry_at,
        )
        variable=effect["variable_after"]
        allocations.append(dict(
            bin_id=bid,pre_reserves=list(b["reserves"]),pre_supply=b["supply"],
            requested=want,amounts_in=effect["amounts_in"],deposited=effect["deposited"],
            shares=effect["shares"],composition_fees=effect["composition_fees"],
            protocol_fees=effect["protocol_fees"],bin_price=price(bid,step),
        ))
        req=_add2(req,effect["amounts_in"])
        deposit=_add2(deposit,effect["deposited"])
        comp=_add2(comp,effect["composition_fees"])
        protocol=_add2(protocol,effect["protocol_fees"])
    spot=price(active,step)
    employed=quote_value(req,spot,quote_side)
    if employed<=0:
        raise BoundaryError("branch_b_zero_employed_capital")
    proposal=dict(
        name="public_mint_geometry",width=(max(ids)-min(ids)+1),bins=list(ids),
        active_bin=active,quote_side=quote_side,capital_requested=int(capital),
        capital_employed=int(employed),token_requirements=req,pool_deposit=deposit,
        composition_fees=comp,protocol_entry_fees=protocol,
        initial_inventory_mix=req,initial_spot_value=int(employed),
        public_geometry=True,public_bin_count=len(ids),
        allocations=allocations,
    )
    raw=json.dumps([proposal],sort_keys=True,separators=(",",":")).encode()
    freeze=dict(
        frozen=True,allocation_authority=False,hurdle_bps=None,
        proposal_hash=hashlib.sha256(raw).hexdigest(),proposals=[proposal],
    )
    return freeze

def _entry_size(rpc,pool,pre,ids,source_amounts,quote_side,entry,entry_at):
    local=sum(
        quote_value(pre["bins"][bid]["reserves"],price(bid,pre["step"]),quote_side)
        for bid in ids
    )
    if local<=0:
        raise BoundaryError("branch_b_local_liquidity_zero")
    failures=[]
    for bps in SIZE_SCHEDULE:
        capital=max(1,local*bps//10000)
        try:
            freeze=_scaled_public_proposal(pre,ids,source_amounts,capital,quote_side,entry_at)
            decision={"freeze":freeze}
            pos=paper_position(freeze,0)
            unwind=_unwind(rpc,pool,decision,{"terminal_state":pre},entry)
            probe=paper_outcome(pos,pre,unwind=unwind,costs={})
            if probe.get("unresolved_inventory") is None:
                return freeze,dict(
                    local_range_liquidity_quote_raw=local,selected_bps=bps,
                    attempted_bps=list(SIZE_SCHEDULE),entry_unwind=unwind,
                    entry_unwind_resolved=True,
                )
            failures.append(dict(bps=bps,reason=probe.get("unresolved_inventory")))
        except BoundaryError as exc:
            failures.append(dict(bps=bps,reason=str(exc)))
    raise BoundaryError("branch_b_no_executable_size:"+json.dumps(failures,separators=(",",":")))

def _quote_cycle_cost(rpc,factory,entry,native_costs,*,cost_anchor_sha256=None):
    total=sum(int(v) for v in native_costs.values())
    if total<=0:
        raise BoundaryError("branch_b_cost_anchor_empty")
    wnative=_wnative(rpc,entry,{})
    routes=_factory_direct_routes(rpc,factory,wnative,USDG,total,entry)
    if routes:
        best=max(routes,key=lambda r:int(r["amount_out"]))
        return int(best["amount_out"]),best

    if COST_FALLBACK.exists():
        fallback=json.loads(COST_FALLBACK.read_text())
        if (
            fallback.get("kind")!="ramses_branch_b_cost_route_fallback_v1"
            or fallback.get("frozen") is not True
            or fallback.get("cost_model_changed") is not False
            or int(fallback.get("native_cycle_cost_raw") or 0)!=total
            or (
                cost_anchor_sha256 is not None
                and fallback.get("cost_anchor_sha256")!=cost_anchor_sha256
            )
        ):
            raise BoundaryError("branch_b_cost_route_fallback_identity")
        quote=int(fallback.get("max_verified_quote_cycle_cost_raw") or 0)
        if quote<=0:
            raise BoundaryError("branch_b_cost_route_fallback_value")
        return quote,dict(
            route_kind="verified_ramses_direct_route_upper_envelope",
            amount_out=quote,
            source=fallback.get("source"),
            verified_candidate_count=fallback.get("verified_candidate_count"),
            verified_pool_count=fallback.get("verified_pool_count"),
            cost_anchor_sha256=fallback.get("cost_anchor_sha256"),
            supporting_maximum=fallback.get("supporting_maximum"),
            conservative_upper_envelope=True,
            candidate_entry_direct_route_available=False,
        )

    raise BoundaryError("branch_b_usdg_cost_route_unavailable")

def _holds(phase):
    if phase=="development":
        return DEV_HOLDS
    frozen=json.loads(FROZEN.read_text())
    if frozen.get("kind")!="ramses_branch_b_frozen_rule_v1" or frozen.get("frozen") is not True:
        raise RuntimeError("branch_b_frozen_rule_missing")
    return (int(frozen["hold_seconds"]),)

def main():
    protocol=json.loads(PROTOCOL.read_text())
    if protocol.get("status")!="preregistered_before_branch_b_development_outcomes":
        raise RuntimeError("branch_b_protocol_state")
    phase=str(os.environ.get(PHASE_ENV,"development")).strip().lower()
    if phase not in ("development","holdout"):
        raise RuntimeError("branch_b_phase")
    if phase=="holdout" and not FROZEN.exists():
        raise RuntimeError("branch_b_holdout_before_freeze")
    cost_anchor=json.loads(COST_ANCHOR.read_text())
    if cost_anchor.get("kind")!="ramses_branch_b_cost_anchor_v1" or cost_anchor.get("frozen") is not True:
        raise RuntimeError("branch_b_cost_anchor_state")

    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(
        endpoint,max_sessions=100,batch_size=16,batch_pause=.25,
        rate_retries=3,rate_cooldown=5.0,adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="branch_b_frontier")
    frontier_ts=int(frontier["timestamp"],16)
    maturity_cutoff=frontier_ts-max(DEV_HOLDS)

    with gzip.open(INDEX,"rt",encoding="utf-8") as fh:
        index=json.load(fh)
    by_swaps,start,end=swap_times(index)
    selected,selection=_selection(
        page("DLMMMint",MINT_FIELDS),page("DLMMPool",POOL_FIELDS),
        by_swaps,start,end,phase,maturity_cutoff,
    )
    raw_index=str(os.environ.get(INDEX_ENV,"") or "").strip()
    if not raw_index:
        raise RuntimeError("branch_b_candidate_index_missing")
    try:
        candidate_index=int(raw_index)
    except ValueError:
        raise RuntimeError("branch_b_candidate_index") from None
    if candidate_index<0 or candidate_index>=CAP:
        raise RuntimeError("branch_b_candidate_index")
    if candidate_index>=len(selected):
        body=dict(
            kind="ramses_branch_b_candidate_v1",phase=phase,status="not_selected",
            candidate_index=candidate_index,selection=selection,
            holdout_outcomes_read=(phase=="holdout"),provider=rpc.telemetry(),
        )
        OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
        print(json.dumps({"status":"not_selected","candidate_index":candidate_index}))
        return

    cand=selected[candidate_index]
    factory=load("ramses_factory")["address"]
    try:
        receipt,event,ids,source_amounts=_authenticate_public_mint(rpc,cand)
        mint_block=int(receipt["blockNumber"],16)
        entry=mint_block+1
        header=rpc.call("eth_getBlockByNumber",[hex(entry),False],scope="branch_b_entry")
        if not header or int(header["number"],16)!=entry:
            raise BoundaryError("branch_b_entry_header")
        entry_at=int(header["timestamp"],16)
        member,code=rpc.batch([
            ("eth_call",[dict(to=factory,data=calldata("isPool(address)",cand["pool"])),hex(entry)]),
            ("eth_getCode",[cand["pool"],hex(entry)]),
        ],scope="branch_b_identity")
        auth=authenticate_pool(code,factory_member=int(member,16)==1)
        if auth["token_x"].lower()==USDG:
            quote_side="x"
        elif auth["token_y"].lower()==USDG:
            quote_side="y"
        else:
            raise BoundaryError("branch_b_non_usdg_pool")
        pre=state(_snapshot(rpc,cand["pool"],entry,ids,initial=True))
        if pre["step"]!=auth["bin_step"]:
            raise BoundaryError("branch_b_step_disagreement")
        freeze,size_meta=_entry_size(
            rpc,cand["pool"],pre,ids,source_amounts,quote_side,entry,entry_at
        )
        decision={"freeze":freeze}
        position=paper_position(freeze,0)
        cost_anchor_sha256=hashlib.sha256(
            json.dumps(cost_anchor,sort_keys=True,separators=(",",":")).encode()
        ).hexdigest()
        cost_quote,cost_route=_quote_cycle_cost(
            rpc,factory,entry,{k:int(v) for k,v in cost_anchor["native_costs"].items()},
            cost_anchor_sha256=cost_anchor_sha256,
        )
        holds=[]
        for hold in _holds(phase):
            selected_block,previous,reads=_first_finalized_block_at_or_after(
                rpc,entry,frontier,entry_at+int(hold)
            )
            exit_block=int(selected_block["number"],16)
            exit_at=int(selected_block["timestamp"],16)
            terminal=state(_snapshot(rpc,cand["pool"],exit_block,ids,initial=False))
            if terminal["step"]!=pre["step"]:
                raise BoundaryError("branch_b_terminal_step")
            unwind=_unwind(rpc,cand["pool"],decision,{"terminal_state":terminal},exit_block)
            outcome=paper_outcome(
                position,terminal,unwind=unwind,
                costs={"conservative_cycle":int(cost_quote)},
            )
            employed=int(position["initial_cost_basis"])
            gross=outcome.get("gross_result")
            stress=None
            stress_bps=None
            if type(gross) is int and employed>0:
                stress=gross-2*int(cost_quote)
                stress_bps=stress*10000//employed
            holds.append(dict(
                requested_hold_seconds=int(hold),exit_block=exit_block,
                exit_timestamp=exit_at,actual_hold_seconds=exit_at-entry_at,
                binary_search_reads=reads,terminal_state_source="archive_rpc_snapshot",
                terminal_equivalence_artifact=10672138725,
                gross_result=gross,
                gross_return_bps=(None if type(gross) is not int or employed<=0 else gross*10000//employed),
                after_cost_result=outcome.get("after_cost_result"),
                after_cost_return_bps=outcome.get("after_cost_return_bps"),
                two_x_cost_stress_result=stress,
                two_x_cost_stress_return_bps=stress_bps,
                inventory_effect=outcome.get("inventory_effect"),
                executable_slippage=outcome.get("executable_slippage"),
                unresolved_inventory=outcome.get("unresolved_inventory"),
                removal_amounts=outcome.get("removal_amounts"),
                cost_quote_raw=int(cost_quote),
                cost_route=cost_route,
            ))
        body=dict(
            kind="ramses_branch_b_candidate_v1",phase=phase,status="complete",
            research_only=True,holdout_outcomes_read=(phase=="holdout"),
            candidate_index=candidate_index,selection=selection,candidate=cand,
            onchain_mint=dict(
                block=mint_block,block_hash=receipt["blockHash"],log_index=cand["log_index"],
                bin_ids=ids,amounts=source_amounts,
            ),
            entry=dict(
                block=entry,timestamp=entry_at,quote_side=quote_side,
                active_bin=pre["active"],bin_step_bps=pre["step"],
                size=size_meta,capital_quote_raw=int(position["initial_cost_basis"]),
                public_geometry_bins=len(ids),
            ),
            cost_anchor_sha256=cost_anchor_sha256,
            holds=holds,provider=rpc.telemetry(),
        )
    except BoundaryError as exc:
        body=dict(
            kind="ramses_branch_b_candidate_v1",phase=phase,status="boundary",
            research_only=True,holdout_outcomes_read=(phase=="holdout"),
            candidate_index=candidate_index,selection=selection,candidate=cand,
            boundary=str(exc),provider=rpc.telemetry(),
        )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps({
        "status":body["status"],"phase":phase,"candidate_index":candidate_index,
        "pool":cand["pool"],"holds":[
            (h["requested_hold_seconds"],h.get("after_cost_return_bps"))
            for h in body.get("holds",[])
        ],
    },sort_keys=True))

if __name__=="__main__":
    main()
