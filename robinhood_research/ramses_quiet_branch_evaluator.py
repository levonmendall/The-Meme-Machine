"""Evaluate the preregistered short symmetric quiet-mint diagnostic.

This script is frozen before the diagnostic artifact is read. It does not inspect
or tune individual candidates; it aggregates every width/hold combination uniformly.
"""
from __future__ import annotations
from collections import defaultdict
import json, math
from pathlib import Path

SRC=Path("ramses-quiet-mint-counterfactual.json")
PROTOCOL=Path("RAMSES_DLMM_QUIET_ENTRY_ESCALATION_V1.json")
OUT=Path("ramses-quiet-branch-decision.json")

def qtile(values,q):
    xs=sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not xs:return None
    if len(xs)==1:return xs[0]
    p=(len(xs)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(p-lo)

def main():
    protocol=json.loads(PROTOCOL.read_text())
    if protocol.get("status")!="preregistered_before_initial_quiet_counterfactual_result":
        raise RuntimeError("quiet_branch_protocol_state")
    data=json.loads(SRC.read_text())
    candidates=data.get("candidates") or []
    if not candidates:raise RuntimeError("quiet_branch_no_candidates")

    combos=defaultdict(list)
    candidate_count=len(candidates)
    for c in candidates:
        cid=(c.get("candidate") or {}).get("selection_hash") or (c.get("candidate") or {}).get("transaction_hash")
        for h in c.get("holds") or []:
            hold=int(h.get("requested_hold_seconds") or 0)
            for v in h.get("variants") or []:
                width=int(v.get("half_width_bins") or 0)
                combos[(width,hold)].append(dict(
                    candidate_id=cid,
                    gross_return_bps=v.get("gross_return_bps"),
                    unresolved_inventory=v.get("unresolved_inventory"),
                    boundary=v.get("boundary") or h.get("replay_boundary"),
                    executable_slippage=v.get("executable_slippage"),
                ))

    table=[]
    for (width,hold),rows in sorted(combos.items()):
        resolved=[r for r in rows if r.get("gross_return_bps") is not None]
        returns=[float(r["gross_return_bps"]) for r in resolved]
        unresolved=sum(bool(r.get("unresolved_inventory")) for r in rows)
        boundaries=sum(bool(r.get("boundary")) for r in rows)
        resolved_fraction=len(resolved)/candidate_count if candidate_count else 0
        positive_rate=(sum(x>0 for x in returns)/len(returns)) if returns else 0
        # "No systematic executable-unwind failure" is operationalized before
        # seeing the result as: >=75% of deterministic candidates resolve, and
        # fewer than 25% of all candidates have unresolved inventory/boundaries.
        execution_ok=(
            resolved_fraction>=0.75
            and (unresolved+boundaries)/candidate_count<0.25
        )
        row=dict(
            half_width_bins=width,total_bins=2*width+1,hold_seconds=hold,
            candidates_expected=candidate_count,observations=len(rows),
            resolved=len(resolved),resolved_fraction=resolved_fraction,
            unresolved_inventory=unresolved,boundaries=boundaries,
            median_gross_return_bps=qtile(returns,.5),
            mean_gross_return_bps=(sum(returns)/len(returns) if returns else None),
            p10_gross_return_bps=qtile(returns,.1),
            positive_rate=positive_rate,execution_ok=execution_ok,
        )
        row["branch_A_pass"]=bool(
            row["median_gross_return_bps"] is not None
            and row["median_gross_return_bps"]>0
            and positive_rate>=0.50
            and execution_ok
        )
        table.append(row)

    passing=[r for r in table if r["branch_A_pass"]]
    # Deterministic choice if more than one passes: highest median return, then
    # positive rate, p10, resolved fraction, narrower range, shorter hold.
    passing.sort(key=lambda r:(
        r["median_gross_return_bps"],r["positive_rate"],
        -10**18 if r["p10_gross_return_bps"] is None else r["p10_gross_return_bps"],
        r["resolved_fraction"],-r["half_width_bins"],-r["hold_seconds"],
    ),reverse=True)
    decision="branch_A_expand_unchanged" if passing else "branch_B_public_mint_geometry"
    out=dict(
        kind="ramses_quiet_branch_decision_v1",research_only=True,
        holdout_outcomes_read=False,decision=decision,
        selected_combo=(passing[0] if passing else None),
        table=table,
        evaluator_rule=dict(
            median_gross_return_bps_gt=0,
            positive_rate_gte=0.50,
            resolved_fraction_gte=0.75,
            unresolved_plus_boundary_fraction_lt=0.25,
            deterministic_tiebreak=["median_return","positive_rate","p10","resolved_fraction","narrower","shorter"],
        ),
    )
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True))
    print(json.dumps(dict(decision=decision,selected=out["selected_combo"],table=table),sort_keys=True))

if __name__=="__main__":main()
