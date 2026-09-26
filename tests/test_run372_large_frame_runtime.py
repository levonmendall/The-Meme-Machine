import asyncio,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceReader
from meme_machine.solana_evidence_runtime import SWAP_SCOPE
from meme_machine.postgrad import PUMPSWAP_PROGRAM
import meme_machine.solana_evidence_service as service


class LargeFrameSocket:
    def __init__(self,frames):
        self.queue=asyncio.Queue()
        self.frames=list(frames)
        self.subs={}
        self.recv_count=0

    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass

    async def send(self,raw):
        req=json.loads(raw)
        self.subs[req['id']]=req
        await self.queue.put(json.dumps(dict(id=req['id'],result=req['id'])))

    async def recv(self):
        self.recv_count+=1
        if not self.queue.empty():
            return await self.queue.get()
        if self.frames:
            return self.frames.pop(0)
        return await self.queue.get()


class FakeIPC:
    def close(self):pass
    async def wait_closed(self):pass


async def local_server(*args,path,**kwargs):
    Path(path).touch()
    return FakeIPC()


def frame(slot,logs,padding):
    relevant=dict(
        transaction=dict(
            signatures=['synthetic'+str(slot)],
            message=dict(accountKeys=[PUMPSWAP_PROGRAM]),
        ),
        meta=dict(err=None,logMessages=logs),
    )
    unrelated=dict(
        transaction=dict(
            signatures=['padding'+str(slot)],
            message=dict(accountKeys=['unrelated']),
        ),
        meta=dict(err=None,logMessages=[padding]),
    )
    row=dict(
        method='blockNotification',
        params=dict(subscription=1,result=dict(value=dict(
            slot=slot,err=None,
            block=dict(
                parentSlot=slot-1,
                blockhash='h'+str(slot),
                previousBlockhash='h'+str(slot-1),
                blockTime=1790430000,
                transactions=[relevant,unrelated],
            ),
        ))),
    )
    return json.dumps(row,separators=(',',':'))


class Run372LargeFrameTests(unittest.IsolatedAsyncioTestCase):
    async def wait_for(self,predicate,attempts=400):
        for _ in range(attempts):
            if predicate():return
            await asyncio.sleep(.01)
        self.fail('large-frame service did not make progress')

    async def test_prepared_transport_keeps_event_loop_live_during_realistic_large_frames(self):
        logs=[]
        padding='x'*(7*1024*1024)
        frames=[frame(slot,logs,padding) for slot in range(300,304)]
        self.assertTrue(all(7_000_000<len(raw)<service.STREAM_MAX_MESSAGE_BYTES for raw in frames))

        original_decode=service.decode_source_message
        decode_calls=[0]
        def deliberately_slow_decode(raw,config):
            decode_calls[0]+=1
            time.sleep(.15)
            return original_decode(raw,config)

        ticks=[]
        async def heartbeat(stop):
            while not stop.is_set():
                ticks.append(time.monotonic())
                await asyncio.sleep(.01)

        with tempfile.TemporaryDirectory() as temp,patch('meme_machine.solana_evidence_service.time.time',return_value=1790430100):
            path=Path(temp)/'db';socket=LargeFrameSocket(frames);stop=asyncio.Event()
            with patch.object(service,'decode_source_message',side_effect=deliberately_slow_decode),patch('websockets.asyncio.client.connect',return_value=socket),patch('asyncio.start_unix_server',side_effect=local_server):
                runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
                ticker=asyncio.create_task(heartbeat(stop))
                try:
                    await self.wait_for(lambda:socket.recv_count>=5)
                    reader=EvidenceReader(path)
                    for _ in range(800):
                        snapshot=reader.telemetry()
                        if snapshot['counters'].get('stream_accepted_messages',0)>=4:
                            break
                        disconnects={k:v for k,v in snapshot['counters'].items()
                                     if k.startswith('disconnect:') and v}
                        if disconnects:
                            self.fail('large-frame disconnect '+json.dumps(disconnects,sort_keys=True))
                        await asyncio.sleep(.01)
                    else:
                        self.fail('large-frame acceptance stalled '+json.dumps(reader.telemetry(),sort_keys=True)[:4000])
                    await self.wait_for(lambda:'stream.raw_message_peak_bytes' in (reader.telemetry()['service_health'].get('ipc') or {}))
                    telemetry=reader.telemetry()
                    runtime=telemetry['service_health']['ipc']
                    self.assertEqual(decode_calls[0],4)
                    self.assertGreaterEqual(runtime['stream.raw_message_peak_bytes'],7_000_000)
                    self.assertGreaterEqual(runtime['stream.dispatch_queue_peak'],2)
                    self.assertGreater(runtime['stream.decode_peak_microseconds'],100_000)
                    self.assertEqual(telemetry['counters'].get('disconnect:local_receive_backpressure_ping_timeout',0),0)
                    self.assertEqual(runtime.get('stream.dispatch_queue_overflow',0),0)
                    self.assertTrue(reader.covered(SWAP_SCOPE,300,302,as_of=1790430100))
                    gaps=[b-a for a,b in zip(ticks,ticks[1:])]
                    self.assertTrue(gaps)
                    self.assertLess(max(gaps),.12)
                    reader.close()
                finally:
                    stop.set()
                    await asyncio.gather(runner,ticker,return_exceptions=True)


if __name__=='__main__':
    unittest.main()
