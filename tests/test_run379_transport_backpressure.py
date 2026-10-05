"""Real loopback websocket framing: paused data queues must not fake a lost source."""
import asyncio,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from websockets.asyncio.client import connect as real_connect
from websockets.asyncio.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed
import meme_machine.solana_evidence_service as service
from meme_machine.solana_evidence_plane import EvidenceReader
from tests.test_dispatch_throughput import block_frame,local_server,database_ready


class IdleSocket:
 def __init__(self):self.queue=asyncio.Queue();self.subs={}
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def send(self,raw):
  request=json.loads(raw);self.subs[request['id']]=request
  await self.queue.put(json.dumps(dict(id=request['id'],result=request['id'])))
 async def recv(self,decode=None):return (await self.queue.get()).encode()
 async def inject(self,slot):
  await self.queue.put(block_frame(slot,padding_bytes=0,relevant_transactions=1))


class TransportBackpressureTests(unittest.IsolatedAsyncioTestCase):
 async def test_silent_source_still_gets_a_bounded_explicit_gap(self):
  wire=IdleSocket();stop=asyncio.Event()
  with tempfile.TemporaryDirectory() as td,patch('websockets.asyncio.client.connect',return_value=wire),patch('asyncio.start_unix_server',side_effect=local_server),patch.object(service,'STREAM_SOURCE_IDLE_SECONDS',.1):
   path=Path(td)/'db';runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
   def observe():
    if not database_ready(path):return {}
    reader=EvidenceReader(path)
    try:return reader.telemetry()
    finally:reader.close()
   try:
    for _ in range(300):
     if wire.subs:break
     if runner.done():await runner
     await asyncio.sleep(.01)
    await wire.inject(100);await wire.inject(101)
    for _ in range(300):
     if runner.done():await runner
     t=await asyncio.to_thread(observe)
     if t.get('counters',{}).get('disconnect:source_receive_idle_timeout'):break
     await asyncio.sleep(.01)
    self.assertEqual(t['counters']['disconnect:source_receive_idle_timeout'],1)
    self.assertGreater(t['unresolved_gaps'],0)
    reader=EvidenceReader(path)
    try:self.assertFalse(reader.covered('program:pumpswap',101,102,as_of=time.time()))
    finally:reader.close()
   finally:stop.set();await runner

 async def test_real_protocol_queue_backpressure_drains_without_ping_disconnect(self):
  stopped=asyncio.Event();frames=320;connections=[]
  async def provider(ws):
   connections.append(ws)
   try:
    request=json.loads(await ws.recv());await ws.send(json.dumps(dict(id=request['id'],result=request['id'])))
    for slot in range(1000,1000+frames):
     await ws.send(block_frame(slot,padding_bytes=1024,relevant_transactions=1))
    await stopped.wait()
   except ConnectionClosed:pass
  original=service.ServiceState.source_batch
  def persistence_slice(state,items):
   # Scale the keepalive clock with this deterministic persistence delay; queue
   # and frame bounds remain the exact production values.
   time.sleep(.08);return original(state,items)
  async with ws_serve(provider,'127.0.0.1',0,ping_interval=None) as server:
   port=server.sockets[0].getsockname()[1]
   def connect(_url,**kwargs):
    kwargs['ping_interval']=.025
    if kwargs['ping_timeout'] is not None:kwargs['ping_timeout']=.025
    return real_connect('ws://127.0.0.1:'+str(port),**kwargs)
   with tempfile.TemporaryDirectory() as td,patch('websockets.asyncio.client.connect',side_effect=connect),patch('asyncio.start_unix_server',side_effect=local_server),patch.object(service.ServiceState,'source_batch',persistence_slice):
    path=Path(td)/'db';stop=asyncio.Event();runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
    def observe():
     if not database_ready(path):return {}
     reader=EvidenceReader(path)
     try:return reader.telemetry()
     finally:reader.close()
    try:
     for _ in range(700):
      if runner.done():await runner
      t=await asyncio.to_thread(observe)
      counters=t.get('counters',{})
      if counters.get('stream_accepted_messages',0)>=frames or any(k.startswith('disconnect:') and v for k,v in counters.items()):break
      await asyncio.sleep(.01)
     self.assertFalse({k:v for k,v in counters.items() if k.startswith('disconnect:') and v})
     self.assertEqual(counters.get('stream_accepted_messages'),frames)
     self.assertEqual(t['unresolved_gaps'],0)
     reader=EvidenceReader(path)
     try:self.assertTrue(reader.covered('program:pumpswap',1000,1318,as_of=time.time()))
     finally:reader.close()
    finally:stop.set();await runner;stopped.set()
    db=sqlite3.connect(path)
    ipc=json.loads(dict(db.execute('SELECT key,value FROM service_health'))['ipc'])
    self.assertEqual(ipc['stream.received_messages'],ipc['stream.commit_messages'])
    self.assertLessEqual(ipc['stream.outstanding_frames_peak'],64)
    self.assertLessEqual(ipc['stream.dispatch_bytes_peak'],96*1024*1024)
    self.assertGreater(ipc['stream.admission_waits'],0)
    self.assertEqual(len(connections),1)
    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',));db.close()


if __name__=='__main__':unittest.main()
