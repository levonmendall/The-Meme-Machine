"""Offline native hooks and lifecycle proofs; no market/financial authority."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.operational import isolated_native_source as executor
from meme_machine.runtime import stop
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from tests import test_isolated_native_resources as sizing
from tests import test_source_ports as source_fixtures


def _deny_probe():
    """Executed by an actual spawned native preparation worker."""
    from meme_machine.runtime.isolated_native_execution import (
        financial_writes_denied, reject_financial_construction,
        IsolatedFinancialWriteDenied,
    )
    try:
        reject_financial_construction()
    except IsolatedFinancialWriteDenied:
        return financial_writes_denied()
    return False


class NativeSourceHookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await source_fixtures.SourcePortsTests.asyncSetUp(self)
        self.environment=self.enterContext(patch.dict(os.environ, {}, clear=True))

    def rpc(self):
        from meme_machine.runtime.evidence_worker import RepairRPC
        return RepairRPC(None, None, native_resources=self.resources, native_ports=self.ports)

    async def test_actual_repair_rpc_uses_exact_parent_role_and_handoff_accounting(self):
        from meme_machine.runtime.provider_purchases import provider_work
        self.physical.body=b'{"jsonrpc":"2.0", "id":1, "result":103}'
        rpc=self.rpc()
        def request():
            with provider_work('history_receipt',family='pump'):
                return rpc.call_delivered('getSlot',[dict(commitment='finalized')],3)
        with patch('urllib.request.urlopen',side_effect=AssertionError('child HTTP fallback')):
            result,receipt=await asyncio.to_thread(request)
        self.assertEqual(result,103)
        self.assertEqual(receipt['calls'],0)
        self.assertEqual(receipt['cu'],0)
        self.assertEqual(receipt['accounting_scope'],'PROTECTED_PARENT_ONLY')
        self.assertEqual(receipt['bytes_scope'],'EXACT_PARENT_PUBLIC_HANDOFF_NOT_PROVIDER_SOCKET')
        self.assertEqual(receipt['bytes'],len(b'{"id":1,"jsonrpc":"2.0","result":103}'))
        self.assertNotEqual(receipt['bytes'],len(self.physical.body))
        self.assertEqual(self.budget.snapshot()['http_attempts'],'1')
        self.assertEqual(sum(row.get('consumer_method:getSlot',0) for row in
            self.http.purchases.snapshot()['operations']),1)
        self.assertEqual(self.budget.snapshot()['http_bytes'],str(len(self.physical.body)))
        counters=rpc.telemetry()
        self.assertFalse(counters['parent_handoff_bytes_are_physical_socket_measurement'])
        self.assertEqual(counters['counters']['parent_rpc_calls'],1)
        self.assertFalse(hasattr(rpc.config,'credential'))
        self.assertFalse(hasattr(rpc.config,'http_url'))
        self.assertFalse(self.parent.contents)

    async def test_unknown_operation_held_priority_and_unproven_block_profile_refuse_before_purchase(self):
        from meme_machine.runtime.provider_purchases import provider_work
        rpc=self.rpc()
        for priority in (0,True,7):
            with self.assertRaisesRegex(ValueError,'source_priority'):
                rpc.call_delivered('getSlot',[],priority)
        with provider_work('history_receipt',family='pump'):
            with self.assertRaisesRegex(ValueError,'repair_method_forbidden'):
                rpc.call_delivered('getBlock',[10,{}],1)
        with provider_work('pump_discovery',family='pump'):
            with self.assertRaises(ValueError):
                rpc.call_delivered('getSlot',[],1)
        self.assertFalse(self.physical.calls)
        self.assertEqual(self.budget.snapshot()['http_attempts'],'0')

    async def test_parent_rpc_error_keeps_native_retry_classification_without_private_text(self):
        from meme_machine.runtime.evidence_worker import DeliveredRPCError
        from meme_machine.runtime.provider_purchases import provider_work
        rpc=self.rpc()
        self.physical.body=b'{"jsonrpc":"2.0","id":1,"error":{"code":-32005,"message":"private-canary"}}'
        def request():
            with provider_work('recovery_restart',family='pump'):
                return rpc.call_delivered('getSlot',[],6)
        with self.assertRaises(DeliveredRPCError) as caught:
            await asyncio.to_thread(request)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.rpc_code,-32005)
        self.assertNotIn('private-canary',str(caught.exception))
        self.assertEqual(rpc.telemetry()['counters']['429s'],1)
        self.assertEqual(self.budget.snapshot()['http_attempts'],'1')
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')

    async def test_actual_native_stream_keeps_original_decode_handler_and_scoped_close(self):
        from meme_machine.solana_selective_source import SelectiveSource
        from meme_machine.yellowstone import geyser_pb2 as pb
        rpc=self.rpc()
        driver=SelectiveSource(rpc.config,rpc,native_resources=self.resources,native_ports=self.ports)
        driver.stop=asyncio.Event()
        calls=[]
        async def work(call,priority=1,**kwargs):
            # Only transport hook is under test; this fixture grants no SQL
            # coverage, candidate proof, readiness or FULL/ACK evidence.
            return None
        driver.work=work
        async def handler(update,size,seen):
            calls.append((update.slot.slot,size))
            driver.stop.set()
        request=pb.SubscribeRequest(commitment=pb.FINALIZED)
        request.slots['f'].filter_by_commitment=True
        raw=pb.SubscribeUpdate(slot=pb.SubscribeUpdateSlot(slot=125)).SerializeToString()
        with patch.dict(os.environ,MM_OPERATIONAL_PHASE='ISOLATED_NATIVE'):
            async with self.ports.source_channel() as channel:
                task=asyncio.create_task(driver.stream(channel,request,handler,'shared'))
                async with asyncio.timeout(2):
                    while not self.sessions:await asyncio.sleep(.005)
                self.sessions[0].values.put_nowait(raw)
                await asyncio.wait_for(task,2)
        self.assertEqual(calls,[(125,len(raw))])
        self.assertEqual(self.sessions[0].writes,[request.SerializeToString()])
        self.assertTrue(self.sessions[0].closed)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertFalse(self.parent.contents)
        self.assertEqual(driver.pipeline_metrics['native_frame:shared:slot']['latest_slot'],125)

    async def test_actual_source_owner_and_all_three_preparation_boundaries_are_bookless(self):
        from meme_machine.solana_evidence_service import serve
        from meme_machine.runtime.isolated_native_execution import financial_writes_denied
        rpc=self.rpc()
        case=self
        observed={}
        class Driver:
            native_resources=case.resources
            native_ports=case.ports
            pipeline_metrics={}
            async def __call__(self,work,stopped):
                observed['owner']=await work(lambda state:financial_writes_denied())
                observed['decoder']=await asyncio.wrap_future(self.preparation_executor.submit(_deny_probe))
                observed['history']=await asyncio.wrap_future(self.historical_executor.submit(_deny_probe))
                observed['delivery']=await asyncio.wrap_future(self.delivery_executor.submit(_deny_probe))
                await work(lambda state:state.fence.health('offline_bookless_initializer_probe',observed))
                stopped.set()
        with patch.dict(os.environ,MM_SOLANA_HISTORY_SEPARATED='1',MM_OPERATIONAL_PHASE='ISOLATED_NATIVE'):
            await asyncio.wait_for(serve(self.resources.root/'solana-evidence.sqlite',None,
                repair_rpc=rpc,stop=asyncio.Event(),source_driver=Driver(),
                native_resources=self.resources,native_ports=self.ports),10)
        self.assertEqual(observed,dict(owner=True,decoder=True,history=True,delivery=True))
        self.assertFalse(Path(str(self.resources.root/'solana-evidence.sqlite')+'.sock').exists())
        self.assertFalse(any(thread.name=='solana-evidence-owner' and thread.is_alive()
            for thread in threading.enumerate()))
        self.assertFalse(self.physical.calls)
        import sqlite3
        with sqlite3.connect(self.resources.root/'solana-evidence.sqlite') as db:
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            proof=json.loads(db.execute("SELECT value FROM service_health WHERE key='offline_bookless_initializer_probe'").fetchone()[0])
        self.assertEqual(proof,observed)
        self.assertFalse(tables&{'journal','positions','genesis','portfolio_events','portfolio_genesis'})

    async def test_original_max_configured_subscription_builders_fit_existing_wire_without_clipping(self):
        import based58
        from meme_machine.solana_candidate_join import candidate_subscription
        from meme_machine.solana_selective_source import scout_request,MAX_LIVE_CANDIDATES
        from meme_machine.solana_activity_routes import ActivityRoutes,SHARD_SIZE
        from meme_machine.yellowstone import geyser_pb2 as pb
        from meme_machine.operational.parent_transport import validate_subscription
        keys=[based58.b58encode((2**256-1-index).to_bytes(32,'big')).decode() for index in range(50)]
        self.assertTrue(all(len(key)==44 for key in keys))
        control=pb.SubscribeRequest(commitment=pb.FINALIZED,from_slot=2**64-1)
        control.blocks_meta['b'].SetInParent();control.slots['f'].filter_by_commitment=True
        with patch.dict(os.environ,MM_OPERATIONAL_PHASE='ISOLATED_NATIVE'):
            scout=scout_request();scout.from_slot=2**64-1
            requests=[control,scout,candidate_subscription(
                {key:'scope:'+key for key in keys[:MAX_LIVE_CANDIDATES]},2**64-1,full_addresses=set()),
                ActivityRoutes(keys[:SHARD_SIZE]).subscription(from_slot=2**64-1)]
        sizes=[]
        for request in requests:
            body=request.SerializeToString()
            validate_subscription('yellowstone',body)
            sizes.append(len(body))
            self.assertLessEqual(len(body),32*1024)
        self.assertEqual(sizes,[29,83,2707,13969])
        self.assertFalse(self.physical.calls)

    async def test_singleflight_consumers_each_record_demand_without_second_attempt(self):
        from meme_machine.runtime.provider_purchases import provider_work
        rpc=self.rpc()
        entered=threading.Event();release=threading.Event()
        demands=[];purchases=[]
        class Port:
            def demand(self,methods):demands.append(list(methods))
        def physical(method,params,priority):
            purchases.append(method);entered.set()
            if not release.wait(2):raise TimeoutError('offline source gate')
            return 'same-immutable-result',dict(bytes=17,cu=0,calls=0)
        def request():
            with provider_work('history_receipt',family='pump'):
                return rpc.call_delivered('getTransaction',['offline-signature',dict(commitment='finalized')],3)
        with patch.object(rpc,'_parent_source_port',return_value=Port()),patch.object(rpc,'_parent_call_delivered',physical):
            first=asyncio.create_task(asyncio.to_thread(request))
            await asyncio.to_thread(entered.wait,1)
            second=asyncio.create_task(asyncio.to_thread(request))
            try:
                async with asyncio.timeout(1):
                    while len(demands)<2:await asyncio.sleep(.005)
            finally:release.set()
            results=await asyncio.gather(first,second)
        self.assertEqual(demands,[['getTransaction'],['getTransaction']])
        self.assertEqual(purchases,['getTransaction'])
        self.assertEqual([row[0] for row in results],['same-immutable-result']*2)
        self.assertEqual(sorted(row[1]['bytes'] for row in results),[0,17])
        self.assertFalse(self.physical.calls)

    async def test_url_and_foreign_capability_cannot_select_source_hook(self):
        from meme_machine.runtime.evidence_worker import RepairRPC
        from meme_machine.solana_selective_source import SelectiveSource
        with self.assertRaisesRegex(ValueError,'source_transport_required'):
            RepairRPC('https://not-an-isolated-port.invalid',None,
                native_resources=self.resources,native_ports=self.ports)
        rpc=self.rpc()
        with self.assertRaisesRegex(ValueError,'source_transport_required'):
            SelectiveSource(rpc.config,rpc,token='forbidden',
                native_resources=self.resources,native_ports=self.ports)
        self.assertFalse(self.physical.calls)


class NativeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.resources=IsolatedNativeResources(Path(self.tmp.name)/'owned',
            sizing_facts=sizing.authenticated(sizing.receipt()),clock=lambda:1000)
        self.addCleanup(self.resources.close)
        self.stopped=threading.Event()
        self.enterContext(patch.object(stop,'requested',threading.Event()))
        self.enterContext(patch.dict(os.environ,{},clear=True))
        self.sizing_calls=0
        self.workers_seen=[]
        self.source_joined=False

    def reader(self, *, fail=False):
        case=self
        class Reader:
            def apply_next(self,resources,*,seconds):
                self_test=resources.basis('pons',500)
                case.assertFalse(self_test['allocation_authority'])
                case.sizing_calls+=1
                if fail:raise ValueError('private-parent-canary')
                case.stopped.wait(.01)
        return Reader()

    async def source(self,event):
        path=self.resources.root/'solana-evidence.sqlite'
        path.touch()
        server=await asyncio.start_unix_server(lambda reader,writer:writer.close(),path=str(path)+'.sock')
        try:
            await event.wait()
            await asyncio.sleep(.02) # Actual owned drain must finish before return.
        finally:
            server.close()
            await server.wait_closed()
            Path(str(path)+'.sock').unlink()
            self.source_joined=True

    def worker(self,name,*,fail=False):
        def run():
            from meme_machine.runtime.isolated_native_execution import financial_writes_denied
            self.assertTrue(financial_writes_denied())
            self.workers_seen.append(name)
            if fail:raise ValueError('private-consumer-canary')
            stop.requested.wait()
        return run

    async def lifecycle(self,**kwargs):
        return await executor._run_lifecycle(resources=self.resources,stopped=self.stopped,
            sizing_reader=kwargs.pop('reader',self.reader()),source=self.source,
            workers=kwargs.pop('workers',[('pump',self.worker('pump')),('pons',self.worker('pons'))]),
            source_path=self.resources.root/'solana-evidence.sqlite',seconds=.15,
            startup_seconds=1,shutdown_seconds=1,**kwargs)

    async def test_actual_threads_concurrent_sizing_deny_and_join_before_complete(self):
        result=await self.lifecycle()
        self.assertTrue(result['all_workers_joined'])
        self.assertTrue(result['full_window_completed'])
        self.assertEqual(set(self.workers_seen),{'pump','pons'})
        self.assertGreater(self.sizing_calls,0)
        self.assertTrue(self.source_joined)
        self.assertFalse(result['financial_authority'])
        self.assertFalse(result['normal_readiness'])
        self.assertFalse(result['complete_production_parity'])
        self.assertTrue(all(row['completed'] for row in result['workers'].values()))
        self.assertEqual(json.loads((self.resources.root/'native-execution.json').read_text()),result)

    async def test_consumer_failure_stops_and_joins_every_owner_preserving_typed_partial(self):
        with self.assertRaisesRegex(executor.ContainedNativeFailure,'pump_failed'):
            await self.lifecycle(workers=[('pump',self.worker('pump',fail=True)),('pons',self.worker('pons'))])
        result=json.loads((self.resources.root/'native-execution.json').read_text())
        self.assertTrue(result['all_workers_joined'])
        self.assertTrue(self.source_joined)
        self.assertEqual(result['status'],'FAILED')
        self.assertNotIn('private',json.dumps(result))
        self.assertFalse(result['normal_readiness'])

    async def test_missing_parent_refresh_stops_source_without_financial_fallback(self):
        with self.assertRaisesRegex(executor.ContainedNativeFailure,'sizing_failed'):
            await self.lifecycle(reader=self.reader(fail=True))
        result=json.loads((self.resources.root/'native-execution.json').read_text())
        self.assertTrue(result['all_workers_joined'])
        self.assertTrue(self.source_joined)
        self.assertEqual(result['failure_code'],'isolated_native_sizing_failed')
        self.assertFalse(list(self.resources.root.glob('*portfolio*')))

    async def test_existing_stop_refuses_before_source_or_worker_start(self):
        self.stopped.set()
        with self.assertRaisesRegex(executor.ContainedNativeFailure,'already_stopped'):
            await self.lifecycle()
        self.assertFalse(self.workers_seen)
        self.assertFalse(list(self.resources.root.glob('*.sqlite')))

    async def test_cancellation_is_joined_and_does_not_claim_complete_window(self):
        async def cancel():
            await asyncio.sleep(.08)
            self.stopped.set()
        task=asyncio.create_task(cancel())
        result=await self.lifecycle()
        await task
        self.assertTrue(result['all_workers_joined'])
        self.assertFalse(result['full_window_completed'])
        self.assertTrue(self.source_joined)

    async def test_progress_keeps_first_and_last_work_samples_before_stop(self):
        values=[]
        def progress():
            value=dict(monotonic=time.monotonic(),accepted=len(values)+1,committed=len(values))
            values.append(value)
            return value
        result=await self.lifecycle(progress=progress)
        self.assertEqual(len(values),2)
        self.assertEqual(result['first_progress'],values[0])
        self.assertEqual(result['last_progress'],values[-1])
        self.assertEqual(result['progress_samples'],2)
        self.assertGreater(values[-1]['monotonic'],values[0]['monotonic'])
        self.assertTrue(result['all_workers_joined'])

    async def test_failed_progress_recording_still_joins_and_preserves_private_failure(self):
        def progress():raise ValueError('private-progress-canary')
        with self.assertRaises(ValueError):
            await self.lifecycle(progress=progress)
        result=json.loads((self.resources.root/'native-execution.json').read_text())
        self.assertTrue(result['all_workers_joined'])
        self.assertTrue(self.source_joined)
        self.assertNotIn('private-progress-canary',json.dumps(result))
        self.assertEqual(result['failure_code'],'isolated_native_runtime_failed')

    async def test_uncooperative_worker_is_failed_never_a_graceful_pass(self):
        release=threading.Event()
        exited=threading.Event()
        def blocked():
            try:release.wait(2)
            finally:exited.set()
        try:
            with self.assertRaisesRegex(executor.ContainedNativeFailure,'shutdown_incomplete'):
                await executor._run_lifecycle(resources=self.resources,stopped=self.stopped,
                    sizing_reader=self.reader(),source=self.source,workers=[('pump',blocked)],
                    source_path=self.resources.root/'solana-evidence.sqlite',seconds=.1,
                    startup_seconds=1,shutdown_seconds=.02)
            result=json.loads((self.resources.root/'native-execution.json').read_text())
            self.assertFalse(result['all_workers_joined'])
            self.assertEqual(result['status'],'FAILED')
            self.assertEqual(result['failure_code'],'isolated_native_shutdown_incomplete')
        finally:
            # Fixture release only: production relies on the fixed outer process
            # boundary, and cannot safely kill an arbitrary Python thread.
            release.set()
            self.assertTrue(await asyncio.to_thread(exited.wait,1))
            for thread in threading.enumerate():
                if thread.name=='isolated-native-pump':thread.join(timeout=1)

    def test_fixed_environment_rejects_inherited_authority_and_wrong_bound_paths(self):
        with patch.dict(os.environ,MM_PAPER_EPOCH='must-not-copy'):
            with self.assertRaisesRegex(executor.ContainedNativeFailure,'inherited_authority'):
                with executor._fixed_environment(self.resources):pass
        with patch.dict(os.environ,MM_SOLANA_EVIDENCE_PLANE_DB='/authoritative/shared.sqlite'):
            with self.assertRaisesRegex(executor.ContainedNativeFailure,'configuration_conflict'):
                with executor._fixed_environment(self.resources):pass
        self.assertFalse(list(self.resources.root.glob('*.sqlite')))

    def test_preimported_consumer_cannot_rebind_original_state_globals(self):
        with patch.dict('sys.modules',{'meme_machine.lanes.pump.runner':object()}):
            with self.assertRaisesRegex(executor.ContainedNativeFailure,'preimported'):
                with executor._fixed_environment(self.resources):pass

    def test_private_output_is_bounded_and_cannot_be_opened_twice(self):
        output=executor._PrivateOutput(self.resources.root/'output')
        try:
            output.write('private-native-report')
            with patch.object(executor,'MAX_OUTPUT_BYTES',output.bytes):
                with self.assertRaisesRegex(executor.ContainedNativeFailure,'output_bound'):
                    output.write('extra')
            with self.assertRaises(FileExistsError):
                executor._PrivateOutput(self.resources.root/'output')
        finally:output.close()


class NativePoolOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_constructed_service_worker_is_joined_after_failure_and_close_error(self):
        from meme_machine import solana_evidence_service as service
        closed=[]
        class Worker:
            def __init__(self,name):self.name=name
            def close(self):
                closed.append(self.name)
                if self.name=='owner':raise ValueError('owner_close_failure')
            def shutdown(self,*,wait,cancel_futures):
                self_test=(wait,cancel_futures)
                if self_test!=(True,True):raise AssertionError('not joined')
                closed.append(self.name)
        async def fail(*args,_workers,**kwargs):
            _workers.update({name:Worker(name) for name in ('owner','decoder','history','delivery')})
            raise ValueError('startup_failure')
        with patch.object(service,'_serve_owned',fail):
            with self.assertRaisesRegex(ValueError,'owner_close_failure'):
                await service.serve('/not-opened',None)
        self.assertEqual(closed,['owner','delivery','history','decoder'])

    async def test_real_spawned_decoder_initializer_denies_financial_construction(self):
        from meme_machine.runtime.isolated_native_execution import install_isolated_native_execution
        pool=ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'),
            initializer=install_isolated_native_execution)
        try:
            self.assertTrue(await asyncio.wrap_future(pool.submit(_deny_probe)))
        finally:
            await asyncio.to_thread(pool.shutdown,wait=True,cancel_futures=True)

    async def test_real_history_worker_keeps_original_limits_and_adds_deny_only_initializer(self):
        from meme_machine.solana_history_work import HistoryExecutor
        with tempfile.TemporaryDirectory() as directory:
            resources=IsolatedNativeResources(Path(directory)/'owned',
                sizing_facts=sizing.authenticated(sizing.receipt()),clock=lambda:1000)
            worker=HistoryExecutor(native_resources=resources)
            try:
                self.assertTrue(await asyncio.wrap_future(worker.submit(_deny_probe)))
            finally:
                await asyncio.to_thread(worker.close)
                resources.close()


if __name__=='__main__':
    unittest.main()
