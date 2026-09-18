from __future__ import annotations
import io,json,os,urllib.parse,urllib.request
from collections import defaultdict,Counter
from datetime import datetime,timedelta,timezone
import requests,zstandard

FOMO="https://api.fomoapi.io";REPLAY="https://replay.shrine.trade/pump";KEY=os.environ["FOMOAPI_KEY"]
QUOTE={"So11111111111111111111111111111111111111112","EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}

def api(path,params=None):
 q=urllib.parse.urlencode(params or {});req=urllib.request.Request(FOMO+path+(("?"+q) if q else ""),headers={"Authorization":"Bearer "+KEY,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def public(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read())
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
def hour(t):return datetime.fromtimestamp(t,timezone.utc).strftime("%Y/%m/%d/%H")

# cohort
by=defaultdict(dict)
for w in ("24h","7d","30d"):
 for r in api(f"/v2/leaderboard/{w}",{"limit":20}).get("traders") or []:
  uid=r.get("userId");ws=r.get("wallets") if isinstance(r.get("wallets"),dict) else {}
  if uid:by[uid][w]={"rank":int(r.get("rank") or 999),"handle":r.get("handle"),"wallet":ws.get("solana"),"verified":bool(ws.get("verified"))}
ranked=[]
for uid,v in by.items():
 s=next(iter(v.values()));top10=sum(x["rank"]<=10 for x in v.values())
 if top10>=2 and s["wallet"] and s["verified"]:
  ranked.append(((-top10,-len(v),sum(x["rank"] for x in v.values())+50*(3-len(v)),uid),uid,s))
ranked.sort();cohort=[{"uid":uid,"handle":s["handle"],"wallet":s["wallet"]} for _,uid,s in ranked[:8]]
idx=public(REPLAY+"/index.json");available=set(idx.get("hours") or []);last=sorted(available)[-1]
end=datetime.strptime(last,"%Y/%m/%d/%H").replace(tzinfo=timezone.utc)+timedelta(hours=1);cutoff=int((end-timedelta(hours=36)).timestamp())
raw=[]
for t in cohort:
 b=api(f"/v2/users/{t['uid']}/swaps")
 for s in b.get("swaps") or []:
  t0=ts(s.get("at") or s.get("createdAt"));ti=addr(s.get("tokenIn"));to=addr(s.get("tokenOut"));chain=str(s.get("chain") or "").lower()
  if not t0 or t0<cutoff or hour(t0) not in available or (chain!="solana" and str(s.get("chainId"))!="1399811149"):continue
  if to and to not in QUOTE and (not ti or ti in QUOTE):raw.append({"ts":t0,"mint":to,"wallet":t["wallet"],"handle":t["handle"]})
raw.sort(key=lambda x:(x["ts"],x["wallet"],x["mint"]))
targets=[];lastbuy={}
for e in raw:
 k=(e["wallet"],e["mint"])
 if k not in lastbuy or e["ts"]-lastbuy[k]>=1800:targets.append(e)
 lastbuy[k]=e["ts"]

# candidate hours incl adjacent
need=set()
for e in targets:
 dt=datetime.fromtimestamp(e["ts"],timezone.utc).replace(minute=0,second=0,microsecond=0)
 for off in (-1,0,1):
  h=(dt+timedelta(hours=off)).strftime("%Y/%m/%d/%H")
  if h in available:need.add(h)
by_mint=defaultdict(list)
for i,e in enumerate(targets):by_mint[e["mint"]].append((i,e))
matches={}
headers={"User-Agent":"Mozilla/5.0"}
for h in sorted(need):
 with requests.get(f"{REPLAY}/{h}.jsonl.zst",headers=headers,stream=True,timeout=60) as r:
  r.raise_for_status();reader=zstandard.ZstdDecompressor().stream_reader(r.raw)
  for rawline in io.TextIOWrapper(reader,encoding="utf-8"):
   try:x=json.loads(rawline)
   except:continue
   if x.get("action")!="buy" or x.get("mint") not in by_mint:continue
   xt=x.get("timestamp");wallets=x.get("tradersInvolved") or []
   if not isinstance(xt,(int,float)) or not isinstance(wallets,list):continue
   for i,e in by_mint[x["mint"]]:
    if e["wallet"] not in wallets:continue
    d=int(xt)-e["ts"]
    if abs(d)>300:continue
    prev=matches.get(i)
    cand={"delta":d,"protocol":x.get("protocol"),"quote":x.get("quoteMint"),"signature":x.get("signature"),"ts":int(xt),"price":x.get("price")}
    if prev is None or abs(d)<abs(prev["delta"]):matches[i]=cand
protocols=Counter(m["protocol"] for m in matches.values())
deltas=[m["delta"] for m in matches.values()]
unmatched=[targets[i] for i in range(len(targets)) if i not in matches]
report={"targets":len(targets),"matched":len(matches),"unmatched":len(unmatched),"protocol_counts":dict(protocols),
"delta_min":min(deltas) if deltas else None,"delta_median":sorted(deltas)[len(deltas)//2] if deltas else None,"delta_max":max(deltas) if deltas else None,
"matched_by_wallet":dict(Counter(targets[i]["handle"] for i in matches)),
"unmatched_by_wallet":dict(Counter(e["handle"] for e in unmatched))}
open("fomo-wallet-alpha-venue-classification.json","w").write(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
