"""Run 380 production bodies, fixed source clock, actual ordered SQLite pipeline.

Reconstructed envelopes, event clocks and failed-transaction filler are explicitly synthetic.
Every source deadline is fixed before recv; backpressure cannot refresh its age.
"""
import asyncio,base64,copy,gzip,hashlib,json,re,sqlite3,struct,tempfile,time,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
import meme_machine.solana_evidence_service as service
from tests.test_dispatch_throughput import database_ready
from tests.evidence_ipc_harness import ipc_transport
class Wire:
 def __init__(self):
  self.templates=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/solana_evidence_plane/run380-production-templates.json.gz').read_bytes()))['templates']
  txs=[]
  for kind,count in [('meteora',128),('pump',48),('pumpswap',80),('empty',256)]:
   for i in range(count):
    t=copy.deepcopy(self.templates[kind if kind!='empty' else 'pumpswap'][i%len(self.templates[kind if kind!='empty' else 'pumpswap'])]);t['transaction']['signatures']=['run380:1000:'+str(len(txs))]
    if kind=='empty':t['meta']['err']={'InstructionError':[0,{'Custom':1}]}
    txs.append(t)
  # Captured event clocks must share the synthetic block's fixed source clock.
  # Preserve every captured byte except the protocol-defined event timestamp.
  self.event_clocks={}
  offsets={bytes([189,219,127,211,78,230,97,238]):89,
           bytes([103,244,82,31,44,245,119,119]):8,
           bytes([62,47,55,10,165,3,220,42]):8,
           hashlib.sha256(b'event:CompletePumpAmmMigrationEvent').digest()[:8]:128}
  for tx in txs:
   for line in tx['meta'].get('logMessages') or []:
    if not line.startswith('Program data: '):continue
    raw=base64.b64decode(line[14:],validate=True);offset=offsets.get(raw[:8])
    if raw[:8]==bytes([27,114,169,77,222,235,99,118]):
     offset=8
     for _ in range(3):
      size=struct.unpack_from('<I',raw,offset)[0];offset+=4+size
     offset+=128
    if offset is not None:self.event_clocks[line.encode()]=(raw,offset)
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
  replacements={}
  for encoded,(body,offset) in self.event_clocks.items():
   rebased=body[:offset]+struct.pack('<q',int(due))+body[offset+8:]
   replacements[encoded]=b'Program data: '+base64.b64encode(rebased)
  # One pass through the frame; repeated whole-frame scans would make the
  # synthetic generator itself an event-loop throughput bottleneck.
  raw=re.sub(rb'Program data: [A-Za-z0-9+/=]+',
             lambda match:replacements.get(match[0],match[0]),raw)
  self.sent+=1;return raw

class SyntheticClockTests(unittest.IsolatedAsyncioTestCase):
 async def test_rebase_preserves_all_nonclock_event_bytes(self):
  wire=Wire();wire.start=1791000000
  original=json.loads(wire.template)['params']['result']['value']['block']['transactions']
  with patch('time.time',return_value=wire.start+30),patch('asyncio.sleep',new_callable=AsyncMock):
   message=json.loads(await wire.recv())
  block=message['params']['result']['value']['block']
  self.assertEqual(block['blockTime'],wire.start)
  changed=0
  for old,new in zip(original,block['transactions']):
   for before,after in zip(old['meta'].get('logMessages') or [],new['meta'].get('logMessages') or []):
    clock=wire.event_clocks.get(before.encode())
    if clock is None:self.assertEqual(before,after);continue
    body,offset=clock;updated=base64.b64decode(after[14:],validate=True)
    self.assertEqual(body[:offset],updated[:offset])
    self.assertEqual(body[offset+8:],updated[offset+8:])
    self.assertEqual(struct.unpack_from('<q',updated,offset)[0],wire.start)
    changed+=1
  self.assertGreater(changed,0)
 async def test_delayed_receive_cannot_refresh_event_or_block_clock(self):
  wire=Wire();wire.start=1791000000;wire.sent=4
  with patch('time.time',return_value=wire.start+40),patch('asyncio.sleep',new_callable=AsyncMock):
   block=json.loads(await wire.recv())['params']['result']['value']['block']
  expected=int(wire.start+4*.27)
  self.assertEqual(block['blockTime'],expected)
  self.assertLess(block['blockTime'],wire.start+40)
  for tx in block['transactions']:
   for line in tx['meta'].get('logMessages') or []:
    if not line.startswith('Program data: '):continue
    updated=base64.b64decode(line[14:],validate=True)
    for body,offset in wire.event_clocks.values():
     if updated[:offset]==body[:offset] and updated[offset+8:]==body[offset+8:]:
      self.assertEqual(struct.unpack_from('<q',updated,offset)[0],expected);break

class SourceClockPressureTests(unittest.IsolatedAsyncioTestCase):
 async def test_sustained_source_clock_candidate_progress_and_durable_drain(self):
  from meme_machine.solana_evidence_plane import EvidenceReader
  from meme_machine.solana_evidence_runtime import RuntimeEvidence
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
