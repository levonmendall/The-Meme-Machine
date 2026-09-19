"""Raw sustained-rate probe for authenticated OnFinality HTTP.

No Alchemy fallback is available in this probe. It measures only the primary endpoint
and never prints the URL, credential, response body, or provider message.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from meme_machine.solana_read_rpc import onfinality_rpc_url

OUT=Path("onfinality-sustained-rate-probe.json")
REQUESTS_PER_RATE=12
RATES_RPS=(1,2,3,4,5)
COOLDOWN_SECONDS=2.0


def classify_rate(successes,total,http_429,other_failures):
    rate=(successes/total if total else 0.0)
    stable=bool(total and successes>=max(1,total-1) and http_429==0 and other_failures<=1)
    return dict(success_rate=rate,stable=stable)


def _one(url,request_id):
    body=json.dumps({
        "jsonrpc":"2.0","id":request_id,"method":"getSlot",
        "params":[{"commitment":"finalized"}],
    }).encode()
    req=urllib.request.Request(url,body,{"Content-Type":"application/json"})
    started=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=8) as response:
            raw=response.read(200_001)
        latency=time.monotonic()-started
        if len(raw)>200_000:
            return False,"response_size_limit",latency
        try:
            payload=json.loads(raw)
        except (json.JSONDecodeError,UnicodeDecodeError):
            return False,"invalid_json_or_encoding",latency
        if not isinstance(payload,dict) or payload.get("error") or not isinstance(payload.get("result"),int):
            return False,"provider_error_or_shape",latency
        return True,None,latency
    except urllib.error.HTTPError as exc:
        return False,f"http_{int(exc.code)}",time.monotonic()-started
    except (TimeoutError,urllib.error.URLError):
        return False,"network_or_timeout",time.monotonic()-started
    except UnicodeDecodeError:
        return False,"invalid_encoding",time.monotonic()-started
    except Exception as exc:
        return False,type(exc).__name__,time.monotonic()-started


def main():
    # Deliberately require an authenticated shape and do not configure a secondary.
    url=onfinality_rpc_url(required=True)
    if "onfinality.io" not in url or url.rstrip("/").endswith("/public"):
        raise SystemExit("authenticated_onfinality_required")

    rows=[];request_id=0
    for rps in RATES_RPS:
        interval=1.0/float(rps)
        failures={}
        latencies=[]
        successes=0
        next_at=time.monotonic()
        for _ in range(REQUESTS_PER_RATE):
            wait=max(0.0,next_at-time.monotonic())
            if wait: time.sleep(wait)
            request_id+=1
            ok,reason,latency=_one(url,request_id)
            latencies.append(latency)
            if ok:
                successes+=1
            else:
                failures[reason]=failures.get(reason,0)+1
            next_at=max(next_at+interval,time.monotonic())
        http_429=int(failures.get("http_429",0))
        other=sum(failures.values())-http_429
        classification=classify_rate(successes,REQUESTS_PER_RATE,http_429,other)
        rows.append(dict(
            requested_rps=rps,minimum_interval_seconds=interval,
            requests=REQUESTS_PER_RATE,successes=successes,
            failures=dict(sorted(failures.items())),
            latency_ms=dict(
                min=round(min(latencies)*1000,1) if latencies else None,
                max=round(max(latencies)*1000,1) if latencies else None,
                mean=round(sum(latencies)/len(latencies)*1000,1) if latencies else None,
            ),
            **classification,
        ))
        time.sleep(COOLDOWN_SECONDS)

    stable=[row for row in rows if row["stable"]]
    highest=max((row["requested_rps"] for row in stable),default=None)
    one=next(row for row in rows if row["requested_rps"]==1)
    recommendation=(
        "remove_onfinality_from_pump_http_evidence"
        if not one["stable"]
        else "throttle_onfinality_primary"
        if highest is not None and highest<5
        else "retain_onfinality_at_validated_rate"
    )
    report=dict(
        kind="onfinality_authenticated_sustained_rate_probe_v1",
        primary_only=True,alchemy_fallback_available=False,
        read_only=True,signing=False,submission=False,
        requests_per_rate=REQUESTS_PER_RATE,rates=rows,
        highest_stable_rps=highest,recommendation=recommendation,
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "highest_stable_rps":highest,"recommendation":recommendation,
        "rates":[(r["requested_rps"],r["successes"],r["failures"]) for r in rows],
    },sort_keys=True))


if __name__=="__main__":
    main()
