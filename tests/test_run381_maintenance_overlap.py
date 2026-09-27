"""Hot cleanup must progress independently of a pending archive worker."""
import asyncio,concurrent.futures,json,sqlite3,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from meme_machine.solana_evidence_plane import EvidenceWriter
import meme_machine.solana_evidence_service as service
from tests.test_run381_retention_progress import record
from tests.test_run373_dispatch_throughput import block_frame,database_ready
from tests.evidence_ipc_harness import ipc_transport

class ArchiveCleanupOverlapTests(unittest.IsolatedAsyncioTestCase):
 async def test_repeated_health_yields_cannot_starve_archive_progress(self):
  calls=[]
  class SeededState(service.ServiceState):
   def __init__(self,path,config):
    super().__init__(path,config)
    self.writer.ingest([replace(record(),identity='health-overlap:'+str(i),market_time=10) for i in range(40)])
   def maintenance_health(self,http):
    calls.append(1)
    raise service.EvidenceUnavailable('evidence_background_yield')
  class Wire:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def send(self,raw):pass
   async def recv(self,decode=None):await asyncio.Future()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(service,'ServiceState',SeededState),patch('websockets.asyncio.client.connect',return_value=Wire()):
   path=Path(td)/'db';stop=asyncio.Event()
   runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   archived=0;deadline=time.monotonic()+3
   try:
    while time.monotonic()<deadline:
     if runner.done():await runner
     if database_ready(path):
      db=sqlite3.connect(path)
      try:
       row=db.execute("SELECT value FROM counters WHERE key='archived_records'").fetchone()
       archived=row[0] if row else 0
      finally:db.close()
     if len(calls)>=2 and archived==40:break
     await asyncio.sleep(.02)
    self.assertGreaterEqual(len(calls),2,'fixture did not exercise repeated health yields')
    self.assertEqual(archived,40,'health scheduling blocked the independent archive pipeline')
   finally:stop.set();await runner

 async def test_hot_cleanup_progresses_while_next_archive_worker_is_pending(self):
  real_pool=concurrent.futures.ProcessPoolExecutor;pending=[]
  class Pool:
   def __init__(self,*a,**k):self.pool=real_pool(*a,**k)
   def submit(self,fn,*a,**k):
    if fn is EvidenceWriter.prepare_and_write_archive:
     future=concurrent.futures.Future();pending.append(future);return future
    return self.pool.submit(fn,*a,**k)
   def shutdown(self,*a,**k):
    for future in pending:future.cancel()
    return self.pool.shutdown(*a,**k)
  class SeededState(service.ServiceState):
   def __init__(self,path,config):
    super().__init__(path,config)
    rows=[replace(record(),scope='program:meteora',identity='overlap:%04d'%i,slot=900+i,market_time=10) for i in range(40)]
    self.writer.ingest(rows)
    plan=self.writer.archive_plan(1000,max_records=20)
    self.writer.commit_archive(plan,self.writer.write_archive(self.writer.path,plan))
  class Wire:
   def __init__(self):self.acks=asyncio.Queue();self.slot=1000
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def send(self,raw):
    request=json.loads(raw);await self.acks.put(json.dumps(dict(id=request['id'],result=request['id'])).encode())
   async def recv(self,decode=None):
    if not self.acks.empty():return await self.acks.get()
    await asyncio.sleep(.03);raw=block_frame(self.slot,padding_bytes=0,relevant_transactions=0)
    self.slot+=1;return raw.encode()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(service,'ServiceState',SeededState),patch('concurrent.futures.ProcessPoolExecutor',Pool),patch('websockets.asyncio.client.connect',return_value=Wire()):
   path=Path(td)/'db';stop=asyncio.Event()
   runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   count=0;deadline=time.monotonic()+8
   try:
    while time.monotonic()<deadline:
     if runner.done():await runner
     if database_ready(path):
      db=sqlite3.connect(path)
      try:
       row=db.execute("SELECT value FROM counters WHERE key='compacted_records'").fetchone()
       count=row[0] if row else 0
      finally:db.close()
     if pending and count>=20:break
     await asyncio.sleep(.02)
    self.assertTrue(pending,'fixture never admitted the archive task')
    self.assertFalse(pending[0].done(),'fixture archive worker must remain pending')
    self.assertGreaterEqual(count,20,'hot cleanup waited for unrelated archive preparation')
    self.assertEqual(len(pending),1,'archive task admission became unbounded')
   finally:
    stop.set();await runner
   db=sqlite3.connect(path)
   try:
    counters=json.loads(db.execute("SELECT value FROM service_health WHERE key='ipc'").fetchone()[0])
    self.assertGreater(counters['owner.stage.retention.calls'],0)
    self.assertGreater(counters['owner.stage.archive_plan.calls'],0)
    self.assertGreaterEqual(counters['owner.stage.retention.queue_total_microseconds'],0)
    labels={k.split('.')[2] for k in counters if k.startswith('owner.stage.')}
    self.assertLessEqual(labels,{'archive_plan','archive_commit_plan','retention','maintenance_health','health_ipc','health_scheduler'})
   finally:db.close()

if __name__=='__main__':unittest.main()
