from __future__ import annotations
import json, os, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE="https://api.fomoapi.io"
OUT=Path("fomo-wallet-alpha-universe.json")
KEY=os.environ["FOMOAPI_KEY"]
QUOTE={
"So11111111111111111111111111111111111111112",
"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
"Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}

def get(path,params=None):
    q=urllib.parse.urlencode(params or {})
    req=urllib.request.Request(BASE+path+(("?"+q) if q else ""),headers={
        "Authorization":"Bearer "+KEY,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read(4_000_000))

def ts(v):
    if isinstance(v,(int,float)): return int(v/1000) if v>1e10 else int(v)
    if isinstance(v,str):
        try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
        except:return None
    return None

def addr(x):
    if isinstance(x,str): return x
    if isinstance(x,dict):
        for k in ("address","tokenAddress","mint"):
            v=x.get(k)
            if isinstance(v,str): return v
    return None

boards={}
by={}
for w in ("24h","7d","30d"):
    b=get(f"/v2/leaderboard/{w}",{"limit":20})
    rows=b.get("traders") or []
    boards[w]=[]
    for r in rows:
        uid=r.get("userId")
        if not uid: continue
        wallets=r.get("wallets") if isinstance(r.get("wallets"),dict) else {}
        row={"user_id":uid,"handle":r.get("handle"),"rank":int(r.get("rank") or 999),
             "pnl_usd":r.get("pnlUsd"),"solana_wallet":wallets.get("solana"),
             "wallet_verified":bool(wallets.get("verified"))}
        boards[w].append(row); by.setdefault(uid,{})[w]=row

ranked=[]
for uid,vals in by.items():
    sample=next(iter(vals.values()))
    top10=sum(v["rank"]<=10 for v in vals.values())
    rank_sum=sum(v["rank"] for v in vals.values())+50*(3-len(vals))
    ranked.append({"user_id":uid,"handle":sample["handle"],"solana_wallet":sample["solana_wallet"],
                   "wallet_verified":sample["wallet_verified"],"top10_windows":top10,
                   "windows":len(vals),"rank_sum":rank_sum,
                   "ranks":{k:v["rank"] for k,v in vals.items()}})
ranked=[r for r in ranked if r["top10_windows"]>=2 and r["wallet_verified"] and r["solana_wallet"]]
ranked.sort(key=lambda r:(-r["top10_windows"],-r["windows"],r["rank_sum"],r["user_id"]))
top=ranked[:8]

summary=[]
all_buys=[]
for trader in top:
    b=get(f"/v2/users/{trader['user_id']}/swaps")
    swaps=b.get("swaps") or []
    sol_buys=[]
    for s in swaps:
        t=ts(s.get("at") or s.get("createdAt")); ti=addr(s.get("tokenIn")); to=addr(s.get("tokenOut"))
        chain=str(s.get("chain") or "").lower(); cid=s.get("chainId")
        if not t or (chain!="solana" and str(cid)!="1399811149"): continue
        if to and to not in QUOTE and (not ti or ti in QUOTE):
            sol_buys.append({"ts":t,"mint":to,"swap_id":s.get("swapId"),"handle":trader["handle"],
                             "wallet":trader["solana_wallet"]})
    sol_buys.sort(key=lambda x:x["ts"])
    all_buys.extend(sol_buys)
    summary.append({"handle":trader["handle"],"ranks":trader["ranks"],
                    "swap_rows":len(swaps),"solana_buys":len(sol_buys),
                    "next_cursor":b.get("nextCursor"),"complete":b.get("complete"),
                    "partial":b.get("partial"),"source_capped":b.get("sourceCapped")})
report={"top":top,"per_trader":summary,"solana_buy_events":len(all_buys),
        "unique_mints":len({x["mint"] for x in all_buys}),
        "hour_counts":dict(Counter(datetime.fromtimestamp(x["ts"],timezone.utc).strftime("%Y/%m/%d/%H") for x in all_buys)),
        "min_ts":min((x["ts"] for x in all_buys),default=None),
        "max_ts":max((x["ts"] for x in all_buys),default=None)}
OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
print(json.dumps(report,indent=2,sort_keys=True))
