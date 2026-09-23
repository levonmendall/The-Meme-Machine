"""Prospective profitability, portfolio, and autonomy acceptance.

All strategy-development/history runs are excluded by construction.  The statistical
unit is a completed campaign block, not an individual trade.  Zero-trade completed
blocks remain zero-return observations.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics

LANES=("pump","meteora","pons","ramses")
ROOT=Path(__file__).resolve().parents[1]
PROTOCOL_PATH=Path(__file__).with_name("profitability_protocol.json")

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"))

def protocol(path=PROTOCOL_PATH):
    p=Path(path);raw=json.loads(p.read_text())
    return raw,hashlib.sha256(canonical(raw).encode()).hexdigest()

def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def _mean_lower95(values):
    vals=[float(v) for v in values if _finite(v)]
    if len(vals)<2:return None
    mean=statistics.fmean(vals)
    sd=statistics.stdev(vals)
    return mean-1.96*sd/math.sqrt(len(vals))

def _profit_factor(values):
    pos=sum(v for v in values if _finite(v) and v>0)
    neg=-sum(v for v in values if _finite(v) and v<0)
    if neg==0:return math.inf if pos>0 else None
    return pos/neg

def _max_drawdown(returns):
    equity=1.0;peak=1.0;worst=0.0
    for r in returns:
        if not _finite(r):continue
        equity*=1.0+float(r)
        peak=max(peak,equity)
        if peak>0:worst=max(worst,(peak-equity)/peak)
    return worst

def _pearson(xs,ys):
    if len(xs)!=len(ys) or len(xs)<2:return None
    mx=statistics.fmean(xs);my=statistics.fmean(ys)
    dx=[x-mx for x in xs];dy=[y-my for y in ys]
    sx=sum(x*x for x in dx);sy=sum(y*y for y in dy)
    if sx<=0 or sy<=0:return None
    return sum(x*y for x,y in zip(dx,dy))/math.sqrt(sx*sy)

def _infra_fraction(row):
    funnel=row.get("funnel") or {}
    denom=funnel.get("unique_admitted")
    if not isinstance(denom,int) or denom<=0:
        denom=funnel.get("unique_evidence_requested")
    if not isinstance(denom,int) or denom<=0:return 0.0
    keys=("unique_capacity_censored","unique_consumer_deadline",
          "unique_local_budget_exhausted","unique_provider_failed")
    censored=min(denom,sum(max(0,int(funnel.get(k) or 0)) for k in keys))
    return censored/denom

def _flat(row):
    if row.get("open_positions") not in (0,None):return False
    if row.get("open_positions_unknown") is True:return False
    return True

def _ramses_capital_seconds(run_dir,ended_at):
    root=Path(run_dir) if run_dir else None
    if not root or not root.exists():return {}
    totals={}
    for path in root.rglob("*.sqlite*"):
        try:
            db=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=1)
        except Exception:
            continue
        try:
            tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "ramses_strategy_journal" not in tables or "ramses_strategy_meta" not in tables:
                continue
            meta=db.execute("SELECT body FROM ramses_strategy_meta WHERE id='genesis'").fetchone()
            if not meta:continue
            genesis=json.loads(meta[0]);asset=str(genesis.get("quote_asset") or "")
            per={}
            for seq,identity,action,encoded in db.execute(
                    "SELECT seq,id,action,body FROM ramses_strategy_journal ORDER BY seq"):
                body=json.loads(encoded);at=body.get("at")
                if not _finite(at):continue
                prev=per.get(identity)
                if prev and at>=prev["at"] and prev["status"] in ("reserved","open","unresolved"):
                    totals[asset]=totals.get(asset,0.0)+max(0,float(prev["reserved"]))*max(0,float(at)-prev["at"])
                per[identity]={
                    "at":float(at),"reserved":float(body.get("reserved") or 0),
                    "status":body.get("status"),
                }
            if _finite(ended_at):
                for prev in per.values():
                    if prev["status"] in ("reserved","open","unresolved") and ended_at>=prev["at"]:
                        totals[asset]=totals.get(asset,0.0)+prev["reserved"]*(float(ended_at)-prev["at"])
        except Exception:
            pass
        finally:
            db.close()
    return totals

def _lane_economics(lane,row,hours,run_dir=None,ended_at=None):
    realized=None;start=None;block_return=None;capital_seconds=None
    denominator_complete=True;flat=_flat(row)
    sleeves={}
    if lane=="pump":
        a=row.get("native_accounting") or {}
        start=a.get("initial");realized=a.get("realized")
        flat=flat and all((a.get(k) or 0)==0 for k in ("basis","pending","reserved"))
        capital_seconds=a.get("capital_unit_seconds")
    elif lane=="pons":
        a=row.get("cohort_accounting") or {}
        start=a.get("genesis");realized=a.get("booked_realized",a.get("realized"))
        flat=flat and all((a.get(k) or 0)==0 for k in ("remaining_cost_basis","reserved","unsettled"))
        ns=a.get("capital_at_risk_unit_nanoseconds")
        capital_seconds=(ns/1e9 if _finite(ns) else None)
        denominator_complete=a.get("capital_integral_complete") is True
    elif lane=="meteora":
        a=row.get("native_accounting") or {}
        g=a.get("genesis") or {};start=g.get("capital");realized=a.get("realized_pnl_lamports")
        flat=flat and all((a.get(k) or 0)==0 for k in ("pending","reserved","unsettled","open_positions"))
        ns=a.get("capital_unit_nanoseconds")
        capital_seconds=(ns/1e9 if _finite(ns) else None)
        denominator_complete=(a.get("economic_replay_verified") is True or int(row.get("natural_settled") or 0)==0)
    else:
        a=row.get("native_accounting") or {};by=a.get("by_quote_asset") or {}
        cap_seconds=_ramses_capital_seconds(run_dir,ended_at)
        returns=[];deploy_rates=[];all_flat=True
        for asset,s in sorted(by.items()):
            cap=s.get("paper_capital");pnl=s.get("realized")
            sleeve_flat=(s.get("committed") or 0)==0 and (s.get("open_positions") or 0)==0
            all_flat=all_flat and sleeve_flat
            ret=(float(pnl)/float(cap) if _finite(cap) and cap>0 and _finite(pnl) else None)
            csec=cap_seconds.get(str(asset).lower())
            deploy=(float(pnl)*3600.0/csec if _finite(csec) and csec>0 and _finite(pnl) else None)
            sleeves[asset]={"starting_capital":cap,"realized":pnl,"block_return":ret,
                            "capital_seconds":csec,"deployed_return_per_capital_hour":deploy,
                            "flat":sleeve_flat}
            if ret is not None:returns.append(ret)
            if deploy is not None:deploy_rates.append(deploy)
        flat=flat and all_flat
        block_return=min(returns) if returns else 0.0 if int(row.get("natural_settled") or 0)==0 else None
        deployed=min(deploy_rates) if deploy_rates else None
        denominator_complete=(int(row.get("natural_settled") or 0)==0 or deployed is not None)
        return {
            "flat":flat,"starting_capital":None,"realized":None,"block_return":block_return,
            "return_per_observed_hour":block_return/hours if block_return is not None and hours>0 else None,
            "capital_seconds":sum(cap_seconds.values()) if cap_seconds else None,
            "deployed_return_per_capital_hour":deployed,
            "capital_time_complete":denominator_complete,
            "sleeves":sleeves,
        }
    if _finite(start) and start>0 and _finite(realized):
        block_return=float(realized)/float(start)
    deployed=(float(realized)*3600.0/float(capital_seconds)
              if _finite(realized) and _finite(capital_seconds) and capital_seconds>0 else None)
    if int(row.get("natural_settled") or 0)>0 and deployed is None:
        denominator_complete=False
    return {
        "flat":flat,"starting_capital":start,"realized":realized,"block_return":block_return,
        "return_per_observed_hour":block_return/hours if block_return is not None and hours>0 else None,
        "capital_seconds":capital_seconds,"deployed_return_per_capital_hour":deployed,
        "capital_time_complete":denominator_complete,"sleeves":sleeves,
    }

def make_record(result,proto,proto_hash,run_dir=None):
    phase=result.get("phase");required=3600 if phase=="hourly" else 14400 if phase=="sustained" else None
    hours=float(result.get("continuous_overlap_seconds") or 0)/3600.0
    engineering=(result.get("hourly_engineering") or {}).get("status")=="PASS" if phase=="hourly" else (
        result.get("status")=="FINISHED" and required is not None and
        float(result.get("continuous_overlap_seconds") or 0)>=required)
    record={
        "schema":"meme-machine-prospective-block-v1",
        "cohort_id":proto["cohort_id"],"protocol_sha256":proto_hash,
        "run_id":result.get("run_id"),"phase":phase,"status":result.get("status"),
        "started_at":result.get("started_at"),"ended_at":result.get("ended_at"),
        "observation_hours":hours,"engineering_pass":bool(engineering),
        "integration_sha":result.get("integration_sha"),
        "source_manifest_hash":result.get("source_manifest_hash"),
        "implementation_hash":result.get("implementation_hash"),
        "lanes":{},
    }
    for lane in LANES:
        row=(result.get("lanes") or {}).get(lane) or {}
        frozen=proto["frozen_lanes"][lane]
        identity=(
            row.get("strategy_version")==frozen["strategy_version"]
            and row.get("policy_hash")==frozen["policy_hash"]
            and (result.get("source_diff_hashes") or {}).get(lane)==frozen["source_diff_sha256"]
        )
        gates=row.get("gates") or {}
        economics=_lane_economics(lane,row,hours,run_dir,record["ended_at"])
        record["lanes"][lane]={
            "identity_match":identity,
            "strategy_version":row.get("strategy_version"),"policy_hash":row.get("policy_hash"),
            "natural_settled":int(row.get("natural_settled") or 0),
            "forced_settled":int(row.get("forced_settled") or 0),
            "process_restarts":int(row.get("process_restarts") or 0),
            "unexpected_exit":bool(row.get("unexpected_exit")),
            "accounting_reconciled":row.get("accounting_reconciled") is True,
            "telemetry_complete":gates.get("telemetry_complete") is True,
            "freshness_finality_unchanged":gates.get("freshness_finality_unchanged") is True,
            "durable_replay":gates.get("durable_replay") is True,
            "infrastructure_censoring_fraction":_infra_fraction(row),
            "economics":economics,
        }
    return record

def _lane_summary(records,lane,proto):
    q=proto["evidence_quality"];e=proto["lane_economic_acceptance"]
    eligible=[r for r in records if r.get("engineering_pass") and r["lanes"][lane].get("identity_match")]
    hours=sum(float(r.get("observation_hours") or 0) for r in eligible)
    settlements=sum(r["lanes"][lane].get("natural_settled",0) for r in eligible)
    active=sum(r["lanes"][lane].get("natural_settled",0)>0 for r in eligible)
    returns=[r["lanes"][lane]["economics"].get("block_return") for r in eligible
             if r["lanes"][lane]["economics"].get("flat") and
                _finite(r["lanes"][lane]["economics"].get("block_return"))]
    hourly=[r["lanes"][lane]["economics"].get("return_per_observed_hour") for r in eligible
            if r["lanes"][lane]["economics"].get("flat") and
               _finite(r["lanes"][lane]["economics"].get("return_per_observed_hour"))]
    deploy=[r["lanes"][lane]["economics"].get("deployed_return_per_capital_hour") for r in eligible
            if _finite(r["lanes"][lane]["economics"].get("deployed_return_per_capital_hour"))]
    infra=max([r["lanes"][lane].get("infrastructure_censoring_fraction",0) for r in eligible],default=0)
    started=[r.get("started_at") for r in eligible if _finite(r.get("started_at"))]
    ended=[r.get("ended_at") for r in eligible if _finite(r.get("ended_at"))]
    span=(max(ended)-min(started))/3600 if started and ended else 0
    quality={
        "completed_blocks":len(eligible)>=q["minimum_completed_market_blocks_per_lane"],
        "observation_hours":hours>=q["minimum_observation_hours_per_lane"],
        "calendar_span":span>=q["minimum_calendar_span_hours"],
        "natural_settlements":settlements>=q["minimum_natural_settlements_per_lane"],
        "active_blocks":active>=q["minimum_active_blocks_per_lane"],
        "infrastructure_censoring":infra<=q["maximum_infrastructure_censoring_fraction"],
        "forced_settlements":all(r["lanes"][lane].get("forced_settled")==q["required_forced_settlements"] for r in eligible),
        "accounting":all(r["lanes"][lane].get("accounting_reconciled") for r in eligible),
        "telemetry":all(r["lanes"][lane].get("telemetry_complete") for r in eligible),
        "freshness_finality":all(r["lanes"][lane].get("freshness_finality_unchanged") for r in eligible),
        "flat_final_records":all(r["lanes"][lane]["economics"].get("flat") for r in eligible),
        "capital_time_complete":all(r["lanes"][lane]["economics"].get("capital_time_complete") for r in eligible),
    }
    lower=_mean_lower95(hourly);pf=_profit_factor(returns);dd=_max_drawdown(returns)
    economics={
        "aggregate_realized_return_positive":sum(returns)>0 if returns else False,
        "lower95_hourly_return_positive":lower is not None and lower>0,
        "profit_factor":pf is not None and pf>=e["minimum_profit_factor"],
        "drawdown":dd<=e["maximum_compounded_peak_to_trough_drawdown"],
        "worst_block":bool(returns) and min(returns)>=e["minimum_single_campaign_return"],
        "deployed_capital_hour_positive":bool(deploy) and statistics.fmean(deploy)>0,
    }
    status="PASS" if all(quality.values()) and all(economics.values()) else "INCOMPLETE"
    if eligible and any(r["lanes"][lane].get("unexpected_exit") or r["lanes"][lane].get("process_restarts") for r in eligible):
        status="FAIL"
    return {
        "status":status,"completed_blocks":len(eligible),"observation_hours":hours,
        "calendar_span_hours":span,"natural_settlements":settlements,"active_blocks":active,
        "maximum_infrastructure_censoring_fraction":infra,"block_returns":returns,
        "mean_return_per_hour":statistics.fmean(hourly) if hourly else None,
        "lower95_return_per_hour":lower,"profit_factor_value":pf,
        "max_drawdown":dd,"mean_deployed_return_per_capital_hour":statistics.fmean(deploy) if deploy else None,
        "quality_checks":quality,"economic_checks":economics,
    }

def evaluate(records,proto,proto_hash,expected_integration_sha=None):
    records=sorted(records,key=lambda r:(r.get("started_at") or 0,str(r.get("run_id"))))
    identity_sets={
        "protocol_sha256":{r.get("protocol_sha256") for r in records},
        "integration_sha":{r.get("integration_sha") for r in records},
        "source_manifest_hash":{r.get("source_manifest_hash") for r in records},
        "implementation_hash":{r.get("implementation_hash") for r in records},
    }
    identity_ok=(
        identity_sets["protocol_sha256"]=={proto_hash}
        and len(identity_sets["integration_sha"])==1
        and len(identity_sets["source_manifest_hash"])==1
        and len(identity_sets["implementation_hash"])==1
        and (expected_integration_sha is None or identity_sets["integration_sha"]=={expected_integration_sha})
    )
    lane_results={lane:_lane_summary(records,lane,proto) for lane in LANES}
    lane_pass=all(x["status"]=="PASS" for x in lane_results.values())

    complete=[]
    weights=proto["portfolio_acceptance"]["lane_weights"]
    for r in records:
        vals={}
        ok=r.get("engineering_pass")
        for lane in LANES:
            econ=r["lanes"][lane]["economics"]
            value=econ.get("block_return")
            if not econ.get("flat") or not _finite(value):ok=False;break
            vals[lane]=float(value)
        if ok:complete.append((r,vals,sum(weights[l]*vals[l] for l in LANES)))
    portfolio_returns=[x[2] for x in complete]
    p=proto["portfolio_acceptance"]
    portfolio_hourly=[ret/float(r.get("observation_hours") or 1) for r,_,ret in complete]
    starts=[r.get("started_at") for r,_,_ in complete if _finite(r.get("started_at"))]
    ends=[r.get("ended_at") for r,_,_ in complete if _finite(r.get("ended_at"))]
    span=(max(ends)-min(starts))/3600 if starts and ends else 0
    correlations={};corr_complete=True
    lanes=list(LANES);cr=p["pairwise_correlation"]
    for i,a in enumerate(lanes):
        for b in lanes[i+1:]:
            pairs=[(vals[a],vals[b]) for _,vals,_ in complete if vals[a]!=0 or vals[b]!=0]
            key=a+"__"+b
            if len(pairs)<cr["minimum_joint_nonzero_blocks"]:
                correlations[key]={"status":"INCOMPLETE","joint_nonzero_blocks":len(pairs),"correlation":None}
                corr_complete=False;continue
            corr=_pearson([x[0] for x in pairs],[x[1] for x in pairs])
            passed=corr is not None and abs(corr)<=cr["maximum_absolute_correlation"]
            correlations[key]={"status":"PASS" if passed else "FAIL",
                               "joint_nonzero_blocks":len(pairs),"correlation":corr}
            if not passed:corr_complete=False
    plower=_mean_lower95(portfolio_hourly);ppf=_profit_factor(portfolio_returns);pdd=_max_drawdown(portfolio_returns)
    portfolio_checks={
        "all_lanes_economic_pass":lane_pass,
        "complete_blocks":len(complete)>=p["minimum_complete_portfolio_blocks"],
        "calendar_span":span>=p["minimum_calendar_span_hours"],
        "lower95_hourly_return_positive":plower is not None and plower>0,
        "profit_factor":ppf is not None and ppf>=p["minimum_profit_factor"],
        "drawdown":pdd<=p["maximum_compounded_peak_to_trough_drawdown"],
        "worst_block":bool(portfolio_returns) and min(portfolio_returns)>=p["minimum_single_campaign_return"],
        "correlation_sample_and_limit":corr_complete,
    }
    portfolio_status="PASS" if all(portfolio_checks.values()) else "INCOMPLETE"
    if any(v.get("status")=="FAIL" for v in correlations.values()):portfolio_status="FAIL"

    a=proto["autonomy_acceptance"]
    autonomy_checks={
        "identity_frozen":identity_ok,
        "chain_binding_required":a["current_chain_binding_preflight_required"],
        "provider_fail_closed":a["provider_fail_closed_required"],
        "automatic_continuation_required":a["automatic_meteora_ramses_position_continuation_required"],
        "no_manual_strategy_intervention":a["manual_strategy_or_policy_intervention_during_cohort_allowed"] is False,
        "portfolio_economic_pass":portfolio_status=="PASS",
    }
    autonomy_status="PASS" if all(autonomy_checks.values()) else "INCOMPLETE"
    return {
        "schema":"meme-machine-profitability-portfolio-autonomy-result-v1",
        "cohort_id":proto["cohort_id"],"protocol_sha256":proto_hash,
        "identity_sets":{k:sorted(str(x) for x in v) for k,v in identity_sets.items()},
        "identity_frozen":identity_ok,"lanes":lane_results,
        "portfolio":{
            "status":portfolio_status,"complete_blocks":len(complete),
            "calendar_span_hours":span,"mean_return_per_hour":statistics.fmean(portfolio_hourly) if portfolio_hourly else None,
            "lower95_return_per_hour":plower,"profit_factor_value":ppf,
            "max_drawdown":pdd,"correlations":correlations,"checks":portfolio_checks,
        },
        "autonomy":{"status":autonomy_status,"checks":autonomy_checks,
                    "automatic_campaign_scheduler_activation_allowed":autonomy_status=="PASS"},
        "promotion_eligible":autonomy_status=="PASS",
        "paper_only":True,"live_money":False,
    }

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="command",required=True)
    r=sub.add_parser("record");r.add_argument("--result",required=True);r.add_argument("--run-dir");r.add_argument("--output",required=True)
    e=sub.add_parser("evaluate");e.add_argument("--record",action="append",default=[]);e.add_argument("--records-dir");e.add_argument("--expected-integration-sha");e.add_argument("--output",required=True)
    a=p.parse_args();proto,ph=protocol()
    if a.command=="record":
        result=json.loads(Path(a.result).read_text())
        row=make_record(result,proto,ph,a.run_dir)
        Path(a.output).parent.mkdir(parents=True,exist_ok=True)
        Path(a.output).write_text(json.dumps(row,sort_keys=True,indent=2)+"\n")
        print(json.dumps({"run_id":row["run_id"],"engineering_pass":row["engineering_pass"],
                          "protocol_sha256":ph},sort_keys=True));return
    paths=[Path(x) for x in a.record]
    if a.records_dir:
        paths.extend(sorted(Path(a.records_dir).rglob("prospective-observation.json")))
    records=[json.loads(x.read_text()) for x in paths]
    result=evaluate(records,proto,ph,a.expected_integration_sha)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"promotion_eligible":result["promotion_eligible"],
                      "lanes":{k:v["status"] for k,v in result["lanes"].items()},
                      "portfolio":result["portfolio"]["status"],
                      "autonomy":result["autonomy"]["status"]},sort_keys=True))

if __name__=="__main__":
    main()
