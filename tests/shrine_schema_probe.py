from __future__ import annotations
import json, urllib.request
req=urllib.request.Request("https://shrine.trade/llms-full.txt",headers={"User-Agent":"Mozilla/5.0","Accept":"text/plain"})
with urllib.request.urlopen(req,timeout=20) as r:
    lines=r.read(2_000_000).decode("utf-8","replace").splitlines()
for start,end in ((412,560),(780,940),(1530,1660)):
    print(f"---LINES {start}-{end}---")
    for i in range(start-1,min(end,len(lines))):
        print(f"{i+1}: {lines[i]}")
