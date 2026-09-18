from __future__ import annotations
import io,json,os,urllib.parse,urllib.request
from datetime import datetime,timezone
import requests,zstandard

BASE="https://api.fomoapi.io"; REPLAY="https://replay.shrine.trade/pump"
key=os.environ["FOMOAPI_KEY"]

def api(path,params=None):
 q=urllib.parse.urlencode(params or {})
 req=urllib.request.Request(BASE+path+(("?"+q) if q else ""),headers={"Authorization":"Bearer "+key,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def ts(v):
 if isinstance(v,(int,float)):return int(v/1000) if v>1e10 else int(v)
 if isinstance(v,str):
  try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
  except:return None
def addr(x):
 if isinstance(x,str):return x
 if isinstance(x,dict):
  for k in ("address","tokenAddress","mint","token","id"):
   v=x.get(k)
   if isinstance(v,str) and len(v)>=30:return v
def hour(t):return datetime.fromtimestamp(t,timezone.utc).strftime("%Y/%m/%d/%H")
idx_req=urllib.request.Request(REPLAY+"/index.json",headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
with urllib.request.urlopen(idx_req,timeout=20) as r: hours=set(json.loads(r.read()).get("hours") or [])
lb=api("/v2/leaderboard/30d",{"limit":1}); row=lb["traders"][0]; uid=row["userId"]
sw=api(f"/v2/users/{uid}/swaps"); swaps=sw.get("swaps") or []
chosen=None
for s in swaps:
 t=ts(s.get("at") or s.get("createdAt"));ti=addr(s.get("tokenIn"));to=addr(s.get("tokenOut"))
 if not t or hour(t) not in hours:continue
 chosen={"raw":s,"ts":t,"hour":hour(t),"tokenIn":ti,"tokenOut":to};break
if not chosen:raise SystemExit("no archived swap")
targets={x for x in (chosen["tokenIn"],chosen["tokenOut"]) if x}
near=[]
with requests.get(f"{REPLAY}/{chosen['hour']}.jsonl.zst",headers={"User-Agent":"Mozilla/5.0"},stream=True,timeout=60) as r:
 r.raise_for_status();reader=zstandard.ZstdDecompressor().stream_reader(r.raw)
 for raw in io.TextIOWrapper(reader,encoding="utf-8"):
  try:e=json.loads(raw)
  except:continue
  if e.get("mint") not in targets or e.get("action") not in ("buy","sell"):continue
  et=e.get("timestamp")
  if not isinstance(et,(int,float)):continue
  near.append({"delta_seconds":int(et)-chosen["ts"],"timestamp":int(et),"action":e.get("action"),"protocol":e.get("protocol"),
               "mint":e.get("mint"),"traders":e.get("tradersInvolved"),"price":e.get("price"),"signature":e.get("signature")})
near.sort(key=lambda x:abs(x["delta_seconds"]))
safe_swap={k:chosen["raw"].get(k) for k in ("at","chain","chainId","swapId","tokenIn","tokenOut","tradeIdIn","tradeIdOut")}
print(json.dumps({"trader":row.get("handle"),"userId":uid,"swap":safe_swap,"parsed_ts":chosen["ts"],"hour":chosen["hour"],"nearest":near[:20]},indent=2))
