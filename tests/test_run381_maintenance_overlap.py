"""Hot cleanup must progress independently of a pending archive worker."""
import asyncio,concurrent.futures,json,sqlite3,tempfile,threading,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from meme_machine.solana_evidence_plane import EvidenceWriter
import meme_machine.solana_evidence_service as service
from tests.test_run381_retention_progress import record,proof
from tests.test_run373_dispatch_throughput import block_frame,database_ready
from tests.evidence_ipc_harness import ipc_transport

class CheckpointRecyclingTests(unittest.TestCase):
 def test_transient_reader_and_concurrent_tail_are_recycled_without_losing_commits(self):
  from meme_machine.solana_provider_config import AlchemyEndpoint
  native_connect=sqlite3.connect
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'db'
   state=service.ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
   reader=native_connect(path,isolation_level=None)
   expected={};sizes=[];calls=[]
   try:
    for cycle in range(12):
     # A short reader protects a prior snapshot while production source rows
     # commit. It ends just after the bulk copy, like an overlapping consumer.
     reader.execute('BEGIN');reader.execute('SELECT COUNT(*) FROM records').fetchone()
     rows=[replace(record(),identity='recycle:%d:%d'%(cycle,i),signature='s:%d:%d'%(cycle,i),
                   payload={'body':str(cycle)+':'+str(i)+'x'*1024}) for i in range(8)]
     state.writer.ingest(rows,proof=proof(10,10));expected.update({r.identity:r.body() for r in rows})
     class Connection(sqlite3.Connection):
      def execute(self,sql,*args,**kwargs):
       cursor=super().execute(sql,*args,**kwargs)
       calls.append(sql)
       if sql=='PRAGMA wal_checkpoint(PASSIVE)':
        # Append after this checkpoint's snapshot, before releasing the read
        # mark. A lone PASSIVE pass cannot make this last committed tail reusable.
        tail=replace(record(),identity='tail:'+str(cycle),signature='t:'+str(cycle))
        state.writer.ingest([tail]);expected[tail.identity]=tail.body()
        reader.execute('ROLLBACK')
       return cursor
     def connect(*args,**kwargs):
      kwargs.setdefault('factory',Connection);return native_connect(*args,**kwargs)
     with patch('sqlite3.connect',connect):
      EvidenceWriter.checkpoint(path)
      result=state.writer.finish_checkpoint()
      self.assertEqual(result[0],0);self.assertEqual(result[1],result[2])
     sizes.append(Path(str(path)+'-wal').stat().st_size)
    self.assertLessEqual(max(sizes),sizes[0]+64*1024,
                         'checkpoint reuse grew beyond the initialized WAL and one bounded tail')
    self.assertEqual(calls,['PRAGMA wal_checkpoint(PASSIVE)']*12)
    self.assertEqual(state.writer.db.execute('PRAGMA synchronous').fetchone()[0],2)
    self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
   finally:reader.close();state.close()
   from meme_machine.solana_evidence_plane import EvidenceReader
   reader=EvidenceReader(path)
   try:
    restored=reader.window('pump',10,10,as_of=1000)
    self.assertEqual({r['identity']:r for r in restored},expected)
   finally:reader.close()

 def test_pinned_reader_keeps_its_snapshot_and_checkpoint_returns_without_waiting(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'db';writer=EvidenceWriter(path);reader=sqlite3.connect(path,isolation_level=None)
   try:
    writer.db.execute('PRAGMA wal_autocheckpoint=0')
    writer.ingest([record()]);reader.execute('BEGIN')
    self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
    writer.ingest([replace(record(),identity='second',signature='second')])
    started=time.monotonic();result=EvidenceWriter.checkpoint(path)
    self.assertLess(time.monotonic()-started,1)
    self.assertNotEqual(result[1],result[2],'checkpoint must preserve a pinned read mark')
    final=writer.finish_checkpoint();self.assertNotEqual(final[1],final[2])
    self.assertGreater(Path(str(path)+'-wal').stat().st_size,0)
    self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)
    reader.execute('ROLLBACK')
    result=EvidenceWriter.checkpoint(path)
    self.assertEqual(result[0],0);self.assertEqual(result[1],result[2])
    self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)
    writer.db.execute('BEGIN IMMEDIATE')
    try:
     started=time.monotonic();result=EvidenceWriter.checkpoint(path)
     self.assertLess(time.monotonic()-started,1)
     with self.assertRaisesRegex(service.EvidenceUnavailable,'checkpoint_inside_source_transaction'):
      writer.finish_checkpoint()
    finally:writer.db.execute('ROLLBACK')
   finally:reader.close();writer.close()

class ArchiveCleanupOverlapTests(unittest.IsolatedAsyncioTestCase):
 async def test_slow_passive_checkpoint_cannot_block_source_and_is_joined_on_shutdown(self):
  from tests.test_run373_dispatch_throughput import SustainedSocket
  entered=threading.Event();release=threading.Event();calls=[]
  native_connect=sqlite3.connect
  class Connection(sqlite3.Connection):
   def execute(self,sql,*args,**kwargs):
    if sql=='PRAGMA wal_checkpoint(PASSIVE)':
     calls.append(threading.get_ident());entered.set()
     if not release.wait(8):raise TimeoutError('checkpoint regression fixture deadline')
    return super().execute(sql,*args,**kwargs)
  def connect(*args,**kwargs):
   kwargs.setdefault('factory',Connection)
   return native_connect(*args,**kwargs)
  class Wire(SustainedSocket):
   async def recv(self,decode=None):
    raw=await super().recv(decode)
    old='1790438999';now=str(int(time.time()))
    return raw.replace(old.encode(),now.encode()) if isinstance(raw,bytes) else raw.replace(old,now)
  wire=Wire(frames=20,interval=.02,padding_bytes=0,relevant_transactions=1)
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch('sqlite3.connect',connect),patch('websockets.asyncio.client.connect',return_value=wire):
   path=Path(td)/'db';stop=asyncio.Event()
   runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   try:
    deadline=time.monotonic()+5;accepted=0
    while time.monotonic()<deadline:
     if runner.done():await runner
     if entered.is_set():
      db=native_connect(path)
      try:
       row=db.execute("SELECT value FROM counters WHERE key='stream_accepted_messages'").fetchone()
       accepted=row[0] if row else 0
      finally:db.close()
     if accepted==20:break
     await asyncio.sleep(.01)
    self.assertTrue(entered.is_set())
    self.assertEqual(accepted,20,'passive disk flush blocked the serial source owner')
    self.assertEqual(len(calls),1,'checkpoint work accumulated behind an unfinished flush')
    stop.set();await asyncio.sleep(.05)
    self.assertFalse(runner.done(),'shutdown abandoned the accepted checkpoint worker')
   finally:
    release.set();stop.set();await asyncio.wait_for(runner,5)
   db=native_connect(path)
   try:
    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
    self.assertEqual(db.execute("SELECT COUNT(*) FROM stream_receipts WHERE scope='program:pumpswap'").fetchone()[0],20)
    self.assertEqual(db.execute("SELECT MAX(slot) FROM stream_receipts WHERE scope='program:pumpswap'").fetchone()[0],1019)
    self.assertEqual(db.execute("SELECT slot FROM cursors WHERE scope='program:pumpswap'").fetchone()[0],1018)
    self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0],2)
   finally:db.close()

 async def test_repeated_health_yields_cannot_starve_archive_progress(self):
  calls=[];finished=[]
  native_finish=EvidenceWriter.finish_checkpoint
  def finish(writer):
   finished.append(threading.get_ident());return native_finish(writer)
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
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(service,'ServiceState',SeededState),patch('websockets.asyncio.client.connect',return_value=Wire()),patch.object(EvidenceWriter,'finish_checkpoint',finish):
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
    self.assertTrue(finished,'production scheduler omitted the completed-copy boundary')
    self.assertEqual(len(set(finished)),1,'tail completion left the single writer owner')
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
    self.assertLessEqual(labels,{'archive_plan','archive_commit_plan','retention','maintenance_health','health_ipc','health_scheduler','checkpoint_finish'})
   finally:db.close()

if __name__=='__main__':unittest.main()
