from __future__ import annotations
import bisect, io, json, math, os, random, statistics, urllib.parse, urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests, zstandard

FOMO="https://api.fomoapi.io"; REPLAY="https://replay.shrine.trade/pump"
OUT=Path("fomo-wallet-alpha-anchor-study.json")
PROTOCOLS={"PUMPFUN","PUMPSWAP"}
QUOTE={"So11111111111111111111111111111111111111112","EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
TOP_N=8; RECENT_HOURS=12; DEDUP=1800; ANCHOR_TOL=30; ENTRY_DELAY=15; ENTRY_TOL=90
HORIZONS=(60,300,900,3600); OUTCOME_TOL=180; ACTIVE_AGE=60; EXCLUSION=900

def api(path,key,params=None):
 q=urllib.parse.urlencode(params or {}); req=urllib.request.Request(FOMO+path+(("?"+q) if q else ""),headers={"Authorization":"Bearer "+key,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def pub(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def pts(v):
 if isinstance(v,(int,float)):return int(v/1000) if v>1e10 else int(v)
 if isinstance(v,str):
  try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
  except:return None
def addr(x):
 if isinstance(x,str):return x
 if isinstance(x,dict):
  for k in ("address","tokenAddress","mint"):
   if isinstance(x.get(k),str):return x[k]
def hr(t):return datetime.fromtimestamp(int(t),timezone.utc).strftime("%Y/%m/%d/%H")

def winners(key):
 by=defaultdict(dict)
 for w in ("24h","7d","30d"):
  for r in api(f"/v2/leaderboard/{w}",key,{"limit":20}).get("traders") or []:
   uid=r.get("userId"); ws=r.get("wallets") if isinstance(r.get("wallets"),dict) else {}
   if uid:by[uid][w]={"rank":int(r.get("rank") or 999),"handle":r.get("handle"),"wallet":ws.get("solana"),"verified":bool(ws.get("verified")),"pnl":r.get("pnlUsd")}
 out=[]
 for uid,v in by.items():
  s=next(iter(v.values()));t10=sum(x["rank"]<=10 for x in v.values())
  if t10>=2 and s["wallet"] and s["verified"]:
   out.append({"user_id":uid,"handle":s["handle"],"wallet":s["wallet"],"ranks":{w:x["rank"] for w,x in v.items()},"pnl":{w:x["pnl"] for w,x in v.items()},"score":(-t10,-len(v),sum(x["rank"] for x in v.values())+50*(3-len(v)))})
 out.sort(key=lambda x:(x["score"],x["user_id"]));return out[:TOP_N]

def buys(key,ws,available,cutoff):
 raw=[];src={}
 for w in ws:
  b=api(f"/v2/users/{urllib.parse.quote(w['user_id'],safe='')}/swaps",key)
  rr=[]
  for s in b.get("swaps") or []:
   t=pts(s.get("at") or s.get("createdAt"));ti=addr(s.get("tokenIn"));to=addr(s.get("tokenOut"))
   chain=str(s.get("chain") or "").lower();cid=s.get("chainId")
   if not t or t<cutoff or hr(t) not in available or (chain!="solana" and str(cid)!="1399811149"):continue
   if to and to not in QUOTE and (not ti or ti in QUOTE):
    x={"ts":t,"mint":to,"handle":w["handle"],"wallet":w["wallet"],"swap_id":s.get("swapId")};rr.append(x);raw.append(x)
  src[w["handle"]]={"recent_buys":len(rr),"rows":len(b.get("swaps") or []),"source_capped":b.get("sourceCapped"),"complete":b.get("complete")}
 raw.sort(key=lambda x:(x["ts"],x["wallet"],x["mint"],str(x.get("swap_id"))))
 out=[];last={}
 for x in raw:
  k=(x["wallet"],x["mint"])
  if k in last and x["ts"]-last[k]<DEDUP:last[k]=x["ts"];continue
  out.append(x);last[k]=x["ts"]
 for x in out:
  x["convergence_wallets_15m"]=len({y["wallet"] for y in raw if y["mint"]==x["mint"] and x["ts"]-900<=y["ts"]<=x["ts"]})
 return raw,out,src

class State:
 def __init__(self):
  self.last_ts=None;self.price=None;self.mcap=None;self.protocol=None;self.quote=None
 def add(self,e):
  self.last_ts=int(e["timestamp"]);self.price=float(e["price"]);self.protocol=e.get("protocol");self.quote=e.get("quoteMint")
  m=e.get("marketCapQuote")
  if isinstance(m,(int,float)) and m>0:self.mcap=float(m)
 def active(self,now):
  return self.last_ts is not None and now-self.last_ts<=ACTIVE_AGE and self.price and self.protocol in PROTOCOLS

def role():
 return {"entry_target":None,"entry_ts":None,"entry_price":None,"prices":{},"max60":None,"min60":None}
def upd(r,ts,p,event_ts):
 if r["entry_target"] is None:r["entry_target"]=event_ts+ENTRY_DELAY
 if r["entry_price"] is None:
  if ts>=r["entry_target"] and ts-r["entry_target"]<=ENTRY_TOL:
   r["entry_ts"]=ts;r["entry_price"]=p;r["max60"]=p;r["min60"]=p
  return
 if ts<r["entry_ts"]:return
 if ts<=r["entry_ts"]+3600:r["max60"]=max(r["max60"],p);r["min60"]=min(r["min60"],p)
 for h in HORIZONS:
  k=str(h)
  if k not in r["prices"] and ts>=r["entry_ts"]+h and ts-(r["entry_ts"]+h)<=OUTCOME_TOL:r["prices"][k]={"ts":ts,"price":p}

def signp(a,b):
 n=a+b
 if not n:return None
 from math import comb
 k=min(a,b);return min(1.0,2*sum(comb(n,i) for i in range(k+1))/(2**n))
def boot(v,seed=91726):
 v=[float(x) for x in v if isinstance(x,(int,float)) and math.isfinite(x)]
 if len(v)<2:return [None,None]
 rng=random.Random(seed);m=[]
 for _ in range(5000):m.append(sum(v[rng.randrange(len(v))] for _ in range(len(v)))/len(v))
 m.sort();return [m[int(.025*len(m))],m[int(.975*len(m))-1]]
def summarize(rows,h):
 tr=[r[f"target_return_{h}s"] for r in rows if f"target_return_{h}s" in r]
 paired=[r for r in rows if f"edge_{h}s" in r];ed=[r[f"edge_{h}s"] for r in paired]
 tc=defaultdict(list);mc=defaultdict(list)
 for r in paired:tc[r["handle"]].append(r[f"edge_{h}s"]);mc[(r["handle"],r["mint"])].append(r[f"edge_{h}s"])
 w=[statistics.mean(x) for x in tc.values()];m=[statistics.mean(x) for x in mc.values()]
 return {"target_n":len(tr),"target_mean_return_pct":statistics.mean(tr) if tr else None,"target_median_return_pct":statistics.median(tr) if tr else None,
  "paired_n":len(ed),"mean_edge_pct_points":statistics.mean(ed) if ed else None,"median_edge_pct_points":statistics.median(ed) if ed else None,
  "bootstrap_95pct_ci_mean_edge":boot(ed),"beats":sum(x>0 for x in ed),"loses":sum(x<0 for x in ed),"sign_p":signp(sum(x>0 for x in ed),sum(x<0 for x in ed)),
  "wallet_cluster_mean_edge":statistics.mean(w) if w else None,"wallet_cluster_sign_p":signp(sum(x>0 for x in w),sum(x<0 for x in w)),
  "wallet_mint_cluster_mean_edge":statistics.mean(m) if m else None,"wallet_mint_cluster_sign_p":signp(sum(x>0 for x in m),sum(x<0 for x in m))}

def main():
 key=os.environ["FOMOAPI_KEY"];idx=pub(REPLAY+"/index.json");available=set(idx.get("hours") or [])
 end=datetime.strptime(sorted(available)[-1],"%Y/%m/%d/%H").replace(tzinfo=timezone.utc)+timedelta(hours=1)
 cutoff=int((end-timedelta(hours=RECENT_HOURS)).timestamp());ws=winners(key);raw,targets,source=buys(key,ws,available,cutoff)
 target_times=defaultdict(list)
 for x in raw:target_times[x["mint"]].append(x["ts"])
 for a in target_times.values():a.sort()
 needed=set()
 for x in targets:
  dt=datetime.fromtimestamp(x["ts"],timezone.utc).replace(minute=0,second=0,microsecond=0)
  for off in (-1,0,1,2):
   h=(dt+timedelta(hours=off)).strftime("%Y/%m/%d/%H")
   if h in available:needed.add(h)
 hours=sorted(needed);states={};pairs=[];watches=defaultdict(list);pending=0;targets=sorted(targets,key=lambda x:x["ts"])
 diagnostics=defaultdict(int);used_controls={}
 headers={"User-Agent":"Mozilla/5.0","Accept":"application/octet-stream"}
 def contaminated(mint,ts):
  a=target_times.get(mint) or [];i=bisect.bisect_left(a,ts)
  return any(0<=j<len(a) and abs(a[j]-ts)<=EXCLUSION for j in (i-1,i))
 def make_pair(t,anchor):
  protocol=anchor.get("protocol");quote=anchor.get("quoteMint");mcap=anchor.get("marketCapQuote")
  diagnostics["anchors"]+=1
  if protocol not in PROTOCOLS:return
  candidates=[]
  if isinstance(mcap,(int,float)) and mcap>0:
   for mint,s in states.items():
    if mint==t["mint"] or not s.active(anchor["timestamp"]) or s.protocol!=protocol or s.quote!=quote or not s.mcap or contaminated(mint,t["ts"]):continue
    if used_controls.get(mint,0)>anchor["timestamp"]-60:continue
    d=abs(math.log(float(mcap)/s.mcap));candidates.append((d,mint,s))
  if not candidates:diagnostics["no_marketcap_control"]+=1
  else:
   d,cm,cs=min(candidates,key=lambda x:(x[0],x[1]));used_controls[cm]=anchor["timestamp"];diagnostics["pairs"]+=1
   p={"handle":t["handle"],"wallet":t["wallet"],"mint":t["mint"],"event_ts":t["ts"],"anchor_ts":int(anchor["timestamp"]),
      "anchor_delay_seconds":int(anchor["timestamp"])-t["ts"],"anchor_protocol":protocol,"anchor_market_cap_quote":mcap,
      "convergence_wallets_15m":t["convergence_wallets_15m"],"control_mint":cm,"marketcap_log_distance":d,
      "target":role(),"control":role()}
   i=len(pairs);pairs.append(p);watches[t["mint"]].append((i,"target"));watches[cm].append((i,"control"))
  # target-only record even when no control
  if not candidates:
   p={"handle":t["handle"],"wallet":t["wallet"],"mint":t["mint"],"event_ts":t["ts"],"anchor_ts":int(anchor["timestamp"]),
      "anchor_delay_seconds":int(anchor["timestamp"])-t["ts"],"anchor_protocol":protocol,"anchor_market_cap_quote":mcap,
      "convergence_wallets_15m":t["convergence_wallets_15m"],"control_mint":None,"marketcap_log_distance":None,
      "target":role(),"control":role()}
   i=len(pairs);pairs.append(p);watches[t["mint"]].append((i,"target"))
 for h in hours:
  with requests.get(f"{REPLAY}/{h}.jsonl.zst",headers=headers,stream=True,timeout=60) as resp:
   resp.raise_for_status();reader=zstandard.ZstdDecompressor().stream_reader(resp.raw)
   for line in io.TextIOWrapper(reader,encoding="utf-8"):
    try:e=json.loads(line)
    except:continue
    ts=e.get("timestamp");mint=e.get("mint");act=e.get("action");prot=e.get("protocol");price=e.get("price")
    if not isinstance(ts,(int,float)) or not mint:continue
    ts=int(ts)
    # expire targets with no Pump-native trade within anchor tolerance
    while pending<len(targets) and targets[pending]["ts"]+ANCHOR_TOL<ts:
     diagnostics["no_anchor_within_30s"]+=1;pending+=1
    # if this is the first trade for pending target mint at/after signal, anchor it
    if act in ("buy","sell") and prot in PROTOCOLS and isinstance(price,(int,float)) and price>0:
     for j in range(pending,min(len(targets),pending+50)):
      t=targets[j]
      if t["ts"]>ts:break
      if 0<=ts-t["ts"]<=ANCHOR_TOL and t["mint"]==mint and not t.get("_anchored"):
       t["_anchored"]=True;make_pair(t,e);diagnostics["targets_anchored"]+=1
     while pending<len(targets) and targets[pending].get("_anchored"):pending+=1
     st=states.get(mint)
     if st is None:st=states[mint]=State()
     st.add(e)
     for i,k in watches.get(mint,[]):upd(pairs[i][k],ts,float(price),pairs[i]["event_ts"])
 while pending<len(targets):diagnostics["no_anchor_within_30s"]+=1;pending+=1
 records=[]
 for p in pairs:
  a=p["target"];b=p["control"];r={k:v for k,v in p.items() if k not in ("target","control")}
  if a["entry_price"]:
   r["target_entry_ts"]=a["entry_ts"];r["target_mfe_60m_pct"]=(a["max60"]/a["entry_price"]-1)*100;r["target_mae_60m_pct"]=(a["min60"]/a["entry_price"]-1)*100
   for h in HORIZONS:
    k=str(h)
    if k in a["prices"]:r[f"target_return_{h}s"]=(a["prices"][k]["price"]/a["entry_price"]-1)*100
  if p["control_mint"] and b["entry_price"]:
   r["control_entry_ts"]=b["entry_ts"]
   for h in HORIZONS:
    k=str(h)
    if k in a["prices"] and k in b["prices"]:
     cr=(b["prices"][k]["price"]/b["entry_price"]-1)*100;r[f"control_return_{h}s"]=cr;r[f"edge_{h}s"]=r[f"target_return_{h}s"]-cr
  if any(f"target_return_{h}s" in r for h in HORIZONS):records.append(r)
 summaries={str(h):summarize(records,h) for h in HORIZONS}
 conv={}
 for n in (1,2,3):
  rr=[r for r in records if r["convergence_wallets_15m"]>=n and "target_return_300s" in r]
  conv[str(n)]={"n":len(rr),"mean_5m_return":statistics.mean([r["target_return_300s"] for r in rr]) if rr else None,
   "median_5m_return":statistics.median([r["target_return_300s"] for r in rr]) if rr else None,
   "paired_n":sum("edge_300s" in r for r in rr),"mean_5m_edge":statistics.mean([r["edge_300s"] for r in rr if "edge_300s" in r]) if any("edge_300s" in r for r in rr) else None}
 report={"kind":"successful_fomo_wallet_pump_anchor_event_study_v1","research_only":True,"provider_spend_usd":0,
  "selection":"current persistent Fomo winners (top-10 in >=2 of 24h/7d/30d); signal timestamp/mint from their normalized Solana buy history",
  "survivorship_warning":"current-winner selection is retrospective and cannot establish an ex-ante trading rule",
  "traders":ws,"source":source,"raw_buys":len(raw),"dedup_targets":len(targets),"unique_mints":len({x["mint"] for x in targets}),
  "diagnostics":dict(diagnostics),"records":records,"summaries":summaries,"convergence_5m":conv,
  "design":{"anchor":"first independent Shrine Pump.fun/PumpSwap trade on mint at/after Fomo skilled-wallet buy, <=30s",
   "entry_delay_seconds":ENTRY_DELAY,"absolute_outcomes":"target returns at 1m/5m/15m/60m after actionable entry",
   "paired_control":"when event-time marketCapQuote exists, nearest same-time active token on same venue/quote by log market-cap distance; successful-wallet target mints excluded +/-15m"},
  "limitations":["Current winners are selected with future information relative to older buys (survivorship bias).","FomoAPI swap pages are source-capped for some traders.","Market-cap matching is available only when Shrine reports marketCapQuote.","Returns are market prices, not execution PnL after fees/slippage."]}
 OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
 print(json.dumps({"raw_buys":report["raw_buys"],"dedup_targets":report["dedup_targets"],"unique_mints":report["unique_mints"],"diagnostics":report["diagnostics"],
  "one_minute":summaries["60"],"five_minute":summaries["300"],"fifteen_minute":summaries["900"],"sixty_minute":summaries["3600"],"convergence_5m":conv},indent=2,sort_keys=True))
if __name__=="__main__":main()
