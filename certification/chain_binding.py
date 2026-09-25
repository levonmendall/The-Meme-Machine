"""Secret-safe chain binding preflight for The Meme Machine.

Proves the configured authenticated endpoints are bound to the intended mainnets.
Never prints endpoint paths, API keys, authorization headers, or raw URLs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SOLANA_HOST="solana-mainnet.g.alchemy.com"
ROBINHOOD_HOST="robinhood-mainnet.g.alchemy.com"
SOLANA_PUBLIC="https://api.mainnet-beta.solana.com"
ROBINHOOD_PUBLIC="https://rpc.mainnet.chain.robinhood.com"
ROBINHOOD_CHAIN_ID="0x1237"
SALT="meme-machine-chain-binding-v1"

def _fingerprint(value):
    return hashlib.sha256((SALT+":"+value).encode()).hexdigest()[:20]

def _rpc(url,method,params,*,timeout=8,transport=None):
    if transport is not None:
        return transport(url,method,params)
    body=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    req=Request(url,data=body,headers={
        "Content-Type":"application/json",
        "Accept":"application/json",
        "User-Agent":"meme-machine-chain-binding/1",
    })
    started=time.monotonic()
    try:
        with urlopen(req,timeout=timeout) as resp:
            raw=resp.read(65536);status=resp.status;headers=resp.headers
    except HTTPError as exc:
        raw=exc.read(65536);status=exc.code;headers=exc.headers
    except (URLError,TimeoutError,OSError) as exc:
        return {"ok":False,"transport_error":type(exc).__name__,
                "latency_seconds":time.monotonic()-started}
    row={"http_status":status,"latency_seconds":time.monotonic()-started,
         "server":headers.get("Server"),"trace_id":headers.get("X-Alchemy-Trace-Id")}
    try:
        obj=json.loads(raw)
        if isinstance(obj,dict):
            if "result" in obj:row["result"]=obj["result"]
            err=obj.get("error")
            if isinstance(err,dict):
                row["rpc_error_code"]=err.get("code")
                row["rpc_error_message"]=str(err.get("message",""))[:200]
    except Exception:
        row["invalid_json"]=True
    row["ok"]=status==200 and "result" in row
    return row

def _endpoint(url,expected_host):
    parsed=urlsplit(url)
    match=re.fullmatch(r"/v2/([^/]+)",parsed.path or "")
    key=match.group(1) if match else ""
    return {
        "configured":bool(url),
        "scheme_https":parsed.scheme=="https",
        "hostname":parsed.hostname,
        "expected_host":parsed.hostname==expected_host,
        "v2_key_path_shape":bool(match),
        "query_present":bool(parsed.query),
        "fragment_present":bool(parsed.fragment),
        "endpoint_identity":_fingerprint(url) if url else None,
        "key_fingerprint":_fingerprint(key) if key else None,
    }

def evaluate(environ=None,transport=None):
    env=os.environ if environ is None else environ
    sol=str(env.get("MM_SOLANA_READ_RPC_URL","") or "").strip()
    rr=str(env.get("MM_ROBINHOOD_READ_RPC_URL","") or "").strip()
    from certification.robinhood.provider_authority import endpoint
    rd=str(env.get("MM_ROBINHOOD_DLMM_RPC_URL","") or "").strip() or rr
    try:
        canonical=endpoint(environ=env)
        authority_valid=True
        rr=rd=canonical
    except ValueError:
        authority_valid=False
    report={
        "schema":"meme-machine-chain-binding-v1",
        "observed_at":time.time(),
        "paper_only":True,
        "solana":_endpoint(sol,SOLANA_HOST),
        "robinhood_read":_endpoint(rr,ROBINHOOD_HOST),
        "robinhood_dlmm":_endpoint(rd,ROBINHOOD_HOST),
    }
    sol_probe=_rpc(sol,"getGenesisHash",[],transport=transport) if sol else {"ok":False,"missing":True}
    sol_public=_rpc(SOLANA_PUBLIC,"getGenesisHash",[],transport=transport)
    report["solana"]["probe"]=sol_probe
    report["solana"]["public_control"]=sol_public
    report["solana"]["mainnet_identity_match"]=bool(
        sol_probe.get("ok") and sol_public.get("ok")
        and sol_probe.get("result")==sol_public.get("result")
    )

    rh_public=_rpc(ROBINHOOD_PUBLIC,"eth_chainId",[],transport=transport)
    report["robinhood_public_control"]=rh_public
    for name,url in (("robinhood_read",rr),("robinhood_dlmm",rd)):
        probe=_rpc(url,"eth_chainId",[],transport=transport) if url else {"ok":False,"missing":True}
        report[name]["probe"]=probe
        report[name]["mainnet_identity_match"]=bool(
            probe.get("ok") and probe.get("result")==ROBINHOOD_CHAIN_ID
            and rh_public.get("ok") and rh_public.get("result")==ROBINHOOD_CHAIN_ID
        )

    sk=report["solana"].get("key_fingerprint")
    rrk=report["robinhood_read"].get("key_fingerprint")
    rdk=report["robinhood_dlmm"].get("key_fingerprint")
    report["key_binding"]={
        "solana_and_robinhood_read_are_distinct":bool(sk and rrk and sk!=rrk),
        "solana_and_robinhood_dlmm_are_distinct":bool(sk and rdk and sk!=rdk),
        "robinhood_read_and_dlmm_same_key":bool(rrk and rdk and rrk==rdk),
    }
    checks={
        "robinhood_single_canonical_authority":authority_valid,
        "solana_configured":report["solana"]["configured"],
        "solana_correct_host":report["solana"]["expected_host"],
        "solana_key_path":report["solana"]["v2_key_path_shape"],
        "solana_mainnet_identity":report["solana"]["mainnet_identity_match"],
        "robinhood_read_configured":report["robinhood_read"]["configured"],
        "robinhood_read_correct_host":report["robinhood_read"]["expected_host"],
        "robinhood_read_key_path":report["robinhood_read"]["v2_key_path_shape"],
        "robinhood_read_mainnet_identity":report["robinhood_read"]["mainnet_identity_match"],
        "robinhood_dlmm_configured":report["robinhood_dlmm"]["configured"],
        "robinhood_dlmm_correct_host":report["robinhood_dlmm"]["expected_host"],
        "robinhood_dlmm_key_path":report["robinhood_dlmm"]["v2_key_path_shape"],
        "robinhood_dlmm_mainnet_identity":report["robinhood_dlmm"]["mainnet_identity_match"],
        "solana_key_distinct_from_robinhood_read":
            report["key_binding"]["solana_and_robinhood_read_are_distinct"],
        "solana_key_distinct_from_robinhood_dlmm":
            report["key_binding"]["solana_and_robinhood_dlmm_are_distinct"],
    }
    report["checks"]=checks
    report["passed"]=all(checks.values())
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True);a=p.parse_args()
    result=evaluate()
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"passed":result["passed"],"checks":result["checks"],
                      "endpoint_identities":{
                        "solana":result["solana"]["endpoint_identity"],
                        "robinhood_read":result["robinhood_read"]["endpoint_identity"],
                        "robinhood_dlmm":result["robinhood_dlmm"]["endpoint_identity"],
                      }},sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)

if __name__=="__main__":
    main()
