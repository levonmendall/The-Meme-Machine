#!/usr/bin/env python3
import copy, json, math, os, sys, tempfile, time as real_time
from pathlib import Path
from collections import defaultdict
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PONS_SRC=os.environ.get("PONS_SRC","/tmp/pons-src")
sys.path.insert(0,PONS_SRC)

from robinhood_research import BoundaryError
from robinhood_research.abi import calldata, topic, decode_event
from robinhood_research.pons import CurveState, factory_record, curve_abi
from robinhood_research.pons_natural_observation import RESEARCH_RECIPIENT, _one_word
from robinhood_research.pons_selective_continuation import (
    ENTRY_THRESHOLDS, POLICY_HASH, qualification_vector, normalized_trade,
)
import robinhood_research.pons_natural_observation as natobs
import robinhood_research.pons_selective_acquisition as acq
import robinhood_research.pons_natural_paper as natpaper
import robinhood_research.pons_selective_paper as paper
import robinhood_research.pons_selective_v4 as v4mod
from robinhood_research.provider import Rpc

RPC_URL=os.environ.get("ROBINHOOD_PUBLIC_RPC","https://rpc.mainnet.chain.robinhood.com")
FACTORY="0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"
ZERO="0x0000000000000000000000000000000000000000"
CAPITAL=10**18

# Lane-active windows. Exact native start/end are used where durable results retain
# them; short early windows use the live job boundary conservatively.
WINDOWS=[
 ("baseline",1789940232,1789940832),
 ("355472-smoke",1789949940,1789950540),
 ("355492-smoke",1789952250,1789952850),
 ("355492-hour",1789953983,1789957583),
 ("355555-smoke",1789959175,1789959775),
 ("355555-hour",1789960902,1789964502),
 ("355631-hour",1789968840,1789970209),
 ("355684-smoke",1789972067,1789972667),
 ("355684-hour",1789973814,1789974123),
 ("355715-hour",1789976288,1789976715),
 ("355784-smoke",1789979680,1789980280),
 ("355784-hour",1789981320,1789984920),
 ("355890-smoke",1789986711,1789987311),
 ("355890-hour",1789988465,1789992065),
 ("356054-smoke",1789997970,1789998570),
]

REVIEW_FILES=[
 "certification/results/campaign-baseline-35539161434.json",
 "certification/results/smoke-35547208867-review.json",
 "certification/results/smoke-35549221493-review.json",
 "certification/results/hourly-35549221493-review.json",
 "certification/results/hourly-35555511322-hosted-review.json",
 "certification/results/hourly-35563114670-cancellation.json",
 "certification/results/smoke-35568442889-review.json",
 "certification/results/hourly-35568442889-stable-archive-audit.json",
 "certification/results/hourly-35571580714-review.json",
 "certification/results/hourly-35578433187-review.json",
 "certification/results/smoke-35589047835-review.json",
 "certification/results/hourly-35589047835-review.json",
 "certification/results/smoke-35605451168-final-cancelled-checkpoint.json",
]

class PublicRPC:
    def __init__(self,url):
        self.url=url; self.next_id=1; self.calls=0; self.failures=defaultdict(int)
        self.block_cache={}; self.time_cache={}
        self.last_http=0.0
        self.min_http_interval=0.55
    def request(self,payload,attempts=20):
        raw=json.dumps(payload,separators=(",",":")).encode()
        req=Request(self.url,data=raw,headers={"Content-Type":"application/json","User-Agent":"meme-machine-market-audit/1"})
        for a in range(attempts):
            try:
                wait=self.min_http_interval-(real_time.monotonic()-self.last_http)
                if wait>0: real_time.sleep(wait)
                self.last_http=real_time.monotonic()
                with urlopen(req,timeout=30) as resp:
                    body=resp.read(25_000_000)
                val=json.loads(body)
                return val
            except HTTPError as e:
                self.failures[f"http_{e.code}"]+=1
                if e.code in (429,500,502,503,504) and a+1<attempts:
                    retry=e.headers.get("Retry-After") if getattr(e,"headers",None) else None
                    try: pause=max(float(retry or 0),min(30,1.0*(2**min(a,5))))
                    except Exception: pause=min(30,1.0*(2**min(a,5)))
                    real_time.sleep(pause); continue
                raise
            except (URLError,TimeoutError,OSError,ValueError) as e:
                self.failures[type(e).__name__]+=1
                if a+1<attempts:
                    real_time.sleep(min(8,0.5*(2**a))); continue
                raise
        raise RuntimeError("rpc_failed")
    def call(self,method,params):
        i=self.next_id;self.next_id+=1;self.calls+=1
        val=self.request({"jsonrpc":"2.0","id":i,"method":method,"params":params})
        if val.get("error"):
            raise RuntimeError(f"{method}:{val['error'].get('code')}:{val['error'].get('message','')[:160]}")
        return val.get("result")
    def batch(self,calls):
        if not calls:return []
        if len(calls)>4:
            out=[]
            for i in range(0,len(calls),4):
                out.extend(self.batch(calls[i:i+4]))
            return out
        payload=[]; ids=[]
        for method,params in calls:
            i=self.next_id;self.next_id+=1;ids.append(i)
            payload.append({"jsonrpc":"2.0","id":i,"method":method,"params":params})
        self.calls+=1
        val=self.request(payload)
        rows={x.get("id"):x for x in val}
        out=[]
        for i,(method,_) in zip(ids,calls):
            x=rows[i]
            if x.get("error"):
                raise RuntimeError(f"{method}:{x['error'].get('code')}:{x['error'].get('message','')[:160]}")
            out.append(x.get("result"))
        return out
    def header(self,n):
        n=int(n)
        if n not in self.block_cache:
            h=self.call("eth_getBlockByNumber",[hex(n),False])
            if not h: raise RuntimeError(f"missing_block:{n}")
            self.block_cache[n]=h; self.time_cache[n]=int(h["timestamp"],16)
        return self.block_cache[n]
    def block_at_or_before(self,ts,latest=None):
        ts=int(ts)
        if latest is None: latest=int(self.call("eth_blockNumber",[]),16)
        lo=0; hi=latest
        while lo<hi:
            mid=(lo+hi+1)//2
            t=int(self.header(mid)["timestamp"],16)
            if t<=ts: lo=mid
            else: hi=mid-1
        return lo
    def logs(self,start,end,topics0):
        out=[]
        calls=[]
        for first in range(int(start),int(end)+1,10):
            calls.append(("eth_getLogs",[{"fromBlock":hex(first),"toBlock":hex(min(end,first+9)),"topics":[topics0]}]))
            if len(calls)==4:
                for x in self.batch(calls): out.extend(x or [])
                calls=[]
        if calls:
            for x in self.batch(calls): out.extend(x or [])
        out.sort(key=lambda e:(int(e["blockNumber"],16),int(e["transactionIndex"],16),int(e["logIndex"],16)))
        return out

RPC=PublicRPC(RPC_URL)

class FakeTime:
    def __init__(self): self.now=0.0
    def set(self,x): self.now=float(x)
    def time(self): return self.now
    def monotonic(self): return self.now
    def sleep(self,s): self.now+=max(0,float(s))

FAKE=FakeTime()

class HistRpc(Rpc):
    def __init__(self,endpoint,limit=200,per_scope=190,retries=0,**kw):
        self.audit_client=RPC
        super().__init__(RPC_URL,limit=min(200,limit),per_scope=min(190,per_scope),retries=0,timeout=30,max_response=10_000_000)
    def _hist_block(self):
        return RPC.block_at_or_before(int(FAKE.time()))
    def _rewrite(self,method,params):
        p=copy.deepcopy(params)
        if method=="eth_blockNumber":
            return method,p
        if method=="eth_getBlockByNumber" and p and p[0] in ("latest","safe","finalized"):
            p[0]=hex(self._hist_block())
        if method in ("eth_call","eth_getCode","eth_getBalance","eth_getStorageAt") and len(p)>=2 and p[-1] in ("latest","safe","finalized"):
            p[-1]=hex(self._hist_block())
        return method,p
    def _http(self,method,params):
        method,params=self._rewrite(method,params)
        if method=="eth_blockNumber":
            return hex(self._hist_block())
        if method=="eth_gasPrice":
            h=RPC.header(self._hist_block())
            if h.get("baseFeePerGas") is not None:
                return h["baseFeePerGas"]
        return RPC.call(method,params)
    def _http_batch(self,calls):
        rewritten=[]
        for method,params in calls:
            method,params=self._rewrite(method,params)
            if method=="eth_blockNumber":
                rewritten.append(("eth_getBlockByNumber",[hex(self._hist_block()),False]))
            elif method=="eth_gasPrice":
                rewritten.append(("eth_getBlockByNumber",[hex(self._hist_block()),False]))
            else: rewritten.append((method,params))
        vals=RPC.batch(rewritten)
        out=[]
        for (om,_),(rm,_),v in zip(calls,rewritten,vals):
            if om=="eth_blockNumber": out.append(v["number"])
            elif om=="eth_gasPrice": out.append(v.get("baseFeePerGas") or RPC.call("eth_gasPrice",[]))
            else: out.append(v)
        return out

def hist_rpc(endpoint=None,**kwargs):
    return HistRpc(RPC_URL,**kwargs)

# Patch only the audit process. Production sources and thresholds remain untouched.
acq._rpc=hist_rpc
natpaper._rpc=hist_rpc
paper.paper_rpc=hist_rpc
paper.evidence_rpc=hist_rpc
natobs.time=FAKE
acq.time=FAKE
natpaper.time=FAKE
paper.time=FAKE
v4mod.time=FAKE

BUY_TOPIC=topic("CurveBuy(address,address,uint256,uint256,uint256,uint256)")
SELL_TOPIC=topic("CurveSell(address,address,uint256,uint256,uint256,uint256)")

def merge_ranges(rows):
    rows=sorted(rows);out=[]
    for a,b in rows:
        if out and a<=out[-1][1]+1: out[-1]=(out[-1][0],max(out[-1][1],b))
        else: out.append((a,b))
    return out

def label_for(ts):
    for name,a,b in WINDOWS:
        if a<=ts<=b:return name
    return None

def word_addr(raw):
    return _one_word(raw,"address").lower()

def cheap_preflight(event):
    block=int(event["blockNumber"],16); addr=event["address"].lower()
    calls=[
      ("eth_call",[{"to":addr,"data":calldata("factory()")},hex(block)]),
      ("eth_call",[{"to":addr,"data":calldata("realQuoteReserve()")},hex(block)]),
      ("eth_call",[{"to":addr,"data":calldata("graduationThreshold()")},hex(block)]),
      ("eth_call",[{"to":addr,"data":calldata("graduated()")},hex(block)]),
      ("eth_call",[{"to":addr,"data":calldata("currentSnipeTaxBps(address)",RESEARCH_RECIPIENT)},hex(block)]),
      ("eth_call",[{"to":addr,"data":calldata("creatorTaxBps()")},hex(block)]),
    ]
    try: vals=RPC.batch(calls)
    except Exception as e:return None,["preflight_rpc:"+str(e)[:100]]
    try:
        factory=word_addr(vals[0]);real=_one_word(vals[1]);threshold=_one_word(vals[2]);grad=bool(_one_word(vals[3],"bool"));snipe=_one_word(vals[4]);tax=_one_word(vals[5])
        progress=min(10000,real*10000//threshold) if threshold>0 else -1
    except Exception as e:return None,["preflight_decode:"+str(e)[:100]]
    reasons=[]
    if factory!=FACTORY: reasons.append("wrong_factory")
    if grad: reasons.append("already_graduated")
    if snipe!=0: reasons.append("snipe_tax_nonzero")
    if not (ENTRY_THRESHOLDS["min_curve_progress_bps"]<=progress<=ENTRY_THRESHOLDS["max_curve_progress_bps"]): reasons.append("curve_progress")
    if tax>ENTRY_THRESHOLDS["max_creator_tax_bps"]:reasons.append("creator_tax")
    return {"progress_bps":progress,"factory":factory,"real_quote":real,"threshold":threshold,"graduated":grad,"snipe":snipe,"creator_tax":tax},reasons

def event_time(event):
    return int(RPC.header(int(event["blockNumber"],16))["timestamp"],16)

def simple_price(decoded):
    a=decoded["args"]
    if decoded["name"]=="CurveBuy":
        q=int(a["quoteIn"]); t=int(a["tokensOut"])
    else:
        q=int(a["quoteOut"]); t=int(a["tokensIn"])
    return (q/t) if t else 0.0

def gross_future_mfe(event,all_by_curve,seconds=900):
    try:
        d=decode_event(curve_abi(),event); p0=simple_price(d); t0=event_time(event)
    except Exception:return None
    if p0<=0:return None
    best=1.0;best_at=t0
    for e in all_by_curve[event["address"].lower()]:
        if int(e["blockNumber"],16)<int(event["blockNumber"],16):continue
        t=event_time(e)
        if t<t0+2 or t>t0+seconds:continue
        try:p=simple_price(decode_event(curve_abi(),e))
        except Exception:continue
        if p>0 and p/p0>best:best=p/p0;best_at=t
    return {"gross_mfe_bps":int((best-1)*10000),"gross_mfe_at":best_at}

def collect_system_transactions():
    qualified=set(); settled=set()
    def walk(v):
        if isinstance(v,list):
            for x in v:walk(x)
        elif isinstance(v,dict):
            st=v.get("source_transaction")
            if st and isinstance(st,str):
                if v.get("vector") or v.get("qualification_vector") or "lifecycle" in str(v.get("kind","")):
                    qualified.add(st.lower())
                if v.get("status")=="settled" or v.get("realized_pnl_quote") is not None:
                    settled.add(st.lower())
            for x in v.values():walk(x)
    for path in REVIEW_FILES:
        p=Path(path)
        if not p.exists():continue
        try:walk(json.loads(p.read_text()))
        except Exception:pass
    return qualified,settled

def replay_lifecycle(evaluation,force_entry=False):
    ev=copy.deepcopy(evaluation)
    if force_entry:
        ev["vector"]["current_threshold_pass"]=True
    FAKE.set(int(ev["vector"]["evidence_available_at"]))
    db=Path(tempfile.mkdtemp())/"paper.sqlite"
    try:
        out=paper.run_lifecycle(RPC_URL,ev,db_path=db)
        return {
          "status":out.get("status"),
          "realized_pnl_quote":out.get("realized_pnl_quote"),
          "exit_reason":(out.get("exit") or {}).get("reason"),
          "carried_through_graduation":bool(out.get("carried_through_graduation")),
          "boundary":out.get("boundary"),
        }
    except Exception as e:
        return {"status":"replay_boundary","boundary":f"{type(e).__name__}:{str(e)}"}

def main():
    chain=int(RPC.call("eth_chainId",[]),16)
    if chain!=4663:raise RuntimeError("wrong_chain")
    latest=int(RPC.call("eth_blockNumber",[]),16)
    ranges=[]
    for _,a,b in WINDOWS:
        ranges.append((RPC.block_at_or_before(a-70,latest),RPC.block_at_or_before(b+930,latest)))
    ranges=merge_ranges(ranges)
    raw=[]
    for a,b in ranges:
        raw.extend(RPC.logs(a,b,[BUY_TOPIC,SELL_TOPIC]))
    dedup={}
    for e in raw:dedup[(e["transactionHash"].lower(),e["logIndex"].lower())]=e
    raw=list(dedup.values());raw.sort(key=lambda e:(int(e["blockNumber"],16),int(e["transactionIndex"],16),int(e["logIndex"],16)))
    by_curve=defaultdict(list)
    for e in raw:by_curve[e["address"].lower()].append(e)
    buys=[]
    last_curve_at={}
    for e in raw:
        if not e.get("topics") or e["topics"][0].lower()!=BUY_TOPIC.lower():continue
        t=event_time(e); lab=label_for(t)
        if lab is None:continue
        curve=e["address"].lower()
        if t-last_curve_at.get(curve,-10**9)<2:continue
        last_curve_at[curve]=t
        buys.append((e,t,lab))
    system_qualified,system_settled=collect_system_transactions()
    rows=[];counts=defaultdict(int)
    ctx=acq.SelectiveEvidenceContext(RPC_URL)
    for idx,(e,t,lab) in enumerate(buys):
        pre,reasons=cheap_preflight(e)
        row={"window":lab,"event_at":t,"curve":e["address"].lower(),"source_transaction":e["transactionHash"].lower(),"log_index":int(e["logIndex"],16),"preflight":pre,"preflight_rejections":reasons}
        mfe=gross_future_mfe(e,by_curve);row.update(mfe or {})
        if reasons:
            counts["preflight_rejected"]+=1; rows.append(row); continue
        counts["preflight_admitted"]+=1
        FAKE.set(t+1)
        try:
            evaluation=acq.evaluate_candidate(
                RPC_URL,e,raw,strategy_capital_quote=CAPITAL,
                wallet_histories=None,creator_history=None,
                evidence_observed_at=None,evidence_observed_monotonic=None,
                evidence_context=ctx,
            )
            v=evaluation["vector"]
            row["complete"]=bool(v.get("complete",True))
            row["strategy_pass"]=bool(v.get("current_threshold_pass"))
            row["strategy_rejections"]=list(v.get("all_rejections") or [])
            row["progress_bps"]=int(v.get("progress_bps",pre["progress_bps"]))
            row["proposed_size_quote"]=int((v.get("proposed_size") or {}).get("amount_quote",0) or 0)
            row["system_qualified"]=row["source_transaction"] in system_qualified
            row["system_settled"]=row["source_transaction"] in system_settled
            counts["full_evaluated"]+=1
            if row["strategy_pass"]:counts["strategy_qualified"]+=1
            # Exact frozen lifecycle replay for all qualified candidates and any
            # rejected candidate with >=10% gross future MFE (lower-bound search for missed winners).
            if row["strategy_pass"] or int(row.get("gross_mfe_bps") or 0)>=1000:
                replay=replay_lifecycle(evaluation,force_entry=not row["strategy_pass"])
                row["counterfactual_lifecycle"]=replay
                pnl=replay.get("realized_pnl_quote")
                if isinstance(pnl,int) and pnl>0:
                    if row["strategy_pass"]:
                        if row["system_settled"]:cat="captured_winner"
                        elif row["system_qualified"]:cat="execution_missed_winner"
                        else:cat="discovery_or_evidence_missed_winner"
                    else:cat="strategy_rejected_winner"
                    row["winner_category"]=cat;counts[cat]+=1
                elif isinstance(pnl,int):
                    counts["counterfactual_nonwinner"]+=1
        except Exception as ex:
            row["evaluation_boundary"]=f"{type(ex).__name__}:{str(ex)}"
            counts["evaluation_boundary"]+=1
        rows.append(row)
        if idx%100==0:
            print(json.dumps({"progress":idx,"buys":len(buys),"counts":dict(counts),"rpc_calls":RPC.calls}),flush=True)
    winners=[r for r in rows if r.get("winner_category")]
    out={
      "kind":"pons-market-wide-missed-winner-audit-v1",
      "policy_hash":POLICY_HASH,
      "rpc":RPC_URL,
      "chain_id":chain,
      "windows":[{"name":n,"start":a,"end":b} for n,a,b in WINDOWS],
      "methodology":{
        "selection":"every distinct CurveBuy in lane-active windows; at most one per curve per 2 seconds",
        "preflight":"same frozen progress/snipe/graduation/creator-tax screen",
        "qualification":"frozen pons-selective-continuation-v1 qualification using historical block state; evidence latency normalized to contemporaneous availability",
        "winner":"positive realized PnL from exact frozen paper lifecycle replay; rejected candidates are force-admitted only for counterfactual entry while retaining sizing and exit rules",
        "rejected_replay_prefilter":"strategy-rejected candidates are exact-replayed only when their raw future unit-price MFE is >=10%, so strategy_rejected_winner is a lower bound",
      },
      "market":{"raw_curve_events":len(raw),"distinct_buy_nominations":len(buys)},
      "counts":dict(counts),
      "system_identity":{"qualified_source_transactions":len(system_qualified),"settled_source_transactions":len(system_settled)},
      "winners":winners,
      "rows":rows,
      "rpc_calls":RPC.calls,"rpc_failures":dict(RPC.failures),
    }
    Path("/tmp/pons-missed-winner-audit.json").write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps({"final":True,"market":out["market"],"counts":out["counts"],"winners":len(winners),"rpc_calls":RPC.calls},sort_keys=True),flush=True)

if __name__=="__main__":main()
