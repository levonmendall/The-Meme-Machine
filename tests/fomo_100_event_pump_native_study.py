from __future__ import annotations

import bisect
import io
import json
import math
import os
import random
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import zstandard

FOMO_BASE="https://api.fomoapi.io"
REPLAY_BASE="https://replay.shrine.trade/pump"
REPORT=Path("fomo-100-event-pump-native-study.json")
TARGET_EVENTS=100
PRIMARY_DELAYS=(15,60)
HORIZONS=(60,300,900)
FOMO_EXCLUSION=900
ROLLING=300
ACTIVE_MAX_AGE=60
ENTRY_TOLERANCE=90
OUTCOME_TOLERANCE=120
PROTOCOLS={"PUMPFUN","PUMPSWAP"}

def utc_hour(ts):
    return datetime.fromtimestamp(int(ts),timezone.utc).strftime("%Y/%m/%d/%H")

def parse_ts(v):
    if isinstance(v,(int,float)):
        return int(v/1000) if v>10_000_000_000 else int(v)
    if isinstance(v,str):
        try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
        except Exception:return None
    return None

def http_json(url, headers=None):
    req=urllib.request.Request(url,headers=headers or {"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read(4_000_000))

def fomo_get(path,key,params=None):
    q=urllib.parse.urlencode(params or {})
    req=urllib.request.Request(
        FOMO_BASE+path+(("?"+q) if q else ""),
        headers={"Authorization":"Bearer "+key,"Accept":"application/json","User-Agent":"Mozilla/5.0"},
    )
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read(4_000_000))

def alerts_list(body):
    if isinstance(body,list):return body
    if isinstance(body,dict):
        for k in ("alerts","items","events","data"):
            if isinstance(body.get(k),list):return body[k]
    return []

def token_address(obj):
    if not isinstance(obj,dict):return None
    tok=obj.get("token")
    if isinstance(tok,dict):
        return tok.get("address") or tok.get("mint")
    return obj.get("tokenAddress") or obj.get("mint") or obj.get("address")

def get_event_universe(key, archive_hours):
    body=fomo_get("/v2/alerts",key,{"chain":"solana","type":"buy","since":"2026-09-17T00:00:00Z","limit":100})
    rows=alerts_list(body)
    primary=[]
    active_traders=[]
    trader_seen=set()
    for r in rows:
        if not isinstance(r,dict):continue
        ts=parse_ts(r.get("ts")); mint=r.get("tokenAddress")
        if not ts or not mint:continue
        ident=r.get("userId") or r.get("trader")
        if ident and ident not in trader_seen:
            trader_seen.add(ident);active_traders.append((ident,r.get("trader")))
        if utc_hour(ts) not in archive_hours:continue
        primary.append({
            "ts":ts,"mint":mint,"symbol":r.get("token"),"trader":r.get("trader"),
            "usd_value":r.get("usdValue"),"event_id":r.get("eventId") or r.get("id"),
            "source":"fomo_feed_alert",
        })
    primary.sort(key=lambda x:(x["ts"],x["mint"],str(x.get("event_id"))))
    # retain every real buy event; duplicates by exact id/time/mint only
    seen=set();primary2=[]
    for e in primary:
        k=e.get("event_id") or (e["mint"],e["ts"],e.get("trader"))
        if k in seen:continue
        seen.add(k);primary2.append(e)
    primary=primary2[:TARGET_EVENTS]

    need=max(0,TARGET_EVENTS-len(primary))
    supplemental=[]
    if need:
        min_primary=min((e["ts"] for e in primary),default=10**20)
        candidates=[]
        # Prefer earlier trade entries close to the same sampled hours so archive IO stays bounded.
        for ident,handle in active_traders[:30]:
            try:
                data=fomo_get(f"/v2/users/{urllib.parse.quote(str(ident),safe='')}/trades",key,{"limit":25})
            except Exception:
                continue
            trades=data.get("trades") if isinstance(data,dict) else []
            if not isinstance(trades,list):continue
            for t in trades:
                if not isinstance(t,dict):continue
                if str(t.get("chain") or "").lower() not in ("solana","sol"):continue
                ts=parse_ts(t.get("createdAt") or t.get("ts"))
                mint=token_address(t)
                if not ts or not mint or utc_hour(ts) not in archive_hours:continue
                if ts>=min_primary:continue
                bought=t.get("boughtAmount")
                transferred=t.get("transferredInAmount")
                if not isinstance(bought,(int,float)) or bought<=0:continue
                if isinstance(transferred,(int,float)) and transferred>0:continue
                candidates.append({
                    "ts":ts,"mint":mint,
                    "symbol":((t.get("token") or {}).get("symbol") if isinstance(t.get("token"),dict) else None),
                    "trader":handle or str(ident),"usd_value":t.get("costBasisUsd"),
                    "event_id":t.get("tradeId"),"source":"fomo_user_trade_entry_supplement",
                })
            if len(candidates)>=need*3:break
        candidates.sort(key=lambda x:(-x["ts"],x["mint"],str(x.get("event_id"))))
        existing={(e["mint"],e["ts"]) for e in primary}
        for e in candidates:
            if any(m==e["mint"] and abs(t-e["ts"])<=5 for m,t in existing):continue
            existing.add((e["mint"],e["ts"]));supplemental.append(e)
            if len(supplemental)>=need:break
    events=(supplemental+primary)
    events.sort(key=lambda x:(x["ts"],x["mint"],x["source"]))
    return events[:TARGET_EVENTS], {"primary_feed":len(primary),"supplemental":len(supplemental),"raw_alert_rows":len(rows)}

class MarketState:
    __slots__=("mint","trades","volume","count","last_ts","last_price","last_mcap","protocol","quote_mint")
    def __init__(self,mint):
        self.mint=mint;self.trades=deque();self.volume=0.0;self.count=0
        self.last_ts=None;self.last_price=None;self.last_mcap=None;self.protocol=None;self.quote_mint=None
    def purge(self,now):
        cutoff=now-ROLLING
        while self.trades and self.trades[0][0]<cutoff:
            _,_,q=self.trades.popleft();self.volume-=q;self.count-=1
    def add(self,e):
        ts=int(e["timestamp"]);price=float(e["price"]);q=abs(float(e.get("quoteAmount") or 0))
        self.purge(ts)
        self.trades.append((ts,price,q));self.volume+=q;self.count+=1
        self.last_ts=ts;self.last_price=price
        m=e.get("marketCapQuote")
        self.last_mcap=float(m) if isinstance(m,(int,float)) and m>0 else self.last_mcap
        self.protocol=e.get("protocol");self.quote_mint=e.get("quoteMint")
    def features(self,now):
        self.purge(now)
        if self.last_ts is None or now-self.last_ts>ACTIVE_MAX_AGE or self.last_price is None or self.count<2:
            return None
        first=self.trades[0][1]
        pre5=(self.last_price/first-1.0) if first>0 else None
        if pre5 is None:return None
        return {
            "last_price":self.last_price,"market_cap_quote":self.last_mcap,
            "pre5_return":pre5,"volume5_quote":max(0.0,self.volume),"trade_count5":self.count,
            "protocol":self.protocol,"quote_mint":self.quote_mint,"last_trade_age":now-self.last_ts,
        }

def fomo_near(times_by_mint,mint,ts):
    arr=times_by_mint.get(mint) or []
    i=bisect.bisect_left(arr,ts)
    for j in (i-1,i):
        if 0<=j<len(arr) and abs(arr[j]-ts)<=FOMO_EXCLUSION:return True
    return False

def dist(a,b):
    if a["protocol"]!=b["protocol"] or a["quote_mint"]!=b["quote_mint"]:return None
    if not a["market_cap_quote"] or not b["market_cap_quote"]:return None
    cap=abs(math.log(a["market_cap_quote"]/b["market_cap_quote"]))
    mom=abs(a["pre5_return"]-b["pre5_return"])/0.20
    vol=abs(math.log1p(a["volume5_quote"])-math.log1p(b["volume5_quote"]))
    cnt=abs(math.log1p(a["trade_count5"])-math.log1p(b["trade_count5"]))
    return 1.5*cap+mom+0.75*vol+0.5*cnt

def add_watch(watches,pair_idx,mint,role):
    watches[mint].append((pair_idx,role))

def init_role():
    return {
        str(d):{
            "entry_target":None,"entry_ts":None,"entry_price":None,"entry_expired":False,
            "prices":{},"max_price":None,"min_price":None,
        } for d in PRIMARY_DELAYS
    }

def update_watch(pair,role,ts,price):
    r=pair[role]
    for d in PRIMARY_DELAYS:
        x=r[str(d)]
        if x["entry_target"] is None:x["entry_target"]=pair["event"]["ts"]+d
        if x["entry_price"] is None:
            if ts>=x["entry_target"]:
                if ts-x["entry_target"]<=ENTRY_TOLERANCE:
                    x["entry_ts"]=ts;x["entry_price"]=price;x["max_price"]=price;x["min_price"]=price
                else:
                    x["entry_expired"]=True
            continue
        if ts>=x["entry_ts"] and ts<=x["entry_ts"]+max(HORIZONS)+OUTCOME_TOLERANCE:
            if ts<=x["entry_ts"]+900:
                x["max_price"]=max(x["max_price"],price);x["min_price"]=min(x["min_price"],price)
            for h in HORIZONS:
                key=str(h)
                if key not in x["prices"] and ts>=x["entry_ts"]+h and ts-(x["entry_ts"]+h)<=OUTCOME_TOLERANCE:
                    x["prices"][key]={"ts":ts,"price":price}

def finalize_metrics(pairs):
    records=[]
    for p in pairs:
        out={"event":p["event"],"match":p["match"],"graduated_event":p.get("graduated_event",False),"graduated_control":p.get("graduated_control",False)}
        usable=False
        for d in PRIMARY_DELAYS:
            dd=str(d); out[dd]={}
            er=p["event_market"][dd];cr=p["control_market"][dd]
            if er["entry_price"] and cr["entry_price"]:
                out[dd]["entry_event_price"]=er["entry_price"];out[dd]["entry_control_price"]=cr["entry_price"]
                for h in HORIZONS:
                    k=str(h)
                    ep=er["prices"].get(k);cp=cr["prices"].get(k)
                    if ep and cp:
                        e_ret=(ep["price"]/er["entry_price"]-1)*100
                        c_ret=(cp["price"]/cr["entry_price"]-1)*100
                        out[dd][f"event_return_{h}s_pct"]=e_ret
                        out[dd][f"control_return_{h}s_pct"]=c_ret
                        out[dd][f"edge_{h}s_pct_points"]=e_ret-c_ret
                        usable=True
                if er["max_price"] and cr["max_price"]:
                    out[dd]["event_mfe_15m_pct"]=(er["max_price"]/er["entry_price"]-1)*100
                    out[dd]["control_mfe_15m_pct"]=(cr["max_price"]/cr["entry_price"]-1)*100
                    out[dd]["event_mae_15m_pct"]=(er["min_price"]/er["entry_price"]-1)*100
                    out[dd]["control_mae_15m_pct"]=(cr["min_price"]/cr["entry_price"]-1)*100
        if usable:records.append(out)
    return records

def exact_sign_p(pos,neg):
    n=pos+neg
    if not n:return None
    from math import comb
    k=min(pos,neg)
    tail=sum(comb(n,i) for i in range(k+1))/(2**n)
    return min(1.0,2*tail)

def bootstrap_mean_ci(vals,seed=52026):
    v=[float(x) for x in vals if x is not None and math.isfinite(x)]
    if len(v)<2:return [None,None]
    rng=random.Random(seed);means=[]
    for _ in range(5000):
        means.append(sum(v[rng.randrange(len(v))] for _ in range(len(v)))/len(v))
    means.sort()
    return [means[int(.025*len(means))],means[int(.975*len(means))-1]]

def summarize(records,delay,h):
    k=f"edge_{h}s_pct_points";ek=f"event_return_{h}s_pct";ck=f"control_return_{h}s_pct"
    rows=[r for r in records if k in r[str(delay)]]
    edges=[r[str(delay)][k] for r in rows]
    ev=[r[str(delay)][ek] for r in rows];co=[r[str(delay)][ck] for r in rows]
    pos=sum(x>0 for x in edges);neg=sum(x<0 for x in edges)
    # cluster sensitivity: mean edge per Fomo mint
    clusters=defaultdict(list)
    for r in rows:clusters[r["event"]["mint"]].append(r[str(delay)][k])
    cedges=[statistics.mean(v) for v in clusters.values()]
    cpos=sum(x>0 for x in cedges);cneg=sum(x<0 for x in cedges)
    primary=[r for r in rows if r["event"]["source"]=="fomo_feed_alert"]
    pedges=[r[str(delay)][k] for r in primary]
    return {
        "n_pairs":len(rows),"unique_fomo_mints":len(clusters),
        "event_mean_return_pct":statistics.mean(ev) if ev else None,
        "event_median_return_pct":statistics.median(ev) if ev else None,
        "control_mean_return_pct":statistics.mean(co) if co else None,
        "control_median_return_pct":statistics.median(co) if co else None,
        "paired_mean_edge_pct_points":statistics.mean(edges) if edges else None,
        "paired_median_edge_pct_points":statistics.median(edges) if edges else None,
        "bootstrap_95pct_ci_mean_edge":bootstrap_mean_ci(edges),
        "event_beats_control":pos,"event_loses_to_control":neg,"sign_test_two_sided_p":exact_sign_p(pos,neg),
        "cluster_by_fomo_mint_mean_edge_pct_points":statistics.mean(cedges) if cedges else None,
        "cluster_sign_test_two_sided_p":exact_sign_p(cpos,cneg),
        "feed_only_n":len(pedges),"feed_only_mean_edge_pct_points":statistics.mean(pedges) if pedges else None,
    }

def main():
    key=os.environ.get("FOMOAPI_KEY")
    if not key:raise SystemExit("FOMOAPI_KEY missing")
    idx=http_json(REPLAY_BASE+"/index.json",{"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    archive_hours=set(idx.get("hours") or [])
    events,source_counts=get_event_universe(key,archive_hours)
    if len(events)<TARGET_EVENTS:
        print(json.dumps({"error":"insufficient_fomo_events","collected":len(events),"source_counts":source_counts}))
        raise SystemExit(3)

    # Known Fomo activity is used only to prevent contaminated controls.
    times_by_mint=defaultdict(list)
    for e in events:times_by_mint[e["mint"]].append(e["ts"])
    for arr in times_by_mint.values():arr.sort()

    event_hours={utc_hour(e["ts"]) for e in events}
    hours_needed=set()
    for e in events:
        dt=datetime.fromtimestamp(e["ts"],timezone.utc)
        for off in (-1,0,1):
            h=(dt+timedelta(hours=off)).strftime("%Y/%m/%d/%H")
            if h in archive_hours:hours_needed.add(h)
    hours=sorted(hours_needed)

    states={}
    pairs=[]
    watches=defaultdict(list)
    events_sorted=sorted(events,key=lambda x:x["ts"])
    next_event=0
    control_last_used={}
    last_cleanup=0
    processed=0
    protocol_trade_counts=defaultdict(int)

    def choose_pair(ev,now):
        st=states.get(ev["mint"]);ef=st.features(now) if st else None
        if not ef or ef["protocol"] not in PROTOCOLS:return None
        choices=[]
        for mint,s in states.items():
            if mint==ev["mint"]:continue
            if now-(s.last_ts or 0)>ACTIVE_MAX_AGE:continue
            if control_last_used.get(mint,0)>now-60:continue
            if fomo_near(times_by_mint,mint,now):continue
            cf=s.features(now)
            if not cf:continue
            d=dist(ef,cf)
            if d is not None:choices.append((d,mint,cf))
        if not choices:return None
        d,mint,cf=min(choices,key=lambda x:(x[0],x[1]))
        control_last_used[mint]=now
        return {
            "event":ev,
            "match":{"control_mint":mint,"distance":d,"event_features":ef,"control_features":cf},
            "event_market":init_role(),"control_market":init_role(),
            "graduated_event":False,"graduated_control":False,
        }

    def advance_events(until_ts):
        nonlocal next_event
        while next_event<len(events_sorted) and events_sorted[next_event]["ts"]<=until_ts:
            ev=events_sorted[next_event]
            p=choose_pair(ev,ev["ts"])
            if p:
                idxp=len(pairs);pairs.append(p)
                add_watch(watches,idxp,ev["mint"],"event_market")
                add_watch(watches,idxp,p["match"]["control_mint"],"control_market")
            next_event+=1

    headers={"User-Agent":"Mozilla/5.0","Accept":"application/octet-stream"}
    for hour in hours:
        url=f"{REPLAY_BASE}/{hour}.jsonl.zst"
        with requests.get(url,headers=headers,stream=True,timeout=60) as r:
            r.raise_for_status()
            reader=zstandard.ZstdDecompressor().stream_reader(r.raw)
            for raw in io.TextIOWrapper(reader,encoding="utf-8"):
                try:e=json.loads(raw)
                except Exception:continue
                ts=e.get("timestamp")
                if not isinstance(ts,(int,float)):continue
                ts=int(ts)
                # freeze event/control state before processing any Shrine trade at the event second
                advance_events(ts)
                action=e.get("action");protocol=e.get("protocol");mint=e.get("mint")
                if action=="migrate" and mint in watches:
                    for pi,role in watches[mint]:
                        if ts>=pairs[pi]["event"]["ts"] and ts<=pairs[pi]["event"]["ts"]+900:
                            pairs[pi]["graduated_event" if role=="event_market" else "graduated_control"]=True
                if action not in ("buy","sell") or protocol not in PROTOCOLS or not mint:continue
                price=e.get("price")
                if not isinstance(price,(int,float)) or price<=0:continue
                processed+=1;protocol_trade_counts[protocol]+=1
                st=states.get(mint)
                if st is None:st=states[mint]=MarketState(mint)
                st.add(e)
                if mint in watches:
                    for pi,role in watches[mint]:
                        update_watch(pairs[pi],role,ts,float(price))
                if ts-last_cleanup>=60:
                    last_cleanup=ts
                    cutoff=ts-900
                    keep=set(watches)
                    for m in list(states):
                        s=states[m]
                        if m not in keep and (s.last_ts or 0)<cutoff:
                            del states[m]
    if hours:
        end=datetime.strptime(hours[-1],"%Y/%m/%d/%H").replace(tzinfo=timezone.utc)+timedelta(hours=1)
        advance_events(int(end.timestamp()))

    records=finalize_metrics(pairs)
    summaries={}
    for d in PRIMARY_DELAYS:
        for h in HORIZONS:
            summaries[f"delay_{d}s_horizon_{h}s"]=summarize(records,d,h)

    report={
        "kind":"fomo_100_event_pump_native_matched_study_v1",
        "research_only":True,"strategy_data_used":False,"paper_trades":0,"provider_spend_usd":0,
        "target_events":TARGET_EVENTS,"fomo_events_collected":len(events),"event_source_counts":source_counts,
        "archive_hours":hours,"shrine_protocol_trade_rows_processed":processed,
        "protocol_trade_counts":dict(protocol_trade_counts),
        "matched_events":len(pairs),"events_with_any_complete_outcome":len(records),
        "design":{
            "pump_native_protocols":sorted(PROTOCOLS),
            "control_rule":"same wall clock; same protocol and quote mint; no known Fomo event within +/-15m; nearest fixed distance on pre-event market cap, 5m return, 5m quote volume, and trade count",
            "fomo_trade_excluded_from_features":True,
            "entry_delays_seconds":list(PRIMARY_DELAYS),"horizons_seconds":list(HORIZONS),
            "primary_metric":"paired 5-minute edge at 15-second delayed entry",
            "no_threshold_or_weight_fitting":True,
        },
        "summaries":summaries,
        "match_distance":{
            "mean":statistics.mean([p["match"]["distance"] for p in pairs]) if pairs else None,
            "median":statistics.median([p["match"]["distance"] for p in pairs]) if pairs else None,
            "p90":sorted([p["match"]["distance"] for p in pairs])[int(.9*(len(pairs)-1))] if pairs else None,
        },
        "graduation_15m":{
            "event_count":sum(p.get("graduated_event") for p in pairs),
            "control_count":sum(p.get("graduated_control") for p in pairs),
        },
        "records":records,
        "limitations":[
            "The 100 Fomo events include repeated buys on some mints; cluster-by-mint sensitivity is reported.",
            "Five events may be supplemented from captured Fomo user trade-entry history if the latest feed has fewer than 100 closed-archive events; feed-only sensitivity is reported separately.",
            "Controls are screened against the sampled Fomo event tape, not Fomo's complete lifetime history.",
            "Shrine documents occasional minute-scale collector gaps and occasional neighboring event swaps; entry delays reduce same-second ambiguity.",
            "This is observational market evidence, not proof that Fomo causes the return or that any strategy can capture it after costs."
        ],
    }
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "fomo_events_collected":report["fomo_events_collected"],
        "event_source_counts":report["event_source_counts"],
        "matched_events":report["matched_events"],
        "events_with_any_complete_outcome":report["events_with_any_complete_outcome"],
        "primary":summaries.get("delay_15s_horizon_300s"),
        "delay60_5m":summaries.get("delay_60s_horizon_300s"),
        "horizon15m":summaries.get("delay_15s_horizon_900s"),
        "graduation_15m":report["graduation_15m"],
        "match_distance":report["match_distance"],
    },indent=2,sort_keys=True))

if __name__=="__main__":
    main()
