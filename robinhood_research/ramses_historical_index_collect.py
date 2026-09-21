"""Collect full indexed Ramses DLMM history for blank-slate research.

The Kingdom index is a discovery/cross-check source. Exact strategy outcomes are
subsequently reauthenticated from chain state and receipts.
"""
from __future__ import annotations
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip, json, math, statistics, time, urllib.request
from pathlib import Path

ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
CHAIN_ID=4663
START=1784678400  # 2026-07-22 UTC; index start used by DefiLlama's Ramses DLMM adapter.
DAY=86400
LIMIT=1000
RAW=Path("ramses-historical-index-data.json.gz")
SUMMARY=Path("ramses-historical-index-summary.json")

SWAP_FIELDS="""id timestamp pool transaction activeId amountUSD amountXIn amountXOut amountYIn amountYOut
protocolFeesX protocolFeesY totalFeesX totalFeesY tokenX tokenY volatilityAccumulator"""
FEE_FIELDS="""id timestamp pool poolAddress transaction blockNumber binId binTotalSupply eventType attributedToLiquidity
lpFeesUSD protocolFeesUSD totalFeesUSD lpFeesX lpFeesY protocolFeesX protocolFeesY totalFeesX totalFeesY tokenX tokenY"""
POOL_FIELDS="""id address symbol tokenX tokenY activeId binStep baseFactor protocolShare filterPeriod decayPeriod
reductionFactor variableFeeControl maxVolatilityAccumulator totalValueLockedUSD volumeUSD feesUSD"""
DAY_FIELDS="id startOfDay tvlUSD volumeUSD feesUSD voterFeesUSD treasuryFeesUSD"

def gql(query,variables=None):
    body=json.dumps({"query":query,"variables":variables or {}}).encode()
    req=urllib.request.Request(ENDPOINT,data=body,headers={
        "Content-Type":"application/json","Accept":"application/json",
        "User-Agent":"meme-machine-ramses-history/1",
    })
    with urllib.request.urlopen(req,timeout=60) as r:
        payload=json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError("graphql:"+json.dumps(payload["errors"],sort_keys=True))
    return payload["data"]

def paginate(root,fields,where,variables,order="id:asc"):
    rows=[];offset=0
    while True:
        q=f"""query($limit:Int!,$offset:Int!,$from:String!,$to:String!){{
          {root}(limit:$limit,offset:$offset,where:{where},order_by:{{{order}}}){{{fields}}}
        }}"""
        data=gql(q,{**variables,"limit":LIMIT,"offset":offset})[root]
        rows.extend(data)
        if len(data)<LIMIT:return rows
        offset+=LIMIT
        time.sleep(0.05)

def fetch_day(root,fields,start,end):
    where=f"""{{chainId:{{_eq:{CHAIN_ID}}},timestamp:{{_gte:$from,_lt:$to}}}}"""
    return paginate(root,fields,where,{"from":str(start),"to":str(end)})

def fetch_pools():
    q=f"""query($limit:Int!,$offset:Int!){{
      DLMMPool(limit:$limit,offset:$offset,where:{{chainId:{{_eq:{CHAIN_ID}}}}},order_by:{{id:asc}}){{{POOL_FIELDS}}}
    }}"""
    rows=[];offset=0
    while True:
        data=gql(q,{"limit":LIMIT,"offset":offset})["DLMMPool"]
        rows.extend(data)
        if len(data)<LIMIT:return rows
        offset+=LIMIT

def fetch_days():
    q=f"""query($limit:Int!,$offset:Int!){{
      DLMMProtocolDayData(limit:$limit,offset:$offset,where:{{chainId:{{_eq:{CHAIN_ID}}}}},order_by:{{startOfDay:asc}}){{{DAY_FIELDS}}}
    }}"""
    rows=[];offset=0
    while True:
        data=gql(q,{"limit":LIMIT,"offset":offset})["DLMMProtocolDayData"]
        rows.extend(data)
        if len(data)<LIMIT:return rows
        offset+=LIMIT

def f(x):
    try:return float(x or 0)
    except (TypeError,ValueError):return 0.0

def i(x):
    try:return int(x)
    except (TypeError,ValueError):return 0

def qtile(values,q):
    xs=sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not xs:return None
    if len(xs)==1:return xs[0]
    p=(len(xs)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)

def windows(swaps,fees,pools,seconds=300):
    pool_meta={str(p.get("address") or "").lower():p for p in pools}
    fee_by=defaultdict(float)
    for e in fees:
        pool=str(e.get("poolAddress") or "").lower()
        bucket=i(e.get("timestamp"))//seconds
        if e.get("attributedToLiquidity") is not False:
            fee_by[(pool,bucket)]+=f(e.get("lpFeesUSD"))
    grouped=defaultdict(list)
    first_swap={}
    for s in swaps:
        pool=str(s.get("pool") or "").split(":")[-1].lower()
        ts=i(s.get("timestamp"));bucket=ts//seconds
        grouped[(pool,bucket)].append(s)
        first_swap[pool]=min(first_swap.get(pool,ts),ts)
    out=[]
    for (pool,bucket),rows in grouped.items():
        rows=sorted(rows,key=lambda r:(i(r.get("timestamp")),str(r.get("transaction")),str(r.get("id"))))
        volume=sum(f(r.get("amountUSD")) for r in rows)
        side=[0.0,0.0];unknown=0
        ids=[]
        for r in rows:
            x=f(r.get("amountXIn"));y=f(r.get("amountYIn"));v=f(r.get("amountUSD"))
            if x>0 and y==0:side[0]+=v
            elif y>0 and x==0:side[1]+=v
            else:unknown+=1
            ids.append(i(r.get("activeId")))
        gross=sum(abs(b-a) for a,b in zip(ids,ids[1:]))
        net=abs(ids[-1]-ids[0]) if len(ids)>1 else 0
        meta=pool_meta.get(pool) or {}
        step=i(meta.get("binStep"))
        lp=fee_by.get((pool,bucket),0.0)
        out.append(dict(
            pool=pool,symbol=meta.get("symbol"),start=bucket*seconds,end=(bucket+1)*seconds,
            pool_age_seconds=bucket*seconds-first_swap[pool],
            swap_count=len(rows),transaction_count=len({r.get("transaction") for r in rows}),
            volume_usd=volume,lp_fees_usd=lp,
            lp_fee_bps=(lp*10000/volume if volume>0 else None),
            x_in_volume_usd=side[0],y_in_volume_usd=side[1],
            two_way_share=(min(side)/volume if volume>0 else 0.0),
            flow_imbalance=(abs(side[0]-side[1])/volume if volume>0 else 1.0),
            unknown_direction_swaps=unknown,
            first_active_id=ids[0],last_active_id=ids[-1],
            min_active_id=min(ids),max_active_id=max(ids),
            gross_bin_travel=gross,net_bin_displacement=net,
            gross_travel_bps=gross*step,net_displacement_bps=net*step,
            chop_ratio=gross/(1+net),
            bin_step_bps=step,
            volatility_accumulator_median=qtile([i(r.get("volatilityAccumulator")) for r in rows],.5),
            volatility_accumulator_max=max(i(r.get("volatilityAccumulator")) for r in rows),
        ))
    out.sort(key=lambda r:(r["start"],r["pool"]))
    return out

def main():
    cutoff=int(time.time())+1
    swaps=[];fees=[]
    ranges=[];cursor=START
    while cursor<cutoff:
        end=min(cutoff,cursor+DAY);ranges.append((cursor,end));cursor=end
    def one_day(pair):
        start,end=pair
        return start,fetch_day("DLMMSwap",SWAP_FIELDS,start,end),fetch_day("DLMMFeeEvent",FEE_FIELDS,start,end)
    completed=0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures=[ex.submit(one_day,pair) for pair in ranges]
        for future in as_completed(futures):
            start,s,e=future.result()
            swaps.extend(s);fees.extend(e);completed+=1
            print(json.dumps(dict(day=start,swaps=len(s),fees=len(e),days_complete=completed,total_days=len(ranges),
                                  cumulative_swaps=len(swaps))),flush=True)
    swaps.sort(key=lambda r:(i(r.get("timestamp")),str(r.get("transaction")),str(r.get("id"))))
    fees.sort(key=lambda r:(i(r.get("timestamp")),i(r.get("blockNumber")),str(r.get("id"))))
    pools=fetch_pools();days=fetch_days()
    ws5=windows(swaps,fees,pools,300)
    ws15=windows(swaps,fees,pools,900)
    ws30=windows(swaps,fees,pools,1800)
    active5=[x for x in ws5 if x["swap_count"]>=2]
    two5=[x for x in active5 if x["swap_count"]>=3 and x["two_way_share"]>0]
    summary=dict(
        kind="ramses_dlmm_indexed_history_v1",research_only=True,
        existing_strategy_policy_used=False,chain_id=CHAIN_ID,
        start_timestamp=START,cutoff_timestamp=cutoff,
        swaps=len(swaps),fee_events=len(fees),pools=len(pools),
        protocol_days=len(days),
        distinct_active_pools=len({str(x.get("pool") or "").split(":")[-1].lower() for x in swaps}),
        active_5m_windows=len(active5),two_way_5m_windows=len(two5),
        distributions=dict(
            swap_volume_usd={q:qtile([f(x.get("amountUSD")) for x in swaps],v) for q,v in [("p50",.5),("p75",.75),("p90",.9),("p99",.99)]},
            active_5m_swap_count={q:qtile([x["swap_count"] for x in active5],v) for q,v in [("p50",.5),("p75",.75),("p90",.9),("p99",.99)]},
            two_way_share={q:qtile([x["two_way_share"] for x in two5],v) for q,v in [("p50",.5),("p75",.75),("p90",.9)]},
            chop_ratio={q:qtile([x["chop_ratio"] for x in two5],v) for q,v in [("p50",.5),("p75",.75),("p90",.9)]},
            lp_fee_bps={q:qtile([x["lp_fee_bps"] for x in active5 if x["lp_fee_bps"] is not None],v) for q,v in [("p50",.5),("p75",.75),("p90",.9),("p99",.99)]},
        ),
        top_two_way_windows=sorted(two5,key=lambda x:(x["lp_fees_usd"],x["volume_usd"],x["swap_count"]),reverse=True)[:500],
        pool_snapshot=sorted(pools,key=lambda x:f(x.get("feesUSD")),reverse=True),
        protocol_day_data=days,
    )
    SUMMARY.write_text(json.dumps(summary,indent=2,sort_keys=True))
    with gzip.open(RAW,"wt",encoding="utf-8") as fh:
        json.dump(dict(swaps=swaps,fee_events=fees,pools=pools,protocol_days=days,
                       windows_5m=ws5,windows_15m=ws15,windows_30m=ws30),fh,separators=(",",":"))
    print(json.dumps(dict(status="complete",swaps=len(swaps),fees=len(fees),pools=len(pools),
                         active_5m=len(active5),two_way_5m=len(two5)),sort_keys=True))
if __name__=="__main__":main()
