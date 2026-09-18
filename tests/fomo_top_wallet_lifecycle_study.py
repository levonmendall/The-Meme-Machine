from __future__ import annotations

import bisect
import io
import json
import math
import os
import statistics
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import zstandard

FOMO="https://api.fomoapi.io"
REPLAY="https://replay.shrine.trade/pump"
OUT=Path("fomo-top-wallet-lifecycle-study.json")
QUOTE={
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}
PROTOCOLS={"PUMPFUN","PUMPSWAP"}
TOP_LIMIT=20
TOP_SELECT=8
CONTROL_SELECT=10
FEED_LIMIT=100
BURN_IN_SECONDS=600
LOOKBACK_SECONDS=4*3600
POST_SECONDS=3600
MATCH_TOL=30

def parse_ts(v):
    if isinstance(v,(int,float)): return int(v/1000) if v>10_000_000_000 else int(v)
    if isinstance(v,str):
        try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
        except Exception:return None
    return None

def api(path,key,params=None):
    q=urllib.parse.urlencode(params or {})
    req=urllib.request.Request(FOMO+path+(("?"+q) if q else ""),headers={
        "Authorization":"Bearer "+key,"Accept":"application/json","User-Agent":"Mozilla/5.0"
    })
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            return r.status,json.loads(r.read(4_000_000))
    except urllib.error.HTTPError as e:
        raw=e.read(64000)
        try:b=json.loads(raw)
        except Exception:b={"error":raw.decode("utf-8","replace")[:1000]}
        return e.code,b

def archive_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))

def hour(ts):return datetime.fromtimestamp(int(ts),timezone.utc).strftime("%Y/%m/%d/%H")

def addr(x):
    if isinstance(x,str):return x
    if isinstance(x,dict):
        for k in ("address","tokenAddress","mint","token","id"):
            v=x.get(k)
            if isinstance(v,str) and len(v)>=30:return v
    return None

def alerts(body):
    if isinstance(body,list):return body
    if isinstance(body,dict):
        for k in ("alerts","items","events","data"):
            if isinstance(body.get(k),list):return body[k]
    return []

def swap_rows(body):
    if not isinstance(body,dict):return []
    for k in ("swaps","items","data"):
        if isinstance(body.get(k),list):return body[k]
    return []

def get_leaderboards(key):
    windows={}
    by_id=defaultdict(dict)
    for w in ("24h","7d","30d"):
        s,b=api(f"/v2/leaderboard/{w}",key,{"limit":TOP_LIMIT})
        rows=b.get("traders") if s==200 and isinstance(b,dict) else []
        windows[w]=[]
        for r in rows or []:
            uid=r.get("userId") or r.get("id")
            if not uid:continue
            row={
                "user_id":uid,"handle":r.get("handle"),"display":r.get("displayName"),
                "rank":int(r.get("rank") or 999),"pnl_usd":r.get("pnlUsd"),
                "profile_solana":((r.get("wallets") or {}).get("solana") if isinstance(r.get("wallets"),dict) else None),
            }
            windows[w].append(row);by_id[uid][w]=row
    ranked=[]
    for uid,vals in by_id.items():
        top10=sum(v["rank"]<=10 for v in vals.values())
        top20=len(vals)
        rank_sum=sum(v["rank"] for v in vals.values())+50*(3-len(vals))
        sample=next(iter(vals.values()))
        ranked.append({
            "user_id":uid,"handle":sample["handle"],"display":sample["display"],
            "top10_windows":top10,"top20_windows":top20,"rank_sum":rank_sum,
            "ranks":{w:vals[w]["rank"] for w in vals},
            "pnl":{w:vals[w]["pnl_usd"] for w in vals},
            "profile_solana":sample["profile_solana"],
        })
    persistent=[r for r in ranked if r["top10_windows"]>=2]
    persistent.sort(key=lambda r:(-r["top10_windows"],-r["top20_windows"],r["rank_sum"],r["user_id"]))
    any_top20={r["user_id"] for r in ranked}
    handles_top20={str(r["handle"]).lower() for r in ranked if r.get("handle")}
    return windows,persistent[:TOP_SELECT],any_top20,handles_top20

def expected_swap(row):
    ts=parse_ts(row.get("at") or row.get("createdAt"))
    if not ts:return None
    chain=str(row.get("chain") or "").lower()
    cid=row.get("chainId")
    if chain and chain!="solana" and str(cid)!="1399811149":return None
    ti=addr(row.get("tokenIn"));to=addr(row.get("tokenOut"))
    if to and to not in QUOTE and (not ti or ti in QUOTE):
        return {"ts":ts,"mint":to,"action":"buy","swap_id":row.get("swapId")}
    if ti and ti not in QUOTE and (not to or to in QUOTE):
        return {"ts":ts,"mint":ti,"action":"sell","swap_id":row.get("swapId")}
    return None

def load_top_swaps(key,top,archive_hours):
    out={}
    for t in top:
        s,b=api(f"/v2/users/{urllib.parse.quote(str(t['user_id']),safe='')}/swaps",key)
        rows=[]
        if s==200:
            for x in swap_rows(b):
                e=expected_swap(x)
                if e and hour(e["ts"]) in archive_hours:rows.append(e)
        rows.sort(key=lambda x:x["ts"],reverse=True)
        out[t["user_id"]]=rows[:12]
    return out

def feed(key,archive_hours,top_handles):
    s,b=api("/v2/alerts",key,{"chain":"solana","type":"buy","since":"2026-09-17T00:00:00Z","limit":FEED_LIMIT})
    rows=[]
    for r in alerts(b) if s==200 else []:
        ts=parse_ts(r.get("ts"));mint=r.get("tokenAddress")
        if not ts or not mint or hour(ts) not in archive_hours:continue
        rows.append({
            "ts":ts,"mint":mint,"trader":r.get("trader"),"usd":r.get("usdValue"),
            "event_id":r.get("eventId") or r.get("id"),
        })
    rows.sort(key=lambda x:(x["ts"],x["mint"],str(x.get("event_id"))))
    if not rows:return [],{},[],None,None
    min_ts=min(x["ts"] for x in rows);max_ts=max(x["ts"] for x in rows)
    first={}
    for r in rows:first.setdefault(r["mint"],r)
    guarded={m:r for m,r in first.items() if r["ts"]>=min_ts+BURN_IN_SECONDS}
    controls=[]
    seen=set()
    for r in rows:
        h=str(r.get("trader") or "").lower()
        if not h or h in top_handles or h in seen:continue
        if r["mint"] not in guarded:continue
        seen.add(h);controls.append({"handle":r["trader"],"anchor_alert":r})
        if len(controls)>=CONTROL_SELECT:break
    return rows,guarded,controls,min_ts,max_ts

def hours_between(start,end,available):
    dt=datetime.fromtimestamp(start,timezone.utc).replace(minute=0,second=0,microsecond=0)
    stop=datetime.fromtimestamp(end,timezone.utc).replace(minute=0,second=0,microsecond=0)
    out=[]
    while dt<=stop:
        h=dt.strftime("%Y/%m/%d/%H")
        if h in available:out.append(h)
        dt+=timedelta(hours=1)
    return out

def match_candidates(expected,events):
    # events already same hour and protocol
    best=None
    for e in events:
        if e.get("mint")!=expected["mint"] or e.get("action")!=expected["action"]:continue
        ts=e.get("timestamp")
        if not isinstance(ts,(int,float)):continue
        delta=abs(int(ts)-expected["ts"])
        if delta>MATCH_TOL:continue
        wallets=e.get("tradersInvolved") or []
        if not isinstance(wallets,list) or not wallets:continue
        cand=(delta,int(ts),wallets,e)
        if best is None or cand[:2]<best[:2]:best=cand
    return best

def resolve_wallets(top,top_swaps,control_rows,archive_cache):
    resolved={}
    evidence={}
    for t in top:
        counts=Counter();matches=[]
        for ex in top_swaps.get(t["user_id"],[]):
            cand=match_candidates(ex,archive_cache.get(hour(ex["ts"]),[]))
            if not cand:continue
            for w in cand[2]:counts[w]+=1
            matches.append({"swap":ex,"chain_ts":cand[1],"wallets":cand[2],"signature":cand[3].get("signature")})
        if counts:
            wallet,n=counts.most_common(1)[0]
            resolved[t["handle"]]=wallet
            evidence[t["handle"]]={"matches":len(matches),"dominant_votes":n,"candidate_counts":dict(counts),
                                  "profile_wallet_matches":bool(t.get("profile_solana") and t["profile_solana"]==wallet)}
    control_resolved={}
    for c in control_rows:
        a=c["anchor_alert"]
        ex={"ts":a["ts"],"mint":a["mint"],"action":"buy"}
        cand=match_candidates(ex,archive_cache.get(hour(a["ts"]),[]))
        if cand and len(cand[2])==1:
            control_resolved[c["handle"]]=cand[2][0]
    return resolved,evidence,control_resolved

def market_event_record(e):
    return {
        "ts":int(e["timestamp"]),"action":e["action"],"protocol":e["protocol"],"mint":e["mint"],
        "price":float(e["price"]),"token_amount":float(e.get("tokenAmount") or 0),
        "quote_amount":float(e.get("quoteAmount") or 0),"market_cap_quote":e.get("marketCapQuote"),
        "wallets":e.get("tradersInvolved") or [],
    }

def lifecycle_for(wallet,first_fomo,market_by_mint,start,end):
    out=[]
    for mint,fo in first_fomo.items():
        evs=market_by_mint.get(mint,[])
        if not evs:continue
        own=[e for e in evs if wallet in e["wallets"] and start<=e["ts"]<=end]
        if not own:continue
        pre=[e for e in own if e["ts"]<fo["ts"]]
        pre_buys=[e for e in pre if e["action"]=="buy"]
        if not pre_buys:continue
        # observed net amount at Fomo time
        net=sum(e["token_amount"] if e["action"]=="buy" else -e["token_amount"] for e in pre)
        if net<=0:continue
        first_buy=min(pre_buys,key=lambda e:e["ts"])
        post=[e for e in own if e["ts"]>=fo["ts"]]
        sells=[e for e in post if e["action"]=="sell"]
        price_before=[e for e in evs if e["ts"]<=fo["ts"]]
        fomo_price=max(price_before,key=lambda e:e["ts"])["price"] if price_before else None
        sold15=sum(e["token_amount"] for e in sells if e["ts"]<=fo["ts"]+900)
        sold60=sum(e["token_amount"] for e in sells if e["ts"]<=fo["ts"]+3600)
        first_sell=min(sells,key=lambda e:e["ts"]) if sells else None
        out.append({
            "mint":mint,"fomo_ts":fo["ts"],"fomo_trader":fo.get("trader"),
            "wallet_first_buy_ts":first_buy["ts"],"lead_seconds":fo["ts"]-first_buy["ts"],
            "first_buy_price":first_buy["price"],"fomo_price":fomo_price,
            "appreciation_before_fomo_pct":((fomo_price/first_buy["price"]-1)*100 if fomo_price and first_buy["price"] else None),
            "observed_net_tokens_at_fomo":net,
            "post_fomo_first_sell_ts":first_sell["ts"] if first_sell else None,
            "first_sell_after_fomo_seconds":first_sell["ts"]-fo["ts"] if first_sell else None,
            "sold_fraction_15m":min(1.5,sold15/net) if net>0 else None,
            "sold_fraction_60m":min(1.5,sold60/net) if net>0 else None,
            "cashout_25pct_15m":sold15>=0.25*net,
            "cashout_50pct_15m":sold15>=0.50*net,
            "cashout_25pct_60m":sold60>=0.25*net,
            "cashout_50pct_60m":sold60>=0.50*net,
            "own_event_count":len(own),
        })
    return out

def cohort_summary(rows):
    leads=[r["lead_seconds"] for r in rows]
    apps=[r["appreciation_before_fomo_pct"] for r in rows if r["appreciation_before_fomo_pct"] is not None]
    s15=[r["sold_fraction_15m"] for r in rows if r["sold_fraction_15m"] is not None]
    s60=[r["sold_fraction_60m"] for r in rows if r["sold_fraction_60m"] is not None]
    return {
        "pre_fomo_positions":len(rows),
        "unique_mints":len({r["mint"] for r in rows}),
        "median_lead_seconds":statistics.median(leads) if leads else None,
        "median_appreciation_before_fomo_pct":statistics.median(apps) if apps else None,
        "sell_within_15m_count":sum(r["post_fomo_first_sell_ts"] is not None and r["first_sell_after_fomo_seconds"]<=900 for r in rows),
        "sell_within_60m_count":sum(r["post_fomo_first_sell_ts"] is not None and r["first_sell_after_fomo_seconds"]<=3600 for r in rows),
        "cashout_25pct_15m_count":sum(r["cashout_25pct_15m"] for r in rows),
        "cashout_50pct_15m_count":sum(r["cashout_50pct_15m"] for r in rows),
        "cashout_25pct_60m_count":sum(r["cashout_25pct_60m"] for r in rows),
        "cashout_50pct_60m_count":sum(r["cashout_50pct_60m"] for r in rows),
        "median_sold_fraction_15m":statistics.median(s15) if s15 else None,
        "median_sold_fraction_60m":statistics.median(s60) if s60 else None,
    }

def main():
    key=os.environ.get("FOMOAPI_KEY")
    if not key:raise SystemExit("FOMOAPI_KEY missing")
    idx=archive_json(REPLAY+"/index.json");available=set(idx.get("hours") or [])
    windows,top,_,top_handles=get_leaderboards(key)
    feed_rows,first_fomo,controls,min_feed,max_feed=feed(key,available,top_handles)
    if not feed_rows or not first_fomo:
        print(json.dumps({"error":"no_archived_feed"}));raise SystemExit(3)

    # resolve top wallets from swaps in closed archive hours. Use the entire replay index for lookup,
    # but only recent swaps returned by FomoAPI.
    resolve_allowed=set(hours_between(min_feed-3*3600,max_feed,available))
    top_swaps=load_top_swaps(key,top,resolve_allowed)
    resolve_hours=sorted({hour(e["ts"]) for rows in top_swaps.values() for e in rows})
    resolve_hours+=sorted({hour(c["anchor_alert"]["ts"]) for c in controls})
    resolve_hours=sorted(set(resolve_hours))

    archive_cache={}
    headers={"User-Agent":"Mozilla/5.0","Accept":"application/octet-stream"}
    for h in resolve_hours:
        buf=[]
        with requests.get(f"{REPLAY}/{h}.jsonl.zst",headers=headers,stream=True,timeout=60) as r:
            r.raise_for_status()
            reader=zstandard.ZstdDecompressor().stream_reader(r.raw)
            for raw in io.TextIOWrapper(reader,encoding="utf-8"):
                try:e=json.loads(raw)
                except Exception:continue
                if e.get("action") not in ("buy","sell") or e.get("protocol") not in PROTOCOLS:continue
                if not e.get("mint") or not isinstance(e.get("timestamp"),(int,float)):continue
                buf.append(e)
        archive_cache[h]=buf

    top_wallets,resolution_evidence,control_wallets=resolve_wallets(top,top_swaps,controls,archive_cache)

    start=min(r["ts"] for r in first_fomo.values())-LOOKBACK_SECONDS
    # only evaluate post horizons present in archived data
    archive_end=max(datetime.strptime(h,"%Y/%m/%d/%H").replace(tzinfo=timezone.utc).timestamp()+3600 for h in available)
    end=min(max(r["ts"] for r in first_fomo.values())+POST_SECONDS,int(archive_end))
    lifecycle_hours=hours_between(start,end,available)

    relevant_mints=set(first_fomo)
    market_by_mint=defaultdict(list)
    all_wallets=set(top_wallets.values())|set(control_wallets.values())
    for h in lifecycle_hours:
        cached=archive_cache.get(h)
        if cached is None:
            cached=[]
            with requests.get(f"{REPLAY}/{h}.jsonl.zst",headers=headers,stream=True,timeout=60) as r:
                r.raise_for_status()
                reader=zstandard.ZstdDecompressor().stream_reader(r.raw)
                for raw in io.TextIOWrapper(reader,encoding="utf-8"):
                    try:e=json.loads(raw)
                    except Exception:continue
                    if e.get("action") not in ("buy","sell") or e.get("protocol") not in PROTOCOLS:continue
                    if e.get("mint") not in relevant_mints:continue
                    if not isinstance(e.get("price"),(int,float)) or e["price"]<=0:continue
                    cached.append(e)
        for e in cached:
            if e.get("mint") in relevant_mints and isinstance(e.get("price"),(int,float)) and e["price"]>0:
                market_by_mint[e["mint"]].append(market_event_record(e))
    for m in market_by_mint:market_by_mint[m].sort(key=lambda e:e["ts"])

    top_rows=[];by_top={}
    for t in top:
        w=top_wallets.get(t["handle"])
        if not w:continue
        rows=lifecycle_for(w,first_fomo,market_by_mint,start,end)
        by_top[t["handle"]]=rows
        for x in rows:top_rows.append({"trader":t["handle"],**x})
    ctrl_rows=[];by_ctrl={}
    for h,w in control_wallets.items():
        rows=lifecycle_for(w,first_fomo,market_by_mint,start,end)
        by_ctrl[h]=rows
        for x in rows:ctrl_rows.append({"trader":h,**x})

    report={
        "kind":"fomo_top_wallet_pre_attention_cashout_study_v1",
        "research_only":True,"strategy_data_used":False,"paper_trades":0,"provider_spend_usd":0,
        "definition_of_fomo_arrival":"first observed Solana BUY alert for the mint in the retained FomoAPI feed, excluding the first 10 minutes of the retained tape as burn-in",
        "leaderboards":windows,
        "persistent_top_traders":top,
        "top_traders_selected":len(top),"top_wallets_resolved":len(top_wallets),
        "wallet_resolution_evidence":resolution_evidence,
        "ordinary_controls_selected":len(controls),"ordinary_control_wallets_resolved":len(control_wallets),
        "retained_feed_rows":len(feed_rows),"guarded_first_fomo_mints":len(first_fomo),
        "feed_min_ts":min_feed,"feed_max_ts":max_feed,
        "wallet_resolution_hours":sorted(resolve_allowed),
        "lifecycle_start":start,"lifecycle_end":end,"archive_hours":lifecycle_hours,
        "top_cohort":cohort_summary(top_rows),"ordinary_active_control":cohort_summary(ctrl_rows),
        "top_positions":top_rows,"control_positions":ctrl_rows,
        "per_top_trader":{h:cohort_summary(rows) for h,rows in by_top.items()},
        "limitations":[
            "Current successful traders are selected using today's 24h/7d/30d leaderboard, so this characterizes today's winners and is not a point-in-time predictive backtest.",
            "Fomo arrival is first observed retained BUY-feed appearance, not historical first-ever FomoScan board appearance; the 10-minute burn-in reduces but cannot eliminate left-censoring.",
            "On-chain accumulation is reconstructed only inside the four-hour pre-Fomo lookback, so older inventory can be missed.",
            "Execution wallets are accepted only when Fomo swap metadata can be matched to Shrine on-chain Pump.fun/PumpSwap trades; unresolved top traders are excluded rather than guessed.",
            "Observed cashout fractions use on-chain token amounts inside the study window and may differ from full-wallet lifetime inventory."
        ],
    }
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "persistent_top_handles":[t["handle"] for t in top],
        "top_wallets_resolved":len(top_wallets),
        "ordinary_control_wallets_resolved":len(control_wallets),
        "guarded_first_fomo_mints":len(first_fomo),
        "top_cohort":report["top_cohort"],
        "ordinary_active_control":report["ordinary_active_control"],
        "per_top_trader":report["per_top_trader"],
    },indent=2,sort_keys=True))

if __name__=="__main__":
    main()
