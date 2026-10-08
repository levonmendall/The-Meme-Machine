"""Measured archive contention: no overtaking or duplicate worker publication."""
from contextlib import closing
import asyncio,concurrent.futures,json,sqlite3,tempfile,threading,time,unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine import solana_evidence_service as service
from tests.test_retention_progress import record
from tests.test_dispatch_throughput import database_ready
from tests.evidence_ipc_harness import ipc_transport


class ArchiveSchedulingTests(unittest.TestCase):
 def test_new_source_commits_cannot_overtake_completed_archive_and_cleanup(self):
  entered=threading.Event();release=threading.Event();order=[];clock=[0.0]
  owner=PriorityOwner(lambda:SimpleNamespace(close=lambda:None),clock=lambda:clock[0])
  try:
   owner.ready.result(1)
   first=owner.submit(lambda s:(entered.set(),release.wait(2)),priority=2)
   self.assertTrue(entered.wait(1))
   def job(name,cost):
    def run(state):order.append(name);clock[0]+=cost
    return run
   # Actual failed-certificate costs, without a wall-clock timing assertion.
   jobs=[owner.submit(job('archive',.085),priority=4),
         owner.submit(job('source-1',.165),priority=2),
         owner.submit(job('cleanup',.1),priority=4),
         owner.submit(job('source-2',.165),priority=2),
         owner.submit(job('counter',0),priority=3),
         owner.submit(job('source-3',.165),priority=2),
         owner.submit(job('foreground',0),priority=1),
         owner.submit(job('exit',0),priority=0)]
   release.set()
   for future in [first,*jobs]:future.result(2)
   self.assertEqual(order,['exit','foreground','archive','source-1','cleanup','source-2','counter','source-3'])
   self.assertLessEqual(owner.telemetry()['queue_peak'],64)
   self.assertEqual(owner.enqueued,{})
  finally:release.set();owner.close()


class ArchiveReceiptRetryTests(unittest.IsolatedAsyncioTestCase):
 @unittest.skip('MODEL A archived; engineering/solana_startup_archive/README.md')
 async def test_periodic_telemetry_does_not_preempt_background_durable_work(self):
  priorities=[];context=threading.local()
  submit=PriorityOwner.submit;health=service.FinalizedFence.health
  def tagged(owner,fn,*,priority=1,expires=None):
   def run(state):context.priority=priority;return fn(state)
   return submit(owner,run,priority=priority,expires=expires)
  def observed(fence,key,value):
   if key in ('ipc','owner_scheduler'):priorities.append(context.priority)
   return health(fence,key,value)
  class Wire:
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def send(self,raw):pass
   async def recv(self,decode=None):await asyncio.Future()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(PriorityOwner,'submit',tagged),patch.object(service.FinalizedFence,'health',observed),patch('websockets.asyncio.client.connect',return_value=Wire()):
   stop=asyncio.Event();runner=asyncio.create_task(service.serve(Path(td)/'db','https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   try:
    deadline=time.monotonic()+3
    while len(priorities)<4 and time.monotonic()<deadline:
     if runner.done():await runner
     await asyncio.sleep(.01)
    self.assertGreaterEqual(len(priorities),4,'periodic health fixture did not publish twice')
    self.assertEqual(set(priorities),{4},'telemetry wakes preempt archive and retention as urgent requests')
   finally:stop.set();await runner

 @unittest.skip('MODEL A archived; engineering/solana_startup_archive/README.md')
 async def test_cooperative_commit_yield_reuses_already_published_archive(self):
  await self.exercise(False)

 @unittest.skip('MODEL A archived; engineering/solana_startup_archive/README.md')
 async def test_yield_after_durable_commit_retries_idempotently(self):
  await self.exercise(True)

 async def exercise(self,after_commit):
  native_pool=concurrent.futures.ProcessPoolExecutor;publications=[];attempts=[]
  class Pool:
   def __init__(self,*args,**kwargs):self.pool=native_pool(*args,**kwargs)
   def submit(self,fn,*args,**kwargs):
    if fn is EvidenceWriter.prepare_and_write_archive:publications.append(1)
    return self.pool.submit(fn,*args,**kwargs)
   def shutdown(self,*args,**kwargs):return self.pool.shutdown(*args,**kwargs)
  class SeededState(service.ServiceState):
   def __init__(self,path,config):
    super().__init__(path,config)
    self.writer.ingest([replace(record(),identity='receipt-retry:'+str(i),market_time=int(time.time())-185,observed_at=time.time()) for i in range(40)])
   def archive_commit_slice(self,plan,receipt):
    attempts.append(receipt)
    if len(attempts)==1:
     if after_commit:self.archive_commit(plan,receipt,retain=False)
     raise service.EvidenceUnavailable('evidence_background_yield')
    return super().archive_commit_slice(plan,receipt)
  class Wire:
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def send(self,raw):pass
   async def recv(self,decode=None):await asyncio.Future()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(service,'ServiceState',SeededState),patch('concurrent.futures.ProcessPoolExecutor',Pool),patch('websockets.asyncio.client.connect',return_value=Wire()):
   path=Path(td)/'db';stop=asyncio.Event()
   runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   archived=0;deadline=time.monotonic()+5
   try:
    while time.monotonic()<deadline:
     if runner.done():await runner
     if database_ready(path):
      with closing(sqlite3.connect(path)) as db:
       row=db.execute("SELECT value FROM counters WHERE key='archived_records'").fetchone()
       archived=row[0] if row else 0
     if len(attempts)>=2 and archived==40:break
     await asyncio.sleep(.01)
    self.assertGreaterEqual(len(attempts),2,'durable archive receipt was abandoned after cooperative yield')
    self.assertEqual(len(publications),1,'SQL scheduling yield reran archive serialization/publication')
    self.assertIs(attempts[0],attempts[1])
    self.assertEqual(archived,40)
   finally:stop.set();await runner
   with closing(sqlite3.connect(path)) as db:
    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
    metrics=json.loads(db.execute("SELECT value FROM service_health WHERE key='storage_maintenance'").fetchone()[0])
    self.assertEqual(metrics['archive_worker.records.total'],40,'worker telemetry double-counted a retained receipt retry')


 @unittest.skip('MODEL A archived; engineering/solana_startup_archive/README.md')
 async def test_ready_archive_receipt_finishes_slices_before_fresh_retention_grant(self):
   order=[]
   class SeededState(service.ServiceState):
    def __init__(self,path,config):
     super().__init__(path,config)
     self.writer.ingest([replace(record(),identity='archive-ready:'+str(i),slot=100+i,
         market_time=int(time.time())-185,observed_at=time.time()) for i in range(700)])
    def archive_commit_slice_and_plan(self,plan,receipt):
     order.append('archive')
     return super().archive_commit_slice_and_plan(plan,receipt)
    def retention(self):
     order.append('retention')
     return super().retention()
   class Wire:
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def send(self,raw):pass
    async def recv(self,decode=None):await asyncio.Future()
   with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(
       service,'ServiceState',SeededState),patch(
       'websockets.asyncio.client.connect',return_value=Wire()):
    path=Path(td)/'db';stop=asyncio.Event()
    runner=asyncio.create_task(service.serve(
        path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
    try:
     deadline=time.monotonic()+6
     while order.count('archive')<2 and time.monotonic()<deadline:
      if runner.done():await runner
      await asyncio.sleep(.01)
     self.assertGreaterEqual(order.count('archive'),2,'fixture did not require two archive commit slices')
     first=order.index('archive');second=order.index('archive',first+1)
     # Keep the historical discovery identity, but verify its safety
     # obligation through the sole production authority, not the superseded
     # one-for-one policy. Both bounded archive slices must complete while
     # retention receives only validated arbiter admissions.
     self.assertTrue(all(side=='retention' for side in order[first+1:second]))
     with closing(sqlite3.connect(path)) as db:
      self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
     self.assertLess(time.monotonic(),deadline,'READY archive service drought')
    finally:stop.set();await runner


# The old AST harness extracted an independent retention coroutine and asserted
# fixed 1:1 alternation. Those mechanisms are deliberately removed. Preserve the
# race, atomicity, native-outcome, FIFO, receipt and liveness obligations against
# the actual production authority instead; no pressure fixture or gate changes.
import ast
from contextlib import contextmanager
from meme_machine.solana_maintenance_runtime import MaintenanceRuntime,ArchiveFlight
from meme_machine.solana_retention_outcome import RetentionOutcome
from meme_machine.solana_provider_config import AlchemyEndpoint
from tests.maintenance_production_harness import (
    Clock,SCOPES,seed_book,rows,ingest,run_case,NativeCompletionPool)


def healthy(test,box):
    test.assertFalse(box['errors'],json.dumps(dict(errors=[str(e) for e in box['errors']],
        clock=box['clock'].monotonic(),origin={str(k):v for k,v in box['runtime'].arbiter.origin.items()},
        recent=list(box['runtime'].ring)[-3:]),sort_keys=True))
    test.assertEqual(box['integrity'],'ok')
    test.assertIsNone(box['runtime'].failure)
    test.assertLessEqual(box['pool'].max_inflight,1)
    test.assertTrue(all(n<=512 for side,_,n in box['operations'] if side=='archive'))
    test.assertTrue(all(v<box['runtime'].leases.drought for v in box['runtime'].arbiter.max_scope_gap.values()))


@contextmanager
def native_owner(seed):
    """Actual queue and SQLite, with a controlled clock, no standalone scheduler."""
    clock=Clock()
    with tempfile.TemporaryDirectory() as td,patch.object(service,'time',clock):
        path=Path(td)/'db'
        class State(service.ServiceState):
            def __init__(self):
                super().__init__(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
                self.writer.clock=clock.time
                try:
                    seed(self,clock)
                    self.runtime=MaintenanceRuntime(self,monotonic=clock.monotonic,wall=clock.time)
                    self.flight=ArchiveFlight()
                except BaseException:self.close();raise
        owner=PriorityOwner(State,clock=clock.monotonic)
        try:
            owner.ready.result(3)
            yield owner,clock,path
        finally:owner.close()


class RetentionExecutionGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_already_queued_retention_defers_after_receipt_readiness(self):
        """Ordering is decided at owner entry, not at a stale pre-queue check."""
        seed=lambda s,c:seed_book(s,c,hot=(12000,0,0),retired=(1,0,0),same_slot=True)
        with native_owner(seed) as (owner,clock,path):
            first=owner.submit(lambda s:s.runtime.turn(s.flight,clock.monotonic()),priority=4).result(3)
            self.assertEqual(first['side'],'archive')
            snapshot=first['snapshot'];self.assertTrue(snapshot)
            receipt_result=EvidenceWriter.prepare_and_write_archive(path,snapshot,max_bytes=16*1024*1024)
            future=concurrent.futures.Future()
            owner.submit(lambda s:s.flight.attach(future,clock.monotonic(),s.runtime.generation),priority=4).result(3)
            entered,release=threading.Event(),threading.Event();order=[]
            blocker=owner.submit(lambda s:(entered.set(),release.wait(3)),priority=2)
            self.assertTrue(entered.wait(2))
            def decision(state):
                value=state.runtime.turn(state.flight,clock.monotonic())
                order.append(value['side']);return value
            queued=owner.submit(decision,priority=4)
            jobs=[owner.submit(lambda s:order.append('source'),priority=2),
                  owner.submit(lambda s:order.append('foreground'),priority=1),
                  owner.submit(lambda s:order.append('urgent'),priority=0)]
            try:
                self.assertFalse(future.done())
                future.set_result(receipt_result)  # became READY after queueing
                release.set()
                for f in [blocker,queued,*jobs]:await asyncio.wrap_future(f)
                self.assertEqual(order,['urgent','foreground','archive','source'])
                self.assertEqual(queued.result()['side'],'archive')
                counters=owner.submit(lambda s:dict(s.writer.db.execute('SELECT key,value FROM counters')),priority=4).result(3)
                self.assertEqual(counters.get('compacted_records',0),0)
                self.assertGreater(counters.get('archived_records',0),1)
            finally:release.set()

    async def test_deferred_callback_does_not_report_idle_or_progress(self):
        checked=[]
        def before(r,f,b):
            b['prior_retired']={tuple(row[:2]):row[3:] for row in r.writer.db.execute(
                "SELECT scope,side,at,units,record_at,records FROM maintenance_progress WHERE side='retirement'")}
        def after(r,f,result,b):
            if result['side']=='archive':
                after={tuple(row[:2]):row[3:] for row in r.writer.db.execute(
                    "SELECT scope,side,at,units,record_at,records FROM maintenance_progress WHERE side='retirement'")}
                self.assertEqual(after,b['prior_retired'])
                self.assertNotIn('retention_outcome',result)
                checked.append(result)
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(3000,0,0),retired=(100,0,0)),
                           before=before,after=after,turns=14)
        healthy(self,box);self.assertTrue(checked)

    async def test_no_ready_receipt_preserves_native_outcome(self):
        for pending in (False,True,None):
            with self.subTest(pending=pending):
                outcomes=[];returned=[]
                def retention(state,native,b):
                    value=replace(native(),pending=pending,interrupted=pending is None)
                    outcomes.append(value);return value
                def after(r,f,result,b):
                    if result['side']=='retirement':returned.append(result['retention_outcome'])
                box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(0,0,0),retired=(300,0,0)),
                                   retention_hook=retention,after=after,turns=4)
                healthy(self,box);self.assertTrue(outcomes)
                self.assertEqual(len(returned),len(outcomes))
                self.assertTrue(all(a is b for a,b in zip(returned,outcomes)))
                self.assertTrue(all(o.pending is pending for o in returned))

    async def test_existing_ready_guard_does_not_enqueue_new_work(self):
        """No independent retention admission remains beside the single loop."""
        tree=ast.parse(Path(service.__file__).read_text())
        loops=[n.name for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef)]
        self.assertEqual(loops.count('maintenance'),1)
        self.assertEqual(loops.count('retention'),0)
        admitted=[]
        def retention(state,native,b):
            decision=b['runtime'].arbiter.pending
            self.assertIsNotNone(decision)
            self.assertEqual(decision.side,'retirement')
            admitted.append(decision.sequence);return native()
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(5000,0,0),retired=(200,0,0),same_slot=True),
                           retention_hook=retention,turns=20)
        healthy(self,box);self.assertTrue(admitted)
        self.assertEqual(len(admitted),len(set(admitted)))

    async def test_current_retention_grant_not_interrupted_by_new_readiness(self):
        ready=[];finished=[];future=concurrent.futures.Future()
        def before(r,f,b):
            if not b.get('attached'):
                snapshot=r.state.archive_plan();self.assertTrue(snapshot)
                b['receipt_result']=EvidenceWriter.prepare_and_write_archive(b['path'],snapshot,max_bytes=16*1024*1024)
                f.prepared=snapshot;f.attach(future,b['clock'].monotonic(),r.generation)
                b['attached']=True
        def retention(state,native,b):
            def traced(sql):
                if not future.done() and sql.startswith('DELETE FROM records'):
                    self.assertTrue(state.writer.db.in_transaction)
                    future.set_result(b['receipt_result']);ready.append('during-native-transaction')
            state.writer.db.set_trace_callback(traced)
            try:
                result=native()
                if ready:finished.append(result)
                return result
            finally:state.writer.db.set_trace_callback(None)
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(100,0,0),retired=(1500,0,0)),
                           before=before,retention_hook=retention,turns=12)
        healthy(self,box);self.assertEqual(ready,['during-native-transaction'])
        self.assertTrue(any(o.retired_records>0 for o in finished))
        self.assertGreater(box['counters'].get('archived_records',0),1500)

    async def test_storage_error_is_not_silently_converted_to_deferral(self):
        calls=[]
        def retention(state,native,b):calls.append(1);raise ValueError('storage_failure')
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(0,0,0),retired=(300,0,0)),
                           retention_hook=retention,turns=3)
        self.assertTrue(any('storage_failure' in str(e) for e in box['errors']))
        self.assertEqual(calls,[1])
        self.assertTrue(box['runtime'].failure)
        self.assertEqual(box['counters'].get('compacted_records',0),0)

    async def test_retention_reenters_when_worker_preparation_releases_ready(self):
        class HoldSuccessor(NativeCompletionPool):
            def __init__(self,*a,**k):super().__init__(*a,**k);self.pending=[]
            def submit(self,fn,*a,**k):
                if fn is EvidenceWriter.prepare_and_write_archive and self.submissions:
                    self.submissions.append(a[1]);future=concurrent.futures.Future();self.pending.append(future);return future
                return super().submit(fn,*a,**k)
            def shutdown(self,*a,**k):
                for f in self.pending:f.cancel()
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(2400,0,0)),pool_class=HoldSuccessor,turns=9)
        healthy(self,box)
        self.assertEqual(len(box['pool'].pending),1)
        self.assertTrue(any(e['selected']=='retirement' and not e['ready']['archive']
            and any(e.get('durable_records',{}).values()) for e in box['runtime'].ring))


class BoundedArchiveRetirementTests(unittest.IsolatedAsyncioTestCase):
    async def test_sustained_ready_work_has_bounded_two_sided_service(self):
        """Replaces the prohibited fixed-ratio assertion, not the liveness gate."""
        def after(r,f,result,b):
            for scope in SCOPES:
                ingest(r.writer,rows(b['clock'],scope,32,start=3_000_000+b['turns']*32,tag='ongoing',same_slot=True))
            b['clock'].advance(.5)
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(2000,2000,2000),retired=(700,700,700)),
                           after=after,turns=72)
        healthy(self,box)
        self.assertGreater(box['clock'].monotonic(),box['runtime'].leases.drought)
        sides=[s for s,_,_ in box['operations']]
        self.assertTrue(any(a==b=='archive' for a,b in zip(sides,sides[1:])),sides)
        for scope in SCOPES:
            self.assertGreater(box['counters'].get('lifecycle.archived.'+scope,0),700)
            self.assertGreater(box['counters'].get('lifecycle.retired.'+scope,0),0)
            self.assertLess(box['runtime'].arbiter.max_scope_gap['archive',scope],box['runtime'].leases.drought)
            self.assertLess(box['runtime'].arbiter.max_scope_gap['retirement',scope],box['runtime'].leases.drought)

    async def test_completed_receipt_prefetch_precedes_earned_retirement(self):
        order=[]
        class Pool(NativeCompletionPool):
            def submit(self,fn,*a,**k):
                if fn is EvidenceWriter.prepare_and_write_archive:order.append('prepare')
                return super().submit(fn,*a,**k)
        def archive(state,plan,receipt,native,b):
            result=native()
            order.append('completed-with-successor' if not result[0] and result[1] else 'archive')
            return result
        def retention(state,native,b):order.append('retirement');return native()
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(5000,0,0),retired=(200,0,0),same_slot=True),
                           archive_hook=archive,retention_hook=retention,pool_class=Pool,turns=22)
        healthy(self,box)
        completed=[i for i,s in enumerate(order) if s=='completed-with-successor']
        self.assertTrue(completed)
        for i in completed:self.assertEqual(order[i+1],'prepare',order)

    async def test_failed_archive_does_not_mint_retirement_turn(self):
        def archive(state,plan,receipt,native,b):raise ValueError('storage_failure')
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(3000,0,0)),archive_hook=archive,turns=5)
        self.assertTrue(any('storage_failure' in str(e) for e in box['errors']))
        sides=[s for s,_,_ in box['operations']];self.assertIn('archive',sides)
        self.assertNotIn('retirement',sides[sides.index('archive')+1:])
        self.assertTrue(box['runtime'].failure)
        self.assertEqual(box['counters'].get('archived_records',0),0)

    async def test_earned_retirement_keeps_unknown_outcome_distinct_from_idle(self):
        outcomes=[]
        def retention(state,native,b):
            value=RetentionOutcome(pending=None,interrupted=True,yield_reason='urgent_sql')
            outcomes.append(value);return value
        def after(r,f,result,b):
            if result['side']=='retirement':
                self.assertIs(result['retention_outcome'],outcomes[-1])
                self.assertIsNone(result['retention_outcome'].pending)
                self.assertFalse(any(r.ring[-1].get('durable_progress',{}).values()))
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(0,0,0),retired=(300,0,0)),
                           retention_hook=retention,after=after,turns=4)
        healthy(self,box);self.assertTrue(outcomes)
        self.assertEqual(box['counters'].get('compacted_records',0),0)
        self.assertEqual(box['runtime'].arbiter.max_gap['retirement'],0)

    async def test_continuous_ready_guard_has_no_unearned_ordinary_retirement(self):
        calls=[]
        def retirement(state,native,b):
            d=b['runtime'].arbiter.pending
            self.assertIsNotNone(d)
            self.assertEqual(d.side,'retirement')
            self.assertIn(d.reason,('debt_surplus','peer_reservation'))
            self.assertGreater(dict(d.need_by_side)['retirement'],0)
            calls.append(d.sequence);return native()
        box=await run_case(seed=lambda s,c:seed_book(s,c,hot=(8000,0,0),retired=(1,0,0),same_slot=True),
                           retention_hook=retirement,turns=25)
        healthy(self,box);self.assertTrue(calls)
        self.assertEqual(len(calls),len(set(calls)))

    async def test_eligible_reader_and_all_scopes_progress_under_source_pressure(self):
        reader=[None];baseline=[None];sources=[];outcomes=[]
        def seed(state,clock):
            seed_book(state,clock,hot=(1500,1500,1500),retired=(900,900,900))
            state.writer.retain(clock.time()-180,max_records=256,archive_first=False,checkpoint=False)
        def before(r,f,b):
            if reader[0] is None:
                db=reader[0]=sqlite3.connect(b['path'],isolation_level=None,check_same_thread=False)
                db.execute('BEGIN');baseline[0]=dict(db.execute('SELECT key,value FROM counters'))
                self.assertTrue(any(db.execute('SELECT 1 FROM records WHERE scope=? AND body IS NULL AND slot<'
                    '(SELECT CAST(value AS INTEGER) FROM meta WHERE key=?) LIMIT 1',(scope,'retention_floor:'+scope)).fetchone() for scope in SCOPES))
        def retention(state,native,b):
            queued=[]
            def source_work(state):
                with state.writer.transaction():state.writer._count('regression_source_progress')
            def trace(sql):
                if not queued and sql.startswith('DELETE FROM lineage'):
                    queued.append(b['owner'].submit(source_work,priority=2));sources.extend(queued)
            state.writer.db.set_trace_callback(trace)
            try:
                result=native();outcomes.append(result);return result
            finally:state.writer.db.set_trace_callback(None)
        def after(r,f,result,b):
            self.assertEqual(dict(reader[0].execute('SELECT key,value FROM counters')),baseline[0])
        try:
            box=await run_case(seed=seed,before=before,after=after,retention_hook=retention,turns=28)
            healthy(self,box)
            self.assertGreater(box['counters'].get('regression_source_progress',0),0)
            self.assertTrue(all(f.done() and f.exception() is None for f in sources))
            self.assertGreater(box['counters'].get('compacted_records',0),baseline[0].get('compacted_records',0))
            self.assertTrue(any(o.retired_records>0 for o in outcomes))
            self.assertTrue(all(o.committed_slices<=3 for o in outcomes if o.yield_reason=='source'))
            for scope in SCOPES:
                self.assertGreater(box['counters'].get('lifecycle.retired.'+scope,0),baseline[0].get('lifecycle.retired.'+scope,0))
        finally:
            if reader[0]:reader[0].execute('ROLLBACK');reader[0].close()


if __name__=='__main__':unittest.main()
