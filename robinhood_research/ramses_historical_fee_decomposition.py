"""Decompose realized Ramses LP returns into fee income vs inventory P&L.

Uses only derivation+validation lifecycle outcomes from the redacted signal join.
Holdout outcome fields remain unavailable and are never queried from the LP outcome artifact.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, InvalidOperation, getcontext
import gzip, json, math, urllib.request
from pathlib import Path

ENDPOINT="https://gateway.kingdom.dev/robinhood/subgraph/v1/graphql"
CHAIN=4663
LIMIT=1000
INDEX=Path("ramses-historical-index-data.json.gz")
FEE_SUPPLEMENT=Path("ramses-historical-fees-with-identity.json.gz")
JOIN=Path("ramses-historical-lp-signal-join.json")
OUT=Path("ramses-historical-fee-decomposition.json")
getcontext().prec=60

VERSION_FIELDS="id owner pool binId liquidity validFromBlock validFromLogIndex validToBlock validToLogIndex isActive"

def gql(query,variables=None):
    body=json.dumps({"query":query,"variables":variables or {}}).encode()
    req=urllib.request.Request(ENDPOINT,data=body,headers={
        "Content-Type":"application/json","Accept":"application/json",
        "User-Agent":"meme-machine-ramses-fee-decomposition/1",
    })
    with urllib.request.urlopen(req,timeout=60) as r:
        payload=json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError("graphql:"+json.dumps(payload["errors"],sort_keys=True))
    return payload["data"]

def page_versions():
    rows=[];offset=0
    while True:
        q=f"""query($limit:Int!,$offset:Int!){{DLMMUserBinLiquidityVersion(
          limit:$limit,offset:$offset,where:{{chainId:{{_eq:{CHAIN}}}}},order_by:{{id:asc}})
          {{{VERSION_FIELDS}}}}}"""
        part=gql(q,{"limit":LIMIT,"offset":offset})["DLMMUserBinLiquidityVersion"]
        rows.extend(part)
        if len(part)<LIMIT:return rows
        offset+=LIMIT

def addr(v):return str(v or "").split(":")[-1].lower()
def i(v):
    try:return int(v)
    except (TypeError,ValueError):return None
def f(v):
    try:return float(v)
    except (TypeError,ValueError):return None
def d(v):
    try:return Decimal(str(v or "0"))
    except (InvalidOperation,ValueError):return Decimal(0)

def event_key(block,log):
    b=i(block);l=i(log)
    if b is None or l is None:return None
    return (b,l)

def version_active(row,key):
    start=event_key(row.get("validFromBlock"),row.get("validFromLogIndex"))
    if start is None or key<start:return False
    vb=row.get("validToBlock");vl=row.get("validToLogIndex")
    if vb is None:return True
    end=event_key(vb,vl)
    return end is None or key<end

def qtile(values,q):
    xs=sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not xs:return None
    if len(xs)==1:return xs[0]
    p=(len(xs)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)

def summary(rows):
    if not rows:return {}
    return dict(
        n=len(rows),pools=len({r["pool"] for r in rows}),owners=len({r["owner"] for r in rows}),
        median_gross_return=qtile([r["gross_return"] for r in rows],.5),
        mean_gross_return=sum(r["gross_return"] for r in rows)/len(rows),
        median_fee_return=qtile([r["fee_return"] for r in rows],.5),
        mean_fee_return=sum(r["fee_return"] for r in rows)/len(rows),
        median_inventory_return=qtile([r["inventory_return"] for r in rows],.5),
        mean_inventory_return=sum(r["inventory_return"] for r in rows)/len(rows),
        gross_win_rate=sum(r["gross_return"]>0 for r in rows)/len(rows),
        fee_positive_rate=sum(r["fee_income_usd"]>0 for r in rows)/len(rows),
        total_deposit_usd=sum(r["deposit_usd"] for r in rows),
        total_gross_pnl_usd=sum(r["gross_pnl_usd"] for r in rows),
        total_fee_income_usd=sum(r["fee_income_usd"] for r in rows),
        total_inventory_pnl_usd=sum(r["inventory_pnl_usd"] for r in rows),
    )

def main():
    join=json.loads(JOIN.read_text())
    lifecycles=join.get("derivation_validation_rows") or []
    if not lifecycles or any(r.get("split")=="holdout" for r in lifecycles):
        raise RuntimeError("fee_decomposition_join_boundary")
    owners={str(r["owner"]).lower() for r in lifecycles}
    pools={addr(r["pool"]) for r in lifecycles}

    versions=page_versions()
    by_version=defaultdict(list)
    relevant_versions=0
    for v in versions:
        owner=str(v.get("owner") or "").lower();pool=addr(v.get("pool"));bid=i(v.get("binId"))
        if owner not in owners or pool not in pools or bid is None:continue
        by_version[(owner,pool,bid)].append(v);relevant_versions+=1
    for rows in by_version.values():
        rows.sort(key=lambda x:(i(x.get("validFromBlock")) or -1,i(x.get("validFromLogIndex")) or -1))

    with gzip.open(INDEX,"rt",encoding="utf-8") as fh:index=json.load(fh)
    if FEE_SUPPLEMENT.exists():
        with gzip.open(FEE_SUPPLEMENT,"rt",encoding="utf-8") as fh:
            fee_source=json.load(fh).get("fee_events") or []
        fee_source_kind="fee_identity_supplement"
    else:
        fee_source=index.get("fee_events") or []
        fee_source_kind="full_index"
    fee_by_pool=defaultdict(list)
    for e in fee_source:
        if e.get("attributedToLiquidity") is False:continue
        pool=addr(e.get("poolAddress") or e.get("pool"));bid=i(e.get("binId"))
        ts=i(e.get("timestamp"));key=event_key(e.get("blockNumber"),e.get("logIndexNumber") or e.get("logIndex"))
        lp=f(e.get("lpFeesUSD"));supply=d(e.get("binTotalSupply"))
        if pool in pools and bid is not None and ts is not None and key is not None and lp is not None and lp>0 and supply>0:
            fee_by_pool[pool].append((ts,key,bid,Decimal(str(lp)),supply))
    for rows in fee_by_pool.values():rows.sort()

    outrows=[];matched_events=0;eligible_events=0;unmatched_liquidity_events=0
    for life in lifecycles:
        owner=str(life["owner"]).lower();pool=addr(life["pool"])
        entry=i(life.get("entry_timestamp"));exit=i(life.get("exit_timestamp"))
        dep=f(life.get("deposit_usd"));gross=f(life.get("gross_pnl_usd"));gross_ret=f(life.get("gross_return"))
        if None in (entry,exit,dep,gross,gross_ret) or dep<=0:continue
        fee=Decimal(0);events=0;matched=0
        for ts,key,bid,lp,supply in fee_by_pool.get(pool,[]):
            if ts<entry:continue
            if ts>exit:break
            events+=1;eligible_events+=1
            active=[v for v in by_version.get((owner,pool,bid),[]) if version_active(v,key)]
            if len(active)!=1:
                if active:raise RuntimeError("fee_decomposition_ambiguous_user_liquidity")
                unmatched_liquidity_events+=1
                continue
            liq=d(active[0].get("liquidity"))
            if liq<=0:continue
            if liq>supply:
                raise RuntimeError("fee_decomposition_liquidity_exceeds_supply")
            fee+=lp*liq/supply;matched+=1;matched_events+=1
        fee_usd=float(fee)
        inventory=float(gross)-fee_usd
        row=dict(life)
        row.update(
            fee_income_usd=fee_usd,inventory_pnl_usd=inventory,
            fee_return=fee_usd/dep,inventory_return=inventory/dep,
            fee_events_in_lifecycle=events,fee_events_with_user_liquidity=matched,
            fee_attribution_complete=(events==matched),
        )
        outrows.append(row)

    analyses={}
    for split in ("derivation","validation"):
        sr=[r for r in outrows if r.get("split")==split]
        quiet=[r for r in sr if (r.get("pre_1800s") or {}).get("swap_count",999)<=2]
        active=[r for r in sr if (r.get("pre_1800s") or {}).get("swap_count",0)>2]
        quiet_usdg=[r for r in quiet if str(r.get("symbol") or "").endswith("/USDG")]
        analyses[split]=dict(
            overall=summary(sr),quiet_30m=summary(quiet),quiet_30m_usdg=summary(quiet_usdg),
            active_30m=summary(active),
        )
    body=dict(
        kind="ramses_dlmm_realized_fee_inventory_decomposition_v1",
        research_only=True,holdout_outcomes_read=False,
        methodology=("For each derivation/validation lifecycle, attribute indexed per-bin LP fee USD "
                     "by the owner's historical DLMMUserBinLiquidityVersion share of binTotalSupply. "
                     "Inventory P&L is realized gross cash-flow P&L minus attributed LP fee income."),
        fee_source_kind=fee_source_kind,
        fee_source_events=len(fee_source),
        counts=dict(
            lifecycles_in=len(lifecycles),lifecycles_out=len(outrows),
            liquidity_versions_total=len(versions),relevant_liquidity_versions=relevant_versions,
            eligible_fee_events=eligible_events,matched_fee_events=matched_events,
            unmatched_fee_events=unmatched_liquidity_events,
        ),
        analyses=analyses,rows=outrows,
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps(dict(status="complete",counts=body["counts"],analyses=analyses),sort_keys=True))

if __name__=="__main__":main()
