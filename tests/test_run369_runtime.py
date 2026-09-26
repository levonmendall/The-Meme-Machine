"""Run 369 regressions. All sockets/providers are local deterministic fixtures."""
import asyncio
import json
import tempfile
import time
import unittest
import threading
import socket
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from meme_machine.solana_evidence_plane import EvidenceWriter, EvidenceReader, EvidenceUnavailable
from meme_machine.solana_evidence_service import FinalizedFence, serve
from meme_machine.solana_evidence_runtime import RuntimeEvidence, METEORA_SCOPE
from meme_machine.solana_evidence_transport import Subscription
from tests.test_solana_evidence_service_runtime import FakeSocket
from tests.evidence_ipc_harness import ipc_transport

PROGRAM = 'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo'


def block(slot=10):
    def tx(sig, program):
        return dict(transaction=dict(signatures=[sig], message=dict(accountKeys=[program])),
                    meta=dict(err=None, logMessages=[], loadedAddresses=dict(writable=[], readonly=[])))
    return dict(method='blockNotification', params=dict(result=dict(value=dict(slot=slot, err=None,
        block=dict(parentSlot=slot-1, blockhash='h'+str(slot), previousBlockhash='h'+str(slot-1),
                   blockTime=slot, transactions=[tx('target'+str(slot), PROGRAM), tx('other'+str(slot), 'other')])))))


class Run369SourceTests(unittest.TestCase):
    def test_running_background_sql_yields_without_poisoning_owner(self):
        from meme_machine.solana_evidence_control import PriorityOwner
        with tempfile.TemporaryDirectory() as temp:
            entered=threading.Event()
            def state():
                writer=EvidenceWriter(Path(temp)/'db')
                return SimpleNamespace(writer=writer,close=writer.close)
            owner=PriorityOwner(state)
            def repair(state):
                with state.writer.transaction():
                    state.writer.db.execute("INSERT INTO counters VALUES('rolled_back',1)")
                    entered.set()
                    state.writer.db.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
            try:
                owner.ready.result(1);background=owner.submit(repair,priority=4)
                self.assertTrue(entered.wait(1))
                foreground=owner.submit(lambda s:s.writer.db.execute("SELECT COUNT(*) FROM counters WHERE key='rolled_back'").fetchone()[0],priority=0)
                self.assertEqual(foreground.result(1),0)
                with self.assertRaisesRegex(EvidenceUnavailable,'evidence_background_yield'):background.result(1)
                self.assertEqual(owner.submit(lambda s:42).result(1),42)
            finally:owner.close()

    def test_pool_pin_and_finite_gap_do_not_pin_unrelated_program_tail(self):
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db',clock=lambda:100)
            try:
                fence=FinalizedFence(writer,endpoint_identity='a'*64)
                sub=Subscription('service',METEORA_SCOPE,PROGRAM,'transactions',4)
                for slot in (10,11,12):fence.block(sub,block(slot),100)
                fence.command(dict(op='interest',owner='position',scope=METEORA_SCOPE,lower_slot=0,
                    addresses=['pool'],lifecycle='open',priority=0))
                writer.gap(METEORA_SCOPE,10,10)
                self.assertEqual([r['body']['slot'] for r in writer.archive_plan(100)],[11,12])
                plan=writer.archive_plan(100)
                fence.command(dict(op='interest',owner='second',scope=METEORA_SCOPE,lower_slot=11,
                    addresses=[PROGRAM],lifecycle='reserved',priority=0))
                self.assertEqual(writer.commit_archive(plan,writer.write_archive(writer.path,plan)),0)
            finally:writer.close()

    def test_whole_block_is_filtered_before_meteora_storage_and_census(self):
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db', clock=lambda:100)
            try:
                fence=FinalizedFence(writer, endpoint_identity='a'*64)
                sub=Subscription('service', METEORA_SCOPE, PROGRAM, 'transactions', 4)
                fence.block(sub, block(), 100)
                self.assertEqual(writer.db.execute('SELECT signature FROM records').fetchall(), [('target10',)])
                census=json.loads(writer.db.execute('SELECT census FROM stream_receipts').fetchone()[0])
                self.assertEqual(census, ['target10'])
            finally: writer.close()

    def test_signature_only_census_is_rejected_and_alt_program_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db',clock=lambda:100)
            try:
                fence=FinalizedFence(writer,endpoint_identity='a'*64,decoders={METEORA_SCOPE:lambda _:[]})
                sub=Subscription('service',METEORA_SCOPE,PROGRAM,'census',4)
                message=block();body=message['params']['result']['value']['block']
                body.pop('transactions');body['signatures']=['unknown-program']
                with self.assertRaises(EvidenceUnavailable):fence.block(sub,message,100)
                self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],0)
                message=block();tx=message['params']['result']['value']['block']['transactions'][0]
                tx['transaction']['message']['accountKeys']=[];tx['meta']['loadedAddresses']['readonly']=[PROGRAM]
                fence.block(Subscription('service',METEORA_SCOPE,PROGRAM,'transactions',4),message,100)
                self.assertEqual(writer.db.execute('SELECT signature FROM records').fetchall(),[('target10',)])
            finally:writer.close()

    def test_durable_receipts_deduplicate_all_mutations_and_reject_identity_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db';writer=EvidenceWriter(path,clock=lambda:100)
            fence=FinalizedFence(writer,endpoint_identity='a'*64)
            requests=[dict(op='interest',scope='scope',lower_slot=10,addresses=['pool'],lifecycle='reserved',priority=0),
                      dict(op='ack',scope='scope',slot=10),dict(op='counter',key='pump.retry',count=7),
                      dict(op='release',scope='scope',resolved=True)]
            try:
                for i,request in enumerate(requests):
                    request.update(owner='pump:owner',consumer='pump',request_id=str(i),expires_at=103)
                    first=fence.command(request);self.assertTrue(first['ok'])
                    self.assertEqual(fence.command(request),first)
                writer.close();writer=EvidenceWriter(path,clock=lambda:101)
                fence=FinalizedFence(writer,endpoint_identity='a'*64)
                for request in requests:self.assertTrue(fence.command(request)['ok'])
                self.assertEqual(writer.db.execute("SELECT value FROM counters WHERE key='pump.retry'").fetchone()[0],7)
                self.assertEqual(writer.db.execute('SELECT active FROM interests').fetchone()[0],0)
                self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM consumers').fetchone()[0],1)
                with self.assertRaises(EvidenceUnavailable):fence.command(dict(requests[2],count=8))
                with patch('meme_machine.solana_evidence_control.MAX_RECEIPTS',4):
                    result=fence.command(dict(requests[2],request_id='overflow'))
                    self.assertEqual(result['error'],'evidence_receipt_capacity')
                self.assertEqual(writer.db.execute("SELECT value FROM counters WHERE key='pump.retry'").fetchone()[0],7)
                writer.clock=lambda:120
                with self.assertRaises(EvidenceUnavailable):fence.command(requests[2])
            finally:writer.close()

    def test_health_states_and_stale_history_fail_closed(self):
        from meme_machine.solana_evidence_health import HealthWatch
        with tempfile.TemporaryDirectory() as temp:
            now=[100];writer=EvidenceWriter(Path(temp)/'db',clock=lambda:now[0]);fence=FinalizedFence(writer,endpoint_identity='a'*64)
            plane=RuntimeEvidence(writer.path,owner='meteora',clock=lambda:now[0],command=fence.command)
            try:
                fence.health('phase','WARMING');fence.health('heartbeat',100)
                self.assertEqual(plane.health(METEORA_SCOPE)['state'],'WARMING')
                for slot in (98,99,100):fence.block(Subscription('service',METEORA_SCOPE,PROGRAM,'transactions',4),block(slot),100)
                fence.health('phase','ACTIVE')
                self.assertTrue(plane.require_usable(METEORA_SCOPE)['usable'])
                writer.gap(METEORA_SCOPE,99,99)
                self.assertEqual(plane.health(METEORA_SCOPE)['state'],'DEGRADED')
                with self.assertRaises(EvidenceUnavailable):plane.frontier(METEORA_SCOPE)
                fence.health('phase','DRAINING');self.assertEqual(plane.health(METEORA_SCOPE)['state'],'DRAINING')
                fence.health('phase','ACTIVE');now[0]=116
                self.assertEqual(plane.health(METEORA_SCOPE)['state'],'FAILED')
                self.assertFalse(plane.admit_candidate(METEORA_SCOPE,addresses=['pool'],owner='meteora:new')['accepted'])
                watch=HealthWatch(0)
                unhealthy=dict(state='WARMING',usable=False,reason='evidence_cold_start')
                self.assertIsNone(watch.observe(unhealthy,89))
                self.assertEqual(watch.observe(unhealthy,90),'evidence_cold_start')
                self.assertEqual(watch.observe(unhealthy,600),'evidence_cold_start')
            finally:plane.close();writer.close()

    def test_missing_service_is_classified_meteora_admission(self):
        with tempfile.TemporaryDirectory() as temp:
            plane=RuntimeEvidence(Path(temp)/'missing',owner='meteora')
            result=plane.admit_candidate(METEORA_SCOPE,addresses=['pool'],owner='meteora:new')
            self.assertFalse(result['accepted']);self.assertFalse(result['economic_rejection'])
            self.assertEqual(result['reason'],'evidence_service_unavailable');plane.close()

    def test_bounded_priority_owner_repair_cannot_starve_lifecycle_or_foreground(self):
        from meme_machine.solana_evidence_control import PriorityOwner
        entered=threading.Event();release=threading.Event();order=[]
        owner=PriorityOwner(lambda:SimpleNamespace(close=lambda:None),capacity=4,reserved=1)
        try:
            owner.ready.result(1)
            blocker=owner.submit(lambda state:(entered.set(),release.wait(2)),priority=4)
            self.assertTrue(entered.wait(1))
            queued=[owner.submit(lambda state,i=i:order.append('repair'+str(i)),priority=4) for i in range(2)]
            foreground=owner.submit(lambda state:order.append('foreground'),priority=1)
            with self.assertRaises(EvidenceUnavailable):owner.submit(lambda state:None,priority=4)
            lifecycle=owner.submit(lambda state:order.append('lifecycle'),priority=0)
            with self.assertRaises(EvidenceUnavailable):owner.submit(lambda state:None,priority=0)
            release.set();blocker.result(1)
            for future in [*queued,foreground,lifecycle]:future.result(1)
            self.assertEqual(order[:2],['lifecycle','foreground'])
        finally:release.set();owner.close()


class Run369IPCTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_after_old_250ms_limit_is_acknowledged_once(self):
        original=FinalizedFence.command
        def slow(fence, request):
            time.sleep(.35)
            return original(fence, request)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db'; stop=asyncio.Event();wire=FakeSocket()
            with ipc_transport(),patch('websockets.asyncio.client.connect', return_value=wire), patch.object(FinalizedFence,'command',slow):
                task=asyncio.create_task(serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
                try:
                    for _ in range(200):
                        if Path(str(path)+'.sock').exists(): break
                        if task.done(): await task
                        await asyncio.sleep(.01)
                    for _ in range(200):
                        if wire.subs:break
                        await asyncio.sleep(.01)
                    await wire.inject(100,[]);await wire.inject(101,[])
                    for _ in range(200):
                        probe=RuntimeEvidence(path,owner='probe')
                        ready=probe.health(METEORA_SCOPE)['usable'];probe.close()
                        if ready:break
                        await asyncio.sleep(.01)
                    def client():
                        plane=RuntimeEvidence(path,owner='meteora')
                        try: return plane.admit_candidate(METEORA_SCOPE,addresses=['pool'],owner='meteora:candidate:pool')
                        finally: plane.close()
                    self.assertTrue((await asyncio.to_thread(client))['accepted'])
                    reader=EvidenceReader(path)
                    try: self.assertEqual(reader.db.execute('SELECT COUNT(*) FROM interests').fetchone()[0],1)
                    finally: reader.close()
                finally: stop.set(); await task

    async def test_disconnected_client_commit_retry_and_service_survival(self):
        original=FinalizedFence.command
        def slow(fence,request):time.sleep(.1);return original(fence,request)
        with tempfile.TemporaryDirectory() as temp,ipc_transport():
            path=Path(temp)/'db';stop=asyncio.Event();errors=[]
            loop=asyncio.get_running_loop();previous=loop.get_exception_handler()
            loop.set_exception_handler(lambda loop,context:errors.append(context))
            with patch('websockets.asyncio.client.connect',return_value=FakeSocket()),patch.object(FinalizedFence,'command',slow):
                task=asyncio.create_task(serve(path,'https://solana-mainnet.g.alchemy.com/v2/offline-test',stop=stop))
                try:
                    for _ in range(200):
                        if Path(str(path)+'.sock').exists():break
                        await asyncio.sleep(.01)
                    request=dict(op='counter',key='meteora.disconnect',count=1,owner='meteora',consumer='meteora',request_id='disconnect',expires_at=time.time()+3)
                    def disconnect():
                        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as stream:
                            stream.connect(str(path)+'.sock');stream.sendall((json.dumps(request)+'\n').encode())
                    await asyncio.to_thread(disconnect);await asyncio.sleep(.2)
                    def retry():
                        plane=RuntimeEvidence(path,owner='meteora')
                        try:
                            self.assertTrue(plane.command(**request)['ok'])
                            self.assertTrue(plane.command(op='counter',key='meteora.normal',count=1)['ok'])
                            self.assertEqual(plane.reader.db.execute("SELECT value FROM counters WHERE key='meteora.disconnect'").fetchone()[0],1)
                        finally:plane.close()
                    await asyncio.to_thread(retry)
                    self.assertFalse(task.done());self.assertEqual(errors,[])
                finally:stop.set();await task;loop.set_exception_handler(previous)
