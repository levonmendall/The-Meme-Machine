import asyncio,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.solana_evidence_service import serve
from meme_machine.solana_evidence_plane import EvidenceReader
from meme_machine.postgrad import PUMPSWAP_PROGRAM
from meme_machine.solana_evidence_runtime import SWAP_SCOPE

class FakeSocket:
    def __init__(self):self.queue=asyncio.Queue();self.subs={}
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def send(self,raw):
        req=json.loads(raw);self.subs[req['id']]=req
        await self.queue.put(json.dumps(dict(id=req['id'],result=req['id'])))
    async def recv(self):return await self.queue.get()
    async def inject(self,slot,logs):
        for identity,req in self.subs.items():
            if PUMPSWAP_PROGRAM not in str(req['params']):continue
            if req['method']=='logsSubscribe':
                msg=dict(method='logsNotification',params=dict(subscription=identity,result=dict(context=dict(slot=slot),value=dict(signature='synthetic'+str(slot),logs=logs,err=None))))
            elif req['method']=='blockSubscribe':
                msg=dict(method='blockNotification',params=dict(subscription=identity,result=dict(value=dict(slot=slot,err=None,block=dict(parentSlot=slot-1,blockhash='h'+str(slot),previousBlockhash='h'+str(slot-1),blockTime=int(time.time())-1,signatures=['synthetic'+str(slot)])))))
            else:continue
            await self.queue.put(json.dumps(msg))

class FakeIPC:
    def close(self):pass
    async def wait_closed(self):pass

async def local_server(*args,path,**kwargs):
    Path(path).touch();return FakeIPC()

class ServiceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def wait_for(self,predicate):
        for _ in range(200):
            if predicate():return
            await asyncio.sleep(.01)
        self.fail('offline service did not make progress')
    async def test_real_service_ingests_while_both_readers_are_paused_and_recovers(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/solana_evidence_plane/run-368-raw-pump.json').read_text())
        logs=fixture['records'][0]['response']['result']['meta']['logMessages']
        with tempfile.TemporaryDirectory() as temp,patch('meme_machine.solana_evidence_service.time.time',return_value=1790347000):
            path=Path(temp)/'db';socket=FakeSocket();stop=asyncio.Event()
            with patch('websockets.asyncio.client.connect',return_value=socket),patch('asyncio.start_unix_server',side_effect=local_server):
                task=asyncio.create_task(serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
                try:
                    await self.wait_for(lambda:len(socket.subs)==5)
                    pump=EvidenceReader(path);meteora=EvidenceReader(path)
                    pump.db.execute('BEGIN');pump.db.execute('SELECT COUNT(*) FROM records').fetchone()
                    for slot in range(100,104):await socket.inject(slot,logs)
                    await self.wait_for(lambda:meteora.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]==4)
                    self.assertEqual(pump.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
                    self.assertTrue(meteora.covered(SWAP_SCOPE,100,102,as_of=time.time()))
                    telemetry=meteora.telemetry()
                    self.assertGreater(telemetry['counters']['stream_bytes'],0)
                    self.assertGreaterEqual(telemetry['counters']['stream_messages'],5)
                    self.assertEqual(telemetry['service_health']['subscriptions']['by_evidence_class'],{'logs':2,'census':2,'transactions':1})
                    self.assertEqual(telemetry['service_health']['provider']['provider'],'alchemy_solana_mainnet')
                    self.assertNotIn('offline-test',json.dumps(telemetry))
                    pump.db.execute('ROLLBACK');meteora.db.execute('BEGIN');meteora.db.execute('SELECT COUNT(*) FROM records').fetchone()
                    for slot in range(104,107):await socket.inject(slot,logs)
                    await self.wait_for(lambda:pump.db.execute('SELECT COUNT(*) FROM records').fetchone()[0]==7)
                    self.assertEqual(meteora.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],4)
                    meteora.db.execute('ROLLBACK');pump.close();meteora.close()
                finally:stop.set();await task
            second=FakeSocket();stop=asyncio.Event()
            with patch('websockets.asyncio.client.connect',return_value=second),patch('asyncio.start_unix_server',side_effect=local_server):
                task=asyncio.create_task(serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
                try:
                    await self.wait_for(lambda:len(second.subs)==5)
                    reader=EvidenceReader(path)
                    self.assertEqual(reader.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],7)
                    self.assertGreaterEqual(reader.telemetry()['unresolved_gaps'],1)
                    self.assertEqual(reader.telemetry()['counters']['restarts'],1)
                    self.assertEqual(reader.db.execute('PRAGMA integrity_check').fetchone()[0],'ok');reader.close()
                finally:stop.set();await task
