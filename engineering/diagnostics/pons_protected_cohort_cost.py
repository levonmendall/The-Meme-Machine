"""Exact native local-turn costs with a synthetic wide retained protection input.

No providers, portfolio, epoch, economic ACKs or production state. Geometry is
matched; payload distribution and peer cadence remain explicitly synthetic.
"""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from engineering.diagnostics.pons_query_cost import fixture
from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational.offline import install_network_guard
from meme_machine.runtime.robinhood.accounting import high_water, project
from meme_machine.runtime.robinhood.plane import Plane, canonical
from meme_machine.runtime.robinhood.pons import Broker, save_cohort_checkpoint
from meme_machine.lanes.pons.pipeline import Pipeline
from meme_machine.lanes.pons.pons_attempts import Attempts

COHORT_BYTES=4932009
GEOMETRY_BYTES=355524608


class Probe:
    def __init__(self):
        self.original=sqlite3.connect;self.connections=[];self.active=False;self.rows={};self.deadline=0

    def attach(self,db):
        self.connections.append(db)
        def trace(sql):
            if not self.active:return
            # Trace expansion itself costs CPU/allocations; the separate untraced
            # measurements below expose that limitation. No values are retained.
            shape=re.sub(r"'(?:''|[^'])*'",'?',sql)
            shape=re.sub(r'\b\d+(?:\.\d+)?\b','?',shape)
            if len(shape)>8192:shape='BOUNDED_SCHEMA_SCRIPT'
            if shape not in self.rows and len(self.rows)>=128:raise ValueError('query_shape_bound')
            self.rows[shape]=self.rows.get(shape,0)+1
        def progress():return int(self.active and time.monotonic()>self.deadline)
        db.set_trace_callback(trace);db.set_progress_handler(progress,10000)

    def connect(self,*args,**kwargs):
        db=self.original(*args,**kwargs);self.attach(db);return db

    def measure(self,label,call,*,repeat=4,prepare=None,traced=False):
        def io():
            path=Path('/proc/self/task')/str(threading.get_native_id())/'io'
            return {key:int(value) for key,value in (line.split(':',1) for line in path.read_text().splitlines())}
        samples=[];self.rows={}
        for _ in range(repeat):
            if prepare is not None:prepare()
            self.deadline=time.monotonic()+20;self.active=traced
            before=io();wall=time.monotonic();cpu=time.thread_time()
            try:call()
            finally:
                used_wall=time.monotonic()-wall;used_cpu=time.thread_time()-cpu;after=io();self.active=False
            samples.append(dict(wall_seconds=used_wall,cpu_seconds=used_cpu,
                io={key:after[key]-before[key] for key in before}))
        result=dict(operation=label,repeat=repeat,traced=traced,
            wall_seconds=sum(row['wall_seconds'] for row in samples),
            cpu_seconds=sum(row['cpu_seconds'] for row in samples),
            thread_io_delta={key:sum(row['io'][key] for row in samples) for key in samples[0]['io']},
            sql_calls=sum(self.rows.values()) if traced else None,
            sql_shapes=[dict(sql=sql,calls=count) for sql,count in sorted(self.rows.items())] if traced else None)
        result['rchar_each']=result['thread_io_delta']['rchar']/repeat
        print(json.dumps({key:value for key,value in result.items() if key!='sql_shapes'}),flush=True)
        return result


def run(output,*,geometry_bytes=GEOMETRY_BYTES,repeat=4):
    if sys.version_info[:3]!=(3,12,14):raise ValueError('pinned_python_required')
    if not 16*1024**2<=geometry_bytes<=384*1024**2 or not 1<=repeat<=8:raise ValueError('fixture_bound')
    sys.dont_write_bytecode=True
    install_network_guard();output=Path(output).resolve();probe=Probe()
    with Scratch() as scratch:
        def audit(event,args):
            if event=='sqlite3.connect':
                path=Path(os.fsdecode(args[0]).removeprefix('file:').split('?',1)[0]).resolve()
                if not path.is_relative_to(scratch.path):raise RuntimeError('foreign_database_forbidden')
            if event=='open' and not isinstance(args[0],int) and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):
                path=Path(os.fsdecode(args[0])).resolve()
                if path!=output and not path.is_relative_to(scratch.path):raise RuntimeError('foreign_write_forbidden')
        sys.addaudithook(audit)
        with patch.dict(os.environ,dict(MM_MODE='PAPER',MM_OPERATIONAL_PHASE='OFFLINE_COST'),clear=True):
            now=[100001.];path=scratch.path/'plane.sqlite'
            broker=Broker(path,'synthetic-offline-policy',clock=lambda:now[0]);plane=broker.plane
            populated=fixture(path,1696,4096,768,0);populated.close()
            with plane.transaction():
                plane.db.execute('UPDATE candidates SET pending=0,observed=?,interpretation=?',
                    (now[0]-90000,canonical(broker.policy)))
            protected=[row[0] for row in plane.db.execute('SELECT id FROM candidates ORDER BY id')]
            native_result=dict(candidate_plane_path=str(path),rows=[],qualifiers=[dict(curve=key.rsplit(':',1)[-1])
                for key in protected],lifecycles=[],discovery_sessions=[],sequencer_recoveries=[],synthetic_padding='')
            checkpoint=dict(result=native_result,cursor=0,phase='synthetic',owner='SYNTHETIC',checkpoint_at=now[0])
            native_result['synthetic_padding']='x'*(COHORT_BYTES-len(canonical(checkpoint).encode()))
            plane.checkpoint('pons_cohort',checkpoint)
            if len(canonical(checkpoint).encode())!=COHORT_BYTES:raise ValueError('cohort_width')
            # Populate only nonfinancial native evidence rows within each
            # namespace's original4096-record retention bound. This is a size
            # model, not purported authenticated market evidence.
            padding=canonical(dict(synthetic=True,padding='e'*65536));number=0
            while plane.db.execute('PRAGMA page_count').fetchone()[0]*4096<geometry_bytes:
                with plane.transaction():
                    for _ in range(64):
                        plane.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',
                            ('pons:synthetic-size:'+str(number//4096),str(number),padding,
                             canonical(dict(authority='SYNTHETIC_NOT_QUALIFICATION')),now[0]))
                        number+=1
                scratch.check()
            peer=Plane(path,clock=lambda:now[0]);pipeline=Pipeline(scratch.path/'pipeline.sqlite','pons','synthetic-offline-policy')
            attempts=Attempts(plane)
            try:
                while project(plane,pipeline,through=high_water(plane))==256:scratch.check()
                attempts.maintain(now[0]);plane.maintain();pipeline.snapshot()
                before=[row[0] for row in plane.db.execute('SELECT id FROM candidates ORDER BY id')]
                for db in (plane.db,pipeline.db):probe.attach(db)
                result=dict(schema='pons-protected-cohort-cost-v1',source_commit=subprocess.check_output(
                    ['git','rev-parse','HEAD'],text=True).strip(),
                    benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    runtime_sha256={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (
                        'meme_machine/runtime/robinhood/plane.py','meme_machine/runtime/robinhood/pons.py',
                        'meme_machine/lanes/pons/pons_selective_cohort.py')},
                    scope='ORIGINAL_NATIVE_LOCAL_CALLS_SYNTHETIC_PROTECTED_POPULATION_NOT_FULL_MARKET_OR_AWS_ATTRIBUTION',
                    provider_requests=0,financial_authority=False,production_state_copied=False,
                    fixture=dict(candidates=1696,old_protected_candidates=len(before),transitions=4096,observations=4096,
                        cohort_bytes=COHORT_BYTES,database_bytes=plane.db.execute('PRAGMA page_count').fetchone()[0]*4096,
                        requested_geometry_bytes=geometry_bytes,evidence_rows=number,
                        retained_attempt_rows=0,retained_attempt_population_unexercised=True),measurements=[])
                serial=[0]
                def mutate():
                    serial[0]+=1;peer.checkpoint('synthetic_unrelated_survivor_checkpoint',dict(sequence=serial[0]))
                def coverage():
                    broker.report_to(pipeline);attempts.maintain(now[0]);pipeline.snapshot()
                def turn():
                    coverage()
                    if next(broker.committed(),None) is not None or broker.pop(now=now[0]) is not None:
                        raise ValueError('unexpected_economic_work')
                with patch('sqlite3.connect',probe.connect):
                    for traced in (False,True):
                        for label,call,prepare in (
                            ('local_turn_unchanged',turn,None),('local_turn_peer_commit',turn,mutate),
                            ('maintain_peer_commit',plane.maintain,mutate),
                            ('checkpoint_fresh_plane',lambda:save_cohort_checkpoint(native_result,0,'synthetic'),None),
                            ('checkpoint_owned_plane',lambda:save_cohort_checkpoint(native_result,0,'synthetic',plane=plane),None)):
                            result['measurements'].append(probe.measure(label,call,repeat=repeat,
                                prepare=prepare,traced=traced));scratch.check()
                            output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
                after=[row[0] for row in plane.db.execute('SELECT id FROM candidates ORDER BY id')]
                if before!=after:raise ValueError('protection_membership_changed')
                result['protection_membership_sha256']=hashlib.sha256(canonical(after).encode()).hexdigest()
                result['protected_candidates_unchanged']=True
                output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');scratch.success=True
            finally:
                peer.close();pipeline.close();broker.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output')
    parser.add_argument('--geometry-bytes',type=int,default=GEOMETRY_BYTES)
    parser.add_argument('--repeat',type=int,default=4)
    args=parser.parse_args();run(args.output,geometry_bytes=args.geometry_bytes,repeat=args.repeat)
