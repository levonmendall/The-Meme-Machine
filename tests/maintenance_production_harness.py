"""Deterministic clocks/work completions around the ACTUAL serve() entrypoint.

No fabricated Need/Observation or replacement of SQLite mutators. The isolated
transport is provider-free; the worker calls the native immutable archiver. Tests
may inject faults explicitly, and all successful SQL mutations remain native.
"""
from __future__ import annotations
import asyncio
from concurrent.futures import Future
from contextlib import ExitStack, closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from meme_machine import solana_evidence_service as service
from meme_machine import solana_maintenance_runtime as production
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceWriter
from tests.test_run381_retention_progress import record
from tests.evidence_ipc_harness import ipc_transport

SCOPES=('program:meteora','program:pump','program:pumpswap')
ENDPOINT='https://solana-mainnet.g.alchemy.com/v2/offline-test'


class Clock:
    def __init__(self):
        self.epoch=1_800_000_000.0;self.value=0.0;self.lock=threading.Lock()
    def monotonic(self):
        with self.lock:return self.value
    def time(self):return self.epoch+self.monotonic()
    def advance(self,value):
        with self.lock:self.value+=value
    sleep=staticmethod(__import__('time').sleep)


def rows(clock,scope,n,*,start=1000,age=185.0,tag='hot',same_slot=False):
    return [replace(record(),scope=scope,identity=f'{scope}:{tag}:{start+i}',
        signature=f'{scope}:{tag}:{start+i}',slot=start if same_slot else start+i,
        market_time=int(clock.time()-age),observed_at=clock.time()) for i in range(n)]


def ingest(writer,values):
    for start in range(0,len(values),1000):writer.ingest(values[start:start+1000])


def seed_book(state,clock,hot=(1000,1000,1000),retired=(0,0,0),*,same_slot=False):
    w=state.writer;w.clock=clock.time
    for scope,n in zip(SCOPES,retired):
        ingest(w,rows(clock,scope,n,start=100,tag='old',same_slot=True))
    while w.archive(clock.time()-180):pass
    for scope,n in zip(SCOPES,hot):
        ingest(w,rows(clock,scope,n,start=1000,tag='hot',same_slot=same_slot))
        # Authenticated source-time input with real native record validation, not
        # a synthetic arbiter recovery deadline. The live fixture also receives
        # empty finalized blocks through the real source pipeline.
        ingest(w,rows(clock,scope,1,start=1_000_000,age=0,tag='frontier'))
        sub=next(s for s in service.program_subscriptions()
                 if s.scope==scope and s.evidence_class in ('census','transactions'))
        state.fence.block(sub,dict(params=dict(result=dict(value=dict(slot=1_000_001,
            err=None,block=dict(parentSlot=1_000_000,blockhash='seed-frontier',
                previousBlockhash='seed-parent',blockTime=int(clock.time()),
                transactions=[]))))),clock.time())


class Wire:
    def __init__(self,clock):self.clock=clock;self.acks=asyncio.Queue();self.slot=2_000_000
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def send(self,raw):
        request=json.loads(raw)
        await self.acks.put(json.dumps(dict(id=request['id'],result=request['id'])).encode())
    async def recv(self,decode=None):
        if not self.acks.empty():return await self.acks.get()
        await asyncio.sleep(.005)
        slot=self.slot;self.slot+=1
        return json.dumps(dict(method='blockNotification',params=dict(subscription=1,
            result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,
            blockhash=f'h{slot}',previousBlockhash=f'h{slot-1}',blockTime=int(self.clock.time()),
            transactions=[])))))).encode()


class NativeCompletionPool:
    def __init__(self,*args,**kwargs):
        self.submissions=[];self.max_inflight=0;self.inflight=0
    def submit(self,fn,*args,**kwargs):
        future=Future()
        if fn is EvidenceWriter.prepare_and_write_archive:
            self.submissions.append(args[1]);self.inflight+=1
            self.max_inflight=max(self.max_inflight,self.inflight)
        try:future.set_result(fn(*args,**kwargs))
        except BaseException as exc:future.set_exception(exc)
        finally:
            if fn is EvidenceWriter.prepare_and_write_archive:self.inflight-=1
        return future
    def shutdown(self,*args,**kwargs):pass


async def run_case(*,seed=None,before=None,after=None,turns=32,
                   archive_hook=None,retention_hook=None,pool_class=NativeCompletionPool,
                   clock=None,path=None):
    """Return actual state/outcomes after one finite in-process serve() test."""
    clock=clock or Clock();loop=asyncio.get_running_loop();stop=asyncio.Event()
    box=dict(runtime=None,turns=0,operations=[],owner=None,pool=None,errors=[],clock=clock)
    original_runtime=production.MaintenanceRuntime
    original_owner_init=PriorityOwner.__init__
    class State(service.ServiceState):
        def __init__(self,path,config):
            super().__init__(path,config);self.writer.clock=clock.time
            try:
                if seed:seed(self,clock)
            except BaseException:
                self.close()
                raise
        def archive_commit_slice_and_plan(self,plan,receipt):
            box['operations'].append(('archive',clock.monotonic(),len(plan[:512])))
            if archive_hook:
                return archive_hook(self,plan,receipt,lambda:super(State,self).archive_commit_slice_and_plan(plan,receipt),box)
            try:return super().archive_commit_slice_and_plan(plan,receipt)
            finally:clock.advance(.25)
        def retention(self):
            box['operations'].append(('retirement',clock.monotonic(),None))
            if retention_hook:
                return retention_hook(self,lambda:super(State,self).retention(),box)
            try:return super().retention()
            finally:clock.advance(.3)
    class Runtime(original_runtime):
        def __init__(self,state):
            super().__init__(state,monotonic=clock.monotonic,wall=clock.time)
            box['runtime']=self
        def turn(self,flight,submitted):
            box['turns']+=1
            if before:before(self,flight,box)
            try:
                result=super().turn(flight,submitted)
                if after:after(self,flight,result,box)
                return result
            finally:
                if box['turns']>=turns:loop.call_soon_threadsafe(stop.set)
    def owner_init(owner,*args,**kwargs):
        box['owner']=owner;return original_owner_init(owner,*args,**kwargs)
    def pool(*args,**kwargs):
        box['pool']=pool_class(*args,**kwargs);return box['pool']
    with ExitStack() as stack:
        if path is None:path=Path(stack.enter_context(tempfile.TemporaryDirectory()))/'db'
        path=Path(path);box['path']=path
        stack.enter_context(ipc_transport())
        for obj,name,value in [(service,'time',clock),(service,'ServiceState',State),
                (production,'MaintenanceRuntime',Runtime),(PriorityOwner,'__init__',owner_init)]:
            stack.enter_context(patch.object(obj,name,value))
        stack.enter_context(patch('concurrent.futures.ProcessPoolExecutor',pool))
        stack.enter_context(patch('websockets.asyncio.client.connect',return_value=Wire(clock)))
        runner=asyncio.create_task(service.serve(path,ENDPOINT,stop=stop))
        try:
            await asyncio.wait_for(asyncio.shield(runner),12)
        except BaseException as exc:
            box['errors'].append(exc)
            stop.set()
            if not runner.done():
                try:await asyncio.wait_for(runner,4)
                except BaseException as inner:box['errors'].append(inner)
        finally:
            if not runner.done():runner.cancel();await asyncio.gather(runner,return_exceptions=True)
        if path.exists():
            with closing(sqlite3.connect(path)) as db:
                box['counters']=dict(db.execute('SELECT key,value FROM counters'))
                box['integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
                box['health']={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM service_health')}
                box['episodes']=db.execute('SELECT * FROM maintenance_episodes ORDER BY scope,side').fetchall()
                box['native_progress']=db.execute('SELECT * FROM maintenance_progress ORDER BY scope,side').fetchall()
                box['records']=db.execute('SELECT scope,slot,body IS NULL,COUNT(*) FROM records GROUP BY scope,slot,body IS NULL').fetchall()
    return box
