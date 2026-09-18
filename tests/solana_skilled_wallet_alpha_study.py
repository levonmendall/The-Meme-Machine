from __future__ import annotations
import bisect,io,json,math,os,random,statistics,tempfile,time,urllib.parse,urllib.request
from collections import defaultdict,deque
from datetime import datetime,timezone
from pathlib import Path
import requests,zstandard

API="https://madeonsol.com/api/v1"; DEMO="msk_demo_try_the_solana_api_2026"
REPLAY="https://replay.shrine.trade/pump"; OUT=Path("solana-skilled-wallet-alpha-study.json")
ENTRY_DELAYS=(15,60); HORIZONS=(60,300,900,3600)
ENTRY_TOL=90; OUTCOME_TOL=180; ROLL=300; ACTIVE=60; DEDUP=1800; EXCLUDE=900
COHORT_N=20; MIN_TOKENS=10

def made(params):
 q=urllib.parse.urlencode(params);req=urllib.request.Request(API+"/alpha/leaderboard?"+q,headers={"Authorization":"Bearer "+DEMO,"Accept":"application/json","User-Agent":"Mozilla/5.0"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def pub(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def cohort():
 data=json.loads(Path("tests/fixtures/solana_alpha_wallet_cohort_frozen.json").read_text())
 persistent=set(data["persistent_7d_top100"])
 out=[]
 for r in data["cohort"]:
  x=dict(r);x["persistent_7d_top100"]=x["wallet"] in persistent;out.append(x)
 return out

def download_hour(hour_name,headers,attempts=5):
 url=f"{REPLAY}/{hour_name}.jsonl.zst"
 last=None
 for attempt in range(attempts):
  fd,path=tempfile.mkstemp(prefix="shrine-hour-",suffix=".jsonl.zst")
  os.close(fd)
  try:
   with requests.get(url,headers=headers,stream=True,timeout=(20,300)) as resp:
    resp.raise_for_status()
    with open(path,"wb") as out:
     for chunk in resp.iter_content(chunk_size=4*1024*1024):
      if chunk:out.write(chunk)
   if os.path.getsize(path)<=0:raise RuntimeError("empty_archive_hour")
   return path
  except Exception as exc:
   last=exc
   try:os.unlink(path)
   except FileNotFoundError:pass
   if attempt+1<attempts:time.sleep(min(5*(attempt+1),20))
 if last:raise last
 raise RuntimeError("archive_download_failed")
class State:
 def __init__(self):
  self.q=deque();self.vol=0.;self.n=0;self.last=None;self.price=None;self.mcap=None;self.protocol=None;self.quote=None;self.created=None
 def purge(self,t):
  while self.q and self.q[0][0]<t-ROLL:
   _,_,q=self.q.popleft();self.vol-=q;self.n-=1
 def trade(self,e):
  t=int(e["timestamp"]);p=float(e["price"]);q=abs(float(e.get("quoteAmount") or 0));self.purge(t)
  self.q.append((t,p,q));self.vol+=q;self.n+=1;self.last=t;self.price=p;self.protocol=e.get("protocol");self.quote=e.get("quoteMint")
  m=e.get("marketCapQuote")
  if isinstance(m,(int,float)) and m>0:self.mcap=float(m)
 def feat(self,t):
  self.purge(t)
  if self.last is None or t-self.last>ACTIVE or self.price is None or self.n<2 or not self.mcap:return None
  first=self.q[0][1]
  if first<=0:return None
  return {"mcap":self.mcap,"pre5":self.price/first-1,"vol5":max(self.vol,0),"count5":self.n,"protocol":self.protocol,"quote":self.quote,
          "age":(t-self.created if self.created else None)}

def distance(a,b):
 if a["protocol"]!=b["protocol"] or a["quote"]!=b["quote"]:return None
 d=1.5*abs(math.log(a["mcap"]/b["mcap"])) + abs(a["pre5"]-b["pre5"])/0.20 + .75*abs(math.log1p(a["vol5"])-math.log1p(b["vol5"])) + .5*abs(math.log1p(a["count5"])-math.log1p(b["count5"]))
 if a.get("age") and b.get("age") and a["age"]>0 and b["age"]>0:d+=.5*abs(math.log1p(a["age"])-math.log1p(b["age"]))
 return d
def role():
 return {str(d):{"target":None,"entry_ts":None,"entry":None,"prices":{},"hi":None,"lo":None} for d in ENTRY_DELAYS}
def upd(r,t,p,event):
 for d in ENTRY_DELAYS:
  x=r[str(d)]
  if x["target"] is None:x["target"]=event+d
  if x["entry"] is None:
   if t>=x["target"] and t-x["target"]<=ENTRY_TOL:
    x["entry_ts"]=t;x["entry"]=p;x["hi"]=p;x["lo"]=p
   continue
  if t<x["entry_ts"]:continue
  if t<=x["entry_ts"]+3600:x["hi"]=max(x["hi"],p);x["lo"]=min(x["lo"],p)
  for h in HORIZONS:
   k=str(h)
   if k not in x["prices"] and t>=x["entry_ts"]+h and t-(x["entry_ts"]+h)<=OUTCOME_TOL:x["prices"][k]={"ts":t,"p":p}
def signp(pos,neg):
 n=pos+neg
 if not n:return None
 from math import comb
 k=min(pos,neg);return min(1.,2*sum(comb(n,i) for i in range(k+1))/(2**n))
def boot(v,seed=180926):
 v=[float(x) for x in v if isinstance(x,(int,float)) and math.isfinite(x)]
 if len(v)<2:return [None,None]
 rng=random.Random(seed);m=[]
 for _ in range(5000):m.append(sum(v[rng.randrange(len(v))] for _ in range(len(v)))/len(v))
 m.sort();return [m[int(.025*len(m))],m[int(.975*len(m))-1]]
def summarize(rows,d,h,persistent_only=False):
 rr=[r for r in rows if (not persistent_only or r["persistent_7d_top100"]) and f"edge_{d}s_{h}s" in r]
 ed=[r[f"edge_{d}s_{h}s"] for r in rr];ta=[r[f"target_return_{d}s_{h}s"] for r in rr];co=[r[f"control_return_{d}s_{h}s"] for r in rr]
 wc=defaultdict(list);mc=defaultdict(list)
 for r in rr:wc[r["wallet"]].append(r[f"edge_{d}s_{h}s"]);mc[(r["wallet"],r["mint"])].append(r[f"edge_{d}s_{h}s"])
 w=[statistics.mean(x) for x in wc.values()];m=[statistics.mean(x) for x in mc.values()]
 pos=sum(x>0 for x in ed);neg=sum(x<0 for x in ed)
 return {"n":len(rr),"wallets":len(wc),"wallet_mints":len(mc),
  "target_mean_pct":statistics.mean(ta) if ta else None,"target_median_pct":statistics.median(ta) if ta else None,
  "control_mean_pct":statistics.mean(co) if co else None,"control_median_pct":statistics.median(co) if co else None,
  "mean_edge_pp":statistics.mean(ed) if ed else None,"median_edge_pp":statistics.median(ed) if ed else None,"bootstrap95_mean_edge":boot(ed),
  "beats":pos,"loses":neg,"sign_p":signp(pos,neg),"wallet_cluster_mean_edge_pp":statistics.mean(w) if w else None,
  "wallet_cluster_sign_p":signp(sum(x>0 for x in w),sum(x<0 for x in w)),
  "wallet_mint_cluster_mean_edge_pp":statistics.mean(m) if m else None,
  "wallet_mint_cluster_sign_p":signp(sum(x>0 for x in m),sum(x<0 for x in m))}
def main():
 cohort_rows=cohort(); wallets={x["wallet"]:x for x in cohort_rows}; walletset=set(wallets)
 idx=pub(REPLAY+"/index.json");hours=idx.get("hours") or []
 states={};pairs=[];watch=defaultdict(list);lastbuy={};top_times=defaultdict(list);used_ctrl={};last_cleanup=0;trade_rows=0;buy_events=0;target_only=0
 headers={"User-Agent":"Mozilla/5.0","Accept":"application/octet-stream"}
 def contaminated(mint,t):
  a=top_times.get(mint) or [];i=bisect.bisect_left(a,t)
  return any(0<=j<len(a) and abs(a[j]-t)<=EXCLUDE for j in (i-1,i))
 def choose(tf,mint,t):
  opts=[]
  for cm,s in states.items():
   if cm==mint or contaminated(cm,t) or used_ctrl.get(cm,0)>t-60:continue
   cf=s.feat(t)
   if not cf:continue
   d=distance(tf,cf)
   if d is not None and d<=4.0:opts.append((d,cm,cf))
  if not opts:return None
  x=min(opts,key=lambda z:(z[0],z[1]));used_ctrl[x[1]]=t;return x
 for h in hours:
  with requests.get(f"{REPLAY}/{h}.jsonl.zst",headers=headers,stream=True,timeout=300) as resp:
   resp.raise_for_status();reader=zstandard.ZstdDecompressor().stream_reader(resp.raw)
   for line in io.TextIOWrapper(reader,encoding="utf-8"):
     try:e=json.loads(line)
     except:continue
     t=e.get("timestamp");mint=e.get("mint");act=e.get("action")
     if not isinstance(t,(int,float)) or not mint:continue
     t=int(t)
     if act=="create":
      st=states.get(mint)
     if st is None:st=states[mint]=State()
     st.created=t;continue
     if act=="migrate":
     for pi,k in watch.get(mint,[]):
      p=pairs[pi]
      if p["event_ts"]<=t<=p["event_ts"]+3600:p["target_grad" if k=="target" else "control_grad"]=True
     continue
     if act not in ("buy","sell"):continue
     price=e.get("price")
     if not isinstance(price,(int,float)) or price<=0:continue
     trade_rows+=1
     involved=set(e.get("tradersInvolved") or [])
     hits=sorted(involved & walletset) if act=="buy" else []
     for w in hits:
      k=(w,mint);prev=lastbuy.get(k)
      top_times[mint].append(t)
      if prev is not None and t-prev<DEDUP:
       lastbuy[k]=t;continue
      lastbuy[k]=t;buy_events+=1
      st=states.get(mint);tf=st.feat(t) if st else None
      meta=wallets[w]
      conv=len({ww for tt,ww in [(tt,ww) for tt,ww in []]}) # overwritten below
      recent_wallets=set()
      # Count cohort wallets seen buying this mint in prior 15m, including current.
      # top_times stores times only, so infer current=1; previous distinct convergence isn't retained per wallet in this compact pass.
     recent_wallets.add(w)
      cc=choose(tf,mint,t) if tf else None
      p={"wallet":w,"rank_30d":meta.get("rank_30d"),"roi_30d":meta.get("roi_30d"),"persistent_7d_top100":meta.get("persistent_7d_top100"),
         "mint":mint,"event_ts":t,"protocol":e.get("protocol"),"quote":e.get("quoteMint"),"event_market_cap_quote":e.get("marketCapQuote"),
         "target_features":tf,"control_mint":None,"match_distance":None,"control_features":None,
         "target":role(),"control":role(),"target_grad":False,"control_grad":False}
      if cc:
       d,cm,cf=cc;p["control_mint"]=cm;p["match_distance"]=d;p["control_features"]=cf
      else:target_only+=1
      pi=len(pairs);pairs.append(p);watch[mint].append((pi,"target"))
      if cc:watch[p["control_mint"]].append((pi,"control"))
     st=states.get(mint)
     if st is None:st=states[mint]=State()
     st.trade(e)
     for pi,k in watch.get(mint,[]):upd(pairs[pi][k],t,float(price),pairs[pi]["event_ts"])
     if t-last_cleanup>=300:
      last_cleanup=t
      live_watch={m for m,arr in watch.items() if any(pairs[i]["event_ts"]+3900>=t for i,_ in arr)}
      for m in list(states):
       if m not in live_watch and (states[m].last or 0)<t-7200:del states[m]
      for m in list(watch):
       watch[m]=[(i,k) for i,k in watch[m] if pairs[i]["event_ts"]+3900>=t]
       if not watch[m]:del watch[m]
  finally:
   try:os.unlink(archive_path)
   except FileNotFoundError:pass
 # post-filter controls contaminated by a top-wallet buy within +/-15m using all observed cohort buys
 for a in top_times.values():a.sort()
 records=[]
 for p in pairs:
  if p["control_mint"] and contaminated(p["control_mint"],p["event_ts"]):continue
  r={k:v for k,v in p.items() if k not in ("target","control")}
  for d in ENTRY_DELAYS:
   a=p["target"][str(d)];b=p["control"][str(d)]
   if a["entry"]:
    r[f"target_mfe_{d}s_60m_pct"]=(a["hi"]/a["entry"]-1)*100;r[f"target_mae_{d}s_60m_pct"]=(a["lo"]/a["entry"]-1)*100
   for h in HORIZONS:
    kk=str(h)
    if a["entry"] and kk in a["prices"]:r[f"target_return_{d}s_{h}s"]=(a["prices"][kk]["p"]/a["entry"]-1)*100
    if p["control_mint"] and b["entry"] and kk in a["prices"] and kk in b["prices"]:
     cr=(b["prices"][kk]["p"]/b["entry"]-1)*100;r[f"control_return_{d}s_{h}s"]=cr
     r[f"edge_{d}s_{h}s"]=r[f"target_return_{d}s_{h}s"]-cr
  if any(k.startswith("target_return_") for k in r):records.append(r)
 summaries={}
 for d in ENTRY_DELAYS:
  for h in HORIZONS:
   summaries[f"d{d}_h{h}"]=summarize(records,d,h,False)
   summaries[f"d{d}_h{h}_persistent"]=summarize(records,d,h,True)
 per_wallet={}
 for w in wallets:
  rr=[r for r in records if r["wallet"]==w]
  vals=[r.get("edge_15s_300s") for r in rr if r.get("edge_15s_300s") is not None]
  per_wallet[w]={"events":len(rr),"paired_5m":len(vals),"mean_5m_edge_pp":statistics.mean(vals) if vals else None}
 report={"kind":"solana_high_roi_wallet_forward_alpha_study_v1","research_only":True,"provider_spend_usd":0,
  "cohort_source":"Frozen MadeOnSol public alpha leaderboard cohort from run 35301582766","selection":{"period":"30d","sort":"roi","min_tokens":MIN_TOKENS,"exclude_bots":True,"top_n":COHORT_N},
  "survivorship_warning":"Current 30d winners are selected using outcomes overlapping the archive. This is exploratory association, not an ex-ante walk-forward proof.",
  "cohort":cohort_rows,"archive_hours":len(hours),"trade_rows_processed":trade_rows,"independent_wallet_buy_events":buy_events,"pairs_created":len(pairs),
  "target_only_events":target_only,"complete_records":len(records),"summaries":summaries,"per_wallet":per_wallet,"records":records,
  "design":{"dedup":"first wallet/mint buy after 30m quiet","entry_delays_seconds":list(ENTRY_DELAYS),"horizons_seconds":list(HORIZONS),
    "control":"same-time active token, same protocol and quote; matched on market cap, prior-5m return, volume, trade count, and token age when known; controls with cohort buys +/-15m removed",
    "primary":"15-second delayed entry, 5-minute forward paired edge","persistent_sensitivity":"wallet also present in current 7d top-100 ROI leaderboard"},
  "limitations":["Cohort selection is survivorship-biased; a separate prospective/walk-forward validation is required before strategy authority.",
    "Shrine can have collector gaps; missing events are not imputed.","Returns are market-price returns and exclude execution fees/slippage."]}
 OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
 print(json.dumps({"cohort":len(cohort_rows),"persistent":sum(x["persistent_7d_top100"] for x in cohort_rows),"archive_hours":len(hours),"buy_events":buy_events,
 "pairs_created":len(pairs),"complete_records":len(records),"primary":summaries["d15_h300"],"persistent_primary":summaries["d15_h300_persistent"],
 "d15_1m":summaries["d15_h60"],"d15_15m":summaries["d15_h900"],"d15_60m":summaries["d15_h3600"],
 "delay60_5m":summaries["d60_h300"],"per_wallet":per_wallet},indent=2,sort_keys=True))
if __name__=="__main__":main()
