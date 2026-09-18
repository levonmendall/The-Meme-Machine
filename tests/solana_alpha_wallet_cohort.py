from __future__ import annotations
import json, urllib.parse, urllib.request
from pathlib import Path
BASE="https://madeonsol.com/api/v1"
KEY="msk_demo_try_the_solana_api_2026"
OUT=Path("solana-alpha-wallet-cohort.json")
def get(params):
    q=urllib.parse.urlencode(params)
    req=urllib.request.Request(BASE+"/alpha/leaderboard?"+q,headers={"Authorization":"Bearer "+KEY,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=30) as r:return r.status,json.loads(r.read(4_000_000))
res={}
for period in ("7d","30d"):
    status,body=get({"period":period,"min_tokens":10,"sort":"roi","exclude_bots":"true","limit":100})
    rows=body.get("leaderboard") or body.get("data") or []
    res[period]={"status":status,"count":len(rows),"rows":rows}
top30=res["30d"]["rows"][:20]
set7={r.get("wallet") for r in res["7d"]["rows"] if r.get("wallet")}
persistent=[r for r in top30 if r.get("wallet") in set7]
report={"source":"MadeOnSol public demo /alpha/leaderboard","selection":{"period":"30d","sort":"roi","min_tokens":10,"exclude_bots":True,"limit":100,"cohort_size":20},
        "status":{"7d":res["7d"]["status"],"30d":res["30d"]["status"]},
        "cohort":top30,"persistent_in_7d_top100":[r.get("wallet") for r in persistent],"persistent_count":len(persistent)}
OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
print(json.dumps({"status":report["status"],"cohort_count":len(top30),"persistent_count":len(persistent),
"top5":[{"rank":r.get("rank"),"wallet":r.get("wallet"),"roi":r.get("roi"),"net_pnl_sol":r.get("net_pnl_sol"),"tokens_traded":r.get("tokens_traded"),"win_rate":r.get("win_rate")} for r in top30[:5]]},indent=2))
