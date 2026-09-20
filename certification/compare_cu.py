"""Compare actual archived work. Lower spend alone is not an engineering PASS."""
import argparse
import json
from pathlib import Path


def compare(before,after):
    lanes={}
    fields=('physical_http_requests','estimated_cu','evaluated_candidates','complete_evidence_candidates',
        'estimated_cu_per_evaluated','estimated_cu_per_complete','stale_after_complete_evidence',
        'stale_after_complete_fraction','queue_wait_seconds','transport_seconds','max_queue_depth')
    for lane in ('pons','ramses'):
        a=before['lanes'][lane];b=after['lanes'][lane]
        lanes[lane]={f:dict(before=a.get(f),after=b.get(f)) for f in fields}
        lanes[lane]['methods']={m:dict(before=a['logical_rpc_by_method'].get(m,0),after=b['logical_rpc_by_method'].get(m,0),
            cu_before=a['estimated_cu_by_method'].get(m),cu_after=b['estimated_cu_by_method'].get(m))
            for m in sorted(set(a['logical_rpc_by_method'])|set(b['logical_rpc_by_method']))}
        for f in ('funnel','cache_metrics','provider_latency_seconds','observation_window'):
            lanes[lane][f]=dict(before=a.get(f),after=b.get(f))
    old=before['totals']['estimated_cu'];new=after['totals']['estimated_cu']
    reduction=None if old is None or new is None or old<=0 else 1-new/old
    a=before['lanes']['pons'];b=after['lanes']['pons']
    def measured(left,right,fn):return None if left is None or right is None else fn(left,right)
    checks=dict(estimated_cu_reduction_at_least_40pct=None if reduction is None else reduction>=.4,
        evaluated_volume_not_lower=measured(a.get('evaluated_candidates'),b.get('evaluated_candidates'),lambda x,y:y>=x),
        complete_vectors_not_lower=measured(a.get('complete_evidence_candidates'),b.get('complete_evidence_candidates'),lambda x,y:y>=x),
        stale_fraction_not_higher=measured(a.get('stale_after_complete_fraction'),b.get('stale_after_complete_fraction'),lambda x,y:y<=x))
    return dict(schema_version=1,baseline_run=before['run_id'],comparison_run=after['run_id'],lanes=lanes,
        total_estimated_cu=dict(before=old,after=new,reduction_fraction=reduction),measured_checks=checks,
        acceptance='NOT_ESTABLISHED',
        limitations=['Market cohorts differ; equal counts alone do not prove equal unique-opportunity coverage.',
            'Terminal integrity, frozen policy/config, per-lane fairness, errors and backlog must also pass.',
            'Full-run totals include normal drain; observation-only wire counts are separate.',
            'A stale terminal may overlap other rejection reasons; do not sum reasons as unique opportunities.',
            'No profitability or natural lifecycle certification follows from RPC efficiency.'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    Path(a.output).write_text(json.dumps(compare(json.loads(Path(a.before).read_text()),json.loads(Path(a.after).read_text())),indent=2,sort_keys=True)+'\n')
