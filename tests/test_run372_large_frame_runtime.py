import asyncio,base64,json,struct,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceReader
from meme_machine.solana_evidence_runtime import SWAP_SCOPE
from meme_machine.lanes.pump.postgrad import PUMPSWAP_PROGRAM
import meme_machine.solana_evidence_service as service
from meme_machine.solana_program_decoders import PUMPSWAP_BUY_EVENT,pumpswap_trade_events


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

    async def recv(self,decode=None):
        self.recv_count+=1
        if not self.queue.empty():
            raw=await self.queue.get()
        elif self.frames:
            raw=self.frames.pop(0)
        else:
            raw=await self.queue.get()
        return raw.encode() if decode is False and isinstance(raw,str) else raw


class FakeIPC:
    def close(self):pass
    async def wait_closed(self):pass


async def local_server(*args,path,**kwargs):
    Path(path).touch()
    return FakeIPC()


async def observe(path,method='telemetry',*args,**kwargs):
    # The independently scheduled reader is not part of the transport event
    # loop. Synchronous SQLite/filesystem probes must not manufacture loop lag.
    def read():
        reader=EvidenceReader(path)
        try:return getattr(reader,method)(*args,**kwargs)
        finally:reader.close()
    return await asyncio.to_thread(read)


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
    @unittest.skip('MODEL A archived; engineering/solana_startup_archive/README.md')
    def test_shared_pumpswap_decoder_is_strategy_independent_and_available(self):
        values=[
            1790430000,  # timestamp
            11,          # base amount
            12,13,14,    # limit/user amounts
            1000,2000,   # pool reserves
            22,           # quote amount
            30,31,32,33,34,35,
        ]
        raw=PUMPSWAP_BUY_EVENT+struct.pack('<q',values[0])+b''.join(
            struct.pack('<Q',v) for v in values[1:]
        )+bytes(range(32))+bytes(range(32,64))
        self.assertEqual(len(raw),184)
        tx=dict(slot=444,meta=dict(err=None,logMessages=[
            'Program '+PUMPSWAP_PROGRAM+' invoke [1]',
            'Program data: '+base64.b64encode(raw).decode(),
            'Program '+PUMPSWAP_PROGRAM+' success',
        ]))
        rows=pumpswap_trade_events(tx)
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['buy'])
        self.assertEqual(rows[0]['amount'],22)
        self.assertEqual(rows[0]['tokens'],11)
        self.assertEqual(rows[0]['pool_base_reserve'],1000)
        self.assertEqual(rows[0]['pool_quote_reserve'],2000)
        self.assertEqual(rows[0]['slot'],444)

    async def wait_for(self,predicate,attempts=1000):
        for _ in range(attempts):
            if predicate():return
            await asyncio.sleep(.01)
        self.fail('large-frame service did not make progress')

    @unittest.skip('MODEL A archived; engineering/solana_startup_archive/README.md')
    async def test_prepared_transport_keeps_event_loop_live_during_realistic_large_frames(self):
        await self.exercise_large_frames()

    @unittest.skip('MODEL A archived; engineering/solana_startup_archive/README.md')
    async def test_slow_independent_observer_does_not_manufacture_transport_lag(self):
        original=EvidenceReader.telemetry;first=[True]
        def slow(reader):
            if first[0]:first[0]=False;time.sleep(.60)
            return original(reader)
        with patch.object(EvidenceReader,'telemetry',slow):
            await self.exercise_large_frames()
        self.assertFalse(first[0])

    @unittest.skip('MODEL A archived; engineering/solana_startup_archive/README.md')
    async def test_real_receive_loop_stall_still_fails_the_original_limit(self):
        original=LargeFrameSocket.recv;first=[True]
        async def stalled(socket,decode=None):
            if first[0] and socket.frames and socket.queue.empty():
                first[0]=False;time.sleep(.60)
            return await original(socket,decode=decode)
        with patch.object(LargeFrameSocket,'recv',stalled):
            with self.assertRaisesRegex(AssertionError,'not less than 0.5'):
                await self.exercise_large_frames()

    async def exercise_large_frames(self):
        logs=[]
        padding='x'*(7*1024*1024)
        frames=[frame(slot,logs,padding) for slot in range(300,304)]
        self.assertTrue(all(7_000_000<len(raw)<service.STREAM_MAX_MESSAGE_BYTES for raw in frames))

        ticks=[]
        async def heartbeat(stop):
            while not stop.is_set():
                ticks.append(time.monotonic())
                await asyncio.sleep(.01)

        with tempfile.TemporaryDirectory() as temp,patch('meme_machine.solana_evidence_service.time.time',return_value=1790430100):
            path=Path(temp)/'db';socket=LargeFrameSocket(frames);stop=asyncio.Event()
            with patch('websockets.asyncio.client.connect',return_value=socket),patch('asyncio.start_unix_server',side_effect=local_server):
                runner=asyncio.create_task(service.serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
                ticker=asyncio.create_task(heartbeat(stop))
                try:
                    for _ in range(1000):
                        if socket.recv_count>=5:
                            break
                        if runner.done():
                            exc=runner.exception()
                            self.fail('large-frame service exited before receive: '
                                      +type(exc).__name__+':'+str(exc))
                        await asyncio.sleep(.01)
                    else:
                        self.fail('large-frame websocket receive did not start')
                    for _ in range(800):
                        snapshot=await observe(path)
                        if snapshot['counters'].get('stream_accepted_messages',0)>=4:
                            break
                        disconnects={k:v for k,v in snapshot['counters'].items()
                                     if k.startswith('disconnect:') and v}
                        if disconnects:
                            self.fail('large-frame disconnect '+json.dumps(disconnects,sort_keys=True))
                        await asyncio.sleep(.01)
                    else:
                        self.fail('large-frame acceptance stalled '+json.dumps(await observe(path),sort_keys=True)[:4000])
                    for _ in range(1000):
                        telemetry=await observe(path)
                        runtime=telemetry['service_health'].get('ipc') or {}
                        if (runtime.get('stream.decode_process_messages',0)>=4
                                and 'stream.event_loop_lag_peak_microseconds' in runtime):break
                        await asyncio.sleep(.01)
                    else:self.fail('large-frame service telemetry did not make progress')
                    runtime=telemetry['service_health']['ipc']
                    self.assertEqual(runtime['stream.decode_process_messages'],4)
                    self.assertGreaterEqual(runtime['stream.raw_message_peak_bytes'],7_000_000)
                    self.assertGreaterEqual(runtime['stream.dispatch_queue_peak'],2)
                    self.assertEqual(runtime['stream.source_transactions'],8)
                    self.assertEqual(runtime['stream.retained_transactions'],4)
                    self.assertEqual(telemetry['counters'].get('disconnect:local_receive_backpressure_ping_timeout',0),0)
                    self.assertEqual(runtime.get('stream.dispatch_queue_overflow',0),0)
                    self.assertTrue(await observe(path,'covered',SWAP_SCOPE,300,302,as_of=1790430100))
                    gaps=[b-a for a,b in zip(ticks,ticks[1:])]
                    self.assertTrue(gaps)
                    self.assertLess(max(gaps),.5)
                    self.assertLess(
                        runtime['stream.event_loop_lag_peak_microseconds'],
                        500_000,
                    )
                finally:
                    stop.set()
                    await asyncio.gather(runner,ticker,return_exceptions=True)


if __name__=='__main__':
    unittest.main()
