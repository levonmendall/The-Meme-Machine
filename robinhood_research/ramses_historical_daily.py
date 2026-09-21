"""Fetch complete Ramses DLMM daily protocol history from the public index."""
import json, urllib.request
from pathlib import Path
ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
OUT=Path("ramses-historical-daily.json")
def gql(q):
    req=urllib.request.Request(ENDPOINT,data=json.dumps({"query":q}).encode(),
      headers={"Content-Type":"application/json","Accept":"application/json","User-Agent":"meme-machine-ramses-daily/1"})
    with urllib.request.urlopen(req,timeout=60) as r:p=json.loads(r.read())
    if p.get("errors"):raise RuntimeError(json.dumps(p["errors"]))
    return p["data"]
def main():
    q='''query{DLMMProtocolDayData(limit:1000,where:{chainId:{_eq:4663}},order_by:{startOfDay:asc}){startOfDay tvlUSD volumeUSD feesUSD voterFeesUSD treasuryFeesUSD}}'''
    rows=gql(q)["DLMMProtocolDayData"]
    for r in rows:
        for k in ("tvlUSD","volumeUSD","feesUSD","voterFeesUSD","treasuryFeesUSD"):
            try:r[k]=float(r.get(k) or 0)
            except:r[k]=0
        tvl=r["tvlUSD"];r["volume_to_tvl"]=r["volumeUSD"]/tvl if tvl>0 else None
        r["fee_to_tvl"]=r["feesUSD"]/tvl if tvl>0 else None
        r["fee_bps_on_volume"]=r["feesUSD"]/r["volumeUSD"]*10000 if r["volumeUSD"]>0 else None
    OUT.write_text(json.dumps({"kind":"ramses_dlmm_daily_history_v1","rows":rows},indent=2,sort_keys=True))
    print(json.dumps({"days":len(rows),"volume":sum(r["volumeUSD"] for r in rows),"fees":sum(r["feesUSD"] for r in rows),
                      "max_day_volume":max((r["volumeUSD"] for r in rows),default=0),
                      "max_day_fees":max((r["feesUSD"] for r in rows),default=0)},sort_keys=True))
if __name__=="__main__":main()
