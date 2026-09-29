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


if __name__=='__main__':unittest.main()
