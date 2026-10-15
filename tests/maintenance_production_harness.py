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
from tests.test_retention_progress import record
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


async def model_b_feed(work,stop,clock):
    """Linked quiet native frames through the Model B publisher and owner.

    The old broad-block WebSocket fixture is archived. This fixture still
    contends with maintenance, while committing real production coverage logic.
    """
    from meme_machine.solana_selective_source import install,commit_control,commit_candidates
    from meme_machine.solana_candidate_join import YellowstoneTransactionFrame
    from meme_machine.solana_selective_history import PROGRAMS
    from meme_machine.solana_rolling_history import program_scope
    from meme_machine.yellowstone import geyser_pb2 as pb
    slot=2_000_000;parent_hash=None;addresses={PROGRAMS[f]:program_scope(f) for f in ('pump','pumpswap')}
    def boot(state):
        nonlocal slot,parent_hash
        h=install(state);h.clock=h.lifecycle.clock=clock.time;h.startup.begin()
        # Resume the fixture's actual durable native frontier. Fixed-slot replay
        # with a new timestamp would conflict with its original immutable block.
        latest=state.writer.db.execute('''SELECT MAX(slot) FROM (
            SELECT slot FROM cursors UNION ALL SELECT slot FROM candidate_blocks
            UNION ALL SELECT slot FROM stream_receipts)''').fetchone()[0]
        slot=max(slot,1+(latest or 0))
        prior=state.writer.db.execute('''SELECT hash FROM candidate_blocks WHERE slot=?
            UNION ALL SELECT hash FROM stream_receipts WHERE slot=? LIMIT 1''',(slot-1,slot-1)).fetchone()
        parent_hash=prior[0] if prior else 'h'+str(slot-1)
        for f in ('pump','pumpswap'):h.startup.feed_ack(f,slot,slot)
        h.startup.native(('pump','pumpswap'))
    await work(boot,0)
    while not stop.is_set():
        u=pb.SubscribeUpdate();b=u.block;b.slot=slot;b.parent_slot=slot-1
        b.blockhash='model-b-'+str(slot);b.parent_blockhash=parent_hash
        b.block_time.timestamp=int(clock.time())
        frame=YellowstoneTransactionFrame(u,u.ByteSize(),clock.time())
        def publish(state):
            commit_control(state,frame);commit_candidates(state,frame,addresses,'offline-model-b')
            # The maintenance fixture deliberately seeds legacy raw records.
            # Linked quiet native headers also bound those raw *gaps*; they do
            # not seal the missing prefix or start a legacy provider producer.
            from meme_machine.solana_selective_source import block_message
            for scope in SCOPES:
                sub=next(s for s in service.program_subscriptions() if s.scope==scope and s.evidence_class in ('census','transactions'))
                state.fence.block(sub,block_message(frame),clock.time())
            install(state).startup.advance()
        await work(publish,2,label='source_commit');parent_hash=b.blockhash;slot+=1
        await asyncio.sleep(.005)


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
    from meme_machine.solana_owner_admission import OwnerAdmission
    native_idle=OwnerAdmission.idle
    async def clocked_idle(admission,stop,worker=None):
        # Idle cadence is simulated by this fixture's controlled clock, just
        # like archive/retirement execution. Keep all requested turns and yield
        # through the real admission/condition machinery. An unfinished native
        # worker still uses the real wait: its completion cannot be invented.
        if worker is None or worker.done():
            clock.advance(1.0)
            admission.wake.set()
        await native_idle(admission,stop,worker)
    with ExitStack() as stack:
        if path is None:path=Path(stack.enter_context(tempfile.TemporaryDirectory()))/'db'
        path=Path(path);box['path']=path
        stack.enter_context(ipc_transport())
        for obj,name,value in [(service,'time',clock),(service,'ServiceState',State),
                (production,'MaintenanceRuntime',Runtime),(PriorityOwner,'__init__',owner_init),
                (OwnerAdmission,'idle',clocked_idle)]:
            stack.enter_context(patch.object(obj,name,value))
        # Construct the prescribed durable workload before timing its service.
        # Large SQLite inserts/archive publication are fixture construction,
        # not owner service or held-reader retirement. They previously consumed
        # several seconds of the unchanged 12-second liveness deadline, and
        # doubled under two-CPU contention. Reopen through the actual serve()
        # owner; no records, scopes, turns, reader pressure or assertions change.
        if seed:
            from meme_machine.solana_provider_config import AlchemyEndpoint
            seeded=State(path,AlchemyEndpoint.parse(ENDPOINT))
            try:seed(seeded,clock)
            finally:seeded.writer.close()
        stack.enter_context(patch('concurrent.futures.ProcessPoolExecutor',pool))
        stack.enter_context(patch('websockets.asyncio.client.connect',return_value=Wire(clock)))
        async def source_driver(work,stop):await model_b_feed(work,stop,clock)
        runner=asyncio.create_task(service.serve(path,ENDPOINT,stop=stop,source_driver=source_driver))
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
