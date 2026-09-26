"""Synthetic pressure derivative of the digest-pinned Run 370 inventory.

No provider calls or economic qualification claims. Complete transaction fields
come from one retained template; identities, times, event decoders and unrelated
block padding are explicitly synthetic. The real writer, fences, maintenance,
local readers and original retention window/capacity are exercised.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch


def run(root,seconds,output,*,dense=False):
    sys.path.insert(0,str(Path(root).resolve()))
    from meme_machine.solana_provider_config import AlchemyEndpoint
    from meme_machine.solana_evidence_service import ServiceState,program_subscriptions
    from meme_machine.solana_evidence_plane import EvidenceReader,EvidenceUnavailable,IntervalProof,canonical
    from meme_machine.solana_evidence_transport import Subscription
    from meme_machine.solana_evidence_runtime import RuntimeEvidence,PUMP_SCOPE,SWAP_SCOPE,METEORA_SCOPE
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):raise AssertionError('pressure_network_forbidden')
    sys.addaudithook(guard)
    fixture=json.loads((Path(__file__).parent.parent/'tests/fixtures/solana_evidence_plane/run370-pressure-template.json').read_text())
    programs={s.scope:s.address for s in program_subscriptions()}
    now=[100000.];started=time.monotonic();samples=[];failure=None;read_counts={'pump':0,'meteora':0};censored={};maximum_source=0
    with tempfile.TemporaryDirectory() as tmp,patch('time.time',side_effect=lambda:now[0]):
        s=ServiceState(Path(tmp)/'db',AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-pressure'))
        s.writer.clock=lambda:now[0];w=s.writer
        peaks=dict(hot_bytes=0,db_bytes=0,wal_bytes=0)
        def measure_hot(statement='COMMIT'):
            if not statement.startswith(('COMMIT','BEGIN','PRAGMA wal_checkpoint')):return
            db_bytes=w.path.stat().st_size
            wal_path=Path(str(w.path)+'-wal');wal_bytes=wal_path.stat().st_size if wal_path.exists() else 0
            for key,value in (('db_bytes',db_bytes),('wal_bytes',wal_bytes),('hot_bytes',db_bytes+wal_bytes)):
                peaks[key]=max(peaks[key],value)
        # Observe transaction/checkpoint boundaries as well as each source and
        # maintenance call. Coarse trend samples alone miss transient WAL peaks.
        w.db.set_trace_callback(measure_hot)
        def decoder(tx):
            return [dict(slot=tx['slot'],market_time=int(now[0])-1,index=0,event_type='trade',
                mint='pressure-mint',pool='pressure-pool',wallet='pressure-wallet',buy=True,amount=100,quote_amount=100)]
        s.fence.decoders={PUMP_SCOPE:decoder,SWAP_SCOPE:decoder}
        reader=EvidenceReader(w.path);plane=RuntimeEvidence(w.path,owner='pump',clock=lambda:now[0],command=s.fence.command)
        baseline=not hasattr(__import__('meme_machine.solana_evidence_plane',fromlist=['decode_body']),'decode_body')
        # Same dispatch cadence on both versions; production selects the slice.
        for n in range(seconds//2+1):
            now[0]=100000+n*2;slot=10000+n;txs=[]
            for j in range(144):
                tx=copy.deepcopy(fixture['transaction']);tx.pop('slot',None);tx.pop('blockTime',None);tx.pop('transactionIndex',None)
                tx['transaction']['signatures']=[f'synthetic:{slot}:{j}']
                # Preserve address fanout, while avoiding an unrealistically tiny
                # one-transaction dictionary across the whole pressure interval.
                def address(k):return hashlib.sha256((str((n*144+j)%700)+':'+str(k)).encode()).hexdigest()[:44]
                message=tx['transaction']['message'];loaded=tx['meta'].get('loadedAddresses') or {}
                message['accountKeys']=[programs[METEORA_SCOPE],('pressure-pool' if j==0 else address(0))]+[address(k+1) for k in range(len(message['accountKeys'])-2)]
                for key in ('writable','readonly'):loaded[key]=[address(100+i+(200 if key=='readonly' else 0)) for i in range(len(loaded.get(key,[])))]
                tx['meta']['loadedAddresses']=loaded;txs.append(tx)
            for scope,count in ((PUMP_SCOPE,14),(SWAP_SCOPE,59)):
                for j in range(count):
                    txs.append(dict(transaction=dict(signatures=[f'{scope}:{slot}:{j}'],message=dict(accountKeys=[programs[scope]])),meta=dict(err=None,logMessages=[])))
            # ~7 MB full messages, including out-of-scope traffic. Dense mode
            # separately exercises >2048 total transactions without scope excess.
            other_count=2100 if dense else 1000
            padding='x'*max(1,(7_000_000-len(canonical(txs)))//other_count-150)
            txs.extend(dict(transaction=dict(signatures=[f'other:{slot}:{j}'],message=dict(accountKeys=['unrelated'])),meta=dict(err=None,logMessages=[padding])) for j in range(other_count))
            msg=dict(method='blockNotification',params=dict(result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),blockTime=int(now[0])-1,transactions=txs)))))
            raw=canonical(msg)
            try:
                tick=time.monotonic();s.source(Subscription('service','chain:solana','all','blocks',2),json.loads(raw),now[0],len(raw));maximum_source=max(maximum_source,time.monotonic()-tick);measure_hot()
                if n==10:
                    s.fence.command(dict(op='interest',owner='lifecycle',scope=METEORA_SCOPE,lower_slot=slot,priority=0,lifecycle='open',addresses=['pressure-pool']))
                    for candidate in range(22):
                        s.fence.command(dict(op='interest',owner='candidate:'+str(candidate),scope=METEORA_SCOPE,
                            lower_slot=slot,priority=2,lifecycle='candidate',addresses=[txs[candidate]['transaction']['message']['accountKeys'][1]]))
                # Seventeen explicit reconnects during the original 511-second
                # interval, followed by successful bounded complete repairs.
                if 15<=n<=255 and n%15==0:s.disconnected('synthetic_provider_disconnect')
                if 17<=n<=257 and n%15==2:
                    for gid,scope,lo,hi in w.db.execute('SELECT id,scope,lo,hi FROM gaps WHERE repaired IS NULL AND hi IS NOT NULL').fetchall():
                        witness=dict(finalized=True,complete=True,scope=scope,lower_slot=lo,upper_slot=hi,lineage_hash='synthetic-complete-repair')
                        w.ingest([],proof=IntervalProof(scope,lo,hi,'alchemy_finalized_repair',s.fence.endpoint_identity,witness,now[0]))
                if n==100:s.fence.command(dict(op='release',owner='lifecycle',scope=METEORA_SCOPE,resolved=True))
                plan=s.maintenance({})
                if plan:s.archive_commit(plan,w.write_archive(w.path,plan))
                measure_hot()
                if n>31 and n%5==0:
                    try:plane.pump_events(PUMP_SCOPE,'pressure-mint',int(now[0])-63,int(now[0])-3,upper_slot=slot-1);read_counts['pump']+=1
                    except EvidenceUnavailable as exc:censored[str(exc)]=censored.get(str(exc),0)+1
                    try:plane.meteora_interval('pressure-pool',slot-2,slot-1);read_counts['meteora']+=1
                    except EvidenceUnavailable as exc:censored[str(exc)]=censored.get(str(exc),0)+1
            except EvidenceUnavailable as exc:failure=str(exc)
            if n%25==0 or failure or n==seconds//2:
                stats=reader.telemetry();samples.append(dict(seconds=n*2,db_bytes=stats['db_bytes'],wal_bytes=stats['wal_bytes'],hot_bytes=stats['hot_bytes'],
                    archive_bytes=stats['archive_bytes'],counters=stats['counters'],coverage=stats['coverage_windows'],unresolved_gaps=stats['unresolved_gaps'],
                    retention_floors=stats['retention_floors'],active_pins=w.db.execute('SELECT COUNT(*) FROM interests WHERE active=1').fetchone()[0],
                    hot_records=w.db.execute('SELECT COUNT(*) FROM records WHERE body IS NOT NULL').fetchone()[0]))
                print(json.dumps(dict(seconds=n*2,hot_bytes=stats['hot_bytes'],failure=failure)),flush=True)
                # Keep measurements if an execution workspace interrupts a long
                # offline run. A partial checkpoint never claims a passing run.
                checkpoint=Path(str(output)+'.partial.json')
                checkpoint.write_text(json.dumps(dict(completed=False,failure=failure,samples=samples),indent=2)+'\n')
            if failure:break
        elapsed=time.monotonic()-started
        steady=[r['hot_bytes'] for r in samples if r['seconds']>=max(1400,seconds-600)]
        bounded=(not failure and seconds>=1800 and len(steady)>=6 and max(steady)-min(steady)<32*1024*1024
                 and peaks['hot_bytes']<w.max_hot_bytes//2 and samples[-1]['unresolved_gaps']==0)
        report=dict(schema='run370-pressure-v1',baseline=baseline,requested_seconds=seconds,completed_seconds=samples[-1]['seconds'],dense_full_blocks=dense,
            fixture_artifact_id=fixture['artifact_id'],fixture_digest=fixture['artifact_sha256'],failure=failure,samples=samples,
            peak_hot_bytes=peaks['hot_bytes'],peak_db_bytes=peaks['db_bytes'],peak_wal_bytes=peaks['wal_bytes'],
            peak_measurement='transaction/checkpoint boundaries and source/maintenance completion; trends every 50 logical seconds',
            local_reads=read_counts,infrastructure_censored_queries=censored,elapsed_seconds=elapsed,max_source_seconds=maximum_source,
            processed_transactions=samples[-1]['counters'].get('ingested_transaction',0),provider_calls=0,
            bounded_with_headroom=bounded,steady_hot_range_bytes=(max(steady)-min(steady) if steady else None),
            observed_ingestion_records_per_second=sum(samples[-1]['counters'].get('ingested_'+k,0) for k in ('transaction','event','account'))/elapsed,
            observed_archive_records_per_second=samples[-1]['counters'].get('archived_records',0)/elapsed,
            limitation='Synthetic timing, padding and events; retained-shape pressure, not counterfactual economic vectors or attribution of undocumented historical websocket closes.')
        plane.close();reader.close();s.close()
    Path(output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--seconds',type=int,default=1200);p.add_argument('--output',required=True);p.add_argument('--dense',action='store_true');a=p.parse_args()
    run(a.runtime,a.seconds,a.output,dense=a.dense)
