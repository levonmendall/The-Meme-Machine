import asyncio,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch

from meme_machine.postgrad import PUMPSWAP_PROGRAM
from meme_machine.solana_evidence_plane import EvidenceReader
from meme_machine.solana_evidence_runtime import SWAP_SCOPE
import meme_machine.solana_evidence_service as service


class FakeIPC:
    def close(self):pass
    async def wait_closed(self):pass


async def local_server(*args,path,**kwargs):
    Path(path).touch()
    return FakeIPC()


def block_frame(slot,*,padding_bytes,relevant_transactions=80):
    txs=[
        dict(
            transaction=dict(
                signatures=[f'relevant:{slot}:{index}'],
                message=dict(accountKeys=[PUMPSWAP_PROGRAM]),
            ),
            meta=dict(err=None,logMessages=[]),
        )
        for index in range(relevant_transactions)
    ]
    txs.append(dict(
        transaction=dict(
            signatures=[f'padding:{slot}'],
            message=dict(accountKeys=['unrelated']),
        ),
        meta=dict(err=None,logMessages=['x'*padding_bytes]),
    ))
    return json.dumps(dict(
        method='blockNotification',
        params=dict(subscription=1,result=dict(value=dict(
            slot=slot,err=None,
            block=dict(
                parentSlot=slot-1,
                blockhash='h'+str(slot),
                previousBlockhash='h'+str(slot-1),
                blockTime=1790438999,
                transactions=txs,
            ),
        ))),
    ),separators=(',',':'))


class SustainedSocket:
    def __init__(self,*,frames,interval,padding_bytes,relevant_transactions=80):
        self.queue=asyncio.Queue();self.subs={}
        self.remaining=frames;self.interval=interval
        self.padding_bytes=padding_bytes;self.relevant_transactions=relevant_transactions
        self.next_slot=1000;self.recv_count=0;self.next_emit=None

    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass

    async def send(self,raw):
        request=json.loads(raw);self.subs[request['id']]=request
        await self.queue.put(json.dumps(dict(id=request['id'],result=request['id'])))

    async def recv(self,decode=None):
        self.recv_count+=1
        if not self.queue.empty():
            raw=await self.queue.get()
        elif self.remaining:
            now=time.monotonic()
            if self.next_emit is None:self.next_emit=now+self.interval
            await asyncio.sleep(max(0.0,self.next_emit-now))
            self.next_emit+=self.interval
            slot=self.next_slot;self.next_slot+=1;self.remaining-=1
            raw=block_frame(
                slot,padding_bytes=self.padding_bytes,
                relevant_transactions=self.relevant_transactions,
            )
        else:
            raw=await self.queue.get()
        return raw.encode() if decode is False and isinstance(raw,str) else raw


class BurstSocket(SustainedSocket):
    def __init__(self,frames):
        super().__init__(frames=frames,interval=0,padding_bytes=1024,relevant_transactions=1)
        self.first_data=True

    async def recv(self,decode=None):
        if not self.queue.empty():
            self.recv_count+=1
            raw=await self.queue.get()
            return raw.encode() if decode is False and isinstance(raw,str) else raw
        if self.remaining:
            if self.first_data:
                self.first_data=False
                await asyncio.sleep(.08)
            self.recv_count+=1
            slot=self.next_slot;self.next_slot+=1;self.remaining-=1
            raw=block_frame(slot,padding_bytes=self.padding_bytes,relevant_transactions=1)
            return raw.encode() if decode is False else raw
        return await super().recv(decode=decode)


def database_ready(path):
    if not Path(path).exists():return False
    try:
        db=sqlite3.connect(path)
        required={'meta','counters','hot_chunks','address_refs','service_health','stream_receipts'}
        names={r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        initialized=(db.execute(
            "SELECT value FROM meta WHERE key='initialized'"
        ).fetchone() if 'meta' in names else None)
        db.close()
        return required.issubset(names) and initialized==('1',)
    except sqlite3.Error:
        return False


class Run373DispatchThroughputTests(unittest.IsolatedAsyncioTestCase):
    async def wait_for(self,predicate,attempts=5000,delay=.01):
        for _ in range(attempts):
            if predicate():return
            await asyncio.sleep(delay)
        self.fail('Run 373 dispatch repair did not make progress')

    async def test_sustains_run373_shaped_large_frame_rate_without_capacity_disconnect(self):
        # Fourteen ~10 MiB blocks at 0.75 s cadence is roughly 13 MiB/s,
        # matching the sustained/bursty range that filled Run 373's dispatch cap.
        frames=14
        socket=SustainedSocket(
            frames=frames,interval=.75,padding_bytes=10*1024*1024,
            relevant_transactions=80,
        )
        stop=asyncio.Event()
        with tempfile.TemporaryDirectory() as temp,patch(
            'meme_machine.solana_evidence_service.time.time',return_value=1790439000
        ),patch(
            'websockets.asyncio.client.connect',return_value=socket
        ),patch(
            'asyncio.start_unix_server',side_effect=local_server
        ):
            path=Path(temp)/'db'
            runner=asyncio.create_task(service.serve(
                path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop
            ))
            try:
                await self.wait_for(lambda:database_ready(path),attempts=2000)
                reader=EvidenceReader(path)
                for _ in range(3500):
                    telemetry=reader.telemetry();counters=telemetry['counters']
                    if counters.get('stream_accepted_messages',0)>=frames:
                        break
                    if runner.done():
                        exc=runner.exception()
                        self.fail('sustained service exited: '
                                  +(type(exc).__name__+':'+str(exc) if exc else 'clean'))
                    await asyncio.sleep(.01)
                else:
                    telemetry=reader.telemetry()
                    self.fail('sustained throughput incomplete '
                              +json.dumps({
                                  'counters':{k:v for k,v in telemetry['counters'].items()
                                              if k.startswith('stream_') or k.startswith('disconnect:')},
                                  'ipc':(telemetry['service_health'].get('ipc') or {}),
                                  'unresolved_gaps':telemetry.get('unresolved_gaps'),
                                  'remaining_frames':socket.remaining,
                              },sort_keys=True))
                await self.wait_for(
                    lambda:(reader.telemetry()['service_health'].get('ipc') or {}).get(
                        'stream.commit_messages',0
                    )>=frames+1,
                    attempts=2000,
                )
                telemetry=reader.telemetry();counters=telemetry['counters']
                ipc=telemetry['service_health']['ipc']
                self.assertEqual(counters.get('disconnect:local_receive_dispatch_capacity',0),0)
                self.assertEqual(counters.get('disconnect:local_receive_backpressure_ping_timeout',0),0)
                self.assertEqual(ipc.get('stream.dispatch_queue_overflow',0),0)
                self.assertGreaterEqual(ipc.get('stream.decode_process_messages',0),frames)
                self.assertGreaterEqual(ipc.get('stream.commit_messages',0),frames+1)
                self.assertGreaterEqual(ipc.get('stream.source_transactions',0),frames*81)
                self.assertGreaterEqual(ipc.get('stream.retained_transactions',0),frames*80)
                self.assertGreater(ipc.get('stream.raw_message_peak_bytes',0),10_000_000)
                self.assertLessEqual(
                    ipc.get('stream.dispatch_bytes_peak',0),
                    service.STREAM_DISPATCH_MAX_BYTES,
                )
                self.assertTrue(reader.covered(
                    SWAP_SCOPE,1000,1000+frames-2,as_of=1790439000
                ))
                reader.close()
            finally:
                stop.set()
                await asyncio.gather(runner,return_exceptions=True)

    async def test_full_block_census_uses_one_completion_not_per_signature_rows(self):
        # Run 375 showed that durable per-signature delivery + order rows created
        # avoidable write amplification. Full-block ingestion is already atomic,
        # so one census completion receipt is sufficient for Pump/PumpSwap.
        frames=6
        socket=SustainedSocket(
            frames=frames,interval=.02,padding_bytes=4096,
            relevant_transactions=250,
        )
        stop=asyncio.Event()
        with tempfile.TemporaryDirectory() as temp,patch(
            'meme_machine.solana_evidence_service.time.time',return_value=1790439000
        ),patch(
            'websockets.asyncio.client.connect',return_value=socket
        ),patch(
            'asyncio.start_unix_server',side_effect=local_server
        ):
            path=Path(temp)/'db'
            runner=asyncio.create_task(service.serve(
                path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop
            ))
            try:
                await self.wait_for(lambda:database_ready(path),attempts=2000)
                reader=EvidenceReader(path)
                for _ in range(3000):
                    counters=reader.telemetry()['counters']
                    if counters.get('stream_accepted_messages',0)>=frames:
                        break
                    if runner.done():
                        exc=runner.exception()
                        self.fail('completion service exited: '
                                  +(type(exc).__name__+':'+str(exc) if exc else 'clean'))
                    await asyncio.sleep(.01)
                else:
                    self.fail('completion path did not ingest all frames')
                await self.wait_for(
                    lambda:reader.db.execute(
                        'SELECT COUNT(*) FROM stream_completions WHERE scope=?',
                        (SWAP_SCOPE,)).fetchone()[0]>=frames,
                    attempts=2000,
                )
                self.assertEqual(reader.db.execute(
                    'SELECT COUNT(*) FROM stream_deliveries WHERE scope=?',
                    (SWAP_SCOPE,)).fetchone()[0],0)
                self.assertEqual(reader.db.execute(
                    'SELECT COUNT(*) FROM stream_order WHERE scope=?',
                    (SWAP_SCOPE,)).fetchone()[0],0)
                self.assertTrue(reader.covered(
                    SWAP_SCOPE,1000,1000+frames-2,as_of=1790439000
                ))
                reader.close()
            finally:
                stop.set()
                await asyncio.gather(runner,return_exceptions=True)

    async def test_capacity_overflow_drains_already_received_frames_before_gap(self):
        socket=BurstSocket(frames=8);stop=asyncio.Event()
        accepted_at_disconnect=[];reasons=[]
        original_source=service.ServiceState.source
        original_disconnected=service.ServiceState.disconnected

        def slow_source(state,*args,**kwargs):
            time.sleep(.12)
            return original_source(state,*args,**kwargs)

        def capture_disconnect(state,reason):
            row=state.writer.db.execute(
                "SELECT value FROM counters WHERE key='stream_accepted_messages'"
            ).fetchone()
            accepted_at_disconnect.append(int(row[0]) if row else 0)
            reasons.append(reason)
            return original_disconnected(state,reason)

        with tempfile.TemporaryDirectory() as temp,patch(
            'meme_machine.solana_evidence_service.time.time',return_value=1790439000
        ),patch.object(
            service,'STREAM_DISPATCH_MAX_MESSAGES',4
        ),patch.object(
            service,'STREAM_DISPATCH_MAX_BYTES',64*1024*1024
        ),patch.object(
            service.ServiceState,'source',slow_source
        ),patch.object(
            service.ServiceState,'disconnected',capture_disconnect
        ),patch(
            'websockets.asyncio.client.connect',return_value=socket
        ),patch(
            'asyncio.start_unix_server',side_effect=local_server
        ):
            path=Path(temp)/'db'
            runner=asyncio.create_task(service.serve(
                path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop
            ))
            try:
                await self.wait_for(lambda:bool(reasons),attempts=3000)
                self.assertEqual(reasons[0],'local_receive_dispatch_capacity')
                # The old implementation cancelled processors immediately on
                # overflow. One control ACK may still occupy an outstanding slot,
                # so the four-frame test bound must still drain at least three
                # admitted data frames before marking the discontinuity.
                self.assertGreaterEqual(accepted_at_disconnect[0],3)
            finally:
                stop.set()
                await asyncio.gather(runner,return_exceptions=True)


if __name__=='__main__':
    unittest.main()
