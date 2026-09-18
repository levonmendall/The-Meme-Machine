from __future__ import annotations
import io,json,os,urllib.parse,urllib.request
from collections import defaultdict
from datetime import datetime,timezone
import requests,zstandard
BASE="https://api.fomoapi.io";REPLAY="https://replay.shrine.trade/pump";KEY=os.environ["FOMOAPI_KEY"]
Q={"So11111111111111111111111111111111111111112","EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
def get(path,params=None):
 q=urllib.parse.urlencode(params or {});req=urllib.request.Request(BASE+path+(("?"+q) if q else ""),headers={"Authorization":"Bearer "+KEY,"Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def ts(v):
 if isinstance(v,(int,float)):return int(v/1000) if v>1e10 else int(v)
 if isinstance(v,str):
  try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
  except:return None
def addr(x):
 if isinstance(x,str):return x
 if isinstance(x,dict):
  for k in ("address","tokenAddress","mint"):
   if isinstance(x.get(k),str):return x[k]
def hr(t):return datetime.fromtimestamp(t,timezone.utc).strftime("%Y/%m/%d/%H")
req=urllib.request.Request(REPLAY+"/index.json",headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
with urllib.request.urlopen(req,timeout=20) as r:hours=set(json.loads(r.read()).get("hours") or [])
# rank persistent top
by=defaultdict(dict)
for w in ("24h","7d","30d"):
 for r in get(f"/v2/leaderboard/{w}",{"limit":20}).get("traders") or []:
  if r.get("userId"):by[r["userId"]][w]=r
top=[]
for uid,vals in by.items():
 s=next(iter(vals.values())); wallets=s.get("wallets") or {}; top10=sum(int(v.get("rank") or 999)<=10 for v in vals.values())
 if top10>=2 and wallets.get("verified") and wallets.get("solana"):
  top.append((-(top10),sum(int(v.get("rank") or 999) for v in vals.values())+50*(3-len(vals)),uid,s.get("handle"),wallets.get("solana")))
top.sort()
chosen=None
for _,_,uid,h,wallet in top:
 b=get(f"/v2/users/{uid}/swaps")
 candidates=[]
 for s in b.get("swaps") or []:
  t=ts(s.get("at") or s.get("createdAt"));ti=addr(s.get("tokenIn"));to=addr(s.get("tokenOut"));chain=str(s.get("chain") or "").lower();cid=s.get("chainId")
  if not t or hr(t) not in hours or (chain!="solana" and str(cid)!="1399811149"):continue
  if to and to not in Q and (not ti or ti in Q):candidates.append((t,to,s))
 if candidates:
  candidates.sort(reverse=True,key=lambda x:x[0]);t,m,s=candidates[0];chosen={"handle":h,"wallet":wallet,"ts":t,"mint":m,"swap":s};break
if not chosen:raise SystemExit("no recent archived Solana buy")
near=[]
# include adjacent hours because timestamps can cross boundary
dt=datetime.fromtimestamp(chosen["ts"],timezone.utc)
for off in (-1,0,1):
 h=(dt.replace(minute=0,second=0,microsecond=0)+__import__("datetime").timedelta(hours=off)).strftime("%Y/%m/%d/%H")
 if h not in hours:continue
 with requests.get(f"{REPLAY}/{h}.jsonl.zst",headers={"User-Agent":"Mozilla/5.0"},stream=True,timeout=60) as r:
  r.raise_for_status();reader=zstandard.ZstdDecompressor().stream_reader(r.raw)
  for raw in io.TextIOWrapper(reader,encoding="utf-8"):
   try:e=json.loads(raw)
   except:continue
   if e.get("mint")!=chosen["mint"] or e.get("action")!="buy":continue
   et=e.get("timestamp")
   if not isinstance(et,(int,float)):continue
   near.append({"delta":int(et)-chosen["ts"],"ts":int(et),"protocol":e.get("protocol"),"wallets":e.get("tradersInvolved"),
                "wallet_match":chosen["wallet"] in (e.get("tradersInvolved") or []),"price":e.get("price"),"signature":e.get("signature")})
near.sort(key=lambda x:abs(x["delta"]))
safe={k:chosen["swap"].get(k) for k in ("at","chain","chainId","swapId","tokenIn","tokenOut","tradeIdIn","tradeIdOut")}
print(json.dumps({"handle":chosen["handle"],"verified_wallet":chosen["wallet"],"parsed_ts":chosen["ts"],"mint":chosen["mint"],"swap":safe,"nearest":near[:30]},indent=2))
