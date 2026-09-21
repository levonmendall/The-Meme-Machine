"""Blank-slate historical Ramses DLMM market census.

Research only. Existing Ramses strategy thresholds are intentionally not imported.
The first stage reconstructs every authenticated Swap event across the current factory
history, then summarizes flow/fee/path regimes for later exact LP replay.
"""
from __future__ import annotations

from collections import defaultdict
import gzip
import json
import math
import os
from pathlib import Path
import statistics
import time

from . import BoundaryError
from .abi import topic
from .identity import authenticate, load
from .ramses import authenticate_pool, decode_ramses_event, price, quote_value, unpack
from .ramses_capture import BoundedMultiRpc
from .ramses_universe import _enumerate_factory

REPORT=Path("ramses-historical-market-census.json")
SWAPS=Path("ramses-historical-swaps.json.gz")
WINDOW_SECONDS=300
INITIAL_SPANS=(2_000_000,1_000_000,500_000,250_000,100_000,50_000,20_000,10_000,5_000,2_000,1_000)
MAX_LOGICAL_LOG_CALLS=20_000
SWAP_TOPIC=topic("Swap(address,address,uint24,bytes32,bytes32,uint24,bytes32,bytes32)")


def _q(values,q):
    xs=sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not xs:return None
    if len(xs)==1:return xs[0]
    p=(len(xs)-1)*q
    lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)


def _first_code_block(rpc,address,head):
    if rpc.call("eth_getCode",[address,hex(head)],scope="history_identity") in ("0x","0x0"):
        raise BoundaryError("ramses_historical_factory_missing_at_head")
    lo,hi=0,int(head)
    while lo<hi:
        mid=(lo+hi)//2
        code=rpc.call("eth_getCode",[address,hex(mid)],scope="history_identity")
        if code not in ("0x","0x0"):
            hi=mid
        else:
            lo=mid+1
    return lo


def _query(rpc,start,end,addresses,counter):
    counter[0]+=1
    if counter[0]>MAX_LOGICAL_LOG_CALLS:
        raise BoundaryError("ramses_historical_log_budget")
    return rpc.call("eth_getLogs",[dict(
        fromBlock=hex(int(start)),toBlock=hex(int(end)),
        address=list(addresses),topics=[[SWAP_TOPIC]],
    )],scope="history_logs")


def _split_range(rpc,start,end,addresses,counter):
    try:
        return _query(rpc,start,end,addresses,counter)
    except BoundaryError:
        if start>=end:
            raise
        mid=(start+end)//2
        return (
            _split_range(rpc,start,mid,addresses,counter)
            +_split_range(rpc,mid+1,end,addresses,counter)
        )


def _probe_span(rpc,start,end,addresses,counter):
    total=end-start+1
    for span in INITIAL_SPANS:
        if span>total:continue
        a=end-span+1
        try:
            _query(rpc,a,end,addresses,counter)
            return span
        except BoundaryError:
            continue
    return min(500,total)


def _all_logs(rpc,start,end,addresses):
    counter=[0]
    span=_probe_span(rpc,start,end,addresses,counter)
    ranges=[(a,min(end,a+span-1)) for a in range(start,end+1,span)]
    out=[]
    # Batch ten accepted-size windows at a time; isolate/split only on a failed batch.
    for i in range(0,len(ranges),10):
        chunk=ranges[i:i+10]
        calls=[("eth_getLogs",[dict(
            fromBlock=hex(a),toBlock=hex(b),address=list(addresses),topics=[[SWAP_TOPIC]],
        )]) for a,b in chunk]
        counter[0]+=len(calls)
        if counter[0]>MAX_LOGICAL_LOG_CALLS:
            raise BoundaryError("ramses_historical_log_budget")
        try:
            pages=rpc.batch(calls,scope="history_logs")
            for page in pages:out.extend(page)
        except BoundaryError:
            for a,b in chunk:
                out.extend(_split_range(rpc,a,b,addresses,counter))
        if i and i%100==0:
            print(json.dumps(dict(stage="swap_logs",ranges_done=i,total_ranges=len(ranges),
                                  logs=len(out),logical_log_calls=counter[0]),sort_keys=True),flush=True)
    out.sort(key=lambda e:(int(e["blockNumber"],16),int(e["transactionIndex"],16),int(e["logIndex"],16)))
    return out,span,counter[0]


def _block_times(rpc,blocks):
    blocks=sorted(set(int(x) for x in blocks))
    out={}
    for i in range(0,len(blocks),20):
        part=blocks[i:i+20]
        rows=rpc.batch(
            [("eth_getBlockByNumber",[hex(b),False]) for b in part],
            scope="history_headers",
        )
        for b,row in zip(part,rows):
            if not row or int(row["number"],16)!=b:
                raise BoundaryError("ramses_historical_header_identity")
            out[b]=int(row["timestamp"],16)
    return out


def _windows(swaps):
    by=defaultdict(list)
    for row in swaps:
        by[(row["pool"],row["timestamp"]//WINDOW_SECONDS)].append(row)
    out=[]
    for (pool,bucket),rows in by.items():
        rows=sorted(rows,key=lambda r:(r["block"],r["transaction_index"],r["log_index"]))
        volume=sum(r["volume_y"] for r in rows)
        fees=sum(r["lp_fee_y"] for r in rows)
        side=[sum(r["volume_y"] for r in rows if r["direction"]==d) for d in (0,1)]
        path=[r["bin_id"] for r in rows]
        gross=sum(abs(b-a) for a,b in zip(path,path[1:]))
        net=abs(path[-1]-path[0]) if len(path)>1 else 0
        two_way=(min(side)/volume if volume>0 else 0.0)
        out.append(dict(
            pool=pool,start=bucket*WINDOW_SECONDS,end=(bucket+1)*WINDOW_SECONDS,
            swap_count=len(rows),volume_y=volume,lp_fee_y=fees,
            lp_fee_bps=(fees*10000/volume if volume>0 else None),
            side_volume_y=side,two_way_share=two_way,
            flow_imbalance=(abs(side[0]-side[1])/volume if volume>0 else 1.0),
            gross_bin_crossings=gross,net_displacement_bins=net,
            chop_ratio=(gross/(1+net)),
            first_bin=path[0],last_bin=path[-1],
            block_start=rows[0]["block"],block_end=rows[-1]["block"],
        ))
    out.sort(key=lambda r:(r["start"],r["pool"]))
    return out


def main():
    endpoint=os.environ.get("MM_ROBINHOOD_READ_RPC_URL","")
    rpc=BoundedMultiRpc(
        endpoint,max_sessions=120,batch_size=20,batch_pause=0.15,
        rate_retries=3,rate_cooldown=4.0,adaptive_batch_floor=2,
    )
    rpc.verify_chain()
    frontier=rpc.call("eth_getBlockByNumber",["finalized",False],scope="history_identity")
    head=int(frontier["number"],16)
    head_ts=int(frontier["timestamp"],16)

    factory_pin=load("ramses_factory")
    factory=factory_pin["address"]
    factory_code=rpc.call("eth_getCode",[factory,hex(head)],scope="history_identity")
    factory_auth=authenticate("ramses_factory",factory,factory_code)
    deployment=_first_code_block(rpc,factory,head)
    deployment_header=rpc.call("eth_getBlockByNumber",[hex(deployment),False],scope="history_identity")

    addresses=_enumerate_factory(
        rpc,factory,head,factory_runtime_sha256=factory_auth["runtime_sha256"]
    )
    codes=rpc.batch(
        [("eth_getCode",[a,hex(head)]) for a in addresses],scope="history_identity"
    )
    meta={}
    for a,code in zip(addresses,codes):
        auth=authenticate_pool(code,factory_member=True)
        meta[a.lower()]=dict(
            token_x=auth["token_x"].lower(),token_y=auth["token_y"].lower(),
            bin_step=int(auth["bin_step"]),
        )

    logs,accepted_span,log_calls=_all_logs(rpc,deployment,head,addresses)
    times=_block_times(rpc,[int(e["blockNumber"],16) for e in logs])

    abi=load("ramses_pool_implementation")["abi"]
    swaps=[]
    per_pool=defaultdict(list)
    for e in logs:
        if e.get("removed"):
            raise BoundaryError("ramses_historical_removed_log")
        pool=e["address"].lower()
        if pool not in meta:
            raise BoundaryError("ramses_historical_unknown_pool")
        d=decode_ramses_event(abi,e)
        if d["name"]!="Swap":
            raise BoundaryError("ramses_historical_topic_decode")
        a=d["args"];bid=int(a["id"]);step=meta[pool]["bin_step"]
        amount_in=unpack(a["amountsIn"])
        protocol=unpack(a.get("protocolFees",0))
        total=unpack(a.get("totalFees",0))
        gross=[amount_in[0]+protocol[0],amount_in[1]+protocol[1]]
        lp=[total[0]-protocol[0],total[1]-protocol[1]]
        p=price(bid,step)
        volume=quote_value(gross,p,"y")
        fee=quote_value(lp,p,"y")
        direction=0 if gross[0]>0 and gross[1]==0 else 1 if gross[1]>0 and gross[0]==0 else -1
        if direction<0:
            raise BoundaryError("ramses_historical_swap_direction")
        row=dict(
            pool=pool,block=int(e["blockNumber"],16),timestamp=times[int(e["blockNumber"],16)],
            transaction_hash=e["transactionHash"],
            transaction_index=int(e["transactionIndex"],16),log_index=int(e["logIndex"],16),
            bin_id=bid,bin_step_bps=step,direction=direction,
            volume_y=int(volume),lp_fee_y=int(fee),
            lp_fee_bps=(fee*10000/volume if volume>0 else None),
        )
        swaps.append(row);per_pool[pool].append(row)

    windows=_windows(swaps)
    active_windows=[r for r in windows if r["swap_count"]>=2]
    candidate_windows=[r for r in active_windows if r["swap_count"]>=3 and r["two_way_share"]>0]

    pool_summary=[]
    for pool,rows in per_pool.items():
        rows=sorted(rows,key=lambda r:(r["timestamp"],r["block"],r["log_index"]))
        vol=sum(r["volume_y"] for r in rows);fee=sum(r["lp_fee_y"] for r in rows)
        side=[sum(r["volume_y"] for r in rows if r["direction"]==d) for d in (0,1)]
        pool_windows=[w for w in active_windows if w["pool"]==pool]
        pool_summary.append(dict(
            pool=pool,**meta[pool],swap_count=len(rows),
            first_swap_time=rows[0]["timestamp"],last_swap_time=rows[-1]["timestamp"],
            active_days=len(set(r["timestamp"]//86400 for r in rows)),
            volume_y=vol,lp_fee_y=fee,
            lp_fee_bps=(fee*10000/vol if vol else None),
            two_way_share=(min(side)/vol if vol else 0.0),
            active_5m_windows=len(pool_windows),
            two_way_5m_windows=sum(w["two_way_share"]>0 for w in pool_windows),
        ))
    pool_summary.sort(key=lambda r:(r["swap_count"],r["last_swap_time"]),reverse=True)

    report=dict(
        kind="ramses_dlmm_historical_market_census_v1",
        research_only=True,allocation_authority=False,
        existing_strategy_policy_used=False,
        chain_id=4663,
        factory=factory.lower(),
        factory_deployment_block=deployment,
        factory_deployment_timestamp=int(deployment_header["timestamp"],16),
        cutoff_block=head,cutoff_timestamp=head_ts,
        factory_pool_count=len(addresses),
        accepted_log_span_blocks=accepted_span,
        log_logical_calls=log_calls,
        swap_events=len(swaps),
        active_pools=len(per_pool),
        active_5m_windows=len(active_windows),
        candidate_two_way_5m_windows=len(candidate_windows),
        window_seconds=WINDOW_SECONDS,
        distributions=dict(
            swaps_per_active_pool=dict(
                median=_q([r["swap_count"] for r in pool_summary],0.5),
                p90=_q([r["swap_count"] for r in pool_summary],0.9),
                p99=_q([r["swap_count"] for r in pool_summary],0.99),
            ),
            active_window_swap_count=dict(
                median=_q([r["swap_count"] for r in active_windows],0.5),
                p90=_q([r["swap_count"] for r in active_windows],0.9),
                p99=_q([r["swap_count"] for r in active_windows],0.99),
            ),
            two_way_share=dict(
                median=_q([r["two_way_share"] for r in candidate_windows],0.5),
                p75=_q([r["two_way_share"] for r in candidate_windows],0.75),
                p90=_q([r["two_way_share"] for r in candidate_windows],0.9),
            ),
            chop_ratio=dict(
                median=_q([r["chop_ratio"] for r in candidate_windows],0.5),
                p75=_q([r["chop_ratio"] for r in candidate_windows],0.75),
                p90=_q([r["chop_ratio"] for r in candidate_windows],0.9),
            ),
            lp_fee_bps=dict(
                median=_q([r["lp_fee_bps"] for r in active_windows],0.5),
                p75=_q([r["lp_fee_bps"] for r in active_windows],0.75),
                p90=_q([r["lp_fee_bps"] for r in active_windows],0.9),
                p99=_q([r["lp_fee_bps"] for r in active_windows],0.99),
            ),
        ),
        pools=pool_summary,
        candidate_windows=sorted(
            candidate_windows,
            key=lambda r:(r["swap_count"],r["two_way_share"],r["chop_ratio"]),
            reverse=True,
        )[:2000],
        provider=rpc.telemetry(),
    )
    REPORT.write_text(json.dumps(report,sort_keys=True,separators=(",",":")))
    with gzip.open(SWAPS,"wt",encoding="utf-8") as fh:
        json.dump(dict(meta=meta,swaps=swaps,windows=windows),fh,separators=(",",":"))
    print(json.dumps(dict(
        status="complete",factory_pools=len(addresses),active_pools=len(per_pool),
        swaps=len(swaps),active_windows=len(active_windows),
        two_way_windows=len(candidate_windows),deployment_block=deployment,
        cutoff_block=head,accepted_log_span=accepted_span,log_calls=log_calls,
    ),sort_keys=True))


if __name__=="__main__":
    main()
