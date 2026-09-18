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
report={
    "shrine_docs":hits,
    "bitquery_api_key_present":bool(os.environ.get("BITQUERY_API_KEY") or os.environ.get("BITQUERY_TOKEN")),
    "shrine_api_key_present":bool(os.environ.get("SHRINE_API_KEY")),
}
OUT.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
