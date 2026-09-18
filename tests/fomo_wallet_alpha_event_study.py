from __future__ import annotations
import bisect, io, json, math, os, random, statistics, urllib.parse, urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests, zstandard

FOMO="https://api.fomoapi.io"
REPLAY="https://replay.shrine.trade/pump"
OUT=Path("fomo-wallet-alpha-event-study.json")
PROTOCOLS={"PUMPFUN","PUMPSWAP"}
QUOTE={
"So11111111111111111111111111111111111111112",
"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
"Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
TOP_N=8
RECENT_HOURS=12
ENTRY_DELAY=15
ENTRY_TOL=90
HORIZONS=(60,300,900,3600)
OUTCOME_TOL=180
ROLL=300
ACTIVE_AGE=60
DEDUP_SECONDS=1800
CONTROL_EXCLUSION=900
MATCH_MAX=4.0

def api(path,key,params=None):
    q=urllib.parse.urlencode(params or {})
    req=urllib.request.Request(FOMO+path+(("?"+q) if q else ""),headers={
        "Authorization":"Bearer "+key,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))

def public_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))

def parse_ts(v):
    if isinstance(v,(int,float)):return int(v/1000) if v>1e10 else int(v)
    if isinstance(v,str):
        try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
        except:return None
    return None

def addr(x):
    if isinstance(x,str):return x
    if isinstance(x,dict):
        for k in ("address","tokenAddress","mint"):
            v=x.get(k)
            if isinstance(v,str):return v
    return None

def hour(ts):return datetime.fromtimestamp(int(ts),timezone.utc).strftime("%Y/%m/%d/%H")

def pick_top(key):
    by=defaultdict(dict)
    for w in ("24h","7d","30d"):
        b=api(f"/v2/leaderboard/{w}",key,{"limit":20})
        for r in b.get("traders") or []:
            uid=r.get("userId"); wallets=r.get("wallets") if isinstance(r.get("wallets"),dict) else {}
            if not uid:continue
            by[uid][w]={"rank":int(r.get("rank") or 999),"handle":r.get("handle"),
                        "wallet":wallets.get("solana"),"verified":bool(wallets.get("verified")),
                        "pnl":r.get("pnlUsd")}
    rows=[]
    for uid,vals in by.items():
        sample=next(iter(vals.values()))
        top10=sum(v["rank"]<=10 for v in vals.values())
        if top10<2 or not sample["wallet"] or not sample["verified"]:continue
        rows.append({"user_id":uid,"handle":sample["handle"],"wallet":sample["wallet"],
                     "ranks":{w:v["rank"] for w,v in vals.items()},
                     "pnl":{w:v["pnl"] for w,v in vals.items()},
                     "top10_windows":top10,"window_count":len(vals),
                     "rank_sum":sum(v["rank"] for v in vals.values())+50*(3-len(vals))})
    rows.sort(key=lambda r:(-r["top10_windows"],-r["window_count"],r["rank_sum"],r["user_id"]))
    return rows[:TOP_N]

def swap_buys(key,traders,available,cutoff):
    raw=[]
    per={}
    for t in traders:
        b=api(f"/v2/users/{urllib.parse.quote(t['user_id'],safe='')}/swaps",key)
        rows=b.get("swaps") or []
        kept=[]
        for s in rows:
            ts=parse_ts(s.get("at") or s.get("createdAt")); ti=addr(s.get("tokenIn")); to=addr(s.get("tokenOut"))
            chain=str(s.get("chain") or "").lower(); cid=s.get("chainId")
            if not ts or ts<cutoff or hour(ts) not in available:continue
            if chain!="solana" and str(cid)!="1399811149":continue
            if to and to not in QUOTE and (not ti or ti in QUOTE):
                e={"approx_ts":ts,"mint":to,"wallet":t["wallet"],"handle":t["handle"],"swap_id":s.get("swapId")}
                kept.append(e);raw.append(e)
        per[t["handle"]]={"swap_rows":len(rows),"recent_solana_buys":len(kept),
                          "complete":b.get("complete"),"source_capped":b.get("sourceCapped"),
                          "next_cursor":b.get("nextCursor")}
    raw.sort(key=lambda e:(e["approx_ts"],e["wallet"],e["mint"],str(e.get("swap_id"))))
    # primary independent entries: first buy per wallet/mint after >=30m quiet period
    dedup=[];last={}
    for e in raw:
        k=(e["wallet"],e["mint"])
        if k in last and e["approx_ts"]-last[k]<DEDUP_SECONDS:
            last[k]=e["approx_ts"];continue
        dedup.append(e);last[k]=e["approx_ts"]
    return raw,dedup,per

class State:
    def __init__(self):
        self.q=deque();self.vol=0.0;self.count=0;self.last_ts=None;self.last_price=None
        self.mcap=None;self.protocol=None;self.quote=None
    def purge(self,now):
        while self.q and self.q[0][0]<now-ROLL:
            _,_,q=self.q.popleft();self.vol-=q;self.count-=1
    def add(self,e):
        ts=int(e["timestamp"]);p=float(e["price"]);q=abs(float(e.get("quoteAmount") or 0))
        self.purge(ts);self.q.append((ts,p,q));self.vol+=q;self.count+=1
        self.last_ts=ts;self.last_price=p;self.protocol=e.get("protocol");self.quote=e.get("quoteMint")
        m=e.get("marketCapQuote")
        if isinstance(m,(int,float)) and m>0:self.mcap=float(m)
    def feat_relaxed(self,now):
        self.purge(now)
        if self.last_ts is None or now-self.last_ts>ACTIVE_AGE or self.count<2 or not self.last_price:return None
        first=self.q[0][1]
        if first<=0:return None
        return {"price":self.last_price,"mcap":self.mcap,"pre5":self.last_price/first-1,
                "vol5":max(self.vol,0),"count5":self.count,"protocol":self.protocol,"quote":self.quote,
                "last_trade_age":now-self.last_ts}
    def feat(self,now):
        x=self.feat_relaxed(now)
        if not x or not x["mcap"]:return None
        return x

def distance(a,b):
    if a["protocol"]!=b["protocol"] or a["quote"]!=b["quote"]:return None
    return (1.5*abs(math.log(a["mcap"]/b["mcap"]))+
            abs(a["pre5"]-b["pre5"])/0.20+
            0.75*abs(math.log1p(a["vol5"])-math.log1p(b["vol5"]))+
            0.5*abs(math.log1p(a["count5"])-math.log1p(b["count5"])))

def distance_relaxed(a,b):
    if a["protocol"]!=b["protocol"] or a["quote"]!=b["quote"]:return None
    return (abs(a["pre5"]-b["pre5"])/0.20+
            0.75*abs(math.log1p(a["vol5"])-math.log1p(b["vol5"]))+
            0.5*abs(math.log1p(a["count5"])-math.log1p(b["count5"]))+
            0.25*abs(a["last_trade_age"]-b["last_trade_age"])/60.0)

def near_target(times,mint,ts):
    arr=times.get(mint) or [];i=bisect.bisect_left(arr,ts)
    return any(0<=j<len(arr) and abs(arr[j]-ts)<=CONTROL_EXCLUSION for j in (i-1,i))

def role():
    return {"entry_target":None,"entry_ts":None,"entry_price":None,"prices":{},
            "max60":None,"min60":None}

def update_role(r,ts,p,event_ts):
    if r["entry_target"] is None:r["entry_target"]=event_ts+ENTRY_DELAY
    if r["entry_price"] is None:
        if ts>=r["entry_target"] and ts-r["entry_target"]<=ENTRY_TOL:
            r["entry_ts"]=ts;r["entry_price"]=p;r["max60"]=p;r["min60"]=p
        return
    if ts<r["entry_ts"]:return
    if ts<=r["entry_ts"]+3600:
        r["max60"]=max(r["max60"],p);r["min60"]=min(r["min60"],p)
    for h in HORIZONS:
        k=str(h)
        if k not in r["prices"] and ts>=r["entry_ts"]+h and ts-(r["entry_ts"]+h)<=OUTCOME_TOL:
            r["prices"][k]={"ts":ts,"price":p}

def contiguous(hours):
    ds=sorted(datetime.strptime(h,"%Y/%m/%d/%H").replace(tzinfo=timezone.utc) for h in hours)
    if not ds:return []
    segs=[[ds[0]]]
    for d in ds[1:]:
        if d-segs[-1][-1]==timedelta(hours=1):segs[-1].append(d)
        else:segs.append([d])
    return [[x.strftime("%Y/%m/%d/%H") for x in s] for s in segs]

def sign_p(pos,neg):
    n=pos+neg
    if not n:return None
    from math import comb
    k=min(pos,neg);tail=sum(comb(n,i) for i in range(k+1))/(2**n)
    return min(1.0,2*tail)

def boot(vals,seed=91726):
    v=[float(x) for x in vals if isinstance(x,(int,float)) and math.isfinite(x)]
    if len(v)<2:return [None,None]
    rng=random.Random(seed);m=[]
    for _ in range(5000):m.append(sum(v[rng.randrange(len(v))] for _ in range(len(v)))/len(v))
    m.sort();return [m[int(.025*len(m))],m[int(.975*len(m))-1]]

def summarize(records,h):
    k=f"edge_{h}s"; rows=[r for r in records if k in r]
    edges=[r[k] for r in rows]; ev=[r[f"target_return_{h}s"] for r in rows];co=[r[f"control_return_{h}s"] for r in rows]
    pos=sum(x>0 for x in edges);neg=sum(x<0 for x in edges)
    wc=defaultdict(list);mc=defaultdict(list)
    for r in rows:
        wc[r["handle"]].append(r[k]);mc[(r["handle"],r["mint"])].append(r[k])
    wvals=[statistics.mean(v) for v in wc.values()];mvals=[statistics.mean(v) for v in mc.values()]
    return {"n":len(rows),"unique_wallets":len(wc),"unique_wallet_mints":len(mc),
            "target_mean_return_pct":statistics.mean(ev) if ev else None,
            "target_median_return_pct":statistics.median(ev) if ev else None,
            "control_mean_return_pct":statistics.mean(co) if co else None,
            "control_median_return_pct":statistics.median(co) if co else None,
            "mean_edge_pct_points":statistics.mean(edges) if edges else None,
            "median_edge_pct_points":statistics.median(edges) if edges else None,
            "bootstrap_95pct_ci_mean_edge":boot(edges),"beats":pos,"loses":neg,"sign_p":sign_p(pos,neg),
            "wallet_cluster_mean_edge":statistics.mean(wvals) if wvals else None,
            "wallet_cluster_sign_p":sign_p(sum(x>0 for x in wvals),sum(x<0 for x in wvals)),
            "wallet_mint_cluster_mean_edge":statistics.mean(mvals) if mvals else None,
            "wallet_mint_cluster_sign_p":sign_p(sum(x>0 for x in mvals),sum(x<0 for x in mvals))}

def main():
    key=os.environ["FOMOAPI_KEY"]
    index=public_json(REPLAY+"/index.json");available=set(index.get("hours") or [])
    end_dt=datetime.strptime(sorted(available)[-1],"%Y/%m/%d/%H").replace(tzinfo=timezone.utc)+timedelta(hours=1)
    cutoff=int((end_dt-timedelta(hours=RECENT_HOURS)).timestamp())
    traders=pick_top(key)
    raw,targets,per=swap_buys(key,traders,available,cutoff)
    target_times=defaultdict(list)
    for e in raw:target_times[e["mint"]].append(e["approx_ts"])
    for x in target_times.values():x.sort()

    # convergence based on distinct successful wallets buying the same mint in the preceding 15m.
    for e in targets:
        e["convergence_wallets_15m"]=len({x["wallet"] for x in raw
            if x["mint"]==e["mint"] and e["approx_ts"]-900<=x["approx_ts"]<=e["approx_ts"]})

    needed=set()
    for e in targets:
        dt=datetime.fromtimestamp(e["approx_ts"],timezone.utc).replace(minute=0,second=0,microsecond=0)
        for off in (-1,0,1,2):
            h=(dt+timedelta(hours=off)).strftime("%Y/%m/%d/%H")
            if h in available:needed.add(h)
    segments=contiguous(needed)

    states={};pairs=[];watch=defaultdict(list);matched=set();control_last={}
    diagnostics=defaultdict(int)

    def choose_control(tf,ts,target_mint,arm):
        choices=[]
        candidate_count=0
        for mint,s in states.items():
            if mint==target_mint or near_target(target_times,mint,ts):continue
            if control_last.get((arm,mint),0)>ts-60:continue
            cf=s.feat(ts) if arm=="strict_market_cap" else s.feat_relaxed(ts)
            if not cf:continue
            if cf["protocol"]!=tf["protocol"] or cf["quote"]!=tf["quote"]:continue
            candidate_count+=1
            d=distance(tf,cf) if arm=="strict_market_cap" else distance_relaxed(tf,cf)
            if d is not None and d<=MATCH_MAX:choices.append((d,mint,cf))
        diagnostics[f"{arm}_eligible_control_states"]+=candidate_count
        if not choices:return None
        d,m,cf=min(choices,key=lambda x:(x[0],x[1]))
        control_last[(arm,m)]=ts
        return d,m,cf

    headers={"User-Agent":"Mozilla/5.0","Accept":"application/octet-stream"}
    trade_rows=0
    for seg in segments:
        states={};control_last={};watch=defaultdict(list)
        seg_start=int(datetime.strptime(seg[0],"%Y/%m/%d/%H").replace(tzinfo=timezone.utc).timestamp())
        seg_end=int((datetime.strptime(seg[-1],"%Y/%m/%d/%H").replace(tzinfo=timezone.utc)+timedelta(hours=1)).timestamp())
        seg_targets=[(i,t) for i,t in enumerate(targets) if seg_start<=t["approx_ts"]<seg_end]
        seg_targets.sort(key=lambda x:(x[1]["approx_ts"],x[0]))
        pending=0

        def trigger_targets(until_ts):
            nonlocal pending
            while pending<len(seg_targets) and seg_targets[pending][1]["approx_ts"]<=until_ts:
                ti,t=seg_targets[pending]; pending+=1
                if ti in matched: continue
                event_ts=t["approx_ts"];mint=t["mint"]
                st=states.get(mint)
                relaxed_tf=st.feat_relaxed(event_ts) if st else None
                strict_tf=st.feat(event_ts) if st else None
                matched.add(ti);diagnostics["targets_triggered"]+=1
                if st is None:diagnostics["target_state_missing"]+=1
                elif relaxed_tf is None:diagnostics["target_state_inactive_or_thin"]+=1
                else:
                    diagnostics["target_relaxed_state_present"]+=1
                    if relaxed_tf["protocol"] not in PROTOCOLS:diagnostics["target_non_pump_protocol"]+=1
                    if relaxed_tf["mcap"] is None:diagnostics["target_market_cap_missing"]+=1
                    if relaxed_tf["quote"] is None:diagnostics["target_quote_missing"]+=1
                for arm,tf in (("strict_market_cap",strict_tf),("activity_matched",relaxed_tf)):
                    if not tf or tf["protocol"] not in PROTOCOLS:continue
                    diagnostics[f"{arm}_targets_eligible"]+=1
                    cc=choose_control(tf,event_ts,mint,arm)
                    if not cc:
                        diagnostics[f"{arm}_no_control_match"]+=1
                        continue
                    d,cm,cf=cc
                    diagnostics[f"{arm}_pairs_created"]+=1
                    p={"arm":arm,"handle":t["handle"],"wallet":t["wallet"],"mint":mint,
                       "approx_ts":event_ts,"event_ts":event_ts,"timestamp_delta":0,
                       "event_definition":"FomoAPI successful-wallet buy timestamp; Pump-native activity independently verified by Shrine immediately before event",
                       "convergence_wallets_15m":t["convergence_wallets_15m"],
                       "match_distance":d,"target_features":tf,"control_mint":cm,"control_features":cf,
                       "target":role(),"control":role(),"target_graduated":False,"control_graduated":False}
                    pi=len(pairs);pairs.append(p);watch[mint].append((pi,"target"));watch[cm].append((pi,"control"))

        for h in seg:
            with requests.get(f"{REPLAY}/{h}.jsonl.zst",headers=headers,stream=True,timeout=60) as resp:
                resp.raise_for_status();reader=zstandard.ZstdDecompressor().stream_reader(resp.raw)
                for rawline in io.TextIOWrapper(reader,encoding="utf-8"):
                    try:e=json.loads(rawline)
                    except:continue
                    ts=e.get("timestamp");mint=e.get("mint");action=e.get("action");protocol=e.get("protocol")
                    if not isinstance(ts,(int,float)) or not mint:continue
                    ts=int(ts)
                    # Freeze the event and control state before consuming any Shrine event
                    # at or after the Fomo buy timestamp.
                    trigger_targets(ts)
                    if action=="migrate":
                        for pi,kind in watch.get(mint,[]):
                            p=pairs[pi]
                            if ts>=p["event_ts"] and ts<=p["event_ts"]+3600:
                                p["target_graduated" if kind=="target" else "control_graduated"]=True
                        continue
                    if action not in ("buy","sell") or protocol not in PROTOCOLS:continue
                    price=e.get("price")
                    if not isinstance(price,(int,float)) or price<=0:continue
                    trade_rows+=1
                    st=states.get(mint)
                    if st is None:st=states[mint]=State()
                    st.add(e)
                    for pi,kind in watch.get(mint,[]):
                        update_role(pairs[pi][kind],ts,float(price),pairs[pi]["event_ts"])
        trigger_targets(seg_end)

    records=[]
    for p in pairs:
        a=p["target"];b=p["control"]
        if not a["entry_price"] or not b["entry_price"]:continue
        r={k:v for k,v in p.items() if k not in ("target","control")}
        r["target_entry_ts"]=a["entry_ts"];r["control_entry_ts"]=b["entry_ts"]
        r["target_mfe_60m_pct"]=(a["max60"]/a["entry_price"]-1)*100 if a["max60"] else None
        r["target_mae_60m_pct"]=(a["min60"]/a["entry_price"]-1)*100 if a["min60"] else None
        r["control_mfe_60m_pct"]=(b["max60"]/b["entry_price"]-1)*100 if b["max60"] else None
        r["control_mae_60m_pct"]=(b["min60"]/b["entry_price"]-1)*100 if b["min60"] else None
        for h in HORIZONS:
            k=str(h)
            if k in a["prices"] and k in b["prices"]:
                ar=(a["prices"][k]["price"]/a["entry_price"]-1)*100
                br=(b["prices"][k]["price"]/b["entry_price"]-1)*100
                r[f"target_return_{h}s"]=ar;r[f"control_return_{h}s"]=br;r[f"edge_{h}s"]=ar-br
        if any(f"edge_{h}s" in r for h in HORIZONS):records.append(r)

    records_by_arm={arm:[r for r in records if r.get("arm")==arm] for arm in ("strict_market_cap","activity_matched")}
    summaries_by_arm={
        arm:{str(h):summarize(rows,h) for h in HORIZONS}
        for arm,rows in records_by_arm.items()
    }
    conv={}
    for arm,arm_records in records_by_arm.items():
        conv[arm]={}
        for level in (1,2,3):
            subset=[r for r in arm_records if r["convergence_wallets_15m"]>=level]
            vals=[r.get("edge_300s") for r in subset if r.get("edge_300s") is not None]
            conv[arm][f"at_least_{level}_wallets"]={"n":len(vals),"mean_5m_edge":statistics.mean(vals) if vals else None,
                "median_5m_edge":statistics.median(vals) if vals else None}

    report={"kind":"successful_fomo_wallet_pump_alpha_event_study_v1","research_only":True,
        "strategy_data_used":False,"provider_spend_usd":0,
        "selection":"current persistent Fomo winners: top-10 in >=2 of 24h/7d/30d, verified Solana wallet; event timestamp comes from that trader's Fomo Solana buy, while Pump-native market state/outcomes come independently from Shrine",
        "survivorship_warning":"Trader selection uses current leaderboard success; results characterize these current winners and are not an ex-ante point-in-time strategy backtest.",
        "traders":traders,"per_trader_source":per,"archive_end":int(end_dt.timestamp()),"recent_hours":RECENT_HOURS,
        "raw_recent_solana_buys":len(raw),"dedup_independent_buy_targets":len(targets),
        "unique_target_mints":len({x["mint"] for x in targets}),"pump_native_targets_evaluated":len(matched),
        "matched_control_pairs":len(pairs),"complete_records":len(records),"trade_rows_processed":trade_rows,
        "diagnostics":dict(diagnostics),
        "design":{"dedup":"first wallet/mint buy after >=30m quiet period","entry_delay_seconds":ENTRY_DELAY,
            "strict_primary_control":"same time/protocol/quote; nearest pre-buy market cap, 5m return, 5m quote volume, trade count; excludes successful-wallet target activity +/-15m",
            "activity_matched_robustness_control":"same time/protocol/quote; nearest pre-buy 5m return, 5m quote volume, trade count, and last-trade recency; does not require marketCapQuote; same fixed max-distance 4.0",
            "pump_native_gate":"Shrine must show active PUMPFUN/PUMPSWAP trading state immediately before the Fomo buy timestamp",
            "horizons_seconds":list(HORIZONS),"primary_horizon_seconds":300},
        "summaries_by_arm":summaries_by_arm,"convergence_5m_by_arm":conv,"records":records,
        "limitations":["FomoAPI swap histories are capped for several traders; this study uses the exposed recent swaps only.",
            "Current-winner selection creates survivorship bias and cannot by itself prove these wallets were identifiable as skilled before each historical trade.",
            "Shrine documents occasional collector gaps; unmatched events are excluded rather than imputed.",
            "Market returns are raw price returns, not a copy-trader execution simulation with slippage/fees."]}
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"raw_recent_solana_buys":report["raw_recent_solana_buys"],
        "dedup_targets":report["dedup_independent_buy_targets"],"unique_target_mints":report["unique_target_mints"],
        "pump_native_targets_evaluated":report["pump_native_targets_evaluated"],"matched_control_pairs":report["matched_control_pairs"],
        "complete_records":report["complete_records"],"diagnostics":report["diagnostics"],
        "strict_primary_5m":summaries_by_arm["strict_market_cap"]["300"],
        "activity_matched_5m":summaries_by_arm["activity_matched"]["300"],
        "activity_matched_1m":summaries_by_arm["activity_matched"]["60"],
        "activity_matched_15m":summaries_by_arm["activity_matched"]["900"],
        "activity_matched_60m":summaries_by_arm["activity_matched"]["3600"],
        "convergence_5m_by_arm":conv},indent=2,sort_keys=True))

if __name__=="__main__":main()
