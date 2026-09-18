from __future__ import annotations
import json,math,os,statistics,urllib.parse,urllib.request
from collections import defaultdict
from pathlib import Path
BASE="https://api.fomoapi.io";KEY=os.environ["FOMOAPI_KEY"];OUT=Path("fomo-top-wallet-closed-outcomes.json")
def get(path,params=None):
 q=urllib.parse.urlencode(params or {});req=urllib.request.Request(BASE+path+(("?"+q) if q else ""),headers={"Authorization":"Bearer "+KEY,"Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=25) as r:return json.loads(r.read(4_000_000))
by=defaultdict(dict)
for w in ("24h","7d","30d"):
 for r in get(f"/v2/leaderboard/{w}",{"limit":20}).get("traders") or []:
  if r.get("userId"):by[r["userId"]][w]=r
top=[]
for uid,vals in by.items():
 sample=next(iter(vals.values()));top10=sum(int(v.get("rank") or 999)<=10 for v in vals.values())
 wallets=sample.get("wallets") if isinstance(sample.get("wallets"),dict) else {}
 if top10>=2 and wallets.get("solana") and wallets.get("verified"):
  top.append((-(top10),-len(vals),sum(int(v.get("rank") or 999) for v in vals.values())+50*(3-len(vals)),uid,sample.get("handle")))
top.sort();top=top[:8]
rows=[];per={}
for *_,uid,h in top:
 b=get(f"/v2/users/{uid}/trades",{"limit":100})
 trades=b.get("trades") or []
 rr=[]
 for t in trades:
  if str(t.get("chain") or "").lower() not in ("solana","sol"):continue
  if str(t.get("status") or "").lower()!="closed":continue
  bought=t.get("boughtAmount");transfer=t.get("transferredInAmount");cost=t.get("costBasisUsd");pnl=t.get("realizedPnlUsd")
  if not isinstance(bought,(int,float)) or bought<=0 or (isinstance(transfer,(int,float)) and transfer>0):continue
  if not isinstance(cost,(int,float)) or cost<=0 or not isinstance(pnl,(int,float)):continue
  roi=float(pnl)/float(cost)*100
  x={"handle":h,"trade_id":t.get("tradeId"),"token":((t.get("token") or {}).get("symbol") if isinstance(t.get("token"),dict) else None),
     "cost_basis_usd":float(cost),"realized_pnl_usd":float(pnl),"roi_pct":roi,
     "createdAt":t.get("createdAt"),"closedAt":t.get("closedAt")}
  rr.append(x);rows.append(x)
 per[h]={"closed_positions":len(rr),"wins":sum(x["roi_pct"]>0 for x in rr),
         "median_roi_pct":statistics.median([x["roi_pct"] for x in rr]) if rr else None,
         "weighted_roi_pct":sum(x["realized_pnl_usd"] for x in rr)/sum(x["cost_basis_usd"] for x in rr)*100 if rr and sum(x["cost_basis_usd"] for x in rr)>0 else None}
report={"traders":[h for *_,h in top],"positions":len(rows),"wins":sum(x["roi_pct"]>0 for x in rows),
 "win_rate":sum(x["roi_pct"]>0 for x in rows)/len(rows) if rows else None,
 "median_roi_pct":statistics.median([x["roi_pct"] for x in rows]) if rows else None,
 "mean_roi_pct":statistics.mean([x["roi_pct"] for x in rows]) if rows else None,
 "weighted_roi_pct":sum(x["realized_pnl_usd"] for x in rows)/sum(x["cost_basis_usd"] for x in rows)*100 if rows and sum(x["cost_basis_usd"] for x in rows)>0 else None,
 "total_pnl_usd":sum(x["realized_pnl_usd"] for x in rows),"total_cost_basis_usd":sum(x["cost_basis_usd"] for x in rows),
 "per_trader":per,"note":"FomoAPI/Fomo-reported closed position economics; not independent market reconstruction."}
OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n");print(json.dumps(report,indent=2,sort_keys=True))
