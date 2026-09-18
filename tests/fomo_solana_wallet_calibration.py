from __future__ import annotations
import io,json,os,urllib.parse,urllib.request
from datetime import datetime,timezone
import requests,zstandard

BASE="https://api.fomoapi.io";REPLAY="https://replay.shrine.trade/pump";key=os.environ["FOMOAPI_KEY"]
Q={"So11111111111111111111111111111111111111112","EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
def api(path,params=None):
 q=urllib.parse.urlencode(params or {});req=urllib.request.Request(BASE+path+(("?"+q) if q else ""),headers={"Authorization":"Bearer "+key,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
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
   v=x.get(k)
   if isinstance(v,str):return v
def hr(t):return datetime.fromtimestamp(t,timezone.utc).strftime("%Y/%m/%d/%H")
req=urllib.request.Request(REPLAY+"/index.json",headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
with urllib.request.urlopen(req,timeout=20) as r:hours=set(json.loads(r.read()).get("hours") or [])
lb=api("/v2/leaderboard/30d",{"limit":30});rows=lb.get("traders") or []
chosen=None;attempted=[]
for row in rows[:20]:
 uid=row.get("userId")
 if not uid:continue
 sw=api(f"/v2/users/{uid}/swaps");items=sw.get("swaps") or []
 sol=[]
 for s in items:
  t=ts(s.get("at"));ti=addr(s.get("tokenIn"));to=addr(s.get("tokenOut"));chain=str(s.get("chain") or "").lower();cid=s.get("chainId")
  if not t or hr(t) not in hours:continue
  if chain!="solana" and str(cid)!="1399811149":continue
  if to and to not in Q and (not ti or ti in Q):action="buy";mint=to
  elif ti and ti not in Q and (not to or to in Q):action="sell";mint=ti
  else:continue
  sol.append({"ts":t,"hour":hr(t),"action":action,"mint":mint,"raw":s})
 attempted.append({"rank":row.get("rank"),"handle":row.get("handle"),"solana_swaps":len(sol)})
 if sol:
  chosen={"row":row,"swap":sol[0]};break
if not chosen:
 print(json.dumps({"attempted":attempted,"chosen":None},indent=2));raise SystemExit(0)
ex=chosen["swap"];near=[]
with requests.get(f"{REPLAY}/{ex['hour']}.jsonl.zst",headers={"User-Agent":"Mozilla/5.0"},stream=True,timeout=60) as r:
 r.raise_for_status();reader=zstandard.ZstdDecompressor().stream_reader(r.raw)
 for raw in io.TextIOWrapper(reader,encoding="utf-8"):
  try:e=json.loads(raw)
  except:continue
  if e.get("mint")!=ex["mint"] or e.get("action")!=ex["action"]:continue
  et=e.get("timestamp")
  if not isinstance(et,(int,float)):continue
  near.append({"delta":int(et)-ex["ts"],"ts":int(et),"protocol":e.get("protocol"),"wallets":e.get("tradersInvolved"),"signature":e.get("signature"),"price":e.get("price")})
near.sort(key=lambda x:abs(x["delta"]))
print(json.dumps({"attempted":attempted,"chosen":{"rank":chosen["row"].get("rank"),"handle":chosen["row"].get("handle"),"userId":chosen["row"].get("userId"),"swap":{"at":ex["raw"].get("at"),"chain":ex["raw"].get("chain"),"chainId":ex["raw"].get("chainId"),"tokenIn":ex["raw"].get("tokenIn"),"tokenOut":ex["raw"].get("tokenOut")},"parsed":{k:ex[k] for k in ("ts","hour","action","mint")}},"nearest":near[:10]},indent=2))
