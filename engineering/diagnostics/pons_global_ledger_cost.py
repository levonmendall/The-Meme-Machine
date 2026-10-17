"""Bounded synthetic large-ledger discriminator at the exact selected source.

Uses temporary native financial replay and provider storage only. It does not
copy an epoch, contact providers, model arrivals or establish AWS attribution.
"""
from contextlib import ExitStack, closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from unittest.mock import patch

from meme_machine.operational.artifact_storage import Scratch
from meme_machine.operational.offline import install_network_guard
from meme_machine.operational.bounded_provider import Budget
from meme_machine.shared_capital.runtime import RuntimeCapital
from tests.test_pump_pons_capital_preparation import RuntimeIntegrationTests
from tests.test_provider_clock_domain import identity


class Probe:
    def __init__(self):
        self.rows={};self.active=False;self.current={};self.deadline=0
        self.truncated=False
        self.original=sqlite3.connect
    def connect(self,*args,**kwargs):
        db=self.original(*args,**kwargs)
        self.attach(db)
        return db
    def attach(self,db):
        key=id(db)
        def trace(sql):
            if not self.active:return
            shape=re.sub(r"'(?:''|[^'])*'",'?',sql)
            shape=re.sub(r'\b\d+(?:\.\d+)?\b','?',shape)
            if shape not in self.rows:
                if len(self.rows)>=96:
                    self.truncated=True;self.current[key]=None
                    return
                self.rows[shape]=dict(sql=shape,calls=0,vm_steps_approx=0)
            self.rows[shape]['calls']+=1;self.current[key]=shape
        def progress():
            if not self.active:return 0
            shape=self.current.get(key)
            if shape in self.rows:self.rows[shape]['vm_steps_approx']+=1000
            return int(time.monotonic()>self.deadline)
        db.set_trace_callback(trace);db.set_progress_handler(progress,1000)
    def measure(self,name,call,*,repeat=2):
        self.rows={};self.current={};self.truncated=False;self.deadline=time.monotonic()+20
        def io():
            return {k:int(v) for k,v in (line.split(':') for line in Path('/proc/self/io').read_text().splitlines())}
        before=io();started=time.monotonic();cpu=time.thread_time();self.active=True
        try:
            for _ in range(repeat):call()
        finally:self.active=False
        ended=time.monotonic();after=io()
        result=dict(operation=name,repeat=repeat,wall_seconds=ended-started,
            thread_cpu_seconds=time.thread_time()-cpu,
            process_io_delta={k:after[k]-before[k] for k in before},
            statements=sum(v['calls'] for v in self.rows.values()),
            query_shape_census_complete=not self.truncated,
            sqlite_vm_steps_approx=sum(v['vm_steps_approx'] for v in self.rows.values()),
            sql_shapes=sorted(self.rows.values(),key=lambda r:r['vm_steps_approx'],reverse=True))
        print(json.dumps({k:v for k,v in result.items() if k!='sql_shapes'},sort_keys=True),flush=True)
        return result


def run(output, *, journal_rows=15857, closed_receipts=120791):
    if sys.version_info[:3]!=(3,12,14):raise ValueError('pinned_python_required')
    if not 1<=journal_rows<=20000 or not 0<=closed_receipts<=150000:
        raise ValueError('synthetic_fixture_bound')
    install_network_guard()
    output=Path(output).resolve()
    with Scratch() as scratch,ExitStack() as stack:
        def audit(event,args):
            if event=='sqlite3.connect':
                value=os.fsdecode(args[0]).removeprefix('file:').split('?',1)[0]
                if not Path(value).resolve().is_relative_to(scratch.path):
                    raise RuntimeError('foreign_database_forbidden')
            if event=='open' and not isinstance(args[0],int) and args[2]&(
                    os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):
                value=Path(os.fsdecode(args[0])).resolve()
                if value!=output and not value.is_relative_to(scratch.path):
                    raise RuntimeError('foreign_write_forbidden')
        sys.addaudithook(audit)
        stack.enter_context(patch.dict(os.environ,{'MM_MODE':'PAPER',
            'MM_OPERATIONAL_PHASE':'OFFLINE_COST'},clear=True))
        stack.enter_context(patch('meme_machine.runtime.provider_clock.current_identity',return_value=identity()))
        fixture=RuntimeIntegrationTests('runTest');stack.callback(fixture.doCleanups)
        root,authority,now,plan=fixture.fixture(owners=False,new_epoch=True)
        def close_native_pool():
            from meme_machine.shared_capital.runtime import _LOCAL
            pool=getattr(_LOCAL,'pool',{})
            for key,(_inode,value) in list(pool.items()):
                if Path(key).is_relative_to(root):
                    value.close();del pool[key]
        stack.callback(close_native_pool)
        seed_started=time.monotonic()
        # Genuine native reducer/journal transitions, no reservations, grants,
        # positions, fills or settlements. This is a synthetic action mix.
        for n in range(journal_rows-1):
            if n%32==0:
                authority.command('offline-publish-'+str(n),'runtime_publish',{},now+n)
            else:
                authority.command('offline-owner-'+str(n),'runtime_owner',dict(
                    regime='pons_current',token='offline-owner-'+str(n%4),
                    pid=os.getpid(),start='offline-not-a-live-manifest',ready=False),now+n)
            if n%1024==0:
                scratch.check()
                print(json.dumps(dict(seeded=n+1,elapsed=time.monotonic()-seed_started)),flush=True)
        state=authority.ledger()
        if any(state.get(k) for k in ('positions','reservations','commitments','obligations',
                'pending_deliveries','runtime_pending','runtime_inbox')):
            raise ValueError('synthetic_financial_state_not_flat')
        # Seed only closed storage-shape rows, not fictitious physical billing.
        # Actual invocation below uses original orphan query and fixed config.
        path=root/'provider.sqlite'
        profile=json.loads((Path(__file__).resolve().parents[2]/
            'operational/pump-first-release/deployment/paper-continuous.four-regime.json').read_text())
        budget=Budget.create(path,continuous=profile)
        with closing(budget.db()) as db:
            db.execute('BEGIN IMMEDIATE')
            db.executemany('INSERT INTO http_receipts VALUES(?,0,1,?)',
                (('offline-closed-'+str(n),json.dumps(dict(synthetic=True,pid=0,start='0')))
                 for n in range(closed_receipts)))
            db.executemany('INSERT INTO streams VALUES(?,0,1)',
                (('offline-stream-'+str(n),) for n in range(387)))
            db.executemany('INSERT INTO run VALUES(?,?)',
                (('stream_owner.offline-stream-'+str(n),json.dumps(dict(synthetic=True,pid=0,start='0')))
                 for n in range(387)))
            db.execute('COMMIT')
        result=dict(schema='pons-global-ledger-cost-v1',source_commit=subprocess.check_output(
                ['git','rev-parse','HEAD'],text=True).strip(),
            benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            scope='SYNTHETIC_LARGE_NATIVE_LEDGERS_NOT_AWS_POPULATION_OR_FULL_LOOP',
            financial_authority=False,provider_requests=0,production_state_copied=False,
            python=sys.version,sqlite=sqlite3.sqlite_version,
            fixture=dict(global_journal_rows=authority.db.execute('SELECT COUNT(*) FROM shared_capital_events').fetchone()[0],
                global_journal_bytes=authority.db.execute('SELECT SUM(length(body)+length(result)) FROM shared_capital_events').fetchone()[0],
                global_projection_bytes=authority.db.execute('SELECT length(body) FROM shared_capital_projection WHERE id=1').fetchone()[0],
                reporting_history_rows=len(state.get('reporting_history',[])),closed_http_storage_rows=closed_receipts,
                provider_operating_mode='CONTINUOUS',synthetic_closed_stream_rows=387,
                global_seed_seconds=time.monotonic()-seed_started),measurements=[])
        probe=Probe();probe.attach(authority.db)
        stack.enter_context(patch('sqlite3.connect',probe.connect))
        def record(name,call,repeat=2):
            result['measurements'].append(probe.measure(name,call,repeat=repeat))
            output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');scratch.check()
        record('RuntimeCapital.ledger existing connection',authority.ledger,8)
        record('RuntimeCapital.snapshot existing connection',authority.snapshot,4)
        record('RuntimeCapital.verify_replay zero-prefix authentication plus full reduction',authority.verify_replay,1)
        def reopen():
            with closing(RuntimeCapital(root/'shared-capital.sqlite')) as value:value.ledger()
        record('RuntimeCapital new verified connection',reopen,2)
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        stack.enter_context(patch.object(cohort,'ROOT',root/'pons-current'))
        stack.enter_context(patch.dict(os.environ,dict(MM_DIRECTIONAL_SLEEVE_DB=str(root/'pons/directional-sleeve.sqlite'),
            MM_PAPER_EPOCH=state['epoch_id'])))
        record('Actual Current native sizing first call',cohort._current_pons_realized_equity,1)
        record('Actual Current native sizing same owner',cohort._current_pons_realized_equity,4)
        record('Actual Current cohort accounting constructors',cohort._cohort_accounting,4)
        record('Budget constructor plus snapshot',lambda:Budget(path).snapshot(),4)
        record('Budget.reap_orphans closed lifetime receipts',budget.reap_orphans,4)
        record('Budget.admission same ledgers',budget.admission,4)
        after=authority.ledger()
        if after!=state:raise ValueError('financial_benchmark_mutated_state')
        result['financial_projection_unchanged']=True
        result['final_native_full_replay']=authority.verify_replay()
        output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
        scratch.success=True
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output')
    parser.add_argument('--journal-rows',type=int,default=15857)
    parser.add_argument('--closed-receipts',type=int,default=120791)
    args=parser.parse_args();run(args.output,journal_rows=args.journal_rows,closed_receipts=args.closed_receipts)
