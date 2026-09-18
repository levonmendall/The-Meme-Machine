from __future__ import annotations
import json, os, urllib.parse, urllib.request, urllib.error
from pathlib import Path

BASE="https://api.fomoapi.io"
OUT=Path("fomo-wallet-route-probe.json")
key=os.environ["FOMOAPI_KEY"]

def get(path,params=None):
    q=urllib.parse.urlencode(params or {})
    req=urllib.request.Request(BASE+path+(("?"+q) if q else ""),headers={"Authorization":"Bearer "+key,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            return r.status,json.loads(r.read(2_000_000))
    except urllib.error.HTTPError as e:
        raw=e.read(64000)
        try:b=json.loads(raw)
        except Exception:b={"error":raw.decode("utf-8","replace")[:500]}
        return e.code,b

s,b=get("/v2/leaderboard/30d",{"limit":5})
rows=(b.get("traders") if isinstance(b,dict) else None) or []
top=rows[0] if rows else {}
ident=top.get("userId") or top.get("id") or top.get("handle")
handle=top.get("handle")
attempts=[]
for candidate in [ident,handle]:
    if not candidate: continue
    for suffix in ("swaps","trades"):
        status,body=get(f"/v2/users/{urllib.parse.quote(str(candidate),safe='')}/{suffix}",{"limit":5} if suffix=="trades" else None)
        attempts.append({
            "candidate_kind":"id_or_handle","candidate":str(candidate)[:80],
            "endpoint":suffix,"status":status,
            "top_keys":sorted(body.keys())[:30] if isinstance(body,dict) else None,
            "item_keys":sorted(((body.get(suffix) or body.get("items") or body.get("data") or [{}])[0]).keys())[:50]
                if isinstance(body,dict) and isinstance(body.get(suffix) or body.get("items") or body.get("data"),list) and (body.get(suffix) or body.get("items") or body.get("data")) else None,
        })
report={
    "leaderboard_status":s,
    "top_trader_sanitized":{
        "rank":top.get("rank"),"handle":handle,"displayName":top.get("displayName"),
        "userId_present":bool(top.get("userId")),"id_present":bool(top.get("id")),
        "wallet_fields":sorted((top.get("wallets") or {}).keys()) if isinstance(top.get("wallets"),dict) else None,
        "raw_keys":sorted(top.keys())[:80] if isinstance(top,dict) else None,
    },
    "route_attempts":attempts,
}
OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
print(json.dumps(report,indent=2,sort_keys=True))
