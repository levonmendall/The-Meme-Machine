"""Five-minute prospective market-only FOMO attention test.

At t0:
  * freeze FOMO's live Solana trending board;
  * independently fetch GeckoTerminal Solana trending pools;
  * greedily match each FOMO token to a NON-FOMO control on market cap/FDV and
    prior 24h return;
  * freeze both groups' independent GeckoTerminal prices.
After five minutes:
  * fetch the same independent prices again;
  * compare paired forward returns.

No Meme Machine strategy data, no Solana RPC, no order authority, no paid source.
"""
from __future__ import annotations
import itertools, json, math, os, statistics, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

FOMO="https://api.fomoapi.io"
GT="https://api.geckoterminal.com/api/v2"
OUT=Path("fomo-prospective-market-test.json")
HOLD_SECONDS=300
PAGES=5

def get(url,headers=None,attempts=4):
    for i in range(attempts):
        req=urllib.request.Request(url,headers=headers or {"Accept":"application/json"})
        try:
            with urllib.request.urlopen(req,timeout=25) as r:
                return r.status,json.loads(r.read(4_000_000))
        except urllib.error.HTTPError as e:
            if e.code==429 and i+1<attempts:
                time.sleep(float(e.headers.get("Retry-After") or 8)); continue
            try: b=json.loads(e.read(64000))
            except Exception: b={}
            return e.code,b
    return 599,{}

def fget(path,key,params=None):
    q=urllib.parse.urlencode(params or {})
    return get(FOMO+path+(("?"+q) if q else ""),{"Authorization":"Bearer "+key,"Accept":"application/json"})

def gtget(path,params=None):
    q=urllib.parse.urlencode(params or {})
    s,b=get(GT+path+(("?"+q) if q else ""),{"Accept":"application/json;version=20230203"})
    time.sleep(2.2)
    return s,b

def mint_from_pool(row):
    try:
        ident=row["relationships"]["base_token"]["data"]["id"]
        return ident.split("_",1)[1]
    except Exception: return None

def number(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except Exception: return None

def pool_features(row):
    a=row.get("attributes") or {}
    pc=a.get("price_change_percentage") or {}
    m=number(a.get("market_cap_usd")) or number(a.get("fdv_usd"))
    return {
        "mint":mint_from_pool(row),
        "symbol":(a.get("name") or "").split(" / ")[0],
        "mcap":m,
        "h24":number(pc.get("h24")),
    }

def board_tokens(body):
    out=[]
    for row in body.get("tokens",[]) if isinstance(body,dict) else []:
        net=row.get("network")
        if isinstance(net,dict): net=net.get("name") or net.get("id")
        if str(net).lower() not in ("solana","solana-mainnet","1399811149"): continue
        tok=row.get("token") or {}
        mint=tok.get("address") if isinstance(tok,dict) else row.get("address")
        m=number(row.get("marketCapUsd"))
        h=number(row.get("change24h"))
        if mint and m and h is not None:
            out.append({"mint":mint,"symbol":tok.get("symbol") if isinstance(tok,dict) else None,
                        "rank":row.get("rank"),"mcap":m,"h24":h})
    return out

def prices(mints):
    out={}
    for i in range(0,len(mints),25):
        chunk=mints[i:i+25]
        s,b=gtget("/simple/networks/solana/token_price/"+",".join(chunk))
        if s!=200: continue
        vals=((b.get("data") or {}).get("attributes") or {}).get("token_prices") or {}
        for k,v in vals.items():
            n=number(v)
            if n and n>0: out[k]=n
    return out

def distance(a,b):
    if not a.get("mcap") or not b.get("mcap") or a.get("h24") is None or b.get("h24") is None:
        return None
    cap=abs(math.log(a["mcap"])-math.log(b["mcap"]))
    mom=abs(a["h24"]-b["h24"])/25.0
    return cap+mom

def signflip(diffs):
    vals=[float(x) for x in diffs]
    n=len(vals)
    if not n or n>20:return None
    obs=abs(statistics.mean(vals)); ext=0; total=0
    for signs in itertools.product((-1,1),repeat=n):
        x=abs(sum(s*v for s,v in zip(signs,vals))/n); total+=1
        if x>=obs-1e-12: ext+=1
    return ext/total

def main():
    key=os.environ.get("FOMOAPI_KEY","")
    if not key:return 2
    s,b=fget("/v2/leaderboard/tokens/trending",key,{"limit":50})
    if s!=200:return 3
    fomo=board_tokens(b)
    fomo_set={x["mint"] for x in fomo}

    controls=[]
    for page in range(1,PAGES+1):
        s,p=gtget("/networks/solana/trending_pools",{"duration":"24h","page":page})
        if s!=200: continue
        for row in p.get("data",[]) if isinstance(p,dict) else []:
            x=pool_features(row)
            if x["mint"] and x["mint"] not in fomo_set and x["mcap"] and x["h24"] is not None:
                controls.append(x)
    # dedupe controls by mint
    seen=set(); controls=[x for x in controls if not (x["mint"] in seen or seen.add(x["mint"]))]

    # Need independent t0 prices before matching final pairs.
    all_t0=prices([x["mint"] for x in fomo]+[x["mint"] for x in controls])
    fomo=[x for x in fomo if x["mint"] in all_t0]
    controls=[x for x in controls if x["mint"] in all_t0]

    pairs=[]; used=set()
    for a in sorted(fomo,key=lambda x:(x["rank"] or 999,x["mint"])):
        choices=[]
        for c in controls:
            if c["mint"] in used: continue
            d=distance(a,c)
            if d is not None: choices.append((d,c))
        if not choices: continue
        d,c=min(choices,key=lambda z:z[0])
        # reject extremely poor matches: > ~e^2 cap ratio plus momentum term
        if d>3.0: continue
        used.add(c["mint"])
        pairs.append({"fomo":a,"control":c,"match_distance":d,
                      "t0_fomo_price":all_t0[a["mint"]],"t0_control_price":all_t0[c["mint"]]})

    t0=int(time.time())
    snapshot={
      "kind":"fomo_prospective_market_test_v1","research_only":True,"strategy_data_used":False,
      "hold_seconds":HOLD_SECONDS,"t0":t0,
      "fomo_board_captured_at":b.get("capturedAt") if isinstance(b,dict) else None,
      "eligible_fomo_tokens":len(fomo),"control_candidates":len(controls),"pairs":pairs,
    }
    OUT.write_text(json.dumps(snapshot,indent=2,sort_keys=True)+"\n")
    if len(pairs)<3:
        print(json.dumps({"pairs":len(pairs),"reason":"insufficient_matches"})); return 4

    time.sleep(HOLD_SECONDS)
    mints=[]
    for p in pairs:mints.extend([p["fomo"]["mint"],p["control"]["mint"]])
    p1=prices(mints)
    results=[]
    for p in pairs:
        fm=p["fomo"]["mint"]; cm=p["control"]["mint"]
        if fm not in p1 or cm not in p1: continue
        fr=(p1[fm]/p["t0_fomo_price"]-1)*100
        cr=(p1[cm]/p["t0_control_price"]-1)*100
        results.append({**p,"t1_fomo_price":p1[fm],"t1_control_price":p1[cm],
                        "fomo_forward_return_pct":fr,"control_forward_return_pct":cr,
                        "edge_pct_points":fr-cr})
    diffs=[x["edge_pct_points"] for x in results]
    report={**snapshot,"t1":int(time.time()),"results":results,"metrics":{
      "n":len(results),
      "fomo_mean_return_pct":statistics.mean([x["fomo_forward_return_pct"] for x in results]) if results else None,
      "fomo_median_return_pct":statistics.median([x["fomo_forward_return_pct"] for x in results]) if results else None,
      "control_mean_return_pct":statistics.mean([x["control_forward_return_pct"] for x in results]) if results else None,
      "control_median_return_pct":statistics.median([x["control_forward_return_pct"] for x in results]) if results else None,
      "paired_mean_edge_pct_points":statistics.mean(diffs) if diffs else None,
      "paired_median_edge_pct_points":statistics.median(diffs) if diffs else None,
      "fomo_beats_control_count":sum(x>0 for x in diffs),
      "exact_two_sided_signflip_p":signflip(diffs),
    },"limitations":[
      "One five-minute cross-section is a pilot, not proof of persistent alpha.",
      "FOMO trending membership may already reflect public attention; matching reduces but cannot eliminate confounding.",
      "GeckoTerminal prices are an independent DEX source but do not cover pre-graduation Pump bonding curves."
    ]}
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report["metrics"],indent=2,sort_keys=True))
    return 0

if __name__=="__main__":raise SystemExit(main())
