"""Sample Ramses DLMM indexed LP-position tables for historical strategy research."""
from __future__ import annotations
import json, urllib.request
from pathlib import Path

ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
CHAIN_ID=4663
OUT=Path("ramses-historical-position-sample.json")

def gql(query,variables=None):
    body=json.dumps({"query":query,"variables":variables or {}}).encode()
    req=urllib.request.Request(ENDPOINT,data=body,headers={
        "Content-Type":"application/json","Accept":"application/json",
        "User-Agent":"meme-machine-ramses-position-probe/1",
    })
    with urllib.request.urlopen(req,timeout=60) as r:
        payload=json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError("graphql:"+json.dumps(payload["errors"],sort_keys=True))
    return payload["data"]

QUERIES={
"DLMMPosition":"""query($n:Int!){DLMMPosition(limit:$n,where:{chainId:{_eq:4663}},order_by:{id:asc}){chainId id owner pool liquidity lastModifiedBlockNumber lastModifiedLogIndex lastModifiedTimestamp}}""",
"DLMMPositionBinSet":"""query($n:Int!){DLMMPositionBinSet(limit:$n,where:{chainId:{_eq:4663}},order_by:{id:asc}){chainId id owner pool poolAddress binIds lastUpdatedBlockNumber lastUpdatedLogIndex lastUpdatedTimestamp}}""",
"DLMMUserBinLiquidityVersion":"""query($n:Int!){DLMMUserBinLiquidityVersion(limit:$n,where:{chainId:{_eq:4663}},order_by:{validFromBlock:asc}){chainId id entityId owner pool binId liquidity isActive stateHash validFromBlock validFromLogIndex validToBlock validToLogIndex}}""",
"DLMMUserBinFeePosition":"""query($n:Int!){DLMMUserBinFeePosition(limit:$n,where:{chainId:{_eq:4663}},order_by:{id:asc}){chainId id owner pool poolAddress binId liquidity settledFeesTokenX settledFeesTokenY settledFeesXRaw settledFeesYRaw feeGrowthX128Checkpoint feeGrowthY128Checkpoint lastSettledBlockNumber lastSettledLogIndex lastSettledTimestamp tokenX tokenY}}""",
"DLMMMint":"""query($n:Int!){DLMMMint(limit:$n,where:{chainId:{_eq:4663}},order_by:{timestamp:asc}){chainId id timestamp pool transaction logIndex sender recipient amountUSD binIds amountsX amountsY totalAmountX totalAmountY}}""",
"DLMMBurn":"""query($n:Int!){DLMMBurn(limit:$n,where:{chainId:{_eq:4663}},order_by:{timestamp:asc}){chainId id timestamp pool transaction logIndex sender recipient amountUSD binIds amountsX amountsY totalAmountX totalAmountY}}""",
"DLMMFeeCollection":"""query($n:Int!){DLMMFeeCollection(limit:$n,where:{chainId:{_eq:4663}},order_by:{timestamp:asc}){chainId id timestamp pool transaction logIndex amountUSD feeDistAmountX feeDistAmountY treasuryAmountX treasuryAmountY}}""",
"DLMMPoolHourData":"""query($n:Int!){DLMMPoolHourData(limit:$n,where:{chainId:{_eq:4663}},order_by:{startOfHour:asc}){chainId id pool startOfHour tvlUSD volumeUSD feesUSD treasuryFeesUSD voterFeesUSD totalValueLockedTokenX totalValueLockedTokenY volumeTokenX volumeTokenY}}""",
"DLMMBinFeeVolumeGrowthHour":"""query($n:Int!){DLMMBinFeeVolumeGrowthHour(limit:$n,where:{chainId:{_eq:4663}},order_by:{startOfHour:asc}){chainId id pool poolAddress binId startOfHour eventCount feeGrowthX128 feeGrowthY128 feeUSDPerLiquidityX128 volumeUSDPerLiquidityX128 firstBlockNumber firstLogIndex lastBlockNumber lastLogIndex tokenX tokenY}}"""
}

def main():
    out={}
    for root,q in QUERIES.items():
        rows=gql(q,{"n":5}).get(root,[])
        out[root]=rows
        print(json.dumps({"table":root,"rows":len(rows)},sort_keys=True),flush=True)
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps({"status":"complete","tables":len(out)},sort_keys=True))

if __name__=="__main__":main()
