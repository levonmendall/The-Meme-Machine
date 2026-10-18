"""Native audit-ring DDL versus evidence-cache retention on synthetic state.

Original Broker/Plane/Attempts/Pipeline methods only. No market provider,
financial state or production copy. Geometry is explicit; no AWS attribution.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from unittest.mock import patch

from engineering.diagnostics.pons_query_cost import fixture
from meme_machine.lanes.pons.pipeline import Pipeline
from meme_machine.lanes.pons.pons_attempts import Attempts
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational.offline import install_network_guard
from meme_machine.runtime.robinhood.accounting import high_water,project
from meme_machine.runtime.robinhood.plane import canonical,digest
from meme_machine.runtime.robinhood.pons import Broker
from tests.lanes.pons.test_pons_candidate_plane import event


SOURCE='0e9a0ffe1912c28258735909ebce933803585556'
NOW=200000.
COHORT_BYTES=5030660


def io():
    return {key:int(value) for key,value in (line.split(':',1) for line in
        (Path('/proc/self/task')/str(threading.get_native_id())/'io').read_text().splitlines())}


def retained(db):
    result={}
    for table,order in (('evidence','namespace,key'),('receipt_obligations','namespace,key,consumer,owner,generation'),
                        ('evidence_retention_revision','namespace')):
        checksum=hashlib.sha256();count=0
        for row in db.execute('SELECT * FROM '+table+' ORDER BY '+order):
            raw=canonical(tuple(row)).encode();checksum.update(len(raw).to_bytes(8,'big')+raw);count+=1
        result[table]=dict(rows=count,sha256=checksum.hexdigest())
    return result


def run(output):
    install_network_guard();output=Path(output).resolve()
    result=dict(schema='pons-audit-schema-cost-v1',source_commit=subprocess.check_output(
        ['git','rev-parse','HEAD'],text=True).strip(),sqlite_version=sqlite3.sqlite_version,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        runtime_plane_sha256=hashlib.sha256(Path('meme_machine/runtime/robinhood/plane.py').read_bytes()).hexdigest(),
        runtime_hashes={name:hashlib.sha256(Path('meme_machine/runtime/'+name).read_bytes()).hexdigest()
            for name in ('robinhood/plane.py','storage.py','native_audit_retention.py')},
        scope='MATCHED_SYNTHETIC_NATIVE_LOCAL_RING_PRUNING_NOT_AWS_FRACTION',provider_requests=0,
        production_state_copied=False,financial_authority=False,cases=[])
    with Scratch() as scratch,patch.dict(os.environ,dict(MM_MODE='PAPER',MM_OPERATIONAL_PHASE='OFFLINE_COST'),clear=True):
        for mode in ('checkpoint','transition_ring','observation_and_transition_rings'):
            path=scratch.path/(mode+'.sqlite')
            owner=Broker(path,'synthetic-offline-policy',clock=lambda:NOW)
            peer=Broker(path,'synthetic-offline-policy',clock=lambda:NOW)
            plane=owner.plane;pipeline=Pipeline(scratch.path/(mode+'-pipeline.sqlite'),'pons','synthetic-offline-policy')
            try:
                seeded=fixture(path,1865,4095,768,0);seeded.close()
                with plane.transaction():
                    plane.db.execute('UPDATE candidates SET pending=0,observed=?,interpretation=?',
                        (NOW-90000,canonical(owner.policy)))
                owner.enqueue(event(1),now=NOW,needs_work=False)
                keys=[r[0] for r in plane.db.execute('SELECT id FROM candidates ORDER BY id')]
                body=dict(qualifiers=[dict(curve=key.rsplit(':',1)[-1]) for key in keys],lifecycles=[],padding='')
                checkpoint=dict(result=body);body['padding']='x'*(COHORT_BYTES-len(canonical(checkpoint).encode()))
                assert len(canonical(checkpoint).encode())==COHORT_BYTES
                plane.checkpoint('pons_cohort',checkpoint)
                domains=['pons:shared:'+digest('synthetic-provider')+':'+digest(['generation',n])+':receipt' for n in range(4)]
                value=canonical(dict(synthetic=True,padding='e'*256));proof=canonical(dict(authority='SYNTHETIC_NOT_QUALIFICATION'))
                with plane.transaction():
                    for ns in domains:
                        plane.db.executemany('INSERT INTO evidence VALUES(?,?,?,?,?)',((ns,
                            canonical(['eth_getTransactionReceipt','0x'+digest(['tx',n]),'0x'+digest(['block',n])]),
                            value,proof,float(n)) for n in range(8192)))
                attempts=Attempts(plane)
                while project(plane,pipeline,through=high_water(plane))==256:scratch.check()
                attempts.maintain(NOW);plane.maintain();pipeline.snapshot()
                before=retained(plane.db)
                counts={name:plane.db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0]
                    for name in ('candidates','transitions','observations')}
                assert counts==dict(candidates=1866,transitions=4096,observations=4096),counts
                assert len(plane._evidence_retention_cache)==4
                samples=[]
                for serial in (1,2):
                    sql=Counter();vm=[0];deadline=time.monotonic()+15
                    def trace(statement):
                        sql['all_statement_callbacks']+=1
                        if statement.startswith('SELECT COUNT(*) FROM evidence WHERE namespace='):sql['evidence_count']+=1
                        elif statement.startswith('DROP TRIGGER history_no_delete'):sql['transition_guard_drop']+=1
                        elif statement.startswith('DROP TRIGGER observations_no_delete'):sql['observation_guard_drop']+=1
                        elif statement.startswith('SELECT name,sql FROM sqlite_master'):sql['schema_validation']+=1
                        elif statement=='SELECT mm_native_audit_delete(NULL,NULL)':sql['audit_predicate_probe']+=1
                        elif statement in ('BEGIN IMMEDIATE','COMMIT','ROLLBACK'):sql[statement]+=1
                    def progress():
                        vm[0]+=1000;return int(time.monotonic()>deadline)
                    for db in (plane.db,peer.plane.db):db.set_trace_callback(trace);db.set_progress_handler(progress,1000)
                    start_schema=plane.db.execute('PRAGMA schema_version').fetchone()[0]
                    start_token=plane._evidence_retention_schema_version
                    before_io=io();wall=time.monotonic();cpu=time.thread_time()
                    try:
                        if mode=='checkpoint':peer.plane.checkpoint('synthetic_peer',dict(sequence=serial))
                        elif mode=='transition_ring':
                            with peer.plane.transaction():peer.plane._audit(peer.plane.get(owner.identity(event(1))),
                                'watching','synthetic_bounded_audit_pressure')
                        else:peer.enqueue(event(serial+1),now=NOW,needs_work=False)
                        peer_schema=plane.db.execute('PRAGMA schema_version').fetchone()[0]
                        peer_counts=dict(sql);peer_io=io();peer_wall=time.monotonic();peer_cpu=time.thread_time()
                        owner.report_to(pipeline);attempts.maintain(NOW);pipeline.snapshot()
                        assert next(owner.committed(),None) is None and owner.pop(now=NOW) is None
                        finish_io=io();finish_wall=time.monotonic();finish_cpu=time.thread_time()
                        end_schema=plane.db.execute('PRAGMA schema_version').fetchone()[0]
                    finally:
                        for db in (plane.db,peer.plane.db):db.set_trace_callback(None);db.set_progress_handler(None,0)
                    samples.append(dict(schema_before=start_schema,schema_after_peer=peer_schema,schema_after_turn=end_schema,
                        schema_token_before=start_token,schema_token_after=plane._evidence_retention_schema_version,
                        cached_namespaces_after=len(plane._evidence_retention_cache),sql_total=dict(sql),sql_peer=peer_counts,
                        sqlite_vm_steps_approx=vm[0],peer_wall_seconds=peer_wall-wall,peer_cpu_seconds=peer_cpu-cpu,
                        main_wall_seconds=finish_wall-peer_wall,main_cpu_seconds=finish_cpu-peer_cpu,
                        peer_io={k:peer_io[k]-before_io[k] for k in before_io},
                        main_io={k:finish_io[k]-peer_io[k] for k in before_io}))
                    scratch.check()
                after=retained(plane.db);assert before==after
                assert counts=={name:plane.db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in counts}
                result['cases'].append(dict(mode=mode,native_counts=counts,cohort_bytes=COHORT_BYTES,
                    namespaces=4,records_per_namespace=8192,body_padding_bytes=256,
                    native_cache_size=plane.db.execute('PRAGMA cache_size').fetchone()[0],
                    unchanged_evidence_obligations_and_revisions=before==after,retained=after,samples=samples))
                output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
            finally:peer.close();pipeline.close();owner.close()
        scratch.success=True


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output');run(parser.parse_args().output)
