"""Collect Ramses DLMM indexed LP position/liquidity history for blank-slate research."""
from __future__ import annotations
from collections import Counter
import gzip, json, time, urllib.request
from pathlib import Path

ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
CHAIN_ID=4663
START=1784678400
DAY=86400
LIMIT=1000
MAX_ROWS=2_000_000
RAW=Path("ramses-historical-position-data.json.gz")
SUMMARY=Path("ramses-historical-position-summary.json")

def gql(query,variables=None):
    body=json.dumps({"query":query,"variables":variables or {}}).encode()
    req=urllib.request.Request(ENDPOINT,data=body,headers={
        "Content-Type":"application/json","Accept":"application/json",
        "User-Agent":"meme-machine-ramses-position-history/1",
    })
    with urllib.request.urlopen(req,timeout=60) as r:
        payload=json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError("graphql:"+json.dumps(payload["errors"],sort_keys=True))
    return payload["data"]

def keyset(root,fields):
    rows=[];after=""
    while True:
        q=f"""query($n:Int!,$after:String!){{{root}(limit:$n,where:{{chainId:{{_eq:{CHAIN_ID}}},id:{{_gt:$after}}}},order_by:{{id:asc}}){{{fields}}}}}"""
        part=gql(q,{"n":LIMIT,"after":after})[root]
        rows.extend(part)
        if len(rows)>MAX_ROWS:raise RuntimeError(root+"_row_capacity")
        if len(part)<LIMIT:return rows
        after=str(part[-1]["id"])
        print(json.dumps({"table":root,"rows":len(rows),"after":after}),flush=True)

def day_events(root,fields):
    rows=[];cursor=START;cutoff=int(time.time())+1
    while cursor<cutoff:
        end=min(cutoff,cursor+DAY);offset=0
        while True:
            q=f"""query($n:Int!,$offset:Int!,$from:String!,$to:String!){{{root}(limit:$n,offset:$offset,where:{{chainId:{{_eq:{CHAIN_ID}}},timestamp:{{_gte:$from,_lt:$to}}}},order_by:{{id:asc}}){{{fields}}}}}"""
            part=gql(q,{"n":LIMIT,"offset":offset,"from":str(cursor),"to":str(end)})[root]
            rows.extend(part)
            if len(rows)>MAX_ROWS:raise RuntimeError(root+"_row_capacity")
            if len(part)<LIMIT:break
            offset+=LIMIT
        print(json.dumps({"table":root,"day":cursor,"rows":len(rows)}),flush=True)
        cursor=end
    return rows

def f(x):
    try:return float(x or 0)
    except (TypeError,ValueError):return 0.0

def main():
    positions=keyset("DLMMPosition","chainId id owner pool liquidity lastModifiedBlockNumber lastModifiedLogIndex lastModifiedTimestamp")
    binsets=keyset("DLMMPositionBinSet","chainId id owner pool poolAddress binIds lastUpdatedBlockNumber lastUpdatedLogIndex lastUpdatedTimestamp")
    versions=keyset("DLMMUserBinLiquidityVersion","chainId id entityId owner pool binId liquidity isActive stateHash validFromBlock validFromLogIndex validToBlock validToLogIndex")
    fee_positions=keyset("DLMMUserBinFeePosition","chainId id owner pool poolAddress binId liquidity settledFeesTokenX settledFeesTokenY settledFeesXRaw settledFeesYRaw feeGrowthX128Checkpoint feeGrowthY128Checkpoint lastSettledBlockNumber lastSettledLogIndex lastSettledTimestamp tokenX tokenY")
    mints=day_events("DLMMMint","chainId id timestamp pool transaction logIndex sender recipient amountUSD binIds amountsX amountsY totalAmountX totalAmountY")
    burns=day_events("DLMMBurn","chainId id timestamp pool transaction logIndex sender recipient amountUSD binIds amountsX amountsY totalAmountX totalAmountY")
    collections=day_events("DLMMFeeCollection","chainId id timestamp pool transaction logIndex amountUSD feeDistAmountX feeDistAmountY treasuryAmountX treasuryAmountY")

    owners={str(x.get("owner") or "").lower() for x in positions if x.get("owner")}
    pools={str(x.get("pool") or "").split(":")[-1].lower() for x in positions if x.get("pool")}
    closed=[x for x in positions if f(x.get("liquidity"))==0]
    summary=dict(
        kind="ramses_dlmm_indexed_lp_history_v1",research_only=True,
        existing_strategy_policy_used=False,chain_id=CHAIN_ID,start_timestamp=START,
        cutoff_timestamp=int(time.time()),positions=len(positions),owners=len(owners),
        position_pools=len(pools),closed_positions=len(closed),
        open_positions=len(positions)-len(closed),position_bin_sets=len(binsets),
        liquidity_versions=len(versions),fee_positions=len(fee_positions),
        mints=len(mints),burns=len(burns),fee_collections=len(collections),
        mint_usd=sum(f(x.get("amountUSD")) for x in mints),
        burn_usd=sum(f(x.get("amountUSD")) for x in burns),
        fee_collection_usd=sum(f(x.get("amountUSD")) for x in collections),
        distinct_mint_recipients=len({str(x.get("recipient") or "").lower() for x in mints if x.get("recipient")}),
        distinct_burn_senders=len({str(x.get("sender") or "").lower() for x in burns if x.get("sender")}),
        version_owner_count=len({str(x.get("owner") or "").lower() for x in versions if x.get("owner")}),
        version_pool_count=len({str(x.get("pool") or "").split(":")[-1].lower() for x in versions if x.get("pool")}),
        version_bins_per_owner_pool=dict(Counter(
            min(1000,sum(1 for y in versions if y.get("owner")==x.get("owner") and y.get("pool")==x.get("pool")))
            for x in positions[:0]
        )),
    )
    SUMMARY.write_text(json.dumps(summary,indent=2,sort_keys=True))
    with gzip.open(RAW,"wt",encoding="utf-8") as fh:
        json.dump(dict(positions=positions,position_bin_sets=binsets,
                       liquidity_versions=versions,fee_positions=fee_positions,
                       mints=mints,burns=burns,fee_collections=collections),
                  fh,separators=(",",":"))
    print(json.dumps({"status":"complete",**{k:summary[k] for k in
        ("positions","owners","closed_positions","liquidity_versions","mints","burns","fee_positions")}},sort_keys=True))

if __name__=="__main__":main()
