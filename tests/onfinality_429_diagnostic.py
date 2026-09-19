"""Diagnose OnFinality public 429 behavior from GitHub-hosted runners.

Public endpoint only. No credentials are sent to OnFinality. Captures only safe
rate-limit/server headers and a short error body classification.
"""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

URL="https://solana.api.onfinality.io/public"
OUT=Path("onfinality-429-diagnostic.json")
SAFE_HEADERS={
    "retry-after","x-ratelimit-limit","x-ratelimit-remaining","x-ratelimit-reset",
    "ratelimit-limit","ratelimit-remaining","ratelimit-reset",
    "server","cf-ray","x-request-id","via","date"
}

def probe(label,method="getHealth"):
    body=json.dumps({"jsonrpc":"2.0","id":1,"method":method}).encode()
    req=urllib.request.Request(URL,body,{
        "Content-Type":"application/json",
        "User-Agent":"meme-machine-dlmm-onfinality-diagnostic/1",
    })
    started=time.time()
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            raw=response.read(2048).decode("utf-8","replace")
            headers={k.lower():v for k,v in response.headers.items()
                     if k.lower() in SAFE_HEADERS}
            return dict(label=label,status=response.status,elapsed=time.time()-started,
                        headers=headers,body=raw[:500])
    except urllib.error.HTTPError as exc:
        try:
            raw=exc.read(2048).decode("utf-8","replace")
        except Exception:
            raw=""
        headers={k.lower():v for k,v in exc.headers.items()
                 if k.lower() in SAFE_HEADERS}
        return dict(label=label,status=exc.code,elapsed=time.time()-started,
                    headers=headers,body=raw[:500])
    except Exception as exc:
        return dict(label=label,status=None,elapsed=time.time()-started,
                    error=type(exc).__name__)

def main():
    rows=[]
    # Cold request after runner setup. Then leave enough idle time that our own
    # 5-rps bucket should be completely replenished if the quota is per-client.
    rows.append(probe("cold_getHealth"))
    time.sleep(12)
    rows.append(probe("after_12s_getHealth"))
    time.sleep(5)
    rows.append(probe("after_5s_getVersion","getVersion"))
    time.sleep(5)
    rows.append(probe("after_5s_getSlot","getSlot"))
    report={"kind":"onfinality_429_diagnostic_v1","rows":rows}
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,sort_keys=True))

if __name__=="__main__":
    main()
