import asyncio,copy,gzip,json,os,sqlite3,tempfile,time
from pathlib import Path
from unittest.mock import patch
import meme_machine.solana_evidence_service as service
from tests.test_run373_dispatch_throughput import database_ready
from tests.evidence_ipc_harness import ipc_transport
class Wire:
 def __init__(self):
  self.templates=json.loads(gzip.decompress((Path(__file__).resolve().parent/'tests/fixtures/run380-production-templates.json.gz').read_bytes()))['templates']
  txs=[]
  for kind,count in [('meteora',128),('pump',48),('pumpswap',80),('empty',256)]:
   for i in range(count):
    t=copy.deepcopy(self.templates[kind if kind!='empty' else 'pumpswap'][i%len(self.templates[kind if kind!='empty' else 'pumpswap'])]);t['transaction']['signatures']=['run380:1000:'+str(len(txs))]
    if kind=='empty':t['meta']['err']={'InstructionError':[0,{'Custom':1}]}
    txs.append(t)
  self.template=json.dumps(dict(method='blockNotification',params=dict(subscription=1,result=dict(value=dict(slot=1000,err=None,block=dict(parentSlot=999,blockhash='h1000',previousBlockhash='h999',blockTime=1000000000,transactions=txs))))),separators=(',',':')).encode()
  self.sent=0;self.frames=int(os.getenv('PRESSURE_FRAMES','160'));self.acks=asyncio.Queue();self.start=None
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
async def main():
 wire=Wire();stop=asyncio.Event();lag=[];started=time.monotonic()
 with tempfile.TemporaryDirectory() as td,ipc_transport(),patch('websockets.asyncio.client.connect',return_value=wire):
  path=Path(td)/'db';runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
  def snapshot():
   if not database_ready(path):return 0,None
   db=sqlite3.connect(path);n=db.execute("select value from counters where key='stream_accepted_messages'").fetchone();f=db.execute("select value from service_health where key='finalized_frontier:program:meteora'").fetchone();db.close();return (n[0] if n else 0,json.loads(f[0]) if f else None)
  try:
   while True:
    if runner.done():await runner
    n,f=await asyncio.to_thread(snapshot)
    if f:lag.append(time.time()-f['time'])
    if n>=wire.frames:break
    if time.monotonic()-started>300:raise RuntimeError('pressure_deadline')
    await asyncio.sleep(.1)
  finally:
   stop.set();await runner
   db=sqlite3.connect(path);health={k:json.loads(v) for k,v in db.execute('select key,value from service_health')};c=dict(db.execute('select key,value from counters'))
   print(json.dumps({'module':service.__file__,'frames':wire.frames,'frame_bytes':len(wire.template),'elapsed':time.monotonic()-started,'lag_peak':max(lag,default=0),'counters':c,'ipc':health.get('ipc'),'owner':health.get('owner_scheduler')},sort_keys=True),flush=True);db.close()
if __name__=='__main__':asyncio.run(main())
