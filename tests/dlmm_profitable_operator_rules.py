"""Deterministic cross-operator rule derivation for reconstructed DLMM operators.

This module may propose a prospective paper rule only from complete, positive,
independent operator clusters. It never chooses a family because it earned the most
money; every categorical boundary and support threshold is preregistered.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
import statistics

PROTOCOL=Path("DLMM_PROFITABLE_OPERATOR_DISCOVERY_V1.json")
DERIVATION_PROTOCOL=Path("DLMM_PROFITABLE_OPERATOR_RULE_DERIVATION_V1.json")
DEFAULT_DEEP=Path("dlmm-profitable-operator-deep-reconstruction.json")
OUT=Path("dlmm-profitable-operator-rule-proposals.json")
FROZEN_OUT=Path("DLMM_PROFITABLE_OPERATOR_RULES_V1.json")


def _modal(values):
    values=[v for v in values if v is not None]
    if not values: return None
    c=Counter(values)
    return sorted(c.items(),key=lambda kv:(-kv[1],str(kv[0])))[0][0]


def _configured_bucket(value,bounds):
    if value is None:return None
    x=float(value)
    for rule in bounds:
        if "exact" in rule and x!=float(rule["exact"]):continue
        if "min_inclusive" in rule and x<float(rule["min_inclusive"]):continue
        if "min_exclusive" in rule and x<=float(rule["min_exclusive"]):continue
        if "max_inclusive" in rule and x>float(rule["max_inclusive"]):continue
        if "max_exclusive" in rule and x>=float(rule["max_exclusive"]):continue
        return rule["label"]
    return None


def _hold_bucket(v):
    if v is None:return None
    v=float(v)
    return ("<15m" if v<900 else "15-60m" if v<3600 else
            "1-4h" if v<14400 else "4-24h" if v<86400 else ">=24h")


def _width_bucket(v):
    if v is None:return None
    v=int(v)
    return "<=10" if v<=10 else "11-25" if v<=25 else "26-50" if v<=50 else ">50"


def _placement_bucket(v):
    if v is None:return None
    v=float(v)
    return "below_active" if v<-5 else "centered" if v<=5 else "above_active"


def _rebalance_bucket(v):
    if v is None:return None
    v=float(v)
    return "none" if v==0 else "occasional" if v<0.25 else "active"


def _entry_family(entry):
    if not isinstance(entry,dict):return None
    family=entry.get("strategy_family") or entry.get("distribution_shape")
    return family


def wallet_behavior(row):
    profiles=row.get("entry_exit_profiles") or []
    families=[];sides=[];widths=[];placements=[];holds=[];rebalance_positions=0
    observed_positions=0
    width_values=[];placement_values=[];hold_values=[]
    for p in profiles:
        entry=p.get("entry")
        if not isinstance(entry,dict):continue
        observed_positions+=1
        families.append(_entry_family(entry))
        if entry.get("one_sided") is True:sides.append("one_sided")
        elif entry.get("two_sided") is True:sides.append("two_sided")
        width=entry.get("width_bins")
        center=entry.get("center_active_offset_bins")
        hold=p.get("hold_seconds")
        widths.append(_width_bucket(width));placements.append(_placement_bucket(center))
        holds.append(_hold_bucket(hold))
        if width is not None:width_values.append(float(width))
        if center is not None:placement_values.append(float(center))
        if hold is not None:hold_values.append(float(hold))
        if int(p.get("rebalance_count") or 0)>0:rebalance_positions+=1
    rebalance_rate=(None if observed_positions==0 else rebalance_positions/observed_positions)
    vote=dict(
        distribution_family=_modal(families),sidedness=_modal(sides),
        width_bucket=_modal(widths),active_bin_placement_bucket=_modal(placements),
        rebalance_bucket=_rebalance_bucket(rebalance_rate),hold_bucket=_modal(holds),
    )
    complete=all(v is not None for v in vote.values())
    context_values=dict(
        pool_age_seconds=[],
        pre_entry_60m_volume_usd=[],
        pre_entry_5m_log_return_volatility=[],
        entry_dynamic_fee_bps_observed=[],
    )
    for p in profiles:
        ctx=p.get("market_context") or {}
        entry=p.get("entry") or {}
        for key in (
            "pool_age_seconds","pre_entry_60m_volume_usd",
            "pre_entry_5m_log_return_volatility"):
            if ctx.get(key) is not None:context_values[key].append(ctx[key])
        if entry.get("entry_dynamic_fee_bps_observed") is not None:
            context_values["entry_dynamic_fee_bps_observed"].append(
                entry["entry_dynamic_fee_bps_observed"])
    return dict(
        wallet=row.get("wallet"),vote=vote,vote_complete=complete,
        observed_entry_positions=observed_positions,
        rebalance_position_rate=rebalance_rate,
        raw_context_values=context_values,
        cluster_parameter_values=dict(
            median_width_bins=(None if not width_values else statistics.median(width_values)),
            median_center_active_offset_bins=(
                None if not placement_values else statistics.median(placement_values)),
            median_hold_seconds=(None if not hold_values else statistics.median(hold_values)),
            rebalance_position_rate=rebalance_rate,
        ),
    )


def cluster_behavior(cluster,by_wallet):
    member=[wallet_behavior(by_wallet[w]) for w in cluster.get("wallets") or []
            if w in by_wallet]
    dimensions=[
        "distribution_family","sidedness","width_bucket",
        "active_bin_placement_bucket","rebalance_bucket","hold_bucket"
    ]
    vote={d:_modal([m["vote"].get(d) for m in member]) for d in dimensions}
    complete=all(v is not None for v in vote.values())
    params={}
    for key in (
        "median_width_bins","median_center_active_offset_bins",
        "median_hold_seconds","rebalance_position_rate"):
        values=[m["cluster_parameter_values"].get(key) for m in member
                if m["cluster_parameter_values"].get(key) is not None]
        params[key]=None if not values else statistics.median(values)
    context_values=defaultdict(list)
    for m in member:
        for key,values in (m.get("raw_context_values") or {}).items():
            context_values[key].extend(values)
    return dict(
        cluster_id=cluster.get("cluster_id"),wallets=cluster.get("wallets") or [],
        vote=vote,vote_complete=complete,cluster_parameters=params,
        raw_context_values=dict(context_values),
        member_wallet_profiles=member,
    )


def derive(path=DEFAULT_DEEP):
    deep=json.loads(Path(path).read_text())
    if deep.get("kind")!="dlmm_profitable_operator_deep_reconstruction_v1":
        raise RuntimeError("dlmm_operator_rule_deep_kind")
    protocol=json.loads(PROTOCOL.read_text())
    derivation=json.loads(DERIVATION_PROTOCOL.read_text())
    required_support=float(
        derivation["core_family"]["independent_cluster_support_required"])
    min_clusters=int(derivation["core_family"]["minimum_independent_clusters"])
    by_wallet={r["wallet"]:r for r in deep.get("wallets") or []}

    qualifying=set()
    for row in deep.get("wallets") or []:
        after=row.get("after_network_cost_pnl_usd")
        if (row.get("capital_at_risk_exact") is True and
                after is not None and float(after)>0):
            qualifying.add(row["wallet"])

    clusters=[]
    for cluster in deep.get("operator_clusters") or []:
        members=[w for w in cluster.get("wallets") or [] if w in qualifying]
        if not members:continue
        # Any fleet is one evidence unit regardless of member count.
        c=dict(cluster);c["wallets"]=members
        profile=cluster_behavior(c,by_wallet)
        clusters.append(profile)

    voting=[c for c in clusters if c["vote_complete"]]
    keys=Counter(tuple(c["vote"][d] for d in (
        "distribution_family","sidedness","width_bucket",
        "active_bin_placement_bucket","rebalance_bucket","hold_bucket"))
        for c in voting)
    proposals=[]
    total=len(voting)
    for key,count in sorted(keys.items(),key=lambda kv:(-kv[1],kv[0])):
        support=(0.0 if total==0 else count/total)
        if count<min_clusters or support<required_support:
            continue
        matched=[c for c in voting if tuple(c["vote"][d] for d in (
            "distribution_family","sidedness","width_bucket",
            "active_bin_placement_bucket","rebalance_bucket","hold_bucket"))==key]
        params={}
        for pkey in (
            "median_width_bins","median_center_active_offset_bins",
            "median_hold_seconds","rebalance_position_rate"):
            values=[c["cluster_parameters"].get(pkey) for c in matched
                    if c["cluster_parameters"].get(pkey) is not None]
            params[pkey]=None if not values else statistics.median(values)
        context_gates={}
        for context_key,bounds in derivation["context_dimensions"].items():
            votes=[]
            for cluster in matched:
                values=(cluster.get("raw_context_values") or {}).get(context_key) or []
                buckets=[_configured_bucket(v,bounds) for v in values]
                vote=_modal(buckets)
                if vote is not None:votes.append((cluster["cluster_id"],vote))
            if len(votes)<min_clusters:
                continue
            counts=Counter(v for _cluster,v in votes)
            winning,winning_count=sorted(
                counts.items(),key=lambda kv:(-kv[1],str(kv[0])))[0]
            support=winning_count/len(votes)
            if support>=required_support:
                context_gates[context_key]=dict(
                    bucket=winning,support=support,
                    independent_clusters_with_context=len(votes),
                    supporting_cluster_ids=[
                        cluster for cluster,vote in votes if vote==winning],
                )
        proposals.append(dict(
            family=dict(zip((
                "distribution_family","sidedness","width_bucket",
                "active_bin_placement_bucket","rebalance_bucket","hold_bucket"),key)),
            independent_cluster_count=count,
            independent_cluster_support=support,
            source_cluster_ids=[c["cluster_id"] for c in matched],
            context_gates=context_gates,
            frozen_parameter_medians=params,
            diagnostic_cluster_parameter_ranges={
                pkey:(None if not [c["cluster_parameters"].get(pkey) for c in matched
                                   if c["cluster_parameters"].get(pkey) is not None]
                      else [
                          min(c["cluster_parameters"][pkey] for c in matched
                              if c["cluster_parameters"].get(pkey) is not None),
                          max(c["cluster_parameters"][pkey] for c in matched
                              if c["cluster_parameters"].get(pkey) is not None),
                      ])
                for pkey in params
            },
        ))

    report=dict(
        kind="dlmm_profitable_operator_rule_proposals_v1",
        status=("candidate_rules_ready_to_freeze_before_prospective_test"
                if proposals else "no_repeatable_family_meets_preregistered_support"),
        protocol_revision=protocol.get("protocol_revision"),
        derivation_protocol_revision=derivation.get("revision"),
        qualifying_independent_clusters=len(clusters),
        complete_voting_clusters=len(voting),
        support_required=required_support,
        minimum_independent_clusters=min_clusters,
        candidate_rule_proposals=proposals,
        incomplete_clusters=[c for c in clusters if not c["vote_complete"]],
        allocation_authority=False,prospective_outcomes_read=False,
    )
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(
        status=report["status"],clusters=len(clusters),voting=len(voting),
        proposals=len(proposals)),sort_keys=True))
    return report


def freeze_proposals(path=OUT,output=FROZEN_OUT):
    proposals=json.loads(Path(path).read_text())
    if proposals.get("kind")!="dlmm_profitable_operator_rule_proposals_v1":
        raise RuntimeError("dlmm_operator_rule_freeze_kind")
    if proposals.get("status")!="candidate_rules_ready_to_freeze_before_prospective_test":
        raise RuntimeError("dlmm_operator_rule_freeze_no_supported_rule")
    if proposals.get("prospective_outcomes_read") is not False:
        raise RuntimeError("dlmm_operator_rule_freeze_outcome_leakage")
    rules=proposals.get("candidate_rule_proposals") or []
    if not rules:
        raise RuntimeError("dlmm_operator_rule_freeze_empty")
    protocol=json.loads(PROTOCOL.read_text())
    derivation=json.loads(DERIVATION_PROTOCOL.read_text())
    if proposals.get("protocol_revision")!=protocol.get("protocol_revision"):
        raise RuntimeError("dlmm_operator_rule_freeze_protocol_mismatch")
    if proposals.get("derivation_protocol_revision")!=derivation.get("revision"):
        raise RuntimeError("dlmm_operator_rule_freeze_derivation_mismatch")
    canonical=json.dumps(rules,sort_keys=True,separators=(",",":")).encode()
    import hashlib
    rule_hash=hashlib.sha256(canonical).hexdigest()
    body=dict(
        kind="dlmm_profitable_operator_rules_v1",
        status="frozen_pre_prospective",
        protocol_revision=protocol.get("protocol_revision"),
        derivation_protocol_revision=derivation.get("revision"),
        rule_hash=rule_hash,
        prospective_outcomes_read_before_freeze=False,
        allocation_authority=False,paper_only=True,
        rule_count=len(rules),rules=rules,
        prospective_test=derivation.get("prospective_test"),
    )
    Path(output).write_text(json.dumps(body,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(
        status=body["status"],rules=len(rules),rule_hash=rule_hash),sort_keys=True))
    return body


def main():
    p=argparse.ArgumentParser()
    p.add_argument("phase",nargs="?",choices=("derive","freeze"),default="derive")
    p.add_argument("--deep",default=str(DEFAULT_DEEP))
    p.add_argument("--proposals",default=str(OUT))
    args=p.parse_args()
    if args.phase=="derive":derive(Path(args.deep))
    else:freeze_proposals(Path(args.proposals),FROZEN_OUT)


if __name__=="__main__":
    main()
