from __future__ import annotations
import io,json,math,os,statistics,urllib.parse,urllib.request
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import requests,zstandard

FOMO="https://api.fomoapi.io";REPLAY="https://replay.shrine.trade/pump";OUT=Path("fomo-successful-wallet-forward-study.json")
QUOTE={"So11111111111111111111111111111111111111112","EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v","Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
PROTOCOLS={"PUMPFUN","PUMPSWAP"};TOP_N=8;RECENT_HOURS=36;DEDUP=1800;ANCHOR_TOL=30;ENTRY_DELAY=15;ENTRY_TOL=90;OUTCOME_TOL=180;H=(60,300,900,3600)

def api(path,key,params=None):
 q=urllib.parse.urlencode(params or {});req=urllib.request.Request(FOMO+path+(("?"+q) if q else ""),headers={"Authorization":"Bearer "+key,"Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def pub(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read(4_000_000))
def ts(v):
 if isinstance(v,(int,float)):return int(v/1000) if v>1e10 else int(v)
 if isinstance(v,str):
  try:return int(datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
  except:return None
def addr(x):
 if isinstance(x,str):return x
 if isinstance(x,dict):
  for k in ("address","tokenAddress","mint"):
   if isinstance(x.get(k),str):return x[k]
def hour(t):return datetime.fromtimestamp(int(t),timezone.utc).strftime("%Y/%m/%d/%H")

def select(key):
 by=defaultdict(dict)
 for w in ("24h","7d","30d"):
  for r in api(f"/v2/leaderboard/{w}",key,{"limit":20}).get("traders") or []:
   uid=r.get("userId");ws=r.get("wallets") if isinstance(r.get("wallets"),dict) else {}
   if uid:by[uid][w]={"rank":int(r.get("rank") or 999),"handle":r.get("handle"),"wallet":ws.get("solana"),"verified":bool(ws.get("verified")),"pnl":r.get("pnlUsd")}
 out=[]
 for uid,v in by.items():
  s=next(iter(v.values()));t10=sum(x["rank"]<=10 for x in v.values())
  if t10>=2 and s["wallet"] and s["verified"]:
   out.append({"user_id":uid,"handle":s["handle"],"wallet":s["wallet"],"ranks":{w:x["rank"] for w,x in v.items()},"pnl":{w:x["pnl"] for w,x in v.items()},"key":(-t10,-len(v),sum(x["rank"] for x in v.values())+50*(3-len(v)))})
 out.sort(key=lambda x:(x["key"],x["user_id"]));return out[:TOP_N]

def get_targets(key,ws,available,cutoff):
 raw=[];src={}
 for w in ws:
  b=api(f"/v2/users/{urllib.parse.quote(w['user_id'],safe='')}/swaps",key);rr=[]
  for s in b.get("swaps") or []:
   t=ts(s.get("at") or s.get("createdAt"));ti=addr(s.get("tokenIn"));to=addr(s.get("tokenOut"));chain=str(s.get("chain") or "").lower();cid=s.get("chainId")
   if not t or t<cutoff or hour(t) not in available or (chain!="solana" and str(cid)!="1399811149"):continue
   if to and to not in QUOTE and (not ti or ti in QUOTE):
    x={"ts":t,"mint":to,"handle":w["handle"],"wallet":w["wallet"],"swap_id":s.get("swapId")};rr.append(x);raw.append(x)
  src[w["handle"]]={"recent_buys":len(rr),"swap_rows":len(b.get("swaps") or []),"source_capped":b.get("sourceCapped"),"complete":b.get("complete")}
 raw.sort(key=lambda x:(x["ts"],x["wallet"],x["mint"],str(x.get("swap_id"))))
 out=[];last={}
 for x in raw:
  k=(x["wallet"],x["mint"])
  if k in last and x["ts"]-last[k]<DEDUP:last[k]=x["ts"];continue
  out.append(x);last[k]=x["ts"]
 for x in out:x["convergence_wallets_15m"]=len({y["wallet"] for y in raw if y["mint"]==x["mint"] and x["ts"]-900<=y["ts"]<=x["ts"]})
 return raw,out,src

def first_at_or_after(rows,target,tol):
 for e in rows:
  if e["ts"]>=target and e["ts"]-target<=tol:return e
  if e["ts"]>target+tol:break
 return None
def nearest(rows,target,tol):
 best=None
 for e in rows:
  d=abs(e["ts"]-target)
  if d<=tol and (best is None or d<best[0]):best=(d,e)
  if e["ts"]>target+tol:break
 return best[1] if best else None

def smry(rows,key):
 v=[r[key] for r in rows if isinstance(r.get(key),(int,float)) and math.isfinite(r[key])]
 if not v:return {"n":0}
 return {"n":len(v),"mean_pct":statistics.mean(v),"median_pct":statistics.median(v),"positive_rate":sum(x>0 for x in v)/len(v),
  "gte_10pct_rate":sum(x>=10 for x in v)/len(v),"gte_25pct_rate":sum(x>=25 for x in v)/len(v),
  "gte_50pct_rate":sum(x>=50 for x in v)/len(v),"gte_100pct_rate":sum(x>=100 for x in v)/len(v),
  "lte_minus10pct_rate":sum(x<=-10 for x in v)/len(v),"min_pct":min(v),"max_pct":max(v)}

def main():
 key=os.environ["FOMOAPI_KEY"];idx=pub(REPLAY+"/index.json");available=set(idx.get("hours") or [])
 end=datetime.strptime(sorted(available)[-1],"%Y/%m/%d/%H").replace(tzinfo=timezone.utc)+timedelta(hours=1);cutoff=int((end-timedelta(hours=RECENT_HOURS)).timestamp())
 ws=select(key);raw,targets,source=get_targets(key,ws,available,cutoff);mints={x["mint"] for x in targets}
 needed=set()
 for x in targets:
  dt=datetime.fromtimestamp(x["ts"],timezone.utc).replace(minute=0,second=0,microsecond=0)
  for off in (-1,0,1,2):
   h=(dt+timedelta(hours=off)).strftime("%Y/%m/%d/%H")
   if h in available:needed.add(h)
 trades=defaultdict(list);migrations=defaultdict(list);headers={"User-Agent":"Mozilla/5.0","Accept":"application/octet-stream"};seen=0
 for h in sorted(needed):
  with requests.get(f"{REPLAY}/{h}.jsonl.zst",headers=headers,stream=True,timeout=60) as r:
   r.raise_for_status();reader=zstandard.ZstdDecompressor().stream_reader(r.raw)
   for line in io.TextIOWrapper(reader,encoding="utf-8"):
    try:e=json.loads(line)
    except:continue
    mint=e.get("mint")
    if mint not in mints:continue
    t=e.get("timestamp");act=e.get("action");prot=e.get("protocol")
    if not isinstance(t,(int,float)):continue
    t=int(t)
    if act=="migrate":migrations[mint].append(t);continue
    if act not in ("buy","sell") or prot not in PROTOCOLS:continue
    p=e.get("price")
    if not isinstance(p,(int,float)) or p<=0:continue
    trades[mint].append({"ts":t,"price":float(p),"action":act,"protocol":prot,"mcap":e.get("marketCapQuote")});seen+=1
 for m in trades:trades[m].sort(key=lambda e:e["ts"])
 rows=[];diag=defaultdict(int)
 for x in targets:
  rr=trades.get(x["mint"],[]);anchor=nearest(rr,x["ts"],ANCHOR_TOL)
  if not anchor:diag["no_nearby_pump_trade"]+=1;continue
  diag["pump_native_verified"]+=1
  entry=first_at_or_after(rr,x["ts"]+ENTRY_DELAY,ENTRY_TOL)
  if not entry:diag["no_actionable_entry"]+=1;continue
  rec={**x,"anchor_ts":anchor["ts"],"anchor_delta_seconds":anchor["ts"]-x["ts"],"anchor_protocol":anchor["protocol"],
       "entry_ts":entry["ts"],"entry_delay_actual_seconds":entry["ts"]-x["ts"],"entry_price":entry["price"],
       "graduated_within_60m":any(x["ts"]<=t<=x["ts"]+3600 for t in migrations.get(x["mint"],[]))}
  window=[e for e in rr if entry["ts"]<=e["ts"]<=entry["ts"]+3600]
  if window:
   rec["mfe_60m_pct"]=(max(e["price"] for e in window)/entry["price"]-1)*100
   rec["mae_60m_pct"]=(min(e["price"] for e in window)/entry["price"]-1)*100
  for h in H:
   e=first_at_or_after(rr,entry["ts"]+h,OUTCOME_TOL)
   if e:rec[f"return_{h}s_pct"]=(e["price"]/entry["price"]-1)*100
  rows.append(rec)
 summaries={str(h):smry(rows,f"return_{h}s_pct") for h in H};summaries["mfe_60m"]=smry(rows,"mfe_60m_pct");summaries["mae_60m"]=smry(rows,"mae_60m_pct")
 per_wallet={}
 for w in ws:
  a=[r for r in rows if r["handle"]==w["handle"]]
  per_wallet[w["handle"]]={"events":len(a),"five_minute":smry(a,"return_300s_pct"),"fifteen_minute":smry(a,"return_900s_pct"),"mfe_60m":smry(a,"mfe_60m_pct")}
 conv={}
 for n in (1,2,3):
  a=[r for r in rows if r["convergence_wallets_15m"]>=n]
  conv[str(n)]={"events":len(a),"five_minute":smry(a,"return_300s_pct"),"fifteen_minute":smry(a,"return_900s_pct"),"mfe_60m":smry(a,"mfe_60m_pct")}
 report={"kind":"successful_fomo_wallet_forward_return_study_v1","research_only":True,"provider_spend_usd":0,
  "selection":"current persistent Fomo winners (top-10 in >=2 of 24h/7d/30d), verified Solana wallets; no Fomo popularity requirement on tokens",
  "survivorship_warning":"current winners are selected with future information relative to some buys; this characterizes their exposed recent buys but is not an ex-ante strategy backtest",
  "traders":ws,"source":source,"raw_buys":len(raw),"dedup_targets":len(targets),"unique_mints":len(mints),"relevant_shrine_trade_rows":seen,
  "diagnostics":dict(diag),"summaries":summaries,"per_wallet":per_wallet,"convergence":conv,"records":rows,
  "design":{"dedup":"first wallet/mint buy after >=30m quiet period","pump_verification":"nearest Shrine PUMPFUN/PUMPSWAP trade within +/-30s of Fomo buy timestamp",
   "actionable_entry":"first Shrine trade at least 15s after Fomo buy and no more than 90s late","outcomes_seconds":list(H)},
  "limitations":["No matched market control in this pass; results describe absolute post-signal behavior, not incremental market-adjusted alpha.",
   "FomoAPI swap histories are source-capped for some traders.","Current-winner selection has survivorship bias.","Returns exclude fees/slippage."]}
 OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
 print(json.dumps({"raw_buys":report["raw_buys"],"dedup_targets":report["dedup_targets"],"unique_mints":report["unique_mints"],"diagnostics":report["diagnostics"],
  "one_minute":summaries["60"],"five_minute":summaries["300"],"fifteen_minute":summaries["900"],"sixty_minute":summaries["3600"],
  "mfe_60m":summaries["mfe_60m"],"mae_60m":summaries["mae_60m"],"convergence":conv,"per_wallet":per_wallet},indent=2,sort_keys=True))
if __name__=="__main__":main()
