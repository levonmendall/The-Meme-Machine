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
     self.assertNotIn('retention',order[first+1:second],
         'fresh retention grant delayed a prepared archive receipt')
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



if __name__=='__main__':unittest.main()
