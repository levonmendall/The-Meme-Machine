"""Production-record work bounds, credential parity and shutdown under load."""
import asyncio,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,FinalizedRecord,IntervalProof,canonical,digest
from meme_machine.solana_provider_config import public_value,SECRET_PATTERN
import meme_machine.solana_evidence_service as service
from tests.test_run373_dispatch_throughput import BurstSocket,local_server,database_ready

def record():
 return FinalizedRecord('pump:signature:10:0','pump',10,'signature:10','program',('pool',),10,
   dict(value=1),'alchemy_finalized_stream','a'*64,100)

def proof():
 return IntervalProof('pump',10,10,'alchemy_finalized_stream','a'*64,
   dict(finalized=True,complete=True,scope='pump',lower_slot=10,upper_slot=10,
        lineage_hash=digest(['pump',10,10])),100)

class PersistenceWorkTests(unittest.TestCase):
 def test_credential_fast_path_is_equivalent_including_unicode_and_bare_key(self):
  cases=['x'*100000,'https://public.invalid/metadata',
    'HtTpS://solana-mainnet.g.alchemy.com/v2/private',
    'WSS://solana-mainnet.streaming.alchemy.com/v2/private',
    'APIKEY=value','API_KEY = value','api-key:value','AUTHORIZATION: Bearer',
    'apİkey=value','authorİzation:value','ſomething','https://evil.invalid/?alchemy.com/v2/private']
  for value in cases:
   with self.subTest(value=value[:80]):
    if SECRET_PATTERN.search(value):
     with self.assertRaisesRegex(ValueError,'credential'):public_value(value)
    else:self.assertEqual(public_value(value),value)
  with self.assertRaisesRegex(ValueError,'credential'):public_value('plain bare-secret string','bare-secret')
 def test_one_content_serialization_serves_size_hash_and_encoding(self):
  from meme_machine import solana_evidence_plane as plane,solana_evidence_storage as storage
  row=replace(record(),payload={'meta':{'logMessages':['safe'*2000]},'retained':True},
              addresses=tuple('account-'+str(i) for i in range(64)))
  expected=row.body();seen=[];old=canonical;old_storage=storage._json
  def capture(value):
   if isinstance(value,dict) and value.get('identity')==row.identity:seen.append('canonical')
   return old(value)
  def encode_capture(value):
   if isinstance(value,dict) and value.get('payload',{}).get('meta',{}).get('logMessages')==row.payload['meta']['logMessages']:seen.append('storage')
   return old_storage(value)
  with tempfile.TemporaryDirectory() as td:
   w=EvidenceWriter(Path(td)/'db')
   with patch.object(plane,'canonical',capture),patch.object(storage,'_json',encode_capture):w.ingest([row],proof=proof())
   self.assertEqual(seen,['canonical'])
   self.assertEqual(w.db.execute('SELECT hash FROM records').fetchone()[0],digest(expected))
   reader=EvidenceReader(w.path)
   self.assertEqual(reader.window(row.scope,10,10,as_of=100)[0]['payload'],expected['payload'])
   self.assertEqual(w.db.execute('SELECT count(*) FROM address_refs').fetchone()[0],64)
   self.assertEqual(w.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
   reader.close();w.close()

class StopDrainTests(unittest.IsolatedAsyncioTestCase):
 async def test_stop_drains_every_admitted_frame_before_process_close(self):
  socket=BurstSocket(frames=48);stop=asyncio.Event();original=service.ServiceState.source_batch
  def delayed(state,items):time.sleep(.08);return original(state,items)
  with tempfile.TemporaryDirectory() as td,patch('websockets.asyncio.client.connect',return_value=socket),patch('asyncio.start_unix_server',side_effect=local_server),patch.object(service.ServiceState,'source_batch',delayed):
   path=Path(td)/'db';runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   try:
    for _ in range(1000):
     if socket.remaining<24:break
     if runner.done():await runner
     await asyncio.sleep(.005)
    self.assertLess(socket.remaining,24)
   finally:stop.set()
   await runner
   db=sqlite3.connect(path);health=dict(db.execute('SELECT key,value FROM service_health'));ipc=json.loads(health['ipc'])
   self.assertGreater(ipc['stream.received_messages'],24)
   self.assertEqual(ipc['stream.received_messages'],ipc['stream.commit_messages'])
   self.assertEqual(json.loads(health['phase']),'OFF')
   self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',));db.close()
   self.assertFalse(Path(str(path)+'.sock').exists())

class ProductionSocket:
 def __init__(self,frames=40):
  import gzip
  self.templates=json.loads(gzip.decompress((Path(__import__('certification').__file__).parent/'tests/fixtures/run377-production-transactions.json.gz').read_bytes()))['transactions']
  self.frames=frames;self.sent=0;self.ack=asyncio.Queue();self.next_emit=None
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def send(self,raw):
  request=json.loads(raw);await self.ack.put(json.dumps(dict(id=request['id'],result=request['id'])))
 async def recv(self,decode=None):
  if not self.ack.empty():raw=await self.ack.get()
  elif self.sent<self.frames:
   if self.next_emit is None:self.next_emit=time.monotonic()
   self.next_emit+=.25
   await asyncio.sleep(max(0,self.next_emit-time.monotonic()))
   from copy import deepcopy
   transactions=[];slot=1000+self.sent
   for i in range(160):
    tx=deepcopy(self.templates[i%len(self.templates)])
    tx['transaction']['signatures']=['run377:%d:%d'%(slot,i)]
    transactions.append({k:tx[k] for k in ('transaction','meta','version')})
   raw=json.dumps(dict(method='blockNotification',params=dict(subscription=1,result=dict(value=dict(
    slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),
     blockTime=int(time.time())-1,transactions=transactions))))),separators=(',',':'))
   self.sent+=1
  else:raw=await self.ack.get()
  return raw.encode() if decode is False else raw

class ProductionPressureTests(unittest.IsolatedAsyncioTestCase):
 async def test_retained_dense_transaction_workload_drains_with_original_bounds(self):
  socket=ProductionSocket();stop=asyncio.Event()
  with tempfile.TemporaryDirectory() as td,patch('websockets.asyncio.client.connect',return_value=socket),patch('asyncio.start_unix_server',side_effect=local_server):
   path=Path(td)/'db';runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop));reader=None
   try:
    for _ in range(6000):
     if reader is None and database_ready(path):reader=EvidenceReader(path)
     if runner.done():await runner
     if reader and reader.telemetry()['counters'].get('stream_accepted_messages',0)>=40:break
     await asyncio.sleep(.01)
    else:self.fail('production-density backlog did not drain')
    t=reader.telemetry();self.assertEqual(t['counters']['stream_accepted_messages'],40)
    self.assertFalse({k:v for k,v in t['counters'].items() if k.startswith('disconnect:') and v})
    self.assertTrue(reader.covered('program:meteora',1000,1038,as_of=time.time()))
    self.assertGreater(t['address_references'],100000)
   finally:
    if reader:reader.close()
    stop.set();await runner
   db=sqlite3.connect(path);ipc=json.loads(dict(db.execute('SELECT key,value FROM service_health'))['ipc'])
   self.assertLessEqual(ipc['stream.outstanding_frames_peak'],64)
   self.assertLessEqual(ipc['stream.dispatch_bytes_peak'],96*1024*1024)
   self.assertEqual(ipc['stream.received_messages'],ipc['stream.commit_messages'])
   self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',));db.close()
