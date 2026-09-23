"""Captured-evidence trajectory parity experiment; zero provider calls."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import sys
from types import SimpleNamespace

def replay(root,lane_source):
    sys.path.insert(0,str(Path(lane_source).resolve()))
    from robinhood_research.pons_selective_acquisition import ImmutableEvidenceCache,_trajectory
    from robinhood_research.abi import calldata
    root=Path(root);headers={};states={};oldmethods=Counter()
    for line in gzip.open(root/'certification-hourly/pons/rpc-evidence.jsonl.gz','rt'):
        row=json.loads(line);calls=row['request'];raw=row.get('response')
        if raw is None:continue
        values=raw if len(calls)>1 else [raw]
        if len(calls)==1 and calls[0][0] not in ('eth_getLogs',) and isinstance(raw,list) and len(raw)==1:values=raw
        if not isinstance(values,list):continue
        for (method,p),v in zip(calls,values):
            oldmethods[method]+=1
            if method in ('eth_getBlockByNumber','eth_getBlockByHash') and isinstance(v,dict):headers[int(v['number'],16)]=v
            if method=='eth_call':states[json.dumps(p,sort_keys=True)]=v
    class Context:
        def __init__(self):self.cache=ImmutableEvidenceCache();self.completed_sessions=[];self.rpc=None;self.methods=Counter();self.batches=0
        def batch(self,calls,scope):
            self.batches+=1;out=[]
            for method,p in calls:
                self.methods[method]+=1
                if method=='eth_getBlockByNumber':out.append(headers[int(p[0],16)])
                elif method=='eth_call':out.append(states[json.dumps(p,sort_keys=True)])
                else:raise AssertionError(method)
            return out
    ctx=Context();matched=0;unavailable=[]
    for line in (root/'certification-native/hourly/pons/pons-selective-continuation-v1-cohort/candidate-rows.jsonl').open():
        row=json.loads(line)
        if not row.get('trajectory_snapshots'):continue
        c=dict(row['candidate']);c['header']=headers[c['block']];c['state']=SimpleNamespace(**c['state'])
        # Native acquisition supplies the launch metadata after its first read;
        # reproduce it from the captured current-block launch result when present.
        key=json.dumps([dict(to=c['curve'].lower(),data=calldata('launchedAt()')),hex(c['block'])],sort_keys=True)
        if key not in states:states[key]='0x'+int(row['launch_at']).to_bytes(32,'big').hex()
        try:snapshots,launch,_=_trajectory('https://offline.invalid',c,evidence_context=ctx)
        except KeyError as exc:unavailable.append(dict(sequence=row['sequence'],missing=str(exc)));continue
        if snapshots!=row['trajectory_snapshots']:raise AssertionError(('trajectory_parity',row['sequence'],snapshots,row['trajectory_snapshots']))
        matched+=1
    return dict(scope='offline exact trajectory replay; not live coverage or latency certification',
        matched_candidate_vectors=matched,captured_evidence_unavailable=unavailable,
        replayed_trajectory_methods=dict(ctx.methods),replayed_trajectory_batches=ctx.batches,
        baseline_all_pons_methods=dict(oldmethods),
        limitations=['Replay excludes discovery/window HTTP rounds and live timing.',
        'Baseline header counts include authentication outside trajectory; no raw total-CU reduction claim follows.'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--artifact-root',required=True);p.add_argument('--lane-source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    Path(a.output).write_text(json.dumps(replay(a.artifact_root,a.lane_source),indent=2,sort_keys=True)+'\n')
