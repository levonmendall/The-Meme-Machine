from __future__ import annotations
import json, os, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

OUT=Path("fomo-shrine-overlap-probe.json")
key=os.environ["FOMOAPI_KEY"]
params=urllib.parse.urlencode({"chain":"solana","type":"buy","since":"2026-09-17T00:00:00Z","limit":100})
req=urllib.request.Request("https://api.fomoapi.io/v2/alerts?"+params,headers={"Authorization":"Bearer "+key,"Accept":"application/json"})
with urllib.request.urlopen(req,timeout=20) as r:
    body=json.loads(r.read(2_000_000))
rows=body.get("alerts") or body.get("items") or body.get("events") or body.get("data") or []
def ts(row):
    v=row.get("ts")
    if isinstance(v,(int,float)): return int(v/1000) if v>10_000_000_000 else int(v)
    if isinstance(v,str):
        try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
        except:return None
    return None
clean=[]
for x in rows:
    if not isinstance(x,dict):continue
    t=ts(x); mint=x.get("tokenAddress")
    if t and mint:
        hour=datetime.fromtimestamp(t,timezone.utc).strftime("%Y/%m/%d/%H")
        clean.append({"ts":t,"hour":hour,"mint":mint,"token":x.get("token"),"trader":x.get("trader"),"usd":x.get("usdValue")})
idx_req=urllib.request.Request(
    "https://replay.shrine.trade/pump/index.json",
    headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"},
)
with urllib.request.urlopen(idx_req,timeout=20) as r:
    idx=json.loads(r.read(2_000_000))
hours=set(idx.get("hours") or [])
overlap=[x for x in clean if x["hour"] in hours]
report={
 "returned_rows":len(rows),"usable_events":len(clean),"unique_mints":len({x["mint"] for x in clean}),
 "hour_counts":dict(Counter(x["hour"] for x in clean)),
 "min_ts":min((x["ts"] for x in clean),default=None),"max_ts":max((x["ts"] for x in clean),default=None),
 "shrine_archive_count":len(hours),"shrine_last_hours":list(idx.get("hours") or [])[-8:],
 "archived_event_count":len(overlap),"archived_unique_mints":len({x["mint"] for x in overlap}),
 "archived_hour_counts":dict(Counter(x["hour"] for x in overlap)),
}
OUT.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
