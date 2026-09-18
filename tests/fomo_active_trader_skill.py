"""Research-only audit of recently active FOMO Solana traders.

Selects traders from the recent Solana BUY feed, not the PnL leaderboard, then
audits their recent closed captured Solana positions. No strategy data or RPC.
"""
from __future__ import annotations
import json, math, os, statistics, sys, urllib.parse, urllib.request, urllib.error
from pathlib import Path

BASE="https://api.fomoapi.io"
OUT=Path("fomo-active-trader-skill.json")
MAX_TRADERS=10

def get(path,key,params=None):
    q=urllib.parse.urlencode(params or {})
    url=BASE+path+(("?"+q) if q else "")
    req=urllib.request.Request(url,headers={"Authorization":"Bearer "+key,"Accept":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            return r.status, json.loads(r.read(2_000_000)), r.headers.get("x-credits-cost"), r.headers.get("x-credits-remaining")
    except urllib.error.HTTPError as e:
        raw=e.read(64000)
        try: body=json.loads(raw)
        except Exception: body={"error":raw.decode("utf-8","replace")[:500]}
        return e.code,body,None,None

def alerts(body):
    if isinstance(body,list): return body
    if isinstance(body,dict):
        for k in ("alerts","items","events","data"):
            if isinstance(body.get(k),list): return body[k]
    return []

def exact_binom_two_sided(k,n,p=.5):
    if not n: return None
    from math import comb
    observed=comb(n,k)*(p**k)*((1-p)**(n-k))
    return min(1.0,sum(comb(n,i)*(p**i)*((1-p)**(n-i))
                       for i in range(n+1)
                       if comb(n,i)*(p**i)*((1-p)**(n-i)) <= observed+1e-15))

def main():
    key=os.environ.get("FOMOAPI_KEY","")
    if not key:
        print("FOMOAPI_KEY unavailable",file=sys.stderr); return 2
    s,b,cost,remaining=get("/v2/alerts",key,{"chain":"solana","type":"buy","limit":100})
    if s!=200: return 3
    active=[]; seen=set()
    for a in alerts(b):
        if not isinstance(a,dict) or str(a.get("chain","")).lower()!="solana": continue
        uid=a.get("userId"); handle=a.get("trader")
        ident=uid or handle
        if not ident or ident in seen: continue
        seen.add(ident); active.append((ident,handle,uid))
        if len(active)>=MAX_TRADERS: break

    rows=[]; trader_summaries=[]; credits=[cost]
    for ident,handle,uid in active:
        s,data,c,r=get(f"/v2/users/{urllib.parse.quote(str(ident),safe='')}/trades",key,{"limit":25})
        credits.append(c)
        trades=(data.get("trades") if isinstance(data,dict) else None) or []
        kept=0
        for t in trades:
            if not isinstance(t,dict): continue
            chain=str(t.get("chain") or "").lower()
            if chain not in ("solana","sol"): continue
            if str(t.get("status") or "").lower()!="closed": continue
            bought=t.get("boughtAmount"); transferred=t.get("transferredInAmount")
            cost_basis=t.get("costBasisUsd"); pnl=t.get("realizedPnlUsd")
            if not isinstance(bought,(int,float)) or bought<=0: continue
            if isinstance(transferred,(int,float)) and transferred>0: continue
            if not isinstance(cost_basis,(int,float)) or cost_basis<=0: continue
            if not isinstance(pnl,(int,float)) or not math.isfinite(float(pnl)): continue
            roi=float(pnl)/float(cost_basis)*100
            rows.append({
                "trader":handle or str(ident),"trade_id":t.get("tradeId"),
                "token":((t.get("token") or {}).get("symbol") if isinstance(t.get("token"),dict) else None),
                "opened_at":t.get("createdAt") or t.get("ts"),"closed_at":t.get("closedAt"),
                "cost_basis_usd":float(cost_basis),"realized_pnl_usd":float(pnl),"roi_pct":roi,
            }); kept+=1
        trader_summaries.append({"trader":handle or str(ident),"http_status":s,"eligible_closed_solana_trades":kept})
    # Dedup positions if feed aliases collide.
    unique=[]; ids=set()
    for x in rows:
        k=x["trade_id"] or (x["trader"],x["token"],x["opened_at"])
        if k in ids: continue
        ids.add(k); unique.append(x)
    rois=[x["roi_pct"] for x in unique]; pnls=[x["realized_pnl_usd"] for x in unique]
    costs=[x["cost_basis_usd"] for x in unique]
    wins=sum(x>0 for x in rois); losses=sum(x<0 for x in rois)
    report={
        "kind":"fomo_active_trader_skill_pilot_v1","research_only":True,
        "selection":"first unique traders appearing in recent Solana FOMO BUY feed; not selected from leaderboard",
        "traders_sampled":len(active),"eligible_closed_solana_positions":len(unique),
        "metrics":{
            "win_count":wins,"loss_count":losses,"win_rate":wins/len(rois) if rois else None,
            "median_roi_pct":statistics.median(rois) if rois else None,
            "mean_roi_pct":statistics.mean(rois) if rois else None,
            "total_realized_pnl_usd":sum(pnls),
            "total_cost_basis_usd":sum(costs),
            "capital_weighted_roi_pct":sum(pnls)/sum(costs)*100 if sum(costs)>0 else None,
            "exact_two_sided_binomial_p_vs_50pct":exact_binom_two_sided(wins,wins+losses) if wins+losses else None,
        },
        "traders":trader_summaries,"positions":unique,
        "credits":{"observed_cost_headers":credits,"last_remaining":remaining},
        "limitations":[
            "FOMO/FomoAPI-reported position economics are not an independent market-price source.",
            "Recent closed positions are a bounded FOMO history, not each trader's complete lifetime.",
            "This tests whether currently active FOMO participants show realized skill; it does not prove a user copying an alert can capture the same return."
        ],
    }
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:report[k] for k in ("traders_sampled","eligible_closed_solana_positions","metrics","limitations")},indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
