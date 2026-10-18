"""Exact EA native cache-maintenance mechanism on bounded synthetic state.

Namespace population/key/body distributions and peer cadence are experiments,
not observations of the AWS database. No providers or financial DBs are opened.
The skip-evidence arm is a causal counterfactual, NOT a safe runtime repair.
"""
import argparse
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from engineering.diagnostics.pons_protected_cohort_cost import Probe
from engineering.diagnostics.pons_query_cost import fixture
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational.offline import install_network_guard
from meme_machine.runtime.robinhood.plane import Plane,canonical,digest
from meme_machine.runtime.robinhood.pons import Broker
from meme_machine.runtime.robinhood.accounting import high_water,project
from meme_machine.lanes.pons.pipeline import Pipeline
from meme_machine.lanes.pons.pons_attempts import Attempts
from unittest.mock import patch

EA='ea7221c3d858ffa8799cd02bfa83a576906f6c21'
COHORT_BYTES=4978487


def probe345(path,domains,records):
    """Original namespace/count SQL on the already retained3.45.1 RO adapter."""
    helper=Path('/workspace/recovery-evidence/pending_history_inventory_sqlite345.py')
    if hashlib.sha256(helper.read_bytes()).hexdigest()!='60373ba710a3357da2602934f99b139662acd64b3e5961ebe87c373df16d219b':
        raise ValueError('sqlite345_adapter_changed')
    spec=importlib.util.spec_from_file_location('pons_cache_capi',helper)
    capi=importlib.util.module_from_spec(spec);spec.loader.exec_module(capi)
    capi.Cursor.fetchone=lambda cursor:cursor.rows[0] if cursor.rows else None
    original=hashlib.sha256(path.read_bytes()).hexdigest();db=capi.Database(path);runs=[]
    def io():
        p=Path('/proc/self/task')/str(threading.get_native_id())/'io'
        return {k:int(v) for k,v in (line.split(':',1) for line in p.read_text().splitlines())}
    try:
        plan=db.execute('EXPLAIN QUERY PLAN SELECT COUNT(*) FROM evidence WHERE namespace=?',(domains[0],)).fetchall()
        code=db.execute('EXPLAIN SELECT COUNT(*) FROM evidence WHERE namespace=?',(domains[0],)).fetchall()
        assert not any(row[1]=='Count' for row in code)
        for cache in ('NEW_CONNECTION64K_NOT_OS_COLD','REUSED_CONNECTION64K_NOT_OS_COLD'):
            deadline=time.monotonic()+10;db.set_progress_handler(lambda:time.monotonic()>deadline,1000)
            start=len(db.queries);before=io();wall=time.monotonic();cpu=time.thread_time()
            db.execute('BEGIN')
            try:
                found=Plane.evidence_namespaces(SimpleNamespace(db=db))
                assert set(found)==set(domains)
                assert all(db.execute('SELECT COUNT(*) FROM evidence WHERE namespace=?',(ns,)).fetchone()[0]==records for ns in found)
            finally:db.execute('ROLLBACK')
            after=io();queries=db.queries[start:]
            runs.append(dict(cache_scope=cache,wall_seconds=time.monotonic()-wall,cpu_seconds=time.thread_time()-cpu,
                rchar=after['rchar']-before['rchar'],syscr=after['syscr']-before['syscr'],
                vm_steps=sum(q['vm_steps'] for q in queries),sorts=sum(q['sorts'] for q in queries),
                returned_rows=sum(q['rows'] for q in queries),statements=len(queries)))
        assert not db.in_transaction
    finally:db.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==original
    return dict(version=capi.version,library_sha256=hashlib.sha256(capi.LIBRARY.read_bytes()).hexdigest(),
        adapter_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),count_plan=[r[3] for r in plan],
        count_opcodes=[r[1] for r in code],runs=runs,readonly_file_hash_unchanged=True,
        scope='ACTUAL3_45_CAPI_ORIGINAL_FIXED_NAMESPACE_SQL_NOT_PRODUCTION_PYTHON_EXTENSION')


def revision345(path,namespace):
    """Actual candidate trigger SQL on3.45, all mutations rolled back."""
    helper=Path('/workspace/recovery-evidence/pending_history_inventory_sqlite345.py')
    spec=importlib.util.spec_from_file_location('pons_revision_capi',helper)
    capi=importlib.util.module_from_spec(spec);spec.loader.exec_module(capi)
    capi.Cursor.fetchone=lambda cursor:cursor.rows[0] if cursor.rows else None
    capi.Cursor.__iter__=lambda cursor:iter(cursor.rows)
    db=capi.Database.__new__(capi.Database)
    db.db=capi.P();db.callback=None;db.on_progress=None;db.queries=[]
    assert capi.opendb(os.fsencode(path),capi.ctypes.byref(db.db),2,None)==0
    owner=SimpleNamespace(db=db,_evidence_retention_cache=OrderedDict(),_evidence_retention_schema_version=None)
    before=hashlib.sha256(path.read_bytes()).hexdigest();read=lambda:db.execute(
        'SELECT generation FROM evidence_retention_revision WHERE namespace=?',(namespace,)).fetchone()[0]
    try:
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA cache_size=-64')
        initial=read();steps=[];db.execute('BEGIN IMMEDIATE')
        for sql,args,delta in (
            ('INSERT INTO evidence VALUES(?,?,?,?,?)',(namespace,'synthetic-new','{}','{}',1000000.),1),
            ('UPDATE evidence SET created=created+1 WHERE namespace=? AND key=?',(namespace,'synthetic-new'),2),
            ('INSERT INTO receipt_obligations VALUES(?,?,?,?,?)',(namespace,'synthetic-new','current','fixture','g'),1),
            ('UPDATE receipt_obligations SET generation=? WHERE namespace=? AND key=?',('g2',namespace,'synthetic-new'),2),
            ('DELETE FROM receipt_obligations WHERE namespace=? AND key=?',(namespace,'synthetic-new'),1),
            ('DELETE FROM evidence WHERE namespace=? AND key=?',(namespace,'synthetic-new'),1)):
            previous=read();db.execute(sql,args);assert read()==previous+delta
            steps.append(dict(statement_kind=sql.split()[0],generation_delta=delta))
        assert Plane._evidence_retention_schema(owner) is not None
        db.execute('ROLLBACK');assert read()==initial and not db.in_transaction
        assert Plane._evidence_retention_revision(owner,namespace)==initial
        return dict(version=capi.version,mutations=steps,rollback_revision_restored=True,
            exact_relevant_schema_validated=True,scope='SYNTHETIC_CAPI_MUTATION_ROLLBACK_NOT_NATIVE_PYTHON_EXTENSION')
    finally:
        if db.in_transaction:db.execute('ROLLBACK')
        assert capi.closedb(db.db)==0
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before


@contextmanager
def skip_unchanged_evidence(plane):
    original=plane.evidence_namespaces
    plane.evidence_namespaces=lambda:()
    try:yield
    finally:plane.evidence_namespaces=original


def run(output,repeat=3,candidate_plane_sha256=None,publication_only=False):
    if sys.version_info[:3]!=(3,12,14) or not 1<=repeat<=6:raise ValueError('pinned_or_bound')
    install_network_guard();sys.dont_write_bytecode=True;output=Path(output).resolve()
    paths=('meme_machine/runtime/robinhood/plane.py','meme_machine/runtime/robinhood/pons.py',
           'meme_machine/runtime/robinhood/accounting.py','meme_machine/lanes/pons/pons_attempts.py')
    for path in paths:
        expected=subprocess.check_output(['git','show',EA+':'+path])
        if Path(path).read_bytes()!=expected and not (path==paths[0] and candidate_plane_sha256 is not None
                and hashlib.sha256(Path(path).read_bytes()).hexdigest()==candidate_plane_sha256):
            raise ValueError('exact_ea_runtime_required')
    result=dict(schema='pons-evidence-maintenance-cost-v1',exact_runtime=EA if candidate_plane_sha256 is None else 'EXPLICIT_PLANE_CANDIDATE',
        predecessor_runtime=EA,candidate_plane_sha256=candidate_plane_sha256,sqlite_version=sqlite3.sqlite_version,
        source_hashes={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='SYNTHETIC_NAMESPACE_GEOMETRY_NATIVE_MAIN_TURN_NOT_AWS_ATTRIBUTION',
        actual_aws_namespace_cardinality='UNAVAILABLE',actual_aws_namespace_key_body_widths='UNAVAILABLE',
        counterfactual_contract='SKIP_EVIDENCE_CENSUS_ONLY_WHEN_FIXTURE_PROVES_NO_EVIDENCE_OR_OBLIGATION_CHANGE_NOT_A_RUNTIME_FIX',
        provider_requests=0,financial_authority=False,production_state_copied=False,cases=[])
    with Scratch() as scratch:
        def audit(event,args):
            if event=='sqlite3.connect':
                target=Path(os.fsdecode(args[0]).removeprefix('file:').split('?',1)[0]).resolve()
                if not target.is_relative_to(scratch.path):raise RuntimeError('foreign_database_forbidden')
            if event=='open' and not isinstance(args[0],int) and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):
                target=Path(os.fsdecode(args[0])).resolve()
                if target!=output and not target.is_relative_to(scratch.path):raise RuntimeError('foreign_write_forbidden')
        sys.addaudithook(audit)
        with patch.dict(os.environ,dict(MM_MODE='PAPER',MM_OPERATIONAL_PHASE='OFFLINE_COST'),clear=True):
            cases=() if publication_only else ((1,4096,256,False),(4,8192,256,False),(4,8193,256,True),(4,8192,4096,False))
            for case_index,(namespaces,records,body_bytes,pinned) in enumerate(cases):
                path=scratch.path/('plane-'+str(case_index)+'.sqlite');now=[100001.]
                broker=Broker(path,'synthetic-offline-policy',clock=lambda:now[0]);plane=broker.plane
                seeded=fixture(path,1849,4096,768,0);seeded.close()
                with plane.transaction():
                    plane.db.execute('UPDATE candidates SET pending=0,observed=?,interpretation=?',
                        (now[0]-90000,canonical(broker.policy)))
                keys=[r[0] for r in plane.db.execute('SELECT id FROM candidates ORDER BY id')]
                payload=dict(qualifiers=[dict(curve=k.rsplit(':',1)[-1]) for k in keys],lifecycles=[],padding='')
                checkpoint=dict(result=payload)
                payload['padding']='x'*(COHORT_BYTES-len(canonical(checkpoint).encode()))
                assert len(canonical(checkpoint).encode())==COHORT_BYTES
                plane.checkpoint('pons_cohort',checkpoint)
                domains=['pons:shared:'+digest('synthetic-provider')+':'+digest(['generation',i])+':receipt' for i in range(namespaces)]
                body=canonical(dict(synthetic=True,padding='e'*body_bytes));proof=canonical(dict(authority='SYNTHETIC_NOT_QUALIFICATION'))
                with plane.transaction():
                    for namespace in domains:
                        for i in range(records):
                            key=canonical(['eth_getTransactionReceipt','0x'+digest(['tx',i]),'0x'+digest(['block',i])])
                            plane.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(namespace,key,body,proof,float(i)))
                            if pinned and i==0:
                                plane.db.execute('INSERT INTO receipt_obligations VALUES(?,?,?,?,?)',
                                    (namespace,key,'survivor','synthetic-native-owner',digest('unresolved-original-receipt')))
                scratch.check();peer=Plane(path,clock=lambda:now[0]);pipeline=Pipeline(scratch.path/('pipeline-'+str(case_index)+'.sqlite'),'pons','synthetic-offline-policy')
                attempts=Attempts(plane);probe=Probe();sequence=[0]
                try:
                    while project(plane,pipeline,through=high_water(plane))==256:scratch.check()
                    attempts.maintain(now[0]);plane.maintain();pipeline.snapshot()
                    expected=[tuple(r) for r in plane.db.execute('SELECT namespace,bytes,records FROM receipt_cache_usage ORDER BY namespace')]
                    before=digest([list(r) for r in plane.db.execute('SELECT id,generation,state,pending FROM candidates ORDER BY id')])
                    for db in (plane.db,pipeline.db):probe.attach(db)
                    def peer_write():
                        sequence[0]+=1;peer.checkpoint('synthetic_unrelated_peer_checkpoint',dict(sequence=sequence[0]))
                    def turn():
                        broker.report_to(pipeline);attempts.maintain(now[0]);pipeline.snapshot()
                        if next(broker.committed(),None) is not None or broker.pop(now=now[0]) is not None:
                            raise ValueError('unexpected_economic_work')
                    def census():
                        for ns in plane.evidence_namespaces():
                            plane.db.execute('SELECT COUNT(*) FROM evidence WHERE namespace=?',(ns,)).fetchone()
                    case=dict(namespaces=namespaces,records_per_namespace=records,body_padding_bytes=body_bytes,
                        oldest_overlimit_receipt_protected=pinned,cohort_bytes=COHORT_BYTES,candidates=1849,
                        database_bytes=path.stat().st_size,page_size=plane.db.execute('PRAGMA page_size').fetchone()[0],
                        cache_size=plane.db.execute('PRAGMA cache_size').fetchone()[0],
                        count_plan=[r[3] for r in plane.db.execute('EXPLAIN QUERY PLAN SELECT COUNT(*) FROM evidence WHERE namespace=?',(domains[0],))],
                        measurements=[])
                    for traced in (False,True):
                        for label,call,prepare in (('native_turn_unchanged',turn,None),
                            ('native_turn_peer_commit',turn,peer_write),('maintain_peer_commit',plane.maintain,peer_write),
                            ('namespace_census_only',census,None)):
                            case['measurements'].append(probe.measure(label,call,repeat=repeat,prepare=prepare,traced=traced));scratch.check()
                        with skip_unchanged_evidence(plane):
                            case['measurements'].append(probe.measure('native_turn_peer_skip_unchanged_evidence_COUNTERFACTUAL',turn,
                                repeat=repeat,prepare=peer_write,traced=traced));scratch.check()
                    assert expected==[tuple(r) for r in plane.db.execute('SELECT namespace,bytes,records FROM receipt_cache_usage ORDER BY namespace')]
                    assert before==digest([list(r) for r in plane.db.execute('SELECT id,generation,state,pending FROM candidates ORDER BY id')])
                    assert all(plane.db.execute('SELECT COUNT(*) FROM evidence WHERE namespace=?',(ns,)).fetchone()[0]==records for ns in domains)
                    assert plane.db.execute('SELECT COUNT(*) FROM receipt_obligations').fetchone()[0]==(namespaces if pinned else 0)
                    case.update(native_candidate_rows_unchanged=True,evidence_and_usage_unchanged=True,receipt_obligations_preserved=True)
                    result['cases'].append(case);output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
                finally:peer.close();pipeline.close();broker.close()
                case['sqlite345']=probe345(path,domains,records)
                if candidate_plane_sha256 is not None:case['sqlite345_revision']=revision345(path,domains[0])
                output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
                scratch.check()
            if publication_only:
                if candidate_plane_sha256 is None:raise ValueError('explicit_candidate_required')
                from meme_machine.runtime.robinhood.plane import _EVIDENCE_RETENTION_SCHEMA
                result['publication_overhead']=[];logical=[]
                for revisions in (False,True):
                    plane=Plane(scratch.path/('publication-'+str(revisions)+'.sqlite'),clock=lambda:100.)
                    try:
                        if not revisions:
                            for name in _EVIDENCE_RETENTION_SCHEMA:
                                if name!='evidence_retention_revision':plane.db.execute('DROP TRIGGER '+name)
                            plane.db.execute('DROP TABLE evidence_retention_revision')
                        ns='pons:shared:synthetic:receipt';scope=('current','synthetic-owner','0'*64)
                        def publish():
                            for i in range(128):
                                assert plane.put_receipt(ns,str(i),dict(synthetic=True,padding='e'*512),
                                    dict(authority='SYNTHETIC_NOT_QUALIFICATION'),scope)
                        probe=Probe()
                        publication=probe.measure('128_native_put_receipt_calls',publish,repeat=1)
                        acknowledgement=probe.measure('original_receipt_scope_ack',lambda:plane.receipt_scope(ns,*scope,acknowledge=True),repeat=1)
                        rows=[list(row) for row in plane.db.execute('SELECT * FROM evidence ORDER BY namespace,key')]
                        usage=[list(row) for row in plane.db.execute('SELECT * FROM receipt_cache_usage ORDER BY namespace')]
                        assert not plane.db.execute('SELECT 1 FROM receipt_obligations').fetchone()
                        logical.append(digest([rows,usage]))
                        result['publication_overhead'].append(dict(revision_triggers=revisions,
                            publication=publication,acknowledgement=acknowledgement,native_rows_sha256=logical[-1]))
                    finally:plane.close()
                assert logical[0]==logical[1]
                result['publication_overhead_contract']='IDENTICAL_NATIVE_PUT_RECEIPT_AND_SCOPE_ACK_128_SYNTHETIC_FACTS_512B_BODY_NOT_AWS_WRITE_ATTRIBUTION'
                output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
        scratch.success=True


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output');parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--candidate-plane-sha256')
    parser.add_argument('--publication-overhead-only',action='store_true')
    args=parser.parse_args();run(args.output,args.repeat,args.candidate_plane_sha256,args.publication_overhead_only)
