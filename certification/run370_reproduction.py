"""Read-only audit and deterministic pre-repair reproductions; no network."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from meme_machine.solana_evidence_plane import EvidenceWriter, EvidenceUnavailable, FinalizedRecord, IntervalProof
from meme_machine.solana_evidence_service import FinalizedFence, program_subscriptions


def audit(root):
    root=Path(root);path=root/'certification-smoke/solana-evidence-plane.sqlite'
    db=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
    q=lambda sql:db.execute(sql).fetchall()
    report=dict(schema='run370-causal-reproduction-v1',artifact_id=10894299703,
        artifact_sha256='c28ce3c2d2ba1375c4bc5035145b52da039d09e4c677e78c2911bc89d7ed77c3',
        scope='post-shutdown preserved DB; lane failure snapshot is earlier',db_bytes=path.stat().st_size,
        wal_bytes=0,wal_note='checkpointed before artifact; use lane snapshot for failure-time WAL',
        categories=q('SELECT scope,kind,COUNT(*),SUM(body IS NOT NULL),SUM(length(body)),MAX(length(body)) FROM records GROUP BY 1,2'),
        physical=q('SELECT name,SUM(pgsize),SUM(payload) FROM dbstat GROUP BY name ORDER BY 2 DESC'),
        counters=dict(q('SELECT key,value FROM counters')),
        gaps=q('SELECT scope,reason,repaired IS NOT NULL,COUNT(*),MIN(lo),MAX(hi) FROM gaps GROUP BY 1,2,3'),
        coverage=q('SELECT scope,COUNT(*),MIN(lo),MAX(hi) FROM coverage GROUP BY scope'),
        pins=q('SELECT scope,lifecycle,active,COUNT(*),MIN(lower_slot),MAX(lower_slot) FROM interests GROUP BY 1,2,3'),
        floors=dict(q("SELECT key,value FROM meta WHERE key LIKE 'retention_floor:%'")))
    # Pump's saved report captures the original service, before supervisor restarts.
    pump=json.loads((root/'certification-smoke/pump/status.json').read_text())['report']
    report['pump_failure_snapshot']=pump.get('stream')
    report['pump_failure']=pump.get('infrastructure_failure')
    report['pump_local_reads']=pump.get('stream',{}).get('counters',{}).get('pump.local_evidence_reads')
    report['disconnects_by_reason']=dict(Counter(reason for _,reason in q("SELECT created,reason FROM gaps WHERE scope='program:meteora' AND reason IN ('ConnectionClosedError','filtered_block_bound')")))
    template=json.loads(db.execute("SELECT body FROM records WHERE kind='transaction' AND body IS NOT NULL LIMIT 1").fetchone()[0])
    db.close()
    # Faithful scope density/address fanout from retained transaction bodies.
    now=[1000.];endpoint='a'*64
    with tempfile.TemporaryDirectory() as tmp:
        w=EvidenceWriter(Path(tmp)/'plane.sqlite',clock=lambda:now[0],max_hot_bytes=32*1024*1024);f=FinalizedFence(w,endpoint_identity=endpoint)
        scope='program:meteora';samples=[]
        report['scaled_reproduction_hot_limit_bytes']=w.max_hot_bytes
        report['scaled_reproduction_note']='100 retained-shape transactions versus one original 64-record maintenance slice per logical minute; scaled capacity, not a full-pressure throughput claim'
        for n in range(40):
            batch=[]
            for j in range(100):
                b=template;sig=f'{n:04}:{j:04}';payload=dict(b['payload']);tx=dict(payload['transaction']);tx['signatures']=[sig];payload['transaction']=tx
                batch.append(FinalizedRecord('tx:'+sig,scope,n*100+j,sig,b['program'],tuple(b['addresses']),int(now[0]),payload,'alchemy_finalized_stream',endpoint,now[0],kind='transaction'))
            start=time.monotonic()
            try:w.ingest(batch)
            except EvidenceUnavailable as exc:
                report['scaled_capacity_failure']=str(exc);break
            # Same bounded 64-record maintenance slice as the certified runtime.
            now[0]+=60;w.archive(now[0]-180,max_records=64);w.retain(now[0]-180,max_records=64,archive_first=False)
            samples.append(dict(simulated_seconds=now[0]-1000,elapsed_seconds=time.monotonic()-start,
                db_bytes=w.path.stat().st_size,wal_bytes=Path(str(w.path)+'-wal').stat().st_size,
                hot_records=w.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0],
                counters=dict(w.db.execute('SELECT key,value FROM counters'))))
        report['pressure_baseline_samples']=samples;w.close()
    with tempfile.TemporaryDirectory() as tmp:
        w=EvidenceWriter(Path(tmp)/'plane.sqlite',clock=lambda:1000);f=FinalizedFence(w,endpoint_identity=endpoint)
        sub=next(s for s in program_subscriptions() if s.evidence_class=='transactions')
        unrelated=dict(transaction=dict(signatures=['unrelated'],message=dict(accountKeys=['other-program'])),meta={})
        message=dict(params=dict(result=dict(value=dict(slot=100,err=None,block=dict(parentSlot=99,blockhash='h',previousBlockhash='p',blockTime=999,transactions=[unrelated]*2049)))))
        try:f.block(sub,message,1000)
        except EvidenceUnavailable as exc:report['full_block_before_scope_filter_failure']=str(exc)
        w.close()
    with tempfile.TemporaryDirectory() as tmp:
        w=EvidenceWriter(Path(tmp)/'plane.sqlite',clock=lambda:1000);f=FinalizedFence(w,endpoint_identity=endpoint)
        scope='program:pump'
        w.db.execute('INSERT INTO cursors VALUES(?,?,?)',(scope,100,1000))
        w.db.execute('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',(scope,100,99,'h','p',999,'[]',f.session,1000,0))
        f.disconnect();w.reconnect(scope,101)
        proof=IntervalProof(scope,100,101,'alchemy_finalized_repair',endpoint,
            dict(finalized=True,complete=True,scope=scope,lower_slot=100,upper_slot=101,lineage_hash='proof'),1001)
        w.ingest([],proof=proof);w.db.execute('UPDATE cursors SET slot=200 WHERE scope=?',(scope,))
        f.disconnect()
        report['repaired_gap_reopened_from_old_receipt']=w.db.execute('SELECT lo FROM gaps WHERE repaired IS NULL').fetchall();w.close()
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    r=audit(a.evidence);Path(a.output).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(output=a.output,capacity_failure=r.get('scaled_capacity_failure'),block_failure=r.get('full_block_before_scope_filter_failure'),disconnects=r['disconnects_by_reason'],reopened=r['repaired_gap_reopened_from_old_receipt'],
        first=r['pressure_baseline_samples'][0],last=r['pressure_baseline_samples'][-1])))
