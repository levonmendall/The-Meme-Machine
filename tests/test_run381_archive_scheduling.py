"""Measured archive contention: no overtaking or duplicate worker publication."""
import asyncio,concurrent.futures,json,sqlite3,tempfile,threading,time,unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from meme_machine.solana_evidence_control import PriorityOwner
from meme_machine.solana_evidence_plane import EvidenceWriter
from meme_machine import solana_evidence_service as service
from tests.test_run381_retention_progress import record
from tests.test_run373_dispatch_throughput import database_ready
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

 async def test_cooperative_commit_yield_reuses_already_published_archive(self):
  await self.exercise(False)

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
    self.writer.ingest([replace(record(),identity='receipt-retry:'+str(i),market_time=10) for i in range(40)])
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
      with sqlite3.connect(path) as db:
       row=db.execute("SELECT value FROM counters WHERE key='archived_records'").fetchone()
       archived=row[0] if row else 0
     if len(attempts)>=2 and archived==40:break
     await asyncio.sleep(.01)
    self.assertGreaterEqual(len(attempts),2,'durable archive receipt was abandoned after cooperative yield')
    self.assertEqual(len(publications),1,'SQL scheduling yield reran archive serialization/publication')
    self.assertIs(attempts[0],attempts[1])
    self.assertEqual(archived,40)
   finally:stop.set();await runner
   with sqlite3.connect(path) as db:
    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
    metrics=json.loads(db.execute("SELECT value FROM service_health WHERE key='storage_maintenance'").fetchone()[0])
    self.assertEqual(metrics['archive_worker.records.total'],40,'worker telemetry double-counted a retained receipt retry')


 async def test_ready_archive_receipt_finishes_slices_before_fresh_retention_grant(self):
   order=[]
   class SeededState(service.ServiceState):
    def __init__(self,path,config):
     super().__init__(path,config)
     self.writer.ingest([replace(record(),identity='archive-ready:'+str(i),slot=100+i,
         market_time=10) for i in range(700)])
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
     # The unchanged ordinary guards still prohibit fresh cleanup here.
     # The new two-way contract earns ONE bounded grant after the first slice;
     # it must not admit repeated ordinary cleanup before the next slice.
     self.assertEqual(order[first+1:second],['retention'],
         'prepared archive did not retain bounded service between earned grants')
    finally:stop.set();await runner


# Diagnostic 36586266000: cover readiness changing after retention submission.
import ast
from meme_machine.solana_retention_outcome import RetentionOutcome


def production_retention(stop, work, counts, pressure):
    module = ast.parse(Path(service.__file__).read_text())
    functions = [node for node in ast.walk(module)
                 if isinstance(node, ast.AsyncFunctionDef) and node.name == 'retention']
    if len(functions) != 1:
        raise AssertionError('production retention coroutine identity changed')
    factory = ast.parse('''
def factory(stop, work, counts, maintenance_pressure):
    archive_commit_ready = False
    def set_ready(value):
        nonlocal archive_commit_ready
        archive_commit_ready = value
    return retention, set_ready
''')
    factory.body[0].body.insert(1, functions[0])
    namespace = {'asyncio': asyncio}
    exec(compile(ast.fix_missing_locations(factory), str(Path(service.__file__)), 'exec'), namespace)
    return namespace['factory'](stop, work, counts, pressure)


class RetentionExecutionGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_already_queued_retention_defers_after_receipt_readiness(self):
        """The original E27 executes retirement here; the repair must not."""
        entered, release = threading.Event(), threading.Event()
        queued = asyncio.Event()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        order, counts, calls = [], {}, []
        pressure = {'retention': True}
        def retire():
            order.append('retention')
            loop.call_soon_threadsafe(stop.set)
            return RetentionOutcome(retired_records=256, pending=True)
        owner = PriorityOwner(lambda: SimpleNamespace(retention=retire, close=lambda: None))
        owner.ready.result(timeout=2)
        blocker = owner.submit(lambda state: (entered.set(), release.wait(3)), priority=2)
        self.assertTrue(entered.wait(2))
        async def work(fn, priority, *, label):
            calls.append((priority, label))
            future = owner.submit(fn, priority=priority)
            queued.set()
            return await asyncio.wrap_future(future)
        retention, ready = production_retention(stop, work, counts, pressure)
        task = asyncio.create_task(retention())
        try:
            await asyncio.wait_for(queued.wait(), 2)
            # Exact observed order: retirement queued while worker not ready;
            # then receipt ready, archive queued, then owner admits retirement.
            ready(True)
            jobs = [owner.submit(lambda state: order.append('source-before'), priority=2),
                    owner.submit(lambda state: (order.append('archive'), ready(False)), priority=4),
                    owner.submit(lambda state: order.append('source-after'), priority=2),
                    owner.submit(lambda state: order.append('foreground'), priority=1),
                    owner.submit(lambda state: order.append('urgent'), priority=0)]
            release.set()
            await asyncio.wait_for(asyncio.gather(*(asyncio.wrap_future(f) for f in [blocker, *jobs])), 3)
            await asyncio.wait_for(task, 3)
            self.assertEqual(order, ['urgent', 'foreground', 'source-before', 'archive',
                                     'source-after', 'retention'])
            self.assertEqual(calls, [(4, 'retention'), (4, 'retention')])
            self.assertEqual(counts.get('retention.archive_ready_at_execution_deferrals'), 1)
            self.assertTrue(pressure['retention'])
        finally:
            release.set(); stop.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            owner.close()

    async def test_deferred_callback_does_not_report_idle_or_progress(self):
        for prior in (False, True):
            with self.subTest(prior=prior):
                stop=asyncio.Event(); counts={}; pressure={'retention':prior}; calls=[]
                def retire():
                    calls.append('forbidden');return RetentionOutcome(pending=False)
                async def work(fn, priority, *, label):
                    ready(True); value=fn(SimpleNamespace(retention=retire));stop.set();return value
                retention,ready=production_retention(stop,work,counts,pressure)
                await retention()
                self.assertEqual(calls,[])
                self.assertIs(pressure['retention'],prior)
                self.assertEqual(counts.get('retention.archive_ready_at_execution_deferrals'),1)

    async def test_no_ready_receipt_preserves_native_outcome(self):
        for pending in (False,True,None):
            with self.subTest(pending=pending):
                stop=asyncio.Event();counts={};pressure={};calls=[]
                outcome=RetentionOutcome(retired_records=256,pending=pending,interrupted=pending is None)
                def retire():calls.append(1);stop.set();return outcome
                async def work(fn,priority,*,label):
                    self.assertEqual((priority,label),(4,'retention'))
                    return fn(SimpleNamespace(retention=retire))
                retention,_=production_retention(stop,work,counts,pressure)
                await retention()
                self.assertEqual(calls,[1]);self.assertIs(pressure['retention'],pending is True)
                self.assertEqual(counts,{})

    async def test_existing_ready_guard_does_not_enqueue_new_work(self):
        stop=asyncio.Event();counts={};pressure={'retention':True};calls=[]
        async def work(*args,**kwargs):calls.append(1);raise AssertionError('must not queue')
        async def sleep(delay):self.assertEqual(delay,.001);stop.set()
        retention,ready=production_retention(stop,work,counts,pressure);ready(True)
        with patch.object(asyncio,'sleep',sleep):await retention()
        self.assertEqual(calls,[]);self.assertTrue(pressure['retention'])
        self.assertEqual(counts,{'retention.archive_commit_ready_deferrals':1})

    async def test_current_retention_grant_not_interrupted_by_new_readiness(self):
        stop=asyncio.Event();counts={};pressure={};calls=[]
        def retire():
            calls.append('entered');ready(True);calls.append('committed');stop.set()
            return RetentionOutcome(retired_records=256,pending=True)
        async def work(fn,priority,*,label):return fn(SimpleNamespace(retention=retire))
        retention,ready=production_retention(stop,work,counts,pressure)
        await retention()
        self.assertEqual(calls,['entered','committed']);self.assertEqual(counts,{})

    async def test_storage_error_is_not_silently_converted_to_deferral(self):
        stop=asyncio.Event();counts={};pressure={}
        def retire():raise ValueError('storage_failure')
        async def work(fn,priority,*,label):return fn(SimpleNamespace(retention=retire))
        retention,_=production_retention(stop,work,counts,pressure)
        with self.assertRaisesRegex(ValueError,'storage_failure'):await retention()
        self.assertEqual(counts,{})

    async def test_retention_reenters_when_worker_preparation_releases_ready(self):
        stop=asyncio.Event();counts={};pressure={};sequence=[];attempts=0
        def retire():sequence.append('retired');stop.set();return RetentionOutcome(pending=True)
        async def work(fn,priority,*,label):
            nonlocal attempts
            attempts+=1
            if attempts==1:
                ready(True);value=fn(SimpleNamespace(retention=retire))
                sequence.append('deferred' if value is None else 'unexpected-service')
                ready(False);return value
            return fn(SimpleNamespace(retention=retire))
        retention,ready=production_retention(stop,work,counts,pressure)
        await retention()
        self.assertEqual(sequence,['deferred','retired']);self.assertEqual(attempts,2)




# Bound maintenance admission in both directions without relying on lucky timing.
def production_maintenance(stop, work, counts, pressure, pool, path):
    module = ast.parse(Path(service.__file__).read_text())
    functions = [node for node in ast.walk(module)
                 if isinstance(node, ast.AsyncFunctionDef) and node.name == 'maintenance']
    if len(functions) != 1:
        raise AssertionError('production maintenance coroutine identity changed')
    factory = ast.parse('''
def factory(stop, work, counts, maintenance_pressure, decoder_pool, path):
    archive_commit_ready = False
    return maintenance
''')
    factory.body[0].body.insert(1, functions[0])
    namespace = {'asyncio': asyncio, 'time': time, 'EvidenceWriter': EvidenceWriter,
                 'EvidenceUnavailable': service.EvidenceUnavailable}
    exec(compile(ast.fix_missing_locations(factory), str(Path(service.__file__)), 'exec'), namespace)
    return namespace['factory'](stop, work, counts, pressure, pool, path)


class BoundedArchiveRetirementTests(unittest.IsolatedAsyncioTestCase):
    async def model(self, *, native_error=False, outcome=None):
        """Always READY worker; fixed 12 archive admissions, no timing retries."""
        stop=asyncio.Event(); counts={}; pressure={}; order=[]; slices=[]
        outcome=RetentionOutcome(retired_records=256,pending=True) if outcome is None else outcome
        class Pool:
            def submit(self, fn, path, snapshot, **kwargs):
                order.append('prepare')
                future=concurrent.futures.Future()
                future.set_result((list(range(1000)), {'hash':'one'}))
                return future
        class State:
            def archive_plan(self):return {'rows':[1]}
            def archive_commit_slice_and_plan(self, plan, receipt):
                order.append('archive'); slices.append(min(len(plan),512))
                if native_error:raise ValueError('storage_failure')
                remaining=plan[512:]
                if len(slices)==12:stop.set()
                return remaining, None if remaining else {'rows':[1]}
            def retention(self):order.append('retention');return outcome
        state=State()
        async def work(fn,priority,*,label):
            self.assertEqual(priority,4)
            order.append('source')  # independent mandatory work between grants
            return fn(state)
        maintenance=production_maintenance(stop,work,counts,pressure,Pool(),'unused')
        if native_error:
            with self.assertRaisesRegex(ValueError,'storage_failure'):await maintenance()
        else:
            await maintenance()
        return order,slices,counts,pressure

    async def test_sustained_ready_work_has_one_retirement_turn_per_archive_slice(self):
        order,slices,counts,pressure=await self.model()
        turns=[x for x in order if x in ('archive','retention')]
        self.assertEqual(turns,['archive','retention']*12,
                         'READY archive service has no bounded retirement handoff')
        self.assertEqual(slices,[512,488]*6)
        self.assertEqual(counts.get('retention.after_archive_slice_grants'),12)
        self.assertIs(pressure['retention'],True)

    async def test_completed_receipt_prefetch_precedes_earned_retirement(self):
        order,_,_,_=await self.model()
        archives=[i for i,x in enumerate(order) if x=='archive']
        for i in archives[1::2]:
            following=order[i+1:]
            self.assertIn('retention',following,'no retirement handoff after completed receipt')
            self.assertLess(following.index('prepare'),following.index('retention'),
                            'retirement delayed starting the next archive worker')

    async def test_failed_archive_does_not_mint_retirement_turn(self):
        order,_,counts,_=await self.model(native_error=True)
        self.assertNotIn('retention',order)
        self.assertNotIn('retention.after_archive_slice_grants',counts)

    async def test_earned_retirement_keeps_unknown_outcome_distinct_from_idle(self):
        order,_,counts,pressure=await self.model(outcome=RetentionOutcome(
            pending=None,interrupted=True,yield_reason='urgent_sql'))
        self.assertEqual(order.count('retention'),12)
        self.assertEqual(counts.get('retention.after_archive_slice_grants'),12)
        self.assertIs(pressure['retention'],False)  # unknown is not proven backlog
        self.assertNotIn('retention_outcome.idle',counts)

    async def test_continuous_ready_guard_has_no_unearned_ordinary_retirement(self):
        stop=asyncio.Event();counts={};pressure={'retention':True};calls=[];checks=0
        async def work(*args,**kwargs):calls.append(1);raise AssertionError('unearned grant')
        async def sleep(delay):
            nonlocal checks
            self.assertEqual(delay,.001);checks+=1
            if checks==1024:stop.set()
        retention,ready=production_retention(stop,work,counts,pressure);ready(True)
        with patch.object(asyncio,'sleep',sleep):await retention()
        self.assertEqual(calls,[])
        self.assertEqual(counts['retention.archive_commit_ready_deferrals'],1024)
        self.assertIs(pressure['retention'],True)

    async def test_eligible_reader_and_all_scopes_progress_under_source_pressure(self):
        """Native SQLite/owner/retention; six bounded maintenance turns.

        The test proves a service-count bound, not a timing adjustment to the
        frozen 1.35s pressure observer. Real cohort timing remains mandatory.
        """
        from meme_machine.solana_provider_config import AlchemyEndpoint
        scopes=('program:meteora','program:pump','program:pumpswap')
        stop=asyncio.Event();counts={};pressure={};archive_sizes=[];sources=[];retired=[]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db'
            class State(service.ServiceState):
                def __init__(self):
                    super().__init__(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
                    old=[replace(record(),scope=s,identity=s+':old:%04d'%i,
                                 signature=s+':old:%04d'%i,slot=10+i,market_time=10)
                         for s in scopes for i in range(900)]
                    for i in range(0,len(old),1000):self.writer.ingest(old[i:i+1000])
                    while self.writer.archive(1000):pass
                    self.writer.retain(1000,max_records=256,archive_first=False,checkpoint=False)
                    hot=[replace(record(),scope=s,identity=s+':hot:%04d'%i,
                                 signature=s+':hot:%04d'%i,slot=1000+i,market_time=20)
                         for s in scopes for i in range(1500)]
                    for i in range(0,len(hot),1000):self.writer.ingest(hot[i:i+1000])
                def archive_commit_slice_and_plan(self,plan,receipt):
                    archive_sizes.append(min(len(plan),512))
                    result=super().archive_commit_slice_and_plan(plan,receipt)
                    if len(archive_sizes)==6:stop.set()
                    return result
                def retention(self):
                    queued=[]
                    def source_work(state):
                        with state.writer.transaction():state.writer._count('stream_accepted_messages')
                    def on_statement(sql):
                        if not queued and sql.startswith('DELETE FROM lineage'):
                            queued.append(owner.submit(source_work,priority=2));sources.extend(queued)
                    self.writer.db.set_trace_callback(on_statement)
                    try:outcome=super().retention()
                    finally:self.writer.db.set_trace_callback(None)
                    retired.append(outcome)
                    return outcome
            owner=PriorityOwner(State);await asyncio.wrap_future(owner.ready)
            class Pool:
                # Publication still uses the real immutable snapshot and receipt.
                def submit(self,fn,*args,**kwargs):
                    future=concurrent.futures.Future()
                    try:future.set_result(fn(*args,**kwargs))
                    except BaseException as exc:future.set_exception(exc)
                    return future
            async def work(fn,priority,*,label):
                return await asyncio.wrap_future(owner.submit(fn,priority=priority))
            reader=sqlite3.connect(path,isolation_level=None)
            try:
                reader.execute('BEGIN')
                before=dict(reader.execute('SELECT key,value FROM counters'))
                eligible=any(reader.execute(
                    'SELECT 1 FROM records WHERE scope=? AND body IS NULL AND slot<'
                    '(SELECT CAST(value AS INTEGER) FROM meta WHERE key=?) LIMIT 1',
                    (scope,'retention_floor:'+scope)).fetchone() for scope in scopes)
                self.assertTrue(eligible)
                maintenance=production_maintenance(stop,work,counts,pressure,Pool(),path)
                await maintenance()
                for f in sources:await asyncio.wrap_future(f)
                self.assertEqual(dict(reader.execute('SELECT key,value FROM counters')),before,
                                 'held reader snapshot changed')
                current=sqlite3.connect(path,isolation_level=None)
                try:after=dict(current.execute('SELECT key,value FROM counters'))
                finally:current.close()
                self.assertGreater(after.get('stream_accepted_messages',0)-before.get('stream_accepted_messages',0),0)
                self.assertGreater(after.get('compacted_records',0)-before.get('compacted_records',0),0)
                self.assertEqual(len(retired),6)
                self.assertTrue(all(o.retired_records>0 and o.committed_slices<=3 for o in retired))
                reader.execute('ROLLBACK')
                durable=dict(reader.execute('SELECT key,value FROM counters'))
                for scope in scopes:self.assertGreater(durable.get('lifecycle.retired.'+scope,0),0,scope)
                self.assertTrue(all(0<n<=512 for n in archive_sizes))
                self.assertEqual(reader.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:
                if reader.in_transaction:reader.execute('ROLLBACK')
                reader.close();owner.close()


if __name__=='__main__':unittest.main()
