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
 def test_completed_bulk_copy_reclaims_physical_wal_at_owner_boundary(self):
  import random
  from meme_machine.solana_provider_config import AlchemyEndpoint
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'db'
   state=service.ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
   try:
    state.writer.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    rows=[replace(record(),identity='physical-wal:'+str(i),signature='physical-wal:'+str(i),
                  payload={'body':random.Random(i).randbytes(16*1024).hex()})
          for i in range(128)]
    state.writer.ingest(rows,proof=proof(10,10))
    wal=Path(str(path)+'-wal')
    self.assertGreater(wal.stat().st_size,2*1024*1024,
                       'fixture did not create meaningful physical WAL allocation')
    passive=EvidenceWriter.checkpoint(path)
    self.assertEqual(passive[0],0);self.assertEqual(passive[1],passive[2])
    self.assertGreater(wal.stat().st_size,2*1024*1024,
                       'PASSIVE unexpectedly hid the production physical-allocation defect')
    result=state.writer.finish_checkpoint()
    self.assertEqual(result,(0,0,0))
    self.assertEqual(wal.stat().st_size,0)
    self.assertEqual(state.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],128)
    self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
    self.assertEqual(state.writer.db.execute('PRAGMA synchronous').fetchone()[0],2)
   finally:state.close()

 def test_archive_commit_is_sliced_without_changing_immutable_manifest(self):
  from meme_machine.solana_provider_config import AlchemyEndpoint
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'db'
   state=service.ServiceState(path,AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/offline-test'))
   try:
    rows=[replace(record(),identity='archive-slice:%04d'%i,signature='archive-slice:%04d'%i,
                  slot=100+i,market_time=10) for i in range(300)]
    state.writer.ingest(rows)
    snapshot=state.writer.archive_snapshot(1000,max_records=300,max_bytes=16*1024*1024)
    plan,receipt=state.writer.prepare_and_write_archive(
      state.writer.path,snapshot,max_bytes=16*1024*1024)
    self.assertEqual(len(plan),300)
    remaining=state.archive_commit_slice(plan,receipt)
    self.assertEqual(remaining,[])
    self.assertEqual(state.writer.db.execute(
      'SELECT COUNT(*) FROM records WHERE body IS NULL').fetchone()[0],300)
    self.assertEqual(state.writer.db.execute(
      'SELECT records FROM archives WHERE name=?',(receipt['name'],)).fetchone()[0],300)
    self.assertEqual(state.writer.db.execute(
      'SELECT COUNT(*) FROM records WHERE body IS NULL').fetchone()[0],300)
    self.assertEqual(state.writer.db.execute(
      'SELECT records FROM archives WHERE name=?',(receipt['name'],)).fetchone()[0],300)
    self.assertEqual(state.writer.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
   finally:state.close()

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
    self.assertEqual(sizes,[0]*12,
                     'owner-boundary completion left physical WAL allocation hot')
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
    started=time.monotonic();final=writer.finish_checkpoint()
    self.assertLess(time.monotonic()-started,.5,'owner-boundary reclaim waited on a pinned reader')
    self.assertTrue(final[0]!=0 or final[1]!=final[2])
    self.assertGreater(Path(str(path)+'-wal').stat().st_size,0)
    self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)
    reader.execute('ROLLBACK')
    result=EvidenceWriter.checkpoint(path)
    self.assertEqual(result[0],0);self.assertEqual(result[1],result[2])
    final=writer.finish_checkpoint();self.assertEqual(final,(0,0,0))
    self.assertEqual(Path(str(path)+'-wal').stat().st_size,0)
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

 async def test_incomplete_passive_checkpoint_skips_owner_truncate(self):
  calls=[];finished=[]
  def checkpoint(path):
   calls.append(1);return (0,10,5)
  def finish(writer):
   finished.append(1);return (0,0,0)
  class Wire:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def send(self,raw):pass
   async def recv(self,decode=None):await asyncio.Future()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch(
      'websockets.asyncio.client.connect',return_value=Wire()),patch.object(
      EvidenceWriter,'checkpoint',side_effect=checkpoint),patch.object(
      EvidenceWriter,'finish_checkpoint',finish):
   path=Path(td)/'db';stop=asyncio.Event()
   runner=asyncio.create_task(service.serve(
     path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   try:
    deadline=time.monotonic()+3
    while time.monotonic()<deadline and not calls:
     if runner.done():await runner
     await asyncio.sleep(.02)
    self.assertTrue(calls,'fixture never exercised the passive checkpoint')
    await asyncio.sleep(.05)
    self.assertEqual(finished,[],
                     'incomplete PASSIVE copy still scheduled an owner TRUNCATE')
   finally:
    stop.set();await runner
   db=sqlite3.connect(path)
   try:
    counters=json.loads(db.execute(
      "SELECT value FROM service_health WHERE key='ipc'").fetchone()[0])
    self.assertGreaterEqual(counters.get('checkpoint.bulk_incomplete',0),1)
    self.assertEqual(counters.get('checkpoint.reclaimed',0),0)
   finally:db.close()

 async def test_completed_passive_checkpoint_joins_source_fifo_for_zero_wait_reset(self):
  calls=[];finished=[]
  def checkpoint(path):
   calls.append(1);return (0,0,0)
  def finish(writer):
   finished.append(threading.get_ident());return (0,0,0)
  class Wire:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def send(self,raw):pass
   async def recv(self,decode=None):await asyncio.Future()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch(
      'websockets.asyncio.client.connect',return_value=Wire()),patch.object(
      EvidenceWriter,'checkpoint',side_effect=checkpoint),patch.object(
      EvidenceWriter,'finish_checkpoint',finish):
   path=Path(td)/'db';stop=asyncio.Event()
   runner=asyncio.create_task(service.serve(
     path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   try:
    deadline=time.monotonic()+3
    while time.monotonic()<deadline and not finished:
     if runner.done():await runner
     await asyncio.sleep(.02)
    self.assertTrue(calls,'fixture never exercised the passive checkpoint')
    self.assertTrue(finished,'completed PASSIVE copy omitted the reset handshake')
   finally:
    stop.set();await runner
   db=sqlite3.connect(path)
   try:
    scheduler=json.loads(db.execute(
      "SELECT value FROM service_health WHERE key='owner_scheduler'").fetchone()[0])
    counters=json.loads(db.execute(
      "SELECT value FROM service_health WHERE key='ipc'").fetchone()[0])
    self.assertGreaterEqual(scheduler.get('priority2.completed',0),1,
                            'checkpoint reset did not join the normal source FIFO')
    self.assertGreaterEqual(counters.get('checkpoint.reclaimed',0),1)
    self.assertGreaterEqual(counters.get('owner.stage.checkpoint_finish.calls',0),1)
   finally:db.close()

 async def test_repeated_health_yields_cannot_starve_archive_progress(self):
  calls=[];finished=[];owner_threads=[]
  from meme_machine.solana_checkpoint import checkpoint_and_reclaim as native_boundary
  native_finish=EvidenceWriter.finish_checkpoint
  def finish(writer):
   result=native_finish(writer)
   if result==(0,0,0):finished.append(('owner',threading.get_ident()))
   return result
  def boundary(path):
   result=native_boundary(path)
   if result==(0,0,0):
    self.assertEqual(Path(str(path)+'-wal').stat().st_size,0)
    finished.append(('handoff',threading.get_ident()))
   return result
  class SeededState(service.ServiceState):
   def __init__(self,path,config):
    super().__init__(path,config);owner_threads.append(threading.get_ident())
    self.writer.ingest([replace(record(),identity='health-overlap:'+str(i),market_time=10) for i in range(40)])
   def maintenance_health(self,http):
    calls.append(1)
    raise service.EvidenceUnavailable('evidence_background_yield')
  class Wire:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def send(self,raw):pass
   async def recv(self,decode=None):await asyncio.Future()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch.object(service,'ServiceState',SeededState),patch('websockets.asyncio.client.connect',return_value=Wire()),patch.object(EvidenceWriter,'finish_checkpoint',finish),patch('meme_machine.solana_checkpoint.checkpoint_and_reclaim',side_effect=boundary):
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
     # Archive publication can invalidate an in-flight checkpoint. The
     # existing three-second deadline also covers the next safe reset.
     if len(calls)>=2 and archived==40 and finished:break
     await asyncio.sleep(.02)
    self.assertGreaterEqual(len(calls),2,'fixture did not exercise repeated health yields')
    self.assertEqual(archived,40,'health scheduling blocked the independent archive pipeline')
    self.assertTrue(finished,'production scheduler omitted the completed-copy boundary')
    self.assertTrue(all((thread==owner_threads[0])==(kind=='owner') for kind,thread in finished),
                    'checkpoint used the wrong execution owner')
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
    self.assertLessEqual(labels,{'archive_plan','archive_commit_plan','retention','maintenance_health','health_ipc','health_scheduler','checkpoint_prepare','checkpoint_finish','source_commit'})
   finally:db.close()

if __name__=='__main__':unittest.main()
