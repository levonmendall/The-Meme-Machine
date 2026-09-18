from __future__ import annotations
import json,urllib.request,urllib.error
KEY="msk_demo_try_the_solana_api_2026"
WALLET="9k7hbwNhmbWF89racE8GtEfeiwBYvjymYgVyH2neimQu"
req=urllib.request.Request(f"https://madeonsol.com/api/v1/alpha/{WALLET}",headers={"Authorization":"Bearer "+KEY,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
try:
    with urllib.request.urlopen(req,timeout=30) as r:
        b=json.loads(r.read(4_000_000));status=r.status
except urllib.error.HTTPError as e:
    status=e.code
    try:b=json.loads(e.read(64000))
    except Exception:b={"error":"http"}
positions=b.get("positions") if isinstance(b,dict) else None
print(json.dumps({"status":status,"top_keys":sorted(b.keys()) if isinstance(b,dict) else None,
"summary_keys":sorted((b.get("summary") or {}).keys()) if isinstance(b,dict) and isinstance(b.get("summary"),dict) else None,
"position_count":len(positions) if isinstance(positions,list) else None,
"position_keys":sorted(positions[0].keys()) if isinstance(positions,list) and positions else None,
"sample_position":positions[0] if isinstance(positions,list) and positions else None},indent=2,default=str))
