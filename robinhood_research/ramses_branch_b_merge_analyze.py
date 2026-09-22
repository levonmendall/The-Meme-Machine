"""Merge Branch B shards, run cost/breadth gates, and select/finalize the frozen rule."""
from __future__ import annotations
from collections import defaultdict
import json, math, os, statistics
from pathlib import Path

ROOT=Path(os.environ.get("RAMSES_BRANCH_B_ROOT","/tmp/ramses-branch-b"))
OUT=Path("ramses-branch-b-analysis.json")
COST=Path("ramses-branch-b-cost-anchor.json")
FROZEN=Path("RAMSES_BRANCH_B_FROZEN_RULE_V1.json")
EXPECTED=24

def qtile(values,q):
    xs=sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not xs:return None
    if len(xs)==1:return xs[0]
    p=(len(xs)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)

def summarize(rows):
    if not rows:
        return dict(resolved=0,pools=0)
    vals=[float(r["after_cost_return_bps"]) for r in rows]
    stress=[float(r["two_x_cost_stress_return_bps"]) for r in rows]
    by_pool=defaultdict(list)
    positive_by_pool=defaultdict(int)
    for r in rows:
        p=r["pool"];by_pool[p].append(r)
        pnl=int(r.get("after_cost_result") or 0)
        if pnl>0:positive_by_pool[p]+=pnl
    pool_medians=[qtile([x["after_cost_return_bps"] for x in rs],.5) for rs in by_pool.values()]
    pool_means=[statistics.fmean([x["after_cost_return_bps"] for x in rs]) for rs in by_pool.values()]
    positive_total=sum(positive_by_pool.values())
    concentration=(max(positive_by_pool.values())/positive_total if positive_total else 0.0)
    return dict(
        resolved=len(rows),pools=len(by_pool),
        median_after_cost_return_bps=qtile(vals,.5),
        mean_after_cost_return_bps=statistics.fmean(vals),
        p10_after_cost_return_bps=qtile(vals,.1),
        win_rate=sum(v>0 for v in vals)/len(vals),
        equal_pool_weighted_median_after_cost_return_bps=qtile(pool_medians,.5),
        equal_pool_weighted_mean_after_cost_return_bps=statistics.fmean(pool_means),
        two_x_cost_stress_median_bps=qtile(stress,.5),
        two_x_cost_stress_mean_bps=statistics.fmean(stress),
        max_single_pool_positive_pnl_share=concentration,
        per_pool={
            pool:dict(
                n=len(rs),
                median_after_cost_return_bps=qtile([x["after_cost_return_bps"] for x in rs],.5),
                mean_after_cost_return_bps=statistics.fmean([x["after_cost_return_bps"] for x in rs]),
                wins=sum(float(x["after_cost_return_bps"])>0 for x in rs),
                positive_pnl_quote_raw=positive_by_pool.get(pool,0),
            )
            for pool,rs in sorted(by_pool.items())
        },
    )

def development_pass(m):
    return bool(
        m.get("resolved",0)>=20 and m.get("pools",0)>=3
        and (m.get("median_after_cost_return_bps") or 0)>0
        and (m.get("mean_after_cost_return_bps") or 0)>0
        and (m.get("win_rate") or 0)>.55
        and (m.get("max_single_pool_positive_pnl_share") or 0)<=.40
        and (m.get("two_x_cost_stress_median_bps") or 0)>0
        and (m.get("two_x_cost_stress_mean_bps") or 0)>0
    )

def holdout_pass(m):
    return bool(
        m.get("resolved",0)>0 and m.get("pools",0)>=3
        and (m.get("median_after_cost_return_bps") or 0)>0
        and (m.get("mean_after_cost_return_bps") or 0)>0
        and (m.get("win_rate") or 0)>.55
        and (m.get("two_x_cost_stress_median_bps") or 0)>0
        and (m.get("two_x_cost_stress_mean_bps") or 0)>0
    )

def main():
    files=sorted(ROOT.glob("**/ramses-branch-b-candidate.json"))
    if len(files)!=EXPECTED:
        raise RuntimeError(f"branch_b_shard_count:{len(files)}")
    bodies=[json.loads(p.read_text()) for p in files]
    phases={b.get("phase") for b in bodies}
    if len(phases)!=1:
        raise RuntimeError("branch_b_phase_mismatch")
    phase=next(iter(phases))
    if phase not in ("development","holdout"):
        raise RuntimeError("branch_b_phase")
    indices=[b.get("candidate_index") for b in bodies]
    if sorted(indices)!=list(range(EXPECTED)):
        raise RuntimeError("branch_b_candidate_indices")
    completed=[b for b in bodies if b.get("status")=="complete"]
    boundaries=[b for b in bodies if b.get("status")=="boundary"]
    not_selected=[b for b in bodies if b.get("status")=="not_selected"]
    digests={b.get("cost_anchor_sha256") for b in completed}
    if len(digests)>1:
        raise RuntimeError("branch_b_cost_anchor_mismatch")
    cost=json.loads(COST.read_text())
    cost_digest=__import__("hashlib").sha256(
        json.dumps(cost,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    if digests and digests!={cost_digest}:
        raise RuntimeError("branch_b_cost_anchor_digest")

    by_hold=defaultdict(list)
    for b in completed:
        pool=b["candidate"]["pool"]
        for h in b.get("holds") or []:
            if h.get("unresolved_inventory") is not None:
                continue
            if h.get("after_cost_return_bps") is None or h.get("two_x_cost_stress_return_bps") is None:
                continue
            by_hold[int(h["requested_hold_seconds"])].append(dict(
                candidate_index=b["candidate_index"],pool=pool,
                selection_hash=b["candidate"]["selection_hash"],
                after_cost_return_bps=h["after_cost_return_bps"],
                after_cost_result=h["after_cost_result"],
                two_x_cost_stress_return_bps=h["two_x_cost_stress_return_bps"],
                cost_quote_raw=h["cost_quote_raw"],
                capital_quote_raw=b["entry"]["capital_quote_raw"],
                selected_size_bps=b["entry"]["size"]["selected_bps"],
                public_geometry_bins=b["entry"]["public_geometry_bins"],
            ))
    metrics={str(hold):summarize(rows) for hold,rows in sorted(by_hold.items())}
    decision=None
    if phase=="development":
        for hold in (86400,259200):
            if str(hold) in metrics:
                metrics[str(hold)]["passes_preregistered_development_gate"]=development_pass(metrics[str(hold)])
        passing=[hold for hold in (86400,259200) if metrics.get(str(hold),{}).get("passes_preregistered_development_gate")]
        if passing:
            def key(hold):
                m=metrics[str(hold)]
                return (
                    m["equal_pool_weighted_median_after_cost_return_bps"],
                    m["equal_pool_weighted_mean_after_cost_return_bps"],
                    m["p10_after_cost_return_bps"],
                    m["win_rate"],
                    -hold,
                )
            chosen=max(passing,key=key)
            decision=dict(
                status="freeze_ready",hold_seconds=chosen,
                cost_anchor_sha256=cost_digest,
                native_costs=cost["native_costs"],
                native_cycle_cost_raw=cost["native_cycle_cost_raw"],
                selected_metrics=metrics[str(chosen)],
                rule_selection_order=[
                    "equal_pool_weighted_median_after_cost_return_bps",
                    "equal_pool_weighted_mean_after_cost_return_bps",
                    "p10_after_cost_return_bps","win_rate","shorter_hold_on_exact_tie",
                ],
            )
        else:
            decision=dict(status="development_gate_failed")
    else:
        frozen=json.loads(FROZEN.read_text())
        if frozen.get("kind")!="ramses_branch_b_frozen_rule_v1" or frozen.get("frozen") is not True:
            raise RuntimeError("branch_b_frozen_rule")
        if frozen.get("cost_anchor_sha256")!=cost_digest:
            raise RuntimeError("branch_b_holdout_cost_anchor_changed")
        hold=int(frozen["hold_seconds"])
        m=metrics.get(str(hold),dict(resolved=0,pools=0))
        m["passes_preregistered_holdout_gate"]=holdout_pass(m)
        metrics[str(hold)]=m
        decision=dict(
            status=("historically_certified" if m["passes_preregistered_holdout_gate"] else "holdout_gate_failed"),
            hold_seconds=hold,holdout=m,
        )

    body=dict(
        kind="ramses_branch_b_analysis_v1",phase=phase,research_only=True,
        holdout_outcomes_read=(phase=="holdout"),
        expected_shards=EXPECTED,completed_candidates=len(completed),
        boundary_candidates=len(boundaries),not_selected_candidates=len(not_selected),
        distinct_completed_pools=len({b["candidate"]["pool"] for b in completed}),
        cost_anchor_sha256=cost_digest,metrics=metrics,decision=decision,
        boundaries=[
            dict(candidate_index=b["candidate_index"],pool=(b.get("candidate") or {}).get("pool"),boundary=b.get("boundary"))
            for b in boundaries
        ],
    )
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True))
    print(json.dumps({
        "phase":phase,"completed":len(completed),"boundaries":len(boundaries),
        "pools":body["distinct_completed_pools"],"decision":decision,
    },sort_keys=True))

if __name__=="__main__":
    main()
