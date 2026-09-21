"""Exact quiet-mint Ramses DLMM counterfactual replay.

Signal and candidate selection use only public information available before entry.
No existing Ramses strategy policy is imported or consulted.
"""
from __future__ import annotations
from bisect import bisect_left
from collections import defaultdict
import gzip, hashlib, json, os, urllib.request
from pathlib import Path

from . import BoundaryError
from .abi import calldata
from .identity import load
from .ramses import (
    authenticate_pool, freeze_proposals, paper_fee_capture, paper_outcome,
    paper_position, price, quote_value, state, values,
)
from .ramses_capture import BoundedMultiRpc, _first_finalized_block_at_or_after
from .ramses_all_pool_lifecycle import _snapshot, _build_segment_replay, _unwind

INDEX=Path("ramses-historical-index-data.json.gz")
PROTOCOL=Path("RAMSES_DLMM_QUIET_MINT_COUNTERFACTUAL_V1.json")
OUT=Path("ramses-quiet-mint-counterfactual.json")
ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
CHAIN=4663
LIMIT=1000
USDG="0x5fc5360d0400a0fd4f2af552add042d716f1d168"
MINT_FIELDS="id timestamp pool recipient sender amountUSD totalAmountX totalAmountY binIds amountsX amountsY transaction logIndex"
POOL_FIELDS="id address symbol tokenX tokenY binStep"
WIDTHS=(3,8,13)
HOLDS=(3600,14400)
MAX_CANDIDATES=6
MAX_PER_POOL=2
DEPTH_BPS=50

def f(v):
    try:return float(v or 0)
    except (TypeError,ValueError):return 0.0

def i(v):
    try:return int(v)
    except (TypeError,ValueError):return 0

def addr(v):
    return str(v or "").split(":")[-1].lower()

def txhash(v):
    raw=str(v or "").split(":")[-1]
    if not raw.startswith("0x") or len(raw)!=66:
        raise RuntimeError("quiet_mint_transaction_identity")
    return raw.lower()

def gql(query,variables=None):
    body=json.dumps({"query":query,"variables":variables or {}}).encode()
    req=urllib.request.Request(ENDPOINT,data=body,headers={
        "Content-Type":"application/json","Accept":"application/json",
        "User-Agent":"meme-machine-ramses-quiet-mint/1",
    })
    with urllib.request.urlopen(req,timeout=60) as r:
        payload=json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError("graphql:"+json.dumps(payload["errors"],sort_keys=True))
    return payload["data"]

def page(root,fields):
    rows=[];offset=0
    while True:
        q=f"""query($limit:Int!,$offset:Int!){{{root}(limit:$limit,offset:$offset,
          where:{{chainId:{{_eq:{CHAIN}}}}},order_by:{{id:asc}}){{{fields}}}}}"""
        part=gql(q,{"limit":LIMIT,"offset":offset})[root]
        rows.extend(part)
        if len(part)<LIMIT:return rows
        offset+=LIMIT

def one_freeze(proposal):
    body=dict(frozen=True,allocation_authority=False,hurdle_bps=None,proposals=[proposal])
    body["proposal_hash"]=hashlib.sha256(
        json.dumps(body["proposals"],sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    return body

def swap_times(index):
    by=defaultdict(list)
    all_ts=[]
    for row in index.get("swaps") or []:
        p=addr(row.get("pool"));ts=i(row.get("timestamp"))
        if p and ts>0:
            by[p].append(ts);all_ts.append(ts)
    for rows in by.values():rows.sort()
    if not all_ts:raise RuntimeError("quiet_mint_index_empty")
    return by,min(all_ts),max(all_ts)+1

def count_between(rows,start,end):
    return bisect_left(rows,end)-bisect_left(rows,start)

def pool_tokens(row):
    return addr(row.get("tokenX")),addr(row.get("tokenY"))

def select_candidates(mints,pools,by_swaps,start,end):
    development_end=start+int((end-start)*.80)
    meta={addr(p.get("address")):p for p in pools}
    eligible=[]
    for m in mints:
        p=addr(m.get("pool"));ts=i(m.get("timestamp"))
        if not p or not start<=ts<development_end:continue
        pm=meta.get(p)
        if not pm:continue
        x,y=pool_tokens(pm)
        if USDG not in (x,y):continue
        rows=by_swaps.get(p,[])
        pre30=count_between(rows,ts-1800,ts)
        pre24=count_between(rows,ts-86400,ts)
        if pre30>2 or pre24<10:continue
        identity=f"{p}|{ts}|{txhash(m.get('transaction'))}"
        eligible.append(dict(
            pool=p,symbol=pm.get("symbol"),token_x=x,token_y=y,
            timestamp=ts,transaction_hash=txhash(m.get("transaction")),
            mint_amount_usd=f(m.get("amountUSD")),
            mint_bin_ids=[i(x) for x in (m.get("binIds") or [])],
            prior_30m_swaps=pre30,prior_24h_swaps=pre24,
            selection_hash=hashlib.sha256(identity.encode()).hexdigest(),
        ))
    eligible.sort(key=lambda r:r["selection_hash"])
    out=[];counts=defaultdict(int)
    for row in eligible:
        if counts[row["pool"]]>=MAX_PER_POOL:continue
        counts[row["pool"]]+=1;out.append(row)
        if len(out)>=MAX_CANDIDATES:break
    return out,dict(
        history_start=start,development_end=development_end,history_end=end,
        eligible_signals=len(eligible),selected=len(out),
        selected_pools=len({r["pool"] for r in out}),
    )

def main():
    protocol=json.loads(PROTOCOL.read_text())
    if protocol.get("status")!="preregistered_before_counterfactual_outcomes":
        raise RuntimeError("quiet_mint_protocol_state")
    with gzip.open(INDEX,"rt",encoding="utf-8") as fh:index=json.load(fh)
    by_swaps,start,end=swap_times(index)
    mints=page("DLMMMint",MINT_FIELDS)
    pools=page("DLMMPool",POOL_FIELDS)
    candidates,selection=select_candidates(mints,pools,by_swaps,start,end)
    if len(candidates)<3:
        raise RuntimeError("quiet_mint_candidate_shortfall")

    endpoint=os.environ.get("MM_ROBINHOOD_DLMM_RPC_URL") or os.environ.get("MM_ROBINHOOD_READ_RPC_URL") or ""
    rpc=BoundedMultiRpc(
        endpoint,max_sessions=240,batch_size=16,batch_pause=.20,
        rate_retries=3,rate_cooldown=4.0,adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="quiet_mint")
    factory=load("ramses_factory")["address"]
    results=[]

    for cand in candidates:
        pool=cand["pool"]
        receipt=rpc.call("eth_getTransactionReceipt",[cand["transaction_hash"]],scope="quiet_mint")
        if not receipt or int(receipt.get("status","0x0"),16)!=1:
            results.append(dict(candidate=cand,boundary="mint_receipt_unavailable"))
            continue
        mint_block=int(receipt["blockNumber"],16)
        entry_block=mint_block+1
        try:
            entry_header=rpc.call("eth_getBlockByNumber",[hex(entry_block),False],scope="quiet_mint")
            if not entry_header or int(entry_header["number"],16)!=entry_block:
                raise BoundaryError("quiet_mint_entry_header")
            entry_at=int(entry_header["timestamp"],16)
            member,code,active_raw,step_raw=rpc.batch([
                ("eth_call",[dict(to=factory,data=calldata("isPool(address)",pool)),hex(entry_block)]),
                ("eth_getCode",[pool,hex(entry_block)]),
                ("eth_call",[dict(to=pool,data=calldata("getActiveId()")),hex(entry_block)]),
                ("eth_call",[dict(to=pool,data=calldata("getBinStep()")),hex(entry_block)]),
            ],scope="quiet_mint")
            if int(member,16)!=1:raise BoundaryError("quiet_mint_not_factory_member")
            auth=authenticate_pool(code,factory_member=True)
            active=values(active_raw)[0];step=values(step_raw)[0]
            if step!=auth["bin_step"]:raise BoundaryError("quiet_mint_step_mismatch")
            quote_side="x" if auth["token_x"].lower()==USDG else "y" if auth["token_y"].lower()==USDG else None
            if quote_side is None:raise BoundaryError("quiet_mint_non_usdg")
            bins=list(range(active-max(WIDTHS),active+max(WIDTHS)+1))
            raw=_snapshot(rpc,pool,entry_block,bins,initial=True)
            pre=state(raw)
            active_liq=quote_value(pre["bins"][active]["reserves"],price(active,step),quote_side)
            capital=max(1,active_liq*DEPTH_BPS//10000)
            freeze=freeze_proposals(
                pre,capital,quote_side=quote_side,entry_timestamp=entry_at,
                prehistory=None,gas_costs=None,widths=WIDTHS,
            )
            by_width={int(p["width"]):p for p in freeze["proposals"]}
            candidate_result=dict(
                candidate=cand,mint_block=mint_block,entry_block=entry_block,
                entry_timestamp=entry_at,active_bin=active,bin_step_bps=step,
                quote_side=quote_side,active_liquidity_quote_raw=active_liq,
                capital_quote_raw=capital,depth_fraction_bps=DEPTH_BPS,
                holds=[],
            )
            for hold in HOLDS:
                target=entry_at+hold
                selected,previous,reads=_first_finalized_block_at_or_after(
                    rpc,entry_block,frontier,target
                )
                exit_block=int(selected["number"],16);exit_at=int(selected["timestamp"],16)
                widest=one_freeze(by_width[max(WIDTHS)])
                replay_decision={"freeze":widest}
                hold_row=dict(
                    requested_hold_seconds=hold,exit_block=exit_block,
                    exit_timestamp=exit_at,actual_hold_seconds=exit_at-entry_at,
                    binary_search_reads=reads,variants=[],
                )
                try:
                    _capture,replayed=_build_segment_replay(
                        rpc,pool,replay_decision,entry_block,exit_block
                    )
                    for width in WIDTHS:
                        proposal=by_width[width]
                        fr=one_freeze(proposal);decision={"freeze":fr}
                        try:
                            pos=paper_position(fr,0)
                            fees=paper_fee_capture(pos,replayed)
                            unwind=_unwind(rpc,pool,decision,replayed,exit_block)
                            outcome=paper_outcome(
                                pos,replayed["terminal_state"],unwind=unwind,costs={},
                                lp_fees_captured=fees,
                            )
                            employed=int(proposal["capital_employed"])
                            hold_row["variants"].append(dict(
                                half_width_bins=width,total_bins=len(proposal["bins"]),
                                capital_quote_raw=employed,
                                terminal_equality=replayed.get("terminal_equality"),
                                fee_capture_quote=fees.get("quote_value"),
                                inventory_effect=outcome.get("inventory_effect"),
                                executable_slippage=outcome.get("executable_slippage"),
                                gross_result=outcome.get("gross_result"),
                                gross_return_bps=(None if outcome.get("gross_result") is None or employed<=0
                                                  else int(outcome["gross_result"])*10000//employed),
                                unresolved_inventory=outcome.get("unresolved_inventory"),
                            ))
                        except BoundaryError as exc:
                            hold_row["variants"].append(dict(
                                half_width_bins=width,boundary=str(exc)
                            ))
                except BoundaryError as exc:
                    hold_row["replay_boundary"]=str(exc)
                candidate_result["holds"].append(hold_row)
            results.append(candidate_result)
        except BoundaryError as exc:
            results.append(dict(candidate=cand,boundary=str(exc)))

    resolved=[
        v for r in results if "holds" in r
        for h in r["holds"] for v in h.get("variants",[])
        if v.get("gross_return_bps") is not None
    ]
    body=dict(
        kind="ramses_dlmm_quiet_mint_counterfactual_v1",
        research_only=True,existing_strategy_policy_used=False,
        holdout_outcomes_read=False,protocol=protocol,
        selection=selection,candidates=results,
        summary=dict(
            selected_candidates=len(candidates),
            resolved_variants=len(resolved),
            positive_variants=sum(v["gross_return_bps"]>0 for v in resolved),
            median_gross_return_bps=(None if not resolved else
                sorted(v["gross_return_bps"] for v in resolved)[len(resolved)//2]),
        ),
        provider=rpc.telemetry(),
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps(dict(status="complete",**body["summary"],selection=selection),sort_keys=True))

if __name__=="__main__":main()
