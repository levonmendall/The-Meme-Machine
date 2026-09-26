"""Retained attempt attribution only. Never synthesize executable quotes or P&L."""
import argparse,gzip,hashlib,json
from pathlib import Path


def replay(path):
    path=Path(path)
    source=json.loads(gzip.decompress(path.read_bytes()))
    rows=[]
    for run in source['runs']:
        for row in run['pons']['lifecycles']:
            evidence=row.get('entry_persistence',{})
            age=evidence.get('quote_age_after_confirmation_seconds')
            if age is None:continue
            demand=evidence['demand'];hard=[]
            if demand['current_net_quote']<=0:hard.append('nonpositive_authenticated_net_demand')
            if demand['creator_sell_quote_15s']>0:hard.append('creator_distribution')
            rows.append(dict(run=run['run'],lifecycle_id=row['lifecycle_id'],
                quote_age_seconds=age,stale=age>5,additional_hard_invalidators=hard,
                classification='stale_plus_hard_market_invalidators' if hard else 'stale_only_among_hard_invalidators',
                retained_persistence_reasons=evidence.get('reasons',[]),
                retained_persistent=evidence['persistent'],
                fresh_quote='UNMEASURABLE',counterfactual_fill='UNMEASURABLE',profit='UNMEASURABLE'))
    assert [r['quote_age_seconds'] for r in rows]==[19,18,21,28,27,18,17]
    assert sum(not r['additional_hard_invalidators'] for r in rows)==4
    assert sum(bool(r['additional_hard_invalidators']) for r in rows)==3
    return dict(scope='preserved_evidence_attribution_only',passed=True,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        stale_only_among_hard_invalidators=4,additional_hard_invalidators=3,
        limitation='Stale-only refers to hard invalidators. All original persistence reasons remain binding; no rescued entries or profitability inferred.',
        attempts=rows,new_provider_collection=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',default='certification/evidence/robinhood-runs-355-368.json.gz');parser.add_argument('--output',required=True)
    args=parser.parse_args();result=replay(args.evidence)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='attempts'}))
