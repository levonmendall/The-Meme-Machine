"""Bounded same-provider diagnostic for unreadable Solana DLMM discovery transactions."""
import json, os, time, urllib.request
from pathlib import Path

URL=os.environ["MM_SOLANA_READ_RPC_URL"]
OUT=Path("dlmm-wallet-provider-diagnostic.json")
SIGNATURES=[
    {"pool_rank":2,"signature":"3UZCsxDtkXYzmZndVULho4PwHTie3usiPMmCj1U5X5pcUyD1wwvobiBeEGiciZXhnee34F7e5s21z54R2JvryknQ"},
    {"pool_rank":3,"signature":"EGXKN76sxFj9AFc1o9CpkeXiHdsZqVRbebVtDUupHhkhBzvAwficb6NcCJBTR24fWr8CXfs33Q8HuxuKXmKUDzV"},
]

def rpc(method,params):
    payload=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    req=urllib.request.Request(URL,payload,{"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            body=json.loads(r.read(3_000_001))
    except Exception as exc:
        return {"transport_error":type(exc).__name__}
    if "error" in body:
        e=body.get("error") or {}
        return {"error_code":e.get("code"),"error_message":str(e.get("message") or "")[:300]}
    result=body.get("result")
    if result is None:
        return {"result":"null"}
    if isinstance(result,dict):
        tx=(result.get("transaction") or {})
        sigs=tx.get("signatures") if isinstance(tx,dict) else None
        return {"result":"ok","slot":result.get("slot"),"version":result.get("version"),
                "signatures":len(sigs) if isinstance(sigs,list) else None}
    return {"result":"ok","type":type(result).__name__}

report={"kind":"dlmm_wallet_provider_diagnostic_v1","pnl_read":False,"rows":[]}
for row in SIGNATURES:
    sig=row["signature"]
    status=rpc("getSignatureStatuses",[[sig],{"searchTransactionHistory":True}])
    for encoding in ("json","jsonParsed","base64"):
        result=rpc("getTransaction",[sig,{"encoding":encoding,"commitment":"finalized","maxSupportedTransactionVersion":0}])
        report["rows"].append({**row,"commitment":"finalized","encoding":encoding,
                               "signature_status":status,"transaction":result})
        time.sleep(1.0)
    result=rpc("getTransaction",[sig,{"encoding":"json","commitment":"confirmed","maxSupportedTransactionVersion":0}])
    report["rows"].append({**row,"commitment":"confirmed","encoding":"json",
                           "signature_status":status,"transaction":result})
    time.sleep(1.0)
OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
print(json.dumps({"rows":len(report["rows"]),"pnl_read":False},sort_keys=True))
