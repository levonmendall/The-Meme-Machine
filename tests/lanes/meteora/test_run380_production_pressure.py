"""Run 380 production bodies, fixed source clock, actual ordered SQLite pipeline.

Reconstructed envelopes and failed-transaction filler are explicitly synthetic.
Every source deadline is fixed before recv; backpressure cannot refresh its age.
"""
import asyncio,copy,gzip,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import meme_machine.lanes.meteora.solana_evidence_service as service
from tests.lanes.meteora.test_run373_dispatch_throughput import database_ready
from tests.lanes.meteora.evidence_ipc_harness import ipc_transport
class Wire:
 def __init__(self):
  self.templates=json.loads(gzip.decompress((Path(__import__('certification').__file__).parent/'tests/fixtures/run380-production-templates.json.gz').read_bytes()))['templates']
  txs=[]
  for kind,count in [('meteora',128),('pump',48),('pumpswap',80),('empty',256)]:
   for i in range(count):
    t=copy.deepcopy(self.templates[kind if kind!='empty' else 'pumpswap'][i%len(self.templates[kind if kind!='empty' else 'pumpswap'])]);t['transaction']['signatures']=['run380:1000:'+str(len(txs))]
    if kind=='empty':t['meta']['err']={'InstructionError':[0,{'Custom':1}]}
    txs.append(t)
  self.template=json.dumps(dict(method='blockNotification',params=dict(subscription=1,result=dict(value=dict(slot=1000,err=None,block=dict(parentSlot=999,blockhash='h1000',previousBlockhash='h999',blockTime=1000000000,transactions=txs))))),separators=(',',':')).encode()
  self.sent=0;self.frames=240;self.acks=asyncio.Queue();self.start=None
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def send(self,raw):
  r=json.loads(raw);await self.acks.put(json.dumps(dict(id=r['id'],result=r['id'])).encode())
 async def recv(self,decode=None):
  if not self.acks.empty():return await self.acks.get()
  if self.sent>=self.frames:return await self.acks.get()
  if self.start is None:self.start=time.time()
  due=self.start+self.sent*.27;await asyncio.sleep(max(0,due-time.time()));slot=1000+self.sent
  raw=self.template.replace(b'run380:1000:',('run380:'+str(slot)+':').encode())
  for old,new in [(b'"slot":1000,',f'"slot":{slot},'.encode()),(b'"parentSlot":999,',f'"parentSlot":{slot-1},'.encode()),(b'"blockhash":"h1000"',f'"blockhash":"h{slot}"'.encode()),(b'"previousBlockhash":"h999"',f'"previousBlockhash":"h{slot-1}"'.encode()),(b'"blockTime":1000000000,',f'"blockTime":{int(due)},'.encode())]:raw=raw.replace(old,new)
  self.sent+=1;return raw

class SourceClockPressureTests(unittest.IsolatedAsyncioTestCase):
 async def test_sustained_source_clock_candidate_progress_and_durable_drain(self):
  from meme_machine.lanes.meteora.solana_evidence_plane import EvidenceReader
  from meme_machine.lanes.meteora.solana_evidence_runtime import RuntimeEvidence
  wire=Wire();stop=asyncio.Event();lags=[];started=time.monotonic()
  with tempfile.TemporaryDirectory() as td,ipc_transport(),patch('websockets.asyncio.client.connect',return_value=wire):
   path=Path(td)/'db';runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   def snapshot():
    if not database_ready(path):return 0,None,0
    db=sqlite3.connect(path)
    try:
     n=db.execute("select value from counters where key='stream_accepted_messages'").fetchone()
     f=db.execute("select value from service_health where key='finalized_frontier:program:meteora'").fetchone()
     gaps=db.execute('select count(*) from gaps where repaired is null').fetchone()[0]
     return n[0] if n else 0,json.loads(f[0]) if f else None,gaps
    finally:db.close()
   def candidate():
    plane=RuntimeEvidence(path,owner='meteora')
    try:
     for _ in range(10):plane.command(op='counter',key='meteora.run380_control_probe',count=1)
     frontier=plane.frontier('program:meteora')
     rows=plane.reader.window('program:meteora',frontier,frontier,as_of=time.time())
     return len(rows)
    finally:plane.close()
   control=None;n=0
   try:
    while n<wire.frames:
     if runner.done():await runner
     n,f,gaps=await asyncio.to_thread(snapshot)
     self.assertEqual(gaps,0)
     if f:lags.append(time.time()-f['time'])
     if n>=20 and control is None:control=asyncio.create_task(asyncio.to_thread(candidate))
     if time.monotonic()-started>240:self.fail('source_clock_pressure_deadline')
     await asyncio.sleep(.1)
    self.assertEqual(await control,128)
    # Leave headroom inside the unchanged 60-second production freshness gate.
    self.assertLess(max(lags),45,'source clock fell behind despite a live process')
    reader=EvidenceReader(path)
    try:
     rows=reader.window('program:meteora',1238,1238,as_of=time.time())
     self.assertEqual(len(rows),128)
     self.assertTrue(all(r['slot']==1238 for r in rows))
     self.assertTrue(reader.covered('program:meteora',1000,1238,as_of=time.time()))
    finally:reader.close()
   finally:
    stop.set();await runner
    if control is not None:await asyncio.gather(control,return_exceptions=True)
   db=sqlite3.connect(path)
   try:
    health={k:json.loads(v) for k,v in db.execute('select key,value from service_health')}
    counters=dict(db.execute('select key,value from counters'));ipc=health['ipc']
    print('run380-source-clock',json.dumps(dict(frames=n,source_seconds=wire.frames*.27,
      lag_peak=max(lags,default=0),elapsed=time.monotonic()-started,ipc=ipc)),flush=True)
    self.assertEqual(counters['stream_accepted_messages'],wire.frames)
    self.assertFalse({k:v for k,v in counters.items() if k.startswith('disconnect:') and v})
    self.assertEqual(counters['meteora.run380_control_probe'],10)
    self.assertEqual(ipc['stream.received_messages'],ipc['stream.commit_messages'])
    self.assertLessEqual(ipc['stream.outstanding_frames_peak'],64)
    self.assertLessEqual(ipc['stream.dispatch_bytes_peak'],96*1024*1024)
    self.assertLessEqual(ipc['stream.commit_batch_bytes_peak'],16*1024*1024)
    self.assertEqual(db.execute('pragma integrity_check').fetchone(),('ok',))
   finally:db.close()

if __name__=='__main__':unittest.main()
