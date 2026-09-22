"""Expand a passing short-symmetric Ramses quiet-entry rule unchanged.

Requires a frozen Branch-A decision artifact. Candidate selection and signal are
identical to the preregistered quiet-mint diagnostic; only sample size expands.
"""
from __future__ import annotations
from collections import defaultdict
import gzip, hashlib, json, os
from pathlib import Path

from . import BoundaryError
from .abi import calldata
from .identity import load
from .ramses import authenticate_pool, freeze_proposals, paper_fee_capture, paper_outcome, paper_position, price, quote_value, state, values
from .ramses_capture import BoundedMultiRpc, _first_finalized_block_at_or_after
from .ramses_all_pool_lifecycle import _snapshot, _build_segment_replay, _unwind
from .ramses_historical_quiet_mint_counterfactual import (
    INDEX, MINT_FIELDS, POOL_FIELDS, USDG, DEPTH_BPS, addr, i, f, page, swap_times, count_between, txhash
)

DECISION=Path("ramses-quiet-branch-decision.json")
OUT=Path("ramses-quiet-short-expansion.json")
TARGET=24
MAX_PER_POOL=4

def candidate_rows(mints,pools,by_swaps,start,end):
    development_end=start+int((end-start)*.80)
    meta={addr(p.get("address")):p for p in pools}
    eligible=[]
    for m in mints:
        p=addr(m.get("pool"));ts=i(m.get("timestamp"))
        if not p or not start<=ts<development_end:continue
        pm=meta.get(p)
        if not pm:continue
        x=addr(pm.get("tokenX"));y=addr(pm.get("tokenY"))
        if USDG not in (x,y):continue
        rows=by_swaps.get(p,[])
        pre30=count_between(rows,ts-1800,ts);pre24=count_between(rows,ts-86400,ts)
        if pre30>2 or pre24<10:continue
        ident=f"{p}|{ts}|{txhash(m.get('transaction'))}"
        eligible.append(dict(
            pool=p,symbol=pm.get("symbol"),timestamp=ts,
            transaction_hash=txhash(m.get("transaction")),
            prior_30m_swaps=pre30,prior_24h_swaps=pre24,
            selection_hash=hashlib.sha256(ident.encode()).hexdigest(),
        ))
    eligible.sort(key=lambda r:r["selection_hash"])
    out=[];counts=defaultdict(int)
    for row in eligible:
        if counts[row["pool"]]>=MAX_PER_POOL:continue
        counts[row["pool"]]+=1;out.append(row)
        if len(out)>=TARGET:break
    return out

def one_freeze(proposal):
    body=dict(frozen=True,allocation_authority=False,hurdle_bps=None,proposals=[proposal])
    body["proposal_hash"]=hashlib.sha256(
        json.dumps(body["proposals"],sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    return body

def main():
    decision=json.loads(DECISION.read_text())
    if decision.get("decision")!="branch_A_expand_unchanged":
        raise RuntimeError("short_expansion_not_branch_A")
    combo=decision.get("selected_combo") or {}
    width=int(combo.get("half_width_bins") or 0)
    hold=int(combo.get("hold_seconds") or 0)
    if width not in (3,8,13) or hold not in (3600,14400):
        raise RuntimeError("short_expansion_combo_outside_original_grid")

    with gzip.open(INDEX,"rt",encoding="utf-8") as fh:index=json.load(fh)
    by_swaps,start,end=swap_times(index)
    candidates=candidate_rows(page("DLMMMint",MINT_FIELDS),page("DLMMPool",POOL_FIELDS),by_swaps,start,end)
    if len(candidates)<20 or len({c["pool"] for c in candidates})<3:
        raise RuntimeError("short_expansion_candidate_shortfall")

    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(endpoint,max_sessions=500,batch_size=16,batch_pause=.20,rate_retries=3,rate_cooldown=4.0,adaptive_batch_floor=2)
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="short_expand")
    factory=load("ramses_factory")["address"]
    results=[]

    for cand in candidates:
        pool=cand["pool"].lower()
        receipt=rpc.call("eth_getTransactionReceipt",[cand["transaction_hash"]],scope="short_expand")
        if not receipt or int(receipt.get("status","0x0"),16)!=1:
            results.append(dict(candidate=cand,boundary="mint_receipt_unavailable"));continue
        mint_block=int(receipt["blockNumber"],16);entry=mint_block+1
        try:
            header=rpc.call("eth_getBlockByNumber",[hex(entry),False],scope="short_expand")
            entry_at=int(header["timestamp"],16)
            member,code,active_raw,step_raw=rpc.batch([
                ("eth_call",[dict(to=factory,data=calldata("isPool(address)",pool)),hex(entry)]),
                ("eth_getCode",[pool,hex(entry)]),
                ("eth_call",[dict(to=pool,data=calldata("getActiveId()")),hex(entry)]),
                ("eth_call",[dict(to=pool,data=calldata("getBinStep()")),hex(entry)]),
            ],scope="short_expand")
            if int(member,16)!=1:raise BoundaryError("short_expand_membership")
            auth=authenticate_pool(code,factory_member=True)
            active=values(active_raw)[0];step=values(step_raw)[0]
            quote_side="x" if auth["token_x"].lower()==USDG else "y" if auth["token_y"].lower()==USDG else None
            if quote_side is None:raise BoundaryError("short_expand_non_usdg")
            bins=list(range(active-width,active+width+1))
            raw=_snapshot(rpc,pool,entry,bins,initial=True);pre=state(raw)
            active_liq=quote_value(pre["bins"][active]["reserves"],price(active,step),quote_side)
            capital=max(1,active_liq*DEPTH_BPS//10000)
            freeze_all=freeze_proposals(pre,capital,quote_side=quote_side,entry_timestamp=entry_at,prehistory=None,gas_costs=None,widths=(width,))
            proposal=freeze_all["proposals"][0];fr=one_freeze(proposal);dec={"freeze":fr}
            selected,previous,reads=_first_finalized_block_at_or_after(rpc,entry,frontier,entry_at+hold)
            exit_block=int(selected["number"],16);exit_at=int(selected["timestamp"],16)
            _capture,replayed=_build_segment_replay(rpc,pool,dec,entry,exit_block)
            unwind=_unwind(rpc,pool,dec,replayed,exit_block)
            pos=paper_position(fr,0);fees=paper_fee_capture(pos,replayed)
            out=paper_outcome(pos,replayed["terminal_state"],unwind=unwind,costs={},lp_fees_captured=fees)
            employed=int(proposal["capital_employed"])
            results.append(dict(
                candidate=cand,entry_block=entry,entry_timestamp=entry_at,
                exit_block=exit_block,exit_timestamp=exit_at,actual_hold_seconds=exit_at-entry_at,
                half_width_bins=width,total_bins=2*width+1,capital_quote_raw=employed,
                terminal_equality=replayed.get("terminal_equality"),
                fee_capture_quote=fees.get("quote_value"),inventory_effect=out.get("inventory_effect"),
                executable_slippage=out.get("executable_slippage"),gross_result=out.get("gross_result"),
                gross_return_bps=(None if out.get("gross_result") is None else int(out["gross_result"])*10000//employed),
                unresolved_inventory=out.get("unresolved_inventory"),binary_search_reads=reads,
            ))
        except BoundaryError as exc:
            results.append(dict(candidate=cand,boundary=str(exc)))

    resolved=[r for r in results if r.get("gross_return_bps") is not None]
    positive=[r for r in resolved if r["gross_return_bps"]>0]
    pos_by_pool=defaultdict(int)
    for r in positive:pos_by_pool[r["candidate"]["pool"]]+=int(r.get("gross_result") or 0)
    total_pos=sum(v for v in pos_by_pool.values() if v>0)
    max_share=(max(pos_by_pool.values())/total_pos if total_pos>0 and pos_by_pool else None)
    vals=sorted(r["gross_return_bps"] for r in resolved)
    body=dict(
        kind="ramses_quiet_short_expansion_v1",research_only=True,holdout_outcomes_read=False,
        frozen_combo=combo,candidate_count=len(candidates),results=results,
        summary=dict(
            resolved=len(resolved),pools=len({r["candidate"]["pool"] for r in resolved}),
            median_gross_return_bps=(vals[len(vals)//2] if vals else None),
            mean_gross_return_bps=(sum(vals)/len(vals) if vals else None),
            positive_rate=(len(positive)/len(resolved) if resolved else 0),
            max_positive_pool_pnl_share=max_share,
        ),
        provider=rpc.telemetry(),
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps(dict(status="complete",summary=body["summary"]),sort_keys=True))

if __name__=="__main__":main()
