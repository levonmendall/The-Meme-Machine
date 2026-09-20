"""Read-only detail from retained public market evidence; no strategy authority."""
import json
import sqlite3
from collections import Counter
from pathlib import Path


def inspect(root):
    root=Path(root);out={}
    for lane,file,fields in (
        ('pump','pump-acceleration-natural-prospective.json',('postgrad','attempts','pumpswap_stream','limitations')),
        ('meteora','solana-dlmm-independent-v1-live.json',('attempts','qualification_failure_counts','limitations')),
        ('pons','pons-selective-continuation-v1-cohort.json',('summary',))):
        path=root/lane/file
        if not path.exists():continue
        report=json.loads(path.read_text());out[lane]={k:report.get(k) for k in fields}
        out[lane]['top_level_fields']=sorted(report)
    path=root/'shared-solana-evidence.sqlite'
    if path.exists():
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            out['broker_jobs']=[dict(kind=k,status=s,count=n,first_deadline=lo,last_deadline=hi) for k,s,n,lo,hi in db.execute('SELECT kind,status,count(*),min(deadline),max(deadline) FROM jobs GROUP BY kind,status')]
        finally:db.close()
    (root/'acquisition-diagnosis.json').write_text(json.dumps(out,indent=2)+'\n')
    print('ACQUISITION_DIAGNOSIS '+json.dumps(out,sort_keys=True))
    return out
