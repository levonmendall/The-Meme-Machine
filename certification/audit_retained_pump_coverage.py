"""Bounded audit of cached compact exports; no provider or artifact downloads."""
import argparse,gzip,hashlib,json
from pathlib import Path

def audit(cache):
    from meme_machine.postgrad import pumpswap_pool
    output=[]
    for run in ('367','368'):
        folder=Path(cache)/run
        report=json.load(gzip.open(folder/'native-pump_pump-acceleration-natural-prospective.json.gz'))
        bodies=set();signatures=[]
        for line in gzip.open(folder/'broker-subset.jsonl.gz','rt'):
            obj=json.loads(line);row=obj['row']
            if obj['table'] in ('immutable_transactions','tx_cache'):bodies.add(row['signature'])
            if obj['table']=='signatures':signatures.append(row)
        # Include transport receipts independently of cache ownership/eviction.
        for line in gzip.open(folder/'pump-rpc-subset.jsonl.gz','rt'):
            row=json.loads(line)
            if row['provider']['provider_kind']!='alchemy':continue
            replies=row.get('response') or []
            if isinstance(replies,dict):replies=[replies]
            byid={r.get('id'):r for r in replies}
            for q in row.get('request') or []:
                response=byid.get(q['id'],{}).get('result')
                if q['method']=='getTransaction' and isinstance(response,dict):bodies.add(q['params'][0])
        for case in report['full_evidence_candidates']:
            pool=pumpswap_pool(case['mint']);end=case['observed_at'];start=end-30
            census=[r for r in signatures if r['address']==pool and r['block_time'] is not None and start<=r['block_time']<=end and not r['err']]
            missing=sorted({r['signature'] for r in census if r['signature'] not in bodies})
            output.append(dict(run=int(run),mint=case['mint'],pool=pool,lower_time=start,upper_time=end,
                successful_census_signatures=len(census),missing_authoritative_bodies=len(missing),
                missing_signature_sha256=hashlib.sha256(json.dumps(missing,separators=(',',':')).encode()).hexdigest(),
                missing_examples=missing[:2],coverage_granted=False,
                status='CENSORED_MISSING_AUTHORITATIVE_BODIES' if missing else 'REQUIRES_CENSUS_AND_AVAILABILITY_VALIDATION'))
    return dict(schema=1,cases=output,public_observations_upgraded=False,provider_calls=0)

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.write_text(json.dumps(audit(args.cache),indent=2)+'\n')
if __name__=='__main__':main()
