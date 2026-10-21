"""Captured log repair demand through bounded actual RPC/source contracts.

No provider is contacted. Synthetic signatures replicate the retained demand:
several exact truncated packets already have native finalized order witnesses.
"""
import asyncio
from concurrent.futures import Future,ThreadPoolExecutor
from copy import deepcopy
import json
import os
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch
import urllib.error

import based58
from meme_machine.runtime.evidence_worker import RepairRPC,DeliveredRPCError
from meme_machine.runtime.provider_purchases import provider_work
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_native_evidence import signature
from meme_machine.solana_selective_source import SelectiveSource
from meme_machine.solana_stream_log_repair import authenticate_supplement
from tests import test_archive_full_log_content as captured_logs


URL='https://solana-mainnet.g.alchemy.com/v2/OFFLINE_BATCH_ONLY'
SIGS=[signature(bytes([n])*64) for n in range(1,9)]


class Response:
    def __init__(self,value):self.raw=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.raw[:limit]


class LogRepairBatchTransportTests(unittest.TestCase):
    def rpc(self):return RepairRPC(URL,MagicMock())

    def test_eight_truncated_native_witnesses_use_one_paced_envelope_with_all_logical_charges(self):
        case=captured_logs.StreamFullLogContentTests();join,_,fetched,_,witness=case.joined()
        requested=[]
        rpc=self.rpc()
        def opened(request,**options):
            body=json.loads(request.data);requested.append(body)
            self.assertEqual(options['timeout'],8)
            return Response([dict(jsonrpc='2.0',id=row['id'],result=dict(fetched,
                transaction=dict(fetched['transaction'],signatures=[row['params'][0]]))) for row in reversed(body)])
        with patch('urllib.request.urlopen',side_effect=opened),patch.dict(os.environ,{'MM_SOLANA_EVIDENCE_PLANE_DB':'offline'}), \
                provider_work('recovery_restart',family='pump',consumer='recovery'):
            results,receipt=rpc.log_batch_delivered(SIGS,2)
        self.assertEqual(len(requested),1);self.assertEqual(len(requested[0]),8)
        self.assertEqual([row['transaction']['signatures'][0] for row in results],SIGS)
        rpc.governor.acquire.assert_called_once_with('solana','evidence',2,deadline_seconds=8,
            methods=('getTransaction',)*8)
        totals=rpc.telemetry()['provider_purchases']['totals'];counts=rpc.telemetry()['counters']
        self.assertEqual((totals['physical_requests'],counts['physical_requests'],counts['logical_calls']),(1,1,8))
        self.assertEqual((counts['log_batch_requests'],counts['log_batch_members']),(1,8))
        self.assertEqual((receipt['cu'],totals['known_estimated_cu'],totals['known_estimated_throughput_cu']),(320,320,320))
        # Batch membership is transport identity only. An exact different
        # native signature cannot satisfy the original witness or create events.
        with self.assertRaisesRegex(EvidenceUnavailable,'supplement_identity_unverified'):
            authenticate_supplement(join,witness,results[0],'a'*64)
        self.assertIsNone(join.drain());self.assertEqual(len(join.incomplete_logs),1)

    def test_strict_envelope_identity_refuses_duplicate_missing_unknown_boolean_and_nonarray(self):
        valid=[dict(id=i,result={}) for i in (1,2)]
        bad=[valid[:1],[valid[0],valid[0]],[valid[0],dict(id=3,result={})],
             [dict(id=True,result={}),valid[1]],dict(id=1,result={}),
             [dict(id=1,result={},error=dict(code=-32005)),valid[1]]]
        for value in bad:
            with self.subTest(value=value):
                rpc=self.rpc()
                with patch('urllib.request.urlopen',return_value=Response(value)):
                    results,receipt=rpc.log_batch_delivered(SIGS[:2],2)
                self.assertTrue(all(isinstance(result,DeliveredRPCError) for result in results))
                self.assertTrue(all(not result.retryable for result in results))
                self.assertEqual((receipt['calls'],receipt['cu']),(1,80));self.assertFalse(rpc.flights)

    def test_member_rate_limit_preserves_good_member_and_shared_cooldown(self):
        rpc=self.rpc()
        with patch('urllib.request.urlopen',return_value=Response([
                dict(id=2,error=dict(code=-32005,message='untrusted private detail')),
                dict(id=1,result=dict(slot=100))])):
            results,receipt=rpc.log_batch_delivered(SIGS[:2],2)
        self.assertEqual(results[0],dict(slot=100));self.assertIsInstance(results[1],DeliveredRPCError)
        self.assertTrue(results[1].retryable);self.assertNotIn('private',str(results[1]))
        rpc.governor.rate_limited.assert_called_once_with('solana',('getTransaction',))
        rpc.governor.succeeded.assert_not_called()
        self.assertEqual((receipt['calls'],receipt['cu']),(1,80))

    def test_transport_failure_and_governor_denial_do_not_reset_accounting_or_leak_endpoint(self):
        for failure in (TimeoutError('offline'),urllib.error.HTTPError(URL,429,URL,{},None)):
            rpc=self.rpc()
            with patch('urllib.request.urlopen',side_effect=failure):
                values,receipt=rpc.log_batch_delivered(SIGS[:2],2)
            self.assertEqual((receipt['calls'],receipt['cu']),(1,80));self.assertFalse(rpc.flights)
            self.assertTrue(all(isinstance(value,DeliveredRPCError) and value.retryable for value in values))
            self.assertNotIn('OFFLINE_BATCH_ONLY',str(values))
        rpc=self.rpc();rpc.governor.acquire.side_effect=TimeoutError('wait')
        with patch('urllib.request.urlopen') as opened:values,receipt=rpc.log_batch_delivered(SIGS[:2],2)
        opened.assert_not_called();self.assertEqual((receipt['calls'],receipt['cu']),(0,0));self.assertFalse(rpc.flights)

    def test_response_budget_and_method_shape_keep_existing_bounds(self):
        rpc=self.rpc()
        class Oversized(Response):
            def read(self,limit):return b' '*limit
        with patch('urllib.request.urlopen',return_value=Oversized(None)):
            values,receipt=rpc.log_batch_delivered(SIGS[:2],2)
        self.assertTrue(all(isinstance(value,DeliveredRPCError) for value in values))
        for signatures in ([],SIGS+[SIGS[0]],SIGS[:1]*2,['not-a-chain-signature'],['x'*1000]):
            with self.subTest(signatures=signatures),patch('urllib.request.urlopen') as opened:
                with self.assertRaisesRegex(ValueError,'repair_batch_shape'):rpc.log_batch_delivered(signatures,2)
                opened.assert_not_called()

    def test_batch_and_scalar_join_existing_immutable_flight_instead_of_duplicate_purchase(self):
        rpc=self.rpc();entered=threading.Event();release=threading.Event();joined=threading.Event();requests=[]
        class JoinedFuture(Future):
            def result(self,*args,**kwargs):
                joined.set();return super().result(*args,**kwargs)
        def opened(request,**options):
            body=json.loads(request.data);requests.append(body);entered.set()
            if not release.wait(2):raise TimeoutError('offline test release')
            return Response([dict(id=row['id'],result=dict(signature=row['params'][0])) for row in body])
        with patch('urllib.request.urlopen',side_effect=opened),patch('concurrent.futures.Future',JoinedFuture),ThreadPoolExecutor(max_workers=2) as pool:
            batch=pool.submit(rpc.log_batch_delivered,SIGS[:2],2)
            self.assertTrue(entered.wait(1))
            scalar=pool.submit(rpc.call_delivered,'getTransaction',[SIGS[0],dict(
                commitment='finalized',encoding='json',maxSupportedTransactionVersion=1)],2)
            self.assertTrue(joined.wait(1));release.set()
            values,receipt=batch.result(2);value,shared=scalar.result(2)
        self.assertEqual(len(requests),1);self.assertEqual(value,values[0]);self.assertEqual(shared['calls'],0)
        self.assertFalse(rpc.flights)

    def test_owned_sqlite_busy_survives_aggregate_and_shared_follower_wrappers(self):
        import sqlite3
        import tempfile
        from contextlib import closing
        from pathlib import Path
        from meme_machine.runtime.sqlite_failure import connect,payload
        entered=threading.Event();release=threading.Event();joined=threading.Event()
        class JoinedFuture(Future):
            def result(self,*args,**kwargs):
                joined.set();return super().result(*args,**kwargs)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'governor.sqlite'
            held=sqlite3.connect(path,isolation_level=None);held.execute('CREATE TABLE retained(value)')
            held.execute('BEGIN IMMEDIATE')
            def busy(*args,**kwargs):
                entered.set()
                if not release.wait(2):raise TimeoutError('offline release')
                with closing(connect(path,diagnostic_role='source_governor.acquire',timeout=0,isolation_level=None)) as db:
                    db.execute('BEGIN IMMEDIATE')
            rpc=self.rpc();rpc.governor.acquire.side_effect=busy
            try:
                with patch('concurrent.futures.Future',JoinedFuture),patch('urllib.request.urlopen') as opened,ThreadPoolExecutor(max_workers=2) as pool:
                    first=pool.submit(rpc.log_batch_delivered,SIGS[:2],2);self.assertTrue(entered.wait(1))
                    second=pool.submit(rpc.log_batch_delivered,SIGS[:2],2);self.assertTrue(joined.wait(1))
                    release.set();a,physical=first.result(2);b,shared=second.result(2)
                opened.assert_not_called();self.assertEqual((physical['calls'],shared['calls']),(0,0))
                for error in [*a,*b]:
                    self.assertIsInstance(error,DeliveredRPCError)
                    owned=payload(error);self.assertEqual(owned['sqlite_errorcode'],sqlite3.SQLITE_BUSY)
                    self.assertEqual(owned['sqlite_errorname'],'SQLITE_BUSY')
                    self.assertEqual(owned['connection_role'],'source_governor.acquire')
            finally:held.close()


class LogRepairSourceBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_scalar_governor_denial_preserves_zero_actual_http_in_durable_source_accounting(self):
        import tempfile
        from pathlib import Path
        from tests.test_solana_closure import state_at
        with tempfile.TemporaryDirectory() as directory:
            state,history=state_at(Path(directory)/'source.sqlite')
            rpc=RepairRPC(URL,MagicMock());rpc.governor.acquire.side_effect=TimeoutError('offline capacity wait')
            source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),rpc)
            async def work(fn,priority=2,**options):return fn(state)
            source.work=work
            try:
                with patch('urllib.request.urlopen') as opened:
                    with self.assertRaises(DeliveredRPCError) as caught:
                        await source.measured_rpc('getTransaction',[SIGS[0],dict(commitment='finalized',
                            encoding='json',maxSupportedTransactionVersion=1)],'rolling_recovery_missing_logs',2)
                opened.assert_not_called();self.assertEqual(caught.exception.receipt,dict(bytes=0,cu=0,calls=0))
                self.assertEqual(history.db.execute('SELECT SUM(calls),SUM(rpc_cu),SUM(raw_bytes) FROM provider_delivery').fetchone(),(0,0,0))
                self.assertEqual(rpc.governor.acquire.call_count,3)
                self.assertTrue(all(call.kwargs['deadline_seconds']==8 for call in rpc.governor.acquire.call_args_list))
                self.assertEqual(rpc.telemetry()['counters']['physical_requests'],0)
                self.assertEqual(source.pipeline_metrics['log_repair:rolling']['repair_physical_requests'],0)
                self.assertEqual(history.db.execute("SELECT COUNT(*) FROM acquisition_observations WHERE kind='rpc_retry'").fetchone()[0],2)
            finally:state.writer.close()

    async def test_partial_retry_keeps_exact_good_response_and_accounts_only_failed_member_again(self):
        deliveries=[];observations=[];physical=[]
        class History:
            def delivery(self,family,transport,**values):deliveries.append(values)
            def _observation(self,*values):observations.append(values)
        history=History();rpc=RepairRPC(URL,MagicMock())
        source=SelectiveSource(SimpleNamespace(credential='offline',identity='a'*64),rpc)
        async def work(fn,priority=2,**options):return fn(None)
        source.work=work
        def opened(request,**options):
            body=json.loads(request.data);physical.append(body)
            if type(body) is list:
                return Response([dict(id=2,error=dict(code=-32603)),dict(id=1,result=dict(signature=SIGS[0]))])
            return Response(dict(id=1,result=dict(signature=SIGS[1])))
        with patch('meme_machine.solana_selective_source.install',return_value=history), \
                patch('urllib.request.urlopen',side_effect=opened):
            values=await source.measured_log_batch(SIGS[:2],2)
        self.assertEqual(values,[dict(signature=sig) for sig in SIGS[:2]])
        self.assertEqual([len(row) if type(row) is list else 1 for row in physical],[2,1])
        self.assertEqual(physical[1]['params'][0],SIGS[1])
        self.assertEqual((sum(row['calls'] for row in deliveries),sum(row['rpc_cu'] for row in deliveries)),(2,120))
        metrics=source.pipeline_metrics['log_repair:rolling']
        self.assertEqual((metrics['repair_physical_requests'],metrics['batch_requests'],metrics['batch_members'],metrics['repair_retry_calls']),(2,1,2,1))
        self.assertTrue(any(row[1]=='rpc_retry' and row[2]['members']==1 for row in observations))

    async def test_permanent_member_failure_never_retries_success_or_claims_publication(self):
        rpc=RepairRPC(URL,MagicMock());source=SelectiveSource(SimpleNamespace(credential='offline'),rpc)
        deliveries=[]
        async def work(fn,priority=2,**options):return fn(None)
        source.work=work
        h=SimpleNamespace(delivery=lambda *args,**values:deliveries.append(values))
        with patch('meme_machine.solana_selective_source.install',return_value=h),patch('urllib.request.urlopen',return_value=Response([
                dict(id=1,result=dict(slot=100)),dict(id=2,error=dict(code=-32602))])) as opened:
            with self.assertRaises(DeliveredRPCError):await source.measured_log_batch(SIGS[:2],2)
        self.assertEqual(opened.call_count,1);self.assertEqual(deliveries[0]['rpc_cu'],80)
        self.assertNotIn('native_stream_log_supplement',str(source.pipeline_metrics))


class RepairLogOccupancyTests(unittest.IsolatedAsyncioTestCase):
    def pressured(self):
        case=captured_logs.StreamFullLogContentTests()
        join,original,fetched,full,witness=case.joined()
        slot=full['slot']
        # Preserve a complete future packet large enough that the old prefix
        # replacement fits the hard bound while current occupancy exceeds half.
        future=['x'*(len(str(full['meta']['logMessages']).encode())+128)]
        join.feed_log(slot+3,'already-buffered-future',future,None,captured_logs.NOW)
        bound=2*join.early_log_bytes-2
        return join,original,fetched,full,witness,bound

    async def test_future_wait_rechecks_exact_native_signature_instead_of_slot_presence(self):
        from meme_machine.solana_candidate_join import scope_labels
        from meme_machine.solana_selective_source import wait_candidate_log_space
        from meme_machine.yellowstone import geyser_pb2 as pb
        join,_,_,full,_,bound=self.pressured();slot=full['slot']+1
        wanted=SIGS[1];wrong=SIGS[2];progress=asyncio.Event();stop=asyncio.Event()
        update=pb.SubscribeUpdate(filters=['b']);m=update.block_meta
        m.slot=slot;m.parent_slot=slot-1;m.blockhash='next';m.parent_blockhash='prior'
        m.block_time.timestamp=full['blockTime'];m.executed_transaction_count=1
        join.feed(update,update.ByteSize(),captured_logs.NOW)
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound), \
                patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES',bound):
            required=asyncio.create_task(wait_candidate_log_space(join,progress,stop,stop,slot,wanted,['required']))
            unrelated=asyncio.create_task(wait_candidate_log_space(join,progress,stop,stop,slot,wrong,['future']))
            try:
                await asyncio.sleep(.01)
                self.assertFalse(required.done());self.assertFalse(unrelated.done())
                # A real successful scoped native status supplies this exact
                # signature/index. Header presence alone grants no escape.
                update=pb.SubscribeUpdate(filters=[scope_labels(join.programs)[next(iter(join.programs.values()))]])
                update.transaction_status.slot=slot;update.transaction_status.index=0
                update.transaction_status.signature=based58.b58decode(wanted.encode())
                join.feed(update,update.ByteSize(),captured_logs.NOW);progress.set()
                await asyncio.wait_for(required,.5)
                self.assertFalse(unrelated.done())
                join.feed_log(slot,wanted,['required'],None,captured_logs.NOW)
                self.assertLessEqual(join.early_log_bytes,bound)
                self.assertGreater(join.early_log_bytes,bound//2)
                self.assertNotIn((slot,wrong),join.early_logs)
                self.assertLessEqual(join.early_log_bytes+len(str(['future']).encode()),bound)
            finally:
                stop.set();progress.set()
                results=await asyncio.gather(required,unrelated,return_exceptions=True)
            # The unrelated signature has no native exception while intake is
            # open. Once intake closes, its already accepted packet may use
            # the remaining hard headroom; waiting itself mutates no content.
            self.assertIsNone(results[1])
            self.assertNotIn((slot,wrong),join.early_logs)

    async def test_authenticated_http_completion_frees_existing_join_and_wakes_future_packet(self):
        from meme_machine.solana_selective_source import wait_candidate_log_space
        from meme_machine.solana_program_decoders import pump_events
        join,_,fetched,full,witness,bound=self.pressured();slot=full['slot'];sig=full['transaction']['signatures'][0]
        progress=asyncio.Event();stop=asyncio.Event()
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound), \
                patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES',bound):
            waiting=asyncio.create_task(wait_candidate_log_space(join,progress,stop,stop,slot+2,'next-future',['next']))
            try:
                await asyncio.sleep(.01);self.assertFalse(waiting.done())
                complete,_=authenticate_supplement(join,witness,fetched,'a'*64)
                frame=join.complete_deferred_log(slot,sig,complete,captured_logs.NOW+1)
                # The production HTTP callback sets the same progress event
                # immediately after mutation, before waiting for owner admission.
                progress.set();await asyncio.wait_for(waiting,.5)
                self.assertEqual(pump_events(frame.log_transactions[0]),pump_events(full))
                join.feed_log(slot+2,'next-future',['next'],None,captured_logs.NOW+2)
                self.assertLessEqual(join.early_log_bytes,bound//2)
            finally:
                stop.set();progress.set();await asyncio.gather(waiting,return_exceptions=True)

    async def test_http_install_of_waiting_key_releases_duplicate_without_new_capacity(self):
        from meme_machine.solana_selective_source import wait_candidate_log_space
        join,_,_,full,_,bound=self.pressured();slot=full['slot']+2;sig='same-http-key';logs=['installed']
        progress=asyncio.Event();stop=asyncio.Event()
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound),                 patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES',bound):
            waiting=asyncio.create_task(wait_candidate_log_space(join,progress,stop,stop,slot,sig,logs))
            try:
                await asyncio.sleep(.01);self.assertFalse(waiting.done())
                before=join.early_log_bytes
                join.feed_log(slot,sig,logs,None,captured_logs.NOW)
                self.assertGreater(join.early_log_bytes,before)
                self.assertGreater(join.early_log_bytes,bound//2)
                self.assertNotIn(slot,join.pending) # No native-witness escape.
                progress.set();await asyncio.wait_for(waiting,.5)
                self.assertIsNone(join.feed_log(slot,sig,logs,None,captured_logs.NOW+1))
                with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_content_conflict'):
                    join.feed_log(slot,sig,['different'],None,captured_logs.NOW+1)
            finally:
                stop.set();progress.set();await asyncio.gather(waiting,return_exceptions=True)

    async def test_future_wait_preserves_120_second_lease_and_cancellation_without_mutation(self):
        from meme_machine.solana_selective_source import wait_candidate_log_space
        join,_,_,full,_,bound=self.pressured();slot=full['slot']+1
        progress=asyncio.Event();stop=asyncio.Event();before=deepcopy(join.early_logs),join.early_log_bytes,join.completed
        self.assertEqual(join.max_join_seconds,120)
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',bound), \
                patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES',bound):
            ticks=iter((0,121));join.clock=lambda:next(ticks)
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_buffer_pressure'):
                await wait_candidate_log_space(join,progress,stop,stop,slot,'future',['held'])
        # Closing a merely soft-limited packet can now finish in hard
        # headroom. This cancellation case must exhaust that original hard
        # bound, not demand abandonment of an otherwise admissible packet.
        with patch('meme_machine.solana_candidate_join.MAX_PENDING_BYTES',join.early_log_bytes), \
                patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES',join.early_log_bytes):
            join.clock=lambda:0
            waiting=asyncio.create_task(wait_candidate_log_space(join,progress,stop,stop,slot,'future',['held']))
            await asyncio.sleep(.01);self.assertFalse(waiting.done());stop.set();progress.set()
            with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(waiting,.5)
        self.assertEqual((join.early_logs,join.early_log_bytes,join.completed),before)

    async def test_projected_decoded_bytes_preserve_hard_bound_even_below_waterline(self):
        from meme_machine.solana_selective_source import wait_candidate_log_space
        case=captured_logs.StreamFullLogContentTests();join,_,_,full,_=case.joined()
        bound=2*join.early_log_bytes+128;oversized=['x'*bound]
        self.assertLess(join.early_log_bytes,bound//2)
        before=join.early_log_bytes,deepcopy(join.early_logs)
        with patch('meme_machine.solana_selective_source.MAX_PENDING_BYTES',bound):
            with self.assertRaisesRegex(EvidenceUnavailable,'candidate_log_buffer_pressure'):
                await wait_candidate_log_space(join,asyncio.Event(),asyncio.Event(),asyncio.Event(),
                    full['slot']+1,'oversized',oversized)
        self.assertEqual((join.early_log_bytes,join.early_logs),before)
        # Compact HTTP bytes are not a decoded-log reservation. Python repr
        # escaping/list spacing can grow; admission uses actual retained bytes.
        logs=['\u0085']*20
        self.assertGreater(len(str(logs).encode()),len(json.dumps(logs,ensure_ascii=False,separators=(',',':')).encode()))
