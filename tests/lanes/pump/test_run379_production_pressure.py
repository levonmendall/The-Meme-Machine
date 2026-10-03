"""Preserved production bodies with concurrent control and aged durable retention."""
import asyncio,gzip,json,sqlite3,tempfile,time,unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import meme_machine.lanes.pump.solana_evidence_service as service
from meme_machine.lanes.pump.solana_evidence_plane import EvidenceReader
from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence
from tests.lanes.pump.test_run373_dispatch_throughput import database_ready
from tests.lanes.pump.evidence_ipc_harness import ipc_transport


class RetainedSocket:
 def __init__(self):
  path=Path(__import__('certification').__file__).parent/'tests/fixtures/run379-production-transactions.json.gz'
  self.templates=json.loads(gzip.decompress(path.read_bytes()))['transactions']
  self.acks=asyncio.Queue();self.sent=0;self.frames=120;self.next_emit=None
  self.template=self.frame(0)
  self.template_time=int(json.loads(self.template)['params']['result']['value']['block']['blockTime'])
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def send(self,raw):
  request=json.loads(raw);await self.acks.put(json.dumps(dict(id=request['id'],result=request['id'])))
 def frame(self,number):
  slot=1000+number;txs=[]
  for i in range(160):
   tx=deepcopy(self.templates[i%len(self.templates)])
   tx['transaction']['signatures']=['run379:%d:%d'%(slot,i)];txs.append(tx)
  # Age the prefix to exercise the unchanged 180-second retention policy without
  # a three-minute test sleep. The fresh tail proves candidate-local progression.
  at=int(time.time())-(240 if number<100 else 1)
  return json.dumps(dict(method='blockNotification',params=dict(subscription=1,result=dict(value=dict(
   slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),
    blockTime=at,transactions=txs))))),separators=(',',':')).encode()
 async def recv(self,decode=None):
  if not self.acks.empty():return (await self.acks.get()).encode()
  if self.sent>=self.frames:return (await self.acks.get()).encode()
  if self.next_emit is None:self.next_emit=time.monotonic()
  self.next_emit+=.05;await asyncio.sleep(max(0,self.next_emit-time.monotonic()))
  # Provider-side JSON construction isn't service CPU. Prepare the retained
  # payload once, then rewrite only fixed-width fixture identities and clocks.
  slot=1000+self.sent;at=int(time.time())-(240 if self.sent<100 else 1)
  raw=self.template.replace(b'run379:1000:',('run379:'+str(slot)+':').encode())
  for old,new in ((b'"slot":1000,',f'"slot":{slot},'.encode()),
                  (b'"parentSlot":999,',f'"parentSlot":{slot-1},'.encode()),
                  (b'"blockhash":"h1000"',f'"blockhash":"h{slot}"'.encode()),
                  (b'"previousBlockhash":"h999"',f'"previousBlockhash":"h{slot-1}"'.encode()),
                  (f'"blockTime":{self.template_time},'.encode(),f'"blockTime":{at},'.encode())):
   raw=raw.replace(old,new)
  self.sent+=1;return raw


class ProductionPressureTests(unittest.IsolatedAsyncioTestCase):
 async def test_dense_commits_controls_and_retention_all_progress_with_original_bounds(self):
  wire=RetainedSocket();stop=asyncio.Event()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch('websockets.asyncio.client.connect',return_value=wire):
   path=Path(td)/'db';runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   def observe():
    if not database_ready(path):return {}
    reader=EvidenceReader(path)
    try:return dict(counters=dict(reader.db.execute('SELECT key,value FROM counters')))
    finally:reader.close()
   def controls():
    plane=RuntimeEvidence(path,owner='pump')
    try:
     for _ in range(25):plane.command(op='counter',key='pump.run379_control_probe',count=1)
    finally:plane.close()
   control=None;archived_before_finish=False
   try:
    for _ in range(9000):
     if runner.done():await runner
     t=await asyncio.to_thread(observe);c=t.get('counters',{})
     n=c.get('stream_accepted_messages',0)
     if n>=5 and control is None:control=asyncio.create_task(asyncio.to_thread(controls))
     if c.get('archived_records',0)>0 and n<wire.frames:archived_before_finish=True
     if n>=wire.frames:break
     await asyncio.sleep(.05)
    self.assertEqual(n,wire.frames)
    if control is not None:await control
    self.assertTrue(archived_before_finish,'retention starved behind continuous commits')
    reader=EvidenceReader(path)
    try:t=reader.telemetry()
    finally:reader.close()
    c=t['counters']
    self.assertEqual(c.get('pump.run379_control_probe'),25)
    self.assertFalse({k:v for k,v in c.items() if k.startswith('disconnect:') and v})
    self.assertEqual(t['unresolved_gaps'],0)
    reader=EvidenceReader(path)
    try:
     rows=reader.window('program:meteora',1118,1118,as_of=time.time())
     self.assertEqual(len(rows),160)
    finally:reader.close()
   finally:
    print('run379-pressure',json.dumps({k:t.get(k) for k in ('counters','unresolved_gaps','hot_bytes')}),flush=True)
    stop.set();await runner
    db=sqlite3.connect(path)
    health={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM service_health')}
    print('run379-stages',json.dumps({k:health.get(k) for k in ('ipc','owner_scheduler')}),flush=True)
    db.close()
    if control is not None:await asyncio.gather(control,return_exceptions=True)
   db=sqlite3.connect(path);ipc=json.loads(dict(db.execute('SELECT key,value FROM service_health'))['ipc'])
   self.assertEqual(ipc['stream.received_messages'],ipc['stream.commit_messages'])
   self.assertLessEqual(ipc['stream.outstanding_frames_peak'],64)
   self.assertLessEqual(ipc['stream.dispatch_bytes_peak'],96*1024*1024)
   self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',));db.close()


if __name__=='__main__':unittest.main()
