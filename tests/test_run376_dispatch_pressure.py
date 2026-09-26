"""Run 376 mixed account/block pressure; no network, original memory bounds."""
import asyncio,json,sqlite3,tempfile,time,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from meme_machine.solana_evidence_plane import EvidenceReader,EvidenceWriter,EvidenceUnavailable
from meme_machine.solana_evidence_transport import Subscription
from meme_machine.solana_provider_config import AlchemyEndpoint
from meme_machine.solana_evidence_runtime import SWAP_SCOPE
import meme_machine.solana_evidence_service as service
from tests.test_run373_dispatch_throughput import local_server,database_ready,block_frame


def account_frame(slot):
    return json.dumps(dict(method='accountNotification',params=dict(subscription=2,
        result=dict(context=dict(slot=slot),value=dict(owner='program',data=['AA==','base64'],lamports=slot)))))


class MixedSocket:
    def __init__(self,frames=160):
        self.remaining=frames;self.queue=asyncio.Queue();self.index=0;self.deadline=None
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def send(self,raw):
        req=json.loads(raw)
        await self.queue.put(json.dumps(dict(id=req['id'],result=req['id'])))
    async def recv(self,decode=None):
        if not self.queue.empty():raw=await self.queue.get()
        elif self.remaining:
            if self.deadline is None:
                # Wait for initial account subscription before sending its data.
                await asyncio.sleep(.12);self.deadline=time.monotonic()
            self.deadline+=.012
            await asyncio.sleep(max(0,self.deadline-time.monotonic()))
            slot=1000+self.index//5
            raw=(block_frame(slot,padding_bytes=4*1024*1024,relevant_transactions=260)
                 if self.index%5==0 else account_frame(slot))
            self.index+=1;self.remaining-=1
        else:raw=await self.queue.get()
        return raw.encode() if decode is False else raw


class Run376PressureTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_large_blocks_and_accounts_drain_without_capacity_churn(self):
        # Four accounts per 4 MiB block models the preserved 3070:~893 mix.
        # Accelerated cadence + fixed 30ms FULL-commit cost recreates ordered-ready
        # pressure without depending on the host disk. Real decode, SQL and fsync.
        socket=MixedSocket();stop=asyncio.Event();original=EvidenceWriter.transaction
        @contextmanager
        def durability_cost(writer):
            outer=not writer.db.in_transaction
            with original(writer):yield
            if outer:time.sleep(.03)
        with tempfile.TemporaryDirectory() as folder,patch(
            'websockets.asyncio.client.connect',return_value=socket
        ),patch('asyncio.start_unix_server',side_effect=local_server),patch.object(
            EvidenceWriter,'transaction',durability_cost
        ),patch.object(service.ServiceState,'interests',return_value=['account-test']):
            path=Path(folder)/'db';runner=asyncio.create_task(service.serve(
                path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
            reader=None
            try:
                for _ in range(1500):
                    if database_ready(path):break
                    await asyncio.sleep(.01)
                reader=EvidenceReader(path)
                for _ in range(3000):
                    t=reader.telemetry()
                    if t['counters'].get('disconnect:local_receive_dispatch_capacity',0):break
                    if t['counters'].get('stream_accepted_messages',0)>=160:break
                    if runner.done():await runner
                    await asyncio.sleep(.01)
                self.assertEqual(t['counters'].get('disconnect:local_receive_dispatch_capacity',0),0)
                self.assertEqual(t['counters'].get('stream_accepted_messages',0),160)
                self.assertTrue(reader.covered(SWAP_SCOPE,1000,1030,as_of=time.time()))
            finally:
                if reader:reader.close()
                stop.set();await asyncio.gather(runner,return_exceptions=True)
            db=sqlite3.connect(path)
            health=dict(db.execute('SELECT key,value FROM service_health'))
            ipc=json.loads(health['ipc'])
            self.assertLessEqual(ipc['stream.outstanding_frames_peak'],64)
            self.assertLessEqual(ipc['stream.dispatch_bytes_peak'],96*1024*1024)
            self.assertEqual(ipc.get('stream.dispatch_queue_overflow',0),0)
            self.assertGreater(ipc['stream.commit_batch_saved_transactions'],32)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM records WHERE kind="account"').fetchone()[0],32)
            db.close()

    def test_mixed_batch_durability_order_and_invalid_frame_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            state=service.ServiceState(Path(folder)/'db',AlchemyEndpoint.parse(
                'https://solana-mainnet.g.alchemy.com/v2/offline-test'))
            block=Subscription('service','chain:solana','all','blocks',2)
            account=Subscription('service','account:account-test','account-test','account',0)
            items=[]
            for slot in (1000,1001):
                raw=block_frame(slot,padding_bytes=4096,relevant_transactions=1)
                items.extend([(block,json.loads(raw),time.time(),len(raw)),
                              (account,json.loads(account_frame(slot)),time.time(),len(account_frame(slot)))])
            try:
                self.assertEqual(state.source_batch(items),4)
                reader=EvidenceReader(state.writer.path)
                self.assertTrue(reader.covered(SWAP_SCOPE,1000,1000,as_of=time.time()))
                reader.close()
                bad=dict(items[-1][1]);bad['method']='wrong'
                with self.assertRaises(EvidenceUnavailable):
                    state.source_batch([(account,json.loads(account_frame(1002)),time.time(),200),
                                        (account,bad,time.time(),200)])
                # Valid predecessor is durable despite the failed following frame.
                db=sqlite3.connect(state.writer.path)
                self.assertEqual(db.execute('SELECT MAX(slot) FROM records WHERE kind="account"').fetchone()[0],1002)
                db.close()
                state.disconnected('deterministic_missing_frame')
                reader=EvidenceReader(state.writer.path)
                self.assertFalse(reader.covered(SWAP_SCOPE,1000,1002,as_of=time.time()))
                reader.close()
            finally:state.close()
