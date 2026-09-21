"""Join clean historical Ramses LP lifecycles to strictly pre-entry swap regimes.

Derivation and validation outcomes are emitted. Holdout outcomes are redacted until a
candidate rule is frozen, preserving the preregistered blind holdout.
"""
from __future__ import annotations
from collections import defaultdict
import gzip, json, math, os
from pathlib import Path

INDEX=Path("ramses-historical-index-data.json.gz")
LP=Path("ramses-historical-lp-outcomes.json")
OUT=Path("ramses-historical-lp-signal-join.json")
WINDOWS=(300,900,1800)

def f(v):
    try:return float(v or 0)
    except:return 0.0
def i(v):
    try:return int(v)
    except:return 0
def pool(v):return str(v or "").split(":")[-1].lower()

def features(rows,start,end):
    xs=[r for r in rows if start<=i(r.get("timestamp"))<end]
    if not xs:return dict(swap_count=0,volume_usd=0.0,two_way_share=0.0,flow_imbalance=1.0,
                          gross_bin_travel=0,net_bin_displacement=0,chop_ratio=0.0,
                          first_active_id=None,last_active_id=None)
    xs.sort(key=lambda r:(i(r.get("timestamp")),str(r.get("transaction")),str(r.get("id"))))
    volume=sum(f(r.get("amountUSD")) for r in xs)
    side=[0.0,0.0];ids=[]
    for r in xs:
        x=f(r.get("amountXIn"));y=f(r.get("amountYIn"));v=f(r.get("amountUSD"))
        if x>0 and y==0:side[0]+=v
        elif y>0 and x==0:side[1]+=v
        ids.append(i(r.get("activeId")))
    gross=sum(abs(b-a) for a,b in zip(ids,ids[1:]))
    net=abs(ids[-1]-ids[0]) if len(ids)>1 else 0
    return dict(
        swap_count=len(xs),volume_usd=volume,
        two_way_share=(min(side)/volume if volume>0 else 0.0),
        flow_imbalance=(abs(side[0]-side[1])/volume if volume>0 else 1.0),
        gross_bin_travel=gross,net_bin_displacement=net,chop_ratio=gross/(1+net),
        first_active_id=ids[0],last_active_id=ids[-1],
    )

def main():
    with gzip.open(INDEX,"rt",encoding="utf-8") as fh:index=json.load(fh)
    lp=json.loads(LP.read_text())
    by=defaultdict(list)
    for r in index.get("swaps") or []:by[pool(r.get("pool"))].append(r)
    for rows in by.values():rows.sort(key=lambda r:i(r.get("timestamp")))
    emitted=[]
    holdout_signals=[]
    for row in lp.get("lifecycles") or []:
        p=pool(row.get("pool"));entry=i(row.get("entry_timestamp"))
        q={k:row.get(k) for k in (
            "owner","pool","symbol","entry_timestamp","exit_timestamp","hold_seconds",
            "deposit_usd","withdrawal_usd","gross_pnl_usd","gross_return","width_bins",
            "lower_bin","upper_bin","sidedness","bin_step_bps","prev_hour_tvl_usd",
            "prev_hour_volume_usd","prev_hour_fees_usd","prev_hour_volume_to_tvl",
            "prev_hour_fee_to_tvl","prev_hour_fee_bps","pool_age_seconds","split"
        )}
        for w in WINDOWS:q[f"pre_{w}s"]=features(by.get(p,[]),entry-w,entry)
        if row.get("split")=="holdout":
            for k in ("exit_timestamp","withdrawal_usd","gross_pnl_usd","gross_return","hold_seconds"):
                q.pop(k,None)
            holdout_signals.append(q)
        else:emitted.append(q)
    out=dict(
      kind="ramses_dlmm_actual_lp_signal_join_v1",research_only=True,
      existing_strategy_policy_used=False,holdout_outcomes_blind=True,
      derivation_validation_rows=emitted,holdout_signal_rows=holdout_signals,
      note="All signal windows end strictly before the LP entry timestamp."
    )
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps({"rows":len(emitted),"holdout_signals":len(holdout_signals),
                      "derivation":sum(r.get("split")=="derivation" for r in emitted),
                      "validation":sum(r.get("split")=="validation" for r in emitted)},sort_keys=True))
if __name__=="__main__":main()
