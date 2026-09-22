"""Build a conservative USDG cost-conversion fallback from prior verified Branch B candidates.

This does not alter the frozen Ramses receipt-gas model. It only supplies a
quote conversion when an old candidate block has no executable WNATIVE/USDG
Ramses route. The fallback is the maximum quote-cycle cost previously obtained
from executable Ramses WNATIVE->USDG getSwapOut evidence under the exact same
frozen native cost anchor.
"""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path

ROOT=Path(os.environ.get("RAMSES_BRANCH_B_PRIOR_ROOT","/tmp/ramses-branch-b-prior"))
COST=Path(os.environ.get("RAMSES_BRANCH_B_COST_ANCHOR","ramses-branch-b-cost-anchor.json"))
OUT=Path("ramses-branch-b-cost-route-fallback.json")


def _digest(body):
    return hashlib.sha256(
        json.dumps(body,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()


def build(root=ROOT,cost_path=COST):
    cost=json.loads(Path(cost_path).read_text())
    if cost.get("kind")!="ramses_branch_b_cost_anchor_v1" or cost.get("frozen") is not True:
        raise RuntimeError("branch_b_cost_fallback_anchor")
    native_total=int(cost.get("native_cycle_cost_raw") or 0)
    if native_total<=0:
        raise RuntimeError("branch_b_cost_fallback_native")
    cost_sha=_digest(cost)

    rows=[]
    for path in sorted(Path(root).glob("**/ramses-branch-b-candidate.json")):
        body=json.loads(path.read_text())
        if body.get("kind")!="ramses_branch_b_candidate_v1" or body.get("phase")!="development":
            continue
        if body.get("status")!="complete":
            continue
        if body.get("cost_anchor_sha256")!=cost_sha:
            raise RuntimeError("branch_b_cost_fallback_anchor_mismatch")
        candidate=body.get("candidate") or {}
        costs=set()
        routes=[]
        for hold in body.get("holds") or []:
            q=hold.get("cost_quote_raw")
            route=hold.get("cost_route")
            if type(q) is not int or q<=0 or not isinstance(route,dict):
                raise RuntimeError("branch_b_cost_fallback_candidate_cost")
            kind=route.get("route_kind")
            if kind not in ("direct_wnative_quote_pool","candidate_wnative_quote_pool","quote_is_wnative"):
                raise RuntimeError("branch_b_cost_fallback_route_kind")
            costs.add(q);routes.append(route)
        if not costs:
            continue
        if len(costs)!=1:
            raise RuntimeError("branch_b_cost_fallback_hold_disagreement")
        rows.append(dict(
            candidate_index=int(body["candidate_index"]),
            pool=str(candidate.get("pool") or "").lower(),
            quote_cycle_cost_raw=next(iter(costs)),
            route_kinds=sorted({r.get("route_kind") for r in routes}),
        ))
    if len(rows)<3:
        raise RuntimeError("branch_b_cost_fallback_sample_shortfall")
    maximum=max(int(r["quote_cycle_cost_raw"]) for r in rows)
    supporting=[r for r in rows if int(r["quote_cycle_cost_raw"])==maximum]
    return dict(
        kind="ramses_branch_b_cost_route_fallback_v1",
        frozen=True,
        research_only=True,
        strategy_parameters_changed=False,
        cost_model_changed=False,
        source="maximum verified executable Ramses WNATIVE-to-USDG quote-cycle cost from prior resolved development candidates",
        native_cycle_cost_raw=native_total,
        cost_anchor_sha256=cost_sha,
        verified_candidate_count=len(rows),
        verified_pool_count=len({r["pool"] for r in rows}),
        max_verified_quote_cycle_cost_raw=maximum,
        min_verified_quote_cycle_cost_raw=min(int(r["quote_cycle_cost_raw"]) for r in rows),
        supporting_maximum=supporting,
        candidates=rows,
    )


def main():
    body=build()
    OUT.write_text(json.dumps(body,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "kind":body["kind"],
        "verified_candidate_count":body["verified_candidate_count"],
        "verified_pool_count":body["verified_pool_count"],
        "max_verified_quote_cycle_cost_raw":body["max_verified_quote_cycle_cost_raw"],
        "cost_anchor_sha256":body["cost_anchor_sha256"],
    },sort_keys=True))


if __name__=="__main__":
    main()
