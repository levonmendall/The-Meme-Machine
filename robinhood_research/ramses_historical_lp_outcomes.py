"""Collect and analyze clean historical Ramses DLMM LP lifecycles.

Discovery evidence only. One-mint/one-burn, fully closed owner/pool lifecycles are used
to avoid ambiguous capital attribution. Entry features use only completed pre-entry
pool-hour data.
"""
from __future__ import annotations
from collections import defaultdict
import json, math, statistics, urllib.request
from pathlib import Path

ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
CHAIN=4663
LIMIT=1000
OUT=Path("ramses-historical-lp-outcomes.json")

def gql(q,vars=None):
    req=urllib.request.Request(ENDPOINT,data=json.dumps({"query":q,"variables":vars or {}}).encode(),
      headers={"Content-Type":"application/json","Accept":"application/json","User-Agent":"meme-machine-ramses-lp-history/1"})
    with urllib.request.urlopen(req,timeout=60) as r:p=json.loads(r.read())
    if p.get("errors"):raise RuntimeError("graphql:"+json.dumps(p["errors"],sort_keys=True))
    return p["data"]

def page(root,fields,where):
    rows=[];offset=0
    while True:
        q=f"""query($limit:Int!,$offset:Int!){{{root}(limit:$limit,offset:$offset,where:{where},order_by:{{id:asc}}){{{fields}}}}}"""
        part=gql(q,{"limit":LIMIT,"offset":offset})[root]
        rows.extend(part)
        if len(part)<LIMIT:return rows
        offset+=LIMIT

def f(v):
    try:return float(v or 0)
    except:return 0.0
def i(v):
    try:return int(v)
    except:return 0
def addr(v):return str(v or "").split(":")[-1].lower()
def qtile(vs,q):
    xs=sorted(float(x) for x in vs if x is not None and math.isfinite(float(x)))
    if not xs:return None
    if len(xs)==1:return xs[0]
    p=(len(xs)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)

def main():
    mints=page("DLMMMint","id timestamp pool recipient sender amountUSD totalAmountX totalAmountY binIds amountsX amountsY transaction logIndex",
               f"{{chainId:{{_eq:{CHAIN}}}}}")
    burns=page("DLMMBurn","id timestamp pool recipient sender amountUSD totalAmountX totalAmountY binIds amountsX amountsY transaction logIndex",
               f"{{chainId:{{_eq:{CHAIN}}}}}")
    positions=page("DLMMPosition","id owner pool liquidity lastModifiedTimestamp lastModifiedBlockNumber lastModifiedLogIndex",
                   f"{{chainId:{{_eq:{CHAIN}}}}}")
    current=page("DLMMUserBinLiquidity","id owner pool binId liquidity",f"{{chainId:{{_eq:{CHAIN}}}}}")
    hours=page("DLMMPoolHourData","id pool startOfHour tvlUSD volumeUSD feesUSD totalValueLockedTokenX totalValueLockedTokenY volumeTokenX volumeTokenY",
               f"{{chainId:{{_eq:{CHAIN}}}}}")
    pools=page("DLMMPool","id address symbol tokenX tokenY binStep baseFactor protocolShare filterPeriod decayPeriod variableFeeControl maxVolatilityAccumulator",
               f"{{chainId:{{_eq:{CHAIN}}}}}")

    poolmeta={addr(p["address"]):p for p in pools}
    by_hour={(addr(h["pool"]),i(h["startOfHour"])):h for h in hours}
    first_hour={}
    for h in hours:
        p=addr(h["pool"]);ts=i(h["startOfHour"])
        if f(h.get("volumeUSD"))>0 or f(h.get("tvlUSD"))>0:
            first_hour[p]=min(first_hour.get(p,ts),ts)

    mintg=defaultdict(list);burng=defaultdict(list)
    for r in mints:mintg[(str(r.get("recipient") or "").lower(),addr(r.get("pool")))].append(r)
    for r in burns:burng[(str(r.get("sender") or "").lower(),addr(r.get("pool")))].append(r)
    open_liq=defaultdict(float)
    for r in current:
        liq=f(r.get("liquidity"))
        if liq>0:open_liq[(str(r.get("owner") or "").lower(),addr(r.get("pool")))]+=liq
    pos_liq={(str(r.get("owner") or "").lower(),addr(r.get("pool"))):f(r.get("liquidity")) for r in positions}

    clean=[]
    keys=set(mintg)|set(burng)
    for key in keys:
        ms=mintg.get(key,[]);bs=burng.get(key,[])
        if len(ms)!=1 or len(bs)!=1:continue
        m,b=ms[0],bs[0]
        mt,bt=i(m.get("timestamp")),i(b.get("timestamp"))
        dep,wd=f(m.get("amountUSD")),f(b.get("amountUSD"))
        if mt<=0 or bt<=mt or dep<=0 or wd<0:continue
        if open_liq.get(key,0)>0 or pos_liq.get(key,0)>0:continue
        mb=[i(x) for x in (m.get("binIds") or [])]
        bb=[i(x) for x in (b.get("binIds") or [])]
        if not mb or not bb:continue
        if set(mb)!=set(bb):continue
        hour=(mt//3600)*3600
        prev=by_hour.get((key[1],hour-3600))
        if not prev:continue
        tvl=f(prev.get("tvlUSD"));vol=f(prev.get("volumeUSD"));fees=f(prev.get("feesUSD"))
        width=max(mb)-min(mb)+1
        x=f(m.get("totalAmountX"));y=f(m.get("totalAmountY"))
        sided="two_sided" if x>0 and y>0 else "x_only" if x>0 else "y_only" if y>0 else "unknown"
        ret=wd/dep-1
        clean.append(dict(
          owner=key[0],pool=key[1],symbol=(poolmeta.get(key[1]) or {}).get("symbol"),
          entry_timestamp=mt,exit_timestamp=bt,hold_seconds=bt-mt,
          deposit_usd=dep,withdrawal_usd=wd,gross_pnl_usd=wd-dep,gross_return=ret,
          width_bins=width,lower_bin=min(mb),upper_bin=max(mb),sidedness=sided,
          bin_step_bps=i((poolmeta.get(key[1]) or {}).get("binStep")),
          prev_hour_tvl_usd=tvl,prev_hour_volume_usd=vol,prev_hour_fees_usd=fees,
          prev_hour_volume_to_tvl=(vol/tvl if tvl>0 else None),
          prev_hour_fee_to_tvl=(fees/tvl if tvl>0 else None),
          prev_hour_fee_bps=(fees/vol*10000 if vol>0 else None),
          pool_age_seconds=(mt-first_hour[key[1]] if key[1] in first_hour else None),
        ))
    clean.sort(key=lambda r:(r["entry_timestamp"],r["owner"],r["pool"]))

    def summarize(rows):
        if not rows:return {}
        return dict(n=len(rows),pools=len({r["pool"] for r in rows}),owners=len({r["owner"] for r in rows}),
                    median_return=qtile([r["gross_return"] for r in rows],.5),
                    mean_return=sum(r["gross_return"] for r in rows)/len(rows),
                    win_rate=sum(r["gross_return"]>0 for r in rows)/len(rows),
                    p10_return=qtile([r["gross_return"] for r in rows],.1),
                    median_hold_seconds=qtile([r["hold_seconds"] for r in rows],.5),
                    median_width_bins=qtile([r["width_bins"] for r in rows],.5),
                    deployed_usd=sum(r["deposit_usd"] for r in rows),
                    pnl_usd=sum(r["gross_pnl_usd"] for r in rows))

    starts=[r["entry_timestamp"] for r in clean]
    lo=min(starts) if starts else 0;hi=max(starts)+1 if starts else 1;span=max(1,hi-lo)
    de=lo+int(span*.6);ve=lo+int(span*.8)
    for r in clean:r["split"]="derivation" if r["entry_timestamp"]<de else "validation" if r["entry_timestamp"]<ve else "holdout"

    width_buckets=[("<=3",0,3),("4-8",4,8),("9-16",9,16),("17-32",17,32),("33-64",33,64),("65+",65,10**9)]
    hold_buckets=[("<15m",0,900),("15-30m",900,1800),("30-60m",1800,3600),("1-2h",3600,7200),("2-4h",7200,14400),("4-12h",14400,43200),("12-24h",43200,86400),("24h+",86400,10**12)]
    analyses={}
    for split in ("derivation","validation","holdout"):
        rows=[r for r in clean if r["split"]==split]
        analyses[split]=dict(overall=summarize(rows),by_width={},by_hold={},by_sidedness={})
        for label,a,b in width_buckets:analyses[split]["by_width"][label]=summarize([r for r in rows if a<=r["width_bins"]<=b])
        for label,a,b in hold_buckets:analyses[split]["by_hold"][label]=summarize([r for r in rows if a<=r["hold_seconds"]<b])
        for label in ("x_only","y_only","two_sided"):analyses[split]["by_sidedness"][label]=summarize([r for r in rows if r["sidedness"]==label])

    out=dict(kind="ramses_dlmm_clean_actual_lp_outcomes_v1",research_only=True,
             interpretation="Gross realized LP cash-flow return before wallet gas. Fees are embedded in bin share value.",
             counts=dict(mints=len(mints),burns=len(burns),positions=len(positions),current_bin_liquidity=len(current),
                         pool_hours=len(hours),pools=len(pools),clean_lifecycles=len(clean)),
             split_bounds=dict(start=lo,derivation_end=de,validation_end=ve,end=hi),
             analyses=analyses,lifecycles=clean)
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps({"status":"complete","counts":out["counts"],"splits":{k:v["overall"] for k,v in analyses.items()}},sort_keys=True))
if __name__=="__main__":main()
