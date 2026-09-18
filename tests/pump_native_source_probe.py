from __future__ import annotations
import json, os, re, urllib.request
from pathlib import Path

OUT=Path("pump-native-source-probe.json")
urls=[
    "https://shrine.trade/llms-full.txt",
    "https://shrine.trade/pump/data-api/overview/",
    "https://shrine.trade/pump/data-api/",
]
patterns=("historical","replay","archive","ohlcv_history","subscribe_trades","trades")
hits=[]
for url in urls:
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/plain,text/html,*/*"})
        with urllib.request.urlopen(req,timeout=20) as r:
            text=r.read(2_000_000).decode("utf-8","replace")
        lines=text.splitlines()
        chosen=[]
        for i,line in enumerate(lines):
            if any(p.lower() in line.lower() for p in patterns):
                chosen.append({"line":i+1,"text":line[:500]})
                if len(chosen)>=100: break
        hits.append({"url":url,"status":200,"bytes":len(text.encode()),"matches":chosen})
    except Exception as exc:
        hits.append({"url":url,"error":type(exc).__name__+":"+str(exc)[:300]})
fomo_alerts_schema={}
try:
    req=urllib.request.Request("https://fomoapi.io/openapi.json",headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=20) as r:
        spec=json.loads(r.read(4_000_000))
    op=((spec.get("paths") or {}).get("/v2/alerts") or {}).get("get") or {}
    fomo_alerts_schema={
        "parameters":[
            {"name":p.get("name"),"in":p.get("in"),"required":p.get("required"),"schema":p.get("schema")}
            for p in op.get("parameters",[])
        ],
        "summary":op.get("summary"),
        "description":op.get("description"),
    }
except Exception as exc:
    fomo_alerts_schema={"error":type(exc).__name__+":"+str(exc)[:300]}

report={
    "shrine_docs":hits,
    "fomo_alerts_schema":fomo_alerts_schema,
    "bitquery_api_key_present":bool(os.environ.get("BITQUERY_API_KEY") or os.environ.get("BITQUERY_TOKEN")),
    "shrine_api_key_present":bool(os.environ.get("SHRINE_API_KEY")),
}
OUT.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
