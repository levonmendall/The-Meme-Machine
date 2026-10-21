"""Failed-run limit reproduction and SDK headroom; all providers are offline."""
from copy import deepcopy
import io
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
import grpc
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace
from threading import Event

from meme_machine.operational.bounded_provider import (Budget,CeilingReached,DeliveredResponse,
    MAX_FRAME,AccountedStream,AccountedWebSocketContext)

MIB=1024**2
LIMITS=dict(rpc_cu=150000,rpc_elements=1800,http_attempts=1200,http_bytes=128*MIB,
    native_bytes=1024*MIB,native_stop_bytes=512*MIB,native_inflight_bytes=512*MIB)


def observation_file(root,budget):
    state=budget.snapshot()
    row=dict(schema='bounded-provider-observation-v1',limits=budget.limits,
        wall_seconds=budget.seconds,modeled_spend_limit=state['modeled_spend_limit'],
        maximum_native_opens=int(state['reconnect_limit']),lanes=['pump'])
    path=Path(root)/'observation-envelope.json';path.write_text(json.dumps(row))
    return path


class ProviderPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'usage.sqlite'
        self.budget=Budget.create(self.path,limits=LIMITS,wall_seconds=900,
            modeled_spend_limit='0.20',maximum_native_opens=8)
        self.file=observation_file(self.root,self.budget)

    def test_explicit_pacing_is_sealed_before_dispatch_and_cannot_change_after_restart(self):
        pacing=dict(solana='0.5',robinhood='0.25')
        path=self.root/'four-rps.sqlite'
        budget=Budget.create(path,limits=LIMITS,physical_http_start_intervals=pacing)
        file=observation_file(self.root,budget);row=json.loads(file.read_text())
        row['physical_http_start_intervals']=dict(pacing);file.write_text(json.dumps(row))
        self.assertEqual(budget.preflight_file(file)['physical_http_start_intervals'],pacing)
        row['physical_http_start_intervals']['robinhood']='0.1';file.write_text(json.dumps(row))
        with self.assertRaisesRegex(CeilingReached,'envelope_unverified'):Budget(path).preflight_file(file)
        self.assertEqual(budget.snapshot()['http_attempts'],'0')
        self.assertEqual(json.loads(budget.snapshot()['physical_http_start_intervals']),pacing)
        with self.assertRaises(ValueError):Budget.create(self.root/'invalid-pace.sqlite',physical_http_start_intervals={})
        self.assertFalse((self.root/'invalid-pace.sqlite').exists())

    def test_persisted_custom_envelope_and_restart_preserve_consumption_and_clocks(self):
        preflight=self.budget.preflight_file(self.file)
        self.assertEqual(preflight['limits'],LIMITS);self.assertEqual(preflight['lanes'],['pump'])
        response=self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        with DeliveredResponse(io.BytesIO(b'authentic-fixture-shape'),response) as r:r.read()
        before=self.budget.snapshot()
        self.assertEqual(before['rpc_cu'],'20');self.assertEqual(before['http_reserved'],'0')
        resumed=Budget(self.path);resumed.preflight_file(self.file)
        self.assertEqual(resumed.snapshot(),before);self.assertEqual(resumed.limits,LIMITS)
        with self.assertRaises(FileExistsError):Budget.create(self.path,limits=LIMITS)
        self.assertEqual(resumed.snapshot(),before)

    def test_original_absent_limits_row_never_substitutes_defaults(self):
        self.budget.change(dict(rpc_cu=20))
        with self.budget.db() as db:db.execute("DELETE FROM run WHERE key='limits'")
        with self.assertRaisesRegex(CeilingReached,'configuration_unverified'):Budget(self.path)
        with self.budget.db() as db:
            state=dict(db.execute('SELECT key,value FROM run'))
        self.assertEqual(state['rpc_cu'],'20');self.assertNotIn('limits',state)
        self.assertEqual(state['reason'],'bounded_provider_configuration_unverified')

    def test_missing_or_mismatched_observation_file_prevents_transport_installation(self):
        from meme_machine.operational.bounded_provider import install
        before=self.budget.snapshot()
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path),MM_BOUNDED_PROVIDER_ENVELOPE=''), \
                patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(CeilingReached,'envelope_unverified'):install()
        network.assert_not_called()
        after=self.budget.snapshot()
        for key in before.keys()-{'reason'}:self.assertEqual(after[key],before[key])
        self.assertTrue(after['reason'])

    def test_missing_invalid_or_changed_configuration_is_durable_before_dispatch(self):
        before=self.budget.snapshot()
        for key,value in [('limits','{}'),('limits','null'),('wall_seconds','-1'),
                ('modeled_spend_limit','NaN'),('reconnect_limit','0'),('started_wall','nan')]:
            with self.subTest(key=key,value=value):
                path=self.root/(key+value.replace('/','_')+'.sqlite')
                b=Budget.create(path,limits=LIMITS)
                with b.db() as db:db.execute('UPDATE run SET value=? WHERE key=?',(value,key))
                with self.assertRaises(CeilingReached):Budget(path)
                with b.db() as db:state=dict(db.execute('SELECT key,value FROM run'))
                self.assertEqual(state['http_attempts'],'0');self.assertTrue(state['reason'])
        # A live instance checks the persisted envelope before its next request.
        with self.budget.db() as db:db.execute("UPDATE run SET value='1' WHERE key='modeled_spend_limit'")
        with self.assertRaisesRegex(CeilingReached,'configuration_changed'):
            self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        self.assertEqual(self.budget.snapshot()['http_attempts'],before['http_attempts'])

    def test_accounted_512_mib_stop_includes_active_and_uncertain_sdk_buffers(self):
        tokens=[self.budget.stream_open('yellowstone'),self.budget.stream_open('solana_websocket')]
        observed_stop=False
        for _ in range(40):
            try:self.budget.native('yellowstone',MAX_FRAME,token=tokens[0])
            except CeilingReached as error:
                self.assertEqual(error.reason,'native_payload_stop');observed_stop=True;break
        self.assertTrue(observed_stop)
        def accounted():
            row=self.budget.snapshot()
            return sum(int(row[k]) for k in ('native_bytes','native_uncertain_bytes','native_reserved'))
        stopping=accounted();self.assertLessEqual(stopping,512*MIB)
        # One already received tail replaces its reserved buffer exactly.
        with self.assertRaises(CeilingReached):self.budget.native('yellowstone',MAX_FRAME,token=tokens[0])
        self.assertEqual(accounted(),stopping)
        for token in tokens:
            self.budget.stream_close(token,unread_possible=True)
            self.budget.stream_close(token,unread_possible=True)
        self.assertEqual(accounted(),stopping);self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        before=self.budget.snapshot()
        with self.assertRaises(CeilingReached):Budget(self.path).preflight_file(self.file)
        with self.assertRaises(CeilingReached):self.budget.stream_open('yellowstone')
        self.assertEqual(self.budget.snapshot(),before)

    def test_stream_cannot_open_without_its_full_stop_and_next_frame_reservation(self):
        self.budget.change(dict(native_bytes=450*MIB))
        before=self.budget.snapshot()
        with self.assertRaisesRegex(CeilingReached,'native_inflight_limit'):self.budget.stream_open('solana_websocket')
        after=self.budget.snapshot()
        for key in ('http_attempts','native_opens','native_reserved','native_bytes'):
            self.assertEqual(after[key],before[key])

    def test_restart_reaps_lost_buffers_once_and_preserves_live_peers(self):
        self.budget.stream_open('yellowstone')
        self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        live=self.budget.snapshot();Budget(self.path).preflight_file(self.file)
        self.assertEqual(self.budget.snapshot(),live)
        with patch('meme_machine.shared_capital.runtime.process_identity',side_effect=OSError):
            resumed=Budget(self.path);resumed.preflight_file(self.file);resumed.preflight_file(self.file)
        after=self.budget.snapshot()
        self.assertEqual(after['native_uncertain_bytes'],str(4*MAX_FRAME))
        self.assertEqual(after['http_uncertain_bytes'],str(MAX_FRAME))
        self.assertEqual(after['native_reserved'],'0');self.assertEqual(after['http_reserved'],'0')
        for key in ('rpc_cu','http_attempts','native_opens','started','started_wall'):
            self.assertEqual(after[key],live[key])

    def test_http_error_and_unknown_tail_consume_existing_response_reservation(self):
        receipt=self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        with DeliveredResponse(io.BytesIO(b'12345'),receipt) as response:
            self.assertEqual(response.read(2),b'12')
        after=self.budget.snapshot()
        self.assertEqual(after['http_bytes'],'2');self.assertEqual(after['http_uncertain_bytes'],str(MAX_FRAME-2))
        self.assertEqual(after['http_reserved'],'0');self.assertEqual(after['rpc_elements'],'1')
        receipt.close();self.assertEqual(self.budget.snapshot(),after)

    def test_failure_between_http_reservation_and_dispatch_closes_receipt(self):
        import urllib.request
        from meme_machine.operational.bounded_provider import install
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path),MM_BOUNDED_PROVIDER_ENVELOPE=str(self.file)), \
                patch('urllib.request.urlopen'),patch('urllib.request.build_opener') as opener, \
                patch('meme_machine.lanes.pons.provider.urlopen'), \
                patch('grpc.aio.secure_channel'),patch('meme_machine.solana_selective_source.connect'):
            install()
            with patch.object(Budget,'admission',side_effect=CeilingReached('bounded_run_wall_limit')):
                with self.assertRaises(CeilingReached):
                    urllib.request.urlopen(urllib.request.Request(
                        'https://solana-mainnet.g.alchemy.com/v2/offline',
                        data=json.dumps(dict(method='getSlot')).encode()))
            opener.return_value.open.assert_not_called()
        row=self.budget.snapshot();self.assertEqual(row['http_reserved'],'0')
        self.assertEqual(row['http_uncertain_bytes'],str(MAX_FRAME))
        self.assertEqual(row['rpc_cu'],'20')

    def test_first_failure_survives_expiration_without_replenishment(self):
        self.budget.change(reason='original_stream_failure',check=False);before=self.budget.snapshot()
        with patch('time.monotonic',return_value=self.budget.started+901):
            with self.assertRaisesRegex(CeilingReached,'original_stream_failure'):Budget(self.path).admission()
        self.assertEqual(self.budget.snapshot(),before)

    def test_invalid_custom_create_allocates_no_allowance(self):
        for key,value in [('native_stop_bytes',2*1024**3),('native_inflight_bytes',1024*MIB),('http_bytes',True)]:
            limits=deepcopy(LIMITS);limits[key]=value
            path=self.root/(key+'.sqlite')
            with self.assertRaises(ValueError):Budget.create(path,limits=limits)
            self.assertFalse(path.exists())

    def test_concurrent_stream_open_counts_and_limits_are_shared_not_reset(self):
        from concurrent.futures import ThreadPoolExecutor
        path=self.root/'concurrent.sqlite'
        Budget.create(path,limits=LIMITS,maximum_native_opens=2)
        def opened(_):
            try:return Budget(path).stream_open('yellowstone')
            except CeilingReached:return None
        with ThreadPoolExecutor(max_workers=4) as pool:tokens=list(pool.map(opened,range(4)))
        self.assertEqual(len([t for t in tokens if t]),2)
        row=Budget(path).snapshot();self.assertEqual(row['native_opens'],'2')
        self.assertEqual(row['http_attempts'],'2');self.assertEqual(row['native_reserved'],str(8*MAX_FRAME))
        self.assertTrue(row['reason'])

    def test_pump_only_observation_cannot_hide_foreign_protection_obligations(self):
        from types import SimpleNamespace
        from meme_machine.operational.supervisor import Supervisor
        state=dict(runtime_admission={},positions={'foreign':dict(status='OPEN',regime='pons_survivor')})
        authority=SimpleNamespace(ledger=lambda:deepcopy(state))
        service=Supervisor(self.root,offline=True,admission='OBSERVATION');service.shared_capital=authority
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path),MM_BOUNDED_PROVIDER_ENVELOPE=str(self.file)):
            with self.assertRaisesRegex(CeilingReached,'cannot_omit_existing_owner'):service.configure_admission()
        self.assertEqual(state['positions']['foreign']['status'],'OPEN')
        self.assertEqual(self.budget.snapshot()['http_attempts'],'0')

    def test_inactive_window_preparation_cannot_repair_an_unverified_resource_envelope(self):
        from meme_machine.operational.bounded_provider import PhaseBudget
        from meme_machine.operational.exceptional_window import prepare
        from tests.test_position_continuation import envelope
        path=self.root/'continuation.sqlite';Budget.create(path,continuation=envelope())
        b=PhaseBudget(path)
        with b.bootstrap.db() as db:
            db.execute("UPDATE run SET value='1' WHERE key='continuation.modeled_spend_limit'")
        with self.assertRaisesRegex(ValueError,'resource_configuration_unverified'):
            prepare(b,maintenance_until=int(b.bootstrap.started_wall)+3600)
        with b.bootstrap.db() as db:row=dict(db.execute('SELECT key,value FROM run'))
        self.assertNotIn('exceptional_operational_window',row)
        self.assertEqual(row['continuation.modeled_spend_limit'],'1')
        self.assertEqual(row['continuation.wall_seconds'],str(envelope()['maximum_seconds']))

    def test_native_meter_does_not_starve_control_and_commits_before_content_returns(self):
        token=self.budget.stream_open('solana_websocket')
        entered=Event();release=Event();committed=Event()
        def native(transport,size):
            entered.set()
            if not release.wait(2):raise RuntimeError('offline_meter_release_missing')
            self.budget.native(transport,size,token=token);committed.set()
        context=AccountedWebSocketContext(None,SimpleNamespace(budget=SimpleNamespace(native=native)))
        context.ws=SimpleNamespace(recv=AsyncMock(side_effect=['authentic-shape-fixture',OSError('offline end')]))
        async def verify():
            reader=asyncio.create_task(context.recv())
            try:
                # A pending independent native/control turn remains runnable
                # while the real durable budget writer is deliberately held.
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.001)
                self.assertTrue(entered.is_set());self.assertFalse(reader.done())
                self.assertFalse(committed.is_set())
                release.set();self.assertEqual(await reader,'authentic-shape-fixture')
                self.assertTrue(committed.is_set())
            finally:
                release.set();await asyncio.gather(reader,return_exceptions=True)
        asyncio.run(verify())
        self.assertEqual(self.budget.snapshot()['native_bytes'],str(len('authentic-shape-fixture')))

    def test_cancelled_native_read_settles_durable_bytes_before_reservation_can_close(self):
        token=self.budget.stream_open('yellowstone');entered=Event();release=Event()
        def native(transport,size):
            entered.set()
            if not release.wait(2):raise RuntimeError('offline_meter_release_missing')
            self.budget.native(transport,size,token=token)
        transport=SimpleNamespace(budget=SimpleNamespace(native=native,ready_at=None))
        stream=AccountedStream(SimpleNamespace(read=AsyncMock(side_effect=[(3,b'raw'),grpc.aio.EOF])),transport,token)
        async def verify():
            reader=asyncio.create_task(stream.read())
            try:
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.001)
                self.assertTrue(entered.is_set());reader.cancel();reader.cancel()
                await asyncio.sleep(.005);self.assertFalse(reader.done())
                self.assertEqual(self.budget.snapshot()['native_bytes'],'0')
                release.set()
                with self.assertRaises(asyncio.CancelledError):await reader
                self.assertEqual(self.budget.snapshot()['native_bytes'],'3')
            finally:
                release.set();await asyncio.gather(reader,return_exceptions=True)
        asyncio.run(verify());self.budget.stream_close(token,unread_possible=True)
        state=self.budget.snapshot();self.assertEqual(state['native_reserved'],'0')
        self.assertEqual(state['native_uncertain_bytes'],str(4*MAX_FRAME))
        self.assertEqual(state['native_bytes'],'3')

    def test_async_native_ceiling_retains_received_tail_and_never_releases_content(self):
        token=self.budget.stream_open('yellowstone')
        self.budget.change(reason='original_failure',check=False)
        native=lambda transport,size:self.budget.native(transport,size,token=token)
        context=SimpleNamespace(budget=SimpleNamespace(native=native,ready_at=None))
        stream=AccountedStream(SimpleNamespace(read=AsyncMock(side_effect=[(3,b'raw'),grpc.aio.EOF])),context,token)
        with self.assertRaisesRegex(CeilingReached,'original_failure'):asyncio.run(stream.read())
        before=self.budget.snapshot();self.assertEqual(before['native_bytes'],'3')
        self.assertEqual(before['native_reserved'],str(4*MAX_FRAME-3))
        self.budget.stream_close(token,unread_possible=True)
        after=Budget(self.path).snapshot();self.assertEqual(after['reason'],'original_failure')
        self.assertEqual(after['native_uncertain_bytes'],str(4*MAX_FRAME-3))
        self.assertEqual(sum(int(after[k]) for k in ('native_bytes','native_reserved','native_uncertain_bytes')),4*MAX_FRAME)

    def test_installed_grpc_boundary_meters_before_delivering_original_decoded_value(self):
        import grpc
        from meme_machine.operational.bounded_provider import install
        from meme_machine.yellowstone import geyser_pb2 as pb
        from engineering.solana_capacity.proof_limits import STREAM_HOST
        captured={}
        class RawStream:
            sent=False
            async def write(self,value):pass
            async def read(self):
                if self.sent:return grpc.aio.EOF
                self.sent=True;return captured['decode'](b'raw')
            def cancel(self):pass
        class RawChannel:
            def stream_stream(self,path,**kwargs):
                captured['decode']=kwargs['response_deserializer']
                return lambda *args,**options:RawStream()
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path),MM_BOUNDED_PROVIDER_ENVELOPE=str(self.file)), \
                patch('urllib.request.urlopen'),patch('meme_machine.lanes.pons.provider.urlopen'), \
                patch('grpc.aio.secure_channel',return_value=RawChannel()), \
                patch('meme_machine.solana_selective_source.connect'):
            install()
            channel=grpc.aio.secure_channel(STREAM_HOST)
            stream=channel.stream_stream('/geyser.Geyser/Subscribe',response_deserializer=lambda b:dict(value=b))()
            async def verify():
                await stream.write(pb.SubscribeRequest())
                self.assertEqual(await stream.read(),dict(value=b'raw'))
                self.assertEqual(self.budget.snapshot()['native_bytes'],'3')
            try:asyncio.run(verify())
            finally:stream.cancel()
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')

class ReplayUnaryDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.budget=Budget.create(self.root/'usage.sqlite',limits=LIMITS,wall_seconds=900,
            modeled_spend_limit='0.20',maximum_native_opens=8)

    def exercise(self, *, unsupported=False):
        from engineering.diagnostics.yellowstone_replay_contract_20261015 import probe,HOST
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from meme_machine.yellowstone import geyser_pb2 as pb
        endpoint=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/disposable-secret')
        requests=[];options=[];closed=[];governor=SimpleNamespace(acquire=lambda *a,**kw:0)
        class Call:
            def __init__(self, result=None, error=None):self.result=result;self.error=error
            def __await__(self):
                async def get():
                    if self.error:raise self.error
                    return self.result
                return get().__await__()
            async def initial_metadata(self):return (('server','fixture'),('x-token','disposable-secret'))
            async def trailing_metadata(self):return ()
            def done(self):return True
        class Channel:
            def unary_unary(self,path,request_serializer,response_deserializer):
                def call(request,**kw):
                    requests.append((path,request,kw))
                    request_serializer(request)  # Actual protobuf request contract.
                    if unsupported and path.endswith('SubscribeReplayInfo'):
                        return Call(error=grpc.aio.AioRpcError(grpc.StatusCode.UNIMPLEMENTED,
                            (),(),details='unsupported method; disposable-secret'))
                    response=(pb.SubscribeReplayInfoResponse(first_available=1000)
                        if path.endswith('SubscribeReplayInfo') else pb.GetSlotResponse(slot=2000))
                    return Call(result=response_deserializer(response.SerializeToString()))
                return call
            async def close(self,**kw):closed.append(True)
        def channel_factory(target,credentials,**kw):
            self.assertEqual(target,HOST);options.extend(kw['options']);return Channel()
        result=asyncio.run(probe(endpoint,endpoint.credential,self.budget,governor,
            self.root/'probe',channel_factory=channel_factory))
        return result,requests,options,closed

    def test_exact_two_unary_reads_preserve_existing_durable_accounting(self):
        from meme_machine.yellowstone import geyser_pb2 as pb
        result,requests,options,closed=self.exercise()
        self.assertEqual([r[0] for r in requests],['/geyser.Geyser/SubscribeReplayInfo','/geyser.Geyser/GetSlot'])
        self.assertEqual(requests[1][1].commitment,pb.FINALIZED)
        self.assertTrue(requests[1][1].HasField('commitment'))
        self.assertTrue(all(r[2]['timeout']==5 and not r[2]['wait_for_ready'] for r in requests))
        self.assertIn(('grpc.enable_retries',0),options);self.assertEqual(closed,[True])
        self.assertEqual([r['status'] for r in result['calls']],['OK','OK'])
        self.assertEqual(result['calls'][0]['first_available'],1000)
        self.assertEqual(result['calls'][1]['slot'],2000)
        self.assertEqual(result['usage_delta']['rpc_cu'],20)
        self.assertEqual(result['usage_delta']['alchemy_rpc_cu'],20)
        self.assertEqual(result['usage_delta']['http_attempts'],2)
        self.assertEqual(result['usage_delta']['solana_rpc_elements'],2)
        self.assertEqual(result['usage_delta']['http_reserved'],0)
        self.assertEqual(result['usage_delta']['native_opens'],0)
        self.assertEqual(result['usage_delta']['http_bytes'],sum(r['response_payload_bytes'] for r in result['calls']))
        self.assertNotIn('disposable-secret',(self.root/'probe/result.json').read_text())
        with self.assertRaises(FileExistsError):self.exercise()

    def test_unsupported_method_is_preserved_without_retry_or_substitution(self):
        result,requests,_,_=self.exercise(unsupported=True)
        self.assertEqual(len(requests),2)
        self.assertEqual(result['calls'][0]['status'],'UNIMPLEMENTED')
        self.assertEqual(result['calls'][0]['details'],'unsupported method; [REDACTED]')
        self.assertEqual(result['calls'][1]['status'],'OK')
        self.assertEqual(result['usage_delta']['rpc_cu'],20)
        self.assertEqual(result['usage_delta']['http_reserved'],0)
        self.assertEqual(result['usage_delta']['http_uncertain_bytes'],MAX_FRAME)

    def test_error_context_redacts_credentials_and_keeps_only_safe_headers(self):
        from engineering.diagnostics.yellowstone_replay_contract_20261015 import safe,metadata
        self.assertEqual(safe('key TOKEN; https://example.alchemy.com/v2/secret',('TOKEN',)),
            'key [REDACTED]; [REDACTED_URL]')
        self.assertLessEqual(len(safe('x'*20000,())),8192)
        self.assertEqual(metadata((('x-token','secret'),('request-id','safe'),
            ('server','secret')),('secret',)),{'request-id':'safe','server':'[REDACTED]'})

    def test_local_recording_failure_closes_reservation_before_any_rpc(self):
        from engineering.diagnostics import yellowstone_replay_contract_20261015 as diagnostic
        real_save=diagnostic.save;injected=[]
        def failed_once(path,value):
            if value['calls'] and value['calls'][-1]['status']=='DISPATCH_READY' and not injected:
                injected.append(True);raise OSError('fixture_output_failed')
            real_save(path,value)
        with patch.object(diagnostic,'save',failed_once):
            with self.assertRaisesRegex(OSError,'fixture_output_failed'):self.exercise()
        final=json.loads((self.root/'probe/result.json').read_text())
        self.assertEqual(len(final['calls']),1)
        self.assertEqual(final['calls'][0]['status'],'LOCAL_FAILURE')
        self.assertNotIn('call_invoked_at',final['calls'][0])
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')


class ReplayCapabilityDiagnosticTests(unittest.TestCase):
    """Actual request/receipt boundaries, disposable ledgers and no network."""
    def setUp(self):
        from engineering.diagnostics import native_replay_capability_20261015 as diagnostic
        from meme_machine.solana_provider_config import AlchemyEndpoint
        self.diagnostic=diagnostic
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.serial=0
        self.config=AlchemyEndpoint.parse('https://solana-mainnet.g.alchemy.com/v2/disposable-secret')
        context=patch.dict(os.environ,MM_OPERATIONAL_PHASE='OBSERVATION')
        context.start();self.addCleanup(context.stop)

    def fixture(self,actions=(),*,unary_error=None,hang_unary=False):
        from meme_machine.yellowstone import geyser_pb2 as pb
        self.serial+=1
        budget=Budget.create(self.root/f'usage-{self.serial}.sqlite',limits=LIMITS,
            wall_seconds=900,modeled_spend_limit='0.20',maximum_native_opens=8)
        state=SimpleNamespace(unary=[],requests=[],stream_options=[],admissions=[],calls=[],
            active=0,peak=0,closed=False,options=[],http_calls=0)
        class UnaryCall:
            def __init__(self,method,decode):self.method=method;self.decode=decode;self.finished=False;self.cancelled=False
            def __await__(self):
                async def get():
                    if hang_unary:await asyncio.Event().wait()
                    self.finished=True
                    if unary_error is not None:raise unary_error
                    value=(pb.SubscribeReplayInfoResponse(first_available=1000)
                        if self.method.endswith('SubscribeReplayInfo') else pb.GetSlotResponse(slot=2000))
                    return self.decode(value.SerializeToString())
                return get().__await__()
            def done(self):return self.finished
            def cancel(self):self.cancelled=True;self.finished=True
            async def initial_metadata(self):return (('server','fixture'),('x-token','disposable-secret'))
            async def trailing_metadata(self):return (('request-id','offline'),)
        class StreamCall:
            def __init__(self,action,decode):
                self.action=action;self.decode=decode;self.reads=0;self.cancelled=False
                state.active+=1;state.peak=max(state.peak,state.active);state.calls.append(self)
            async def write(self,request):
                if self.action=='write_hang':await asyncio.Event().wait()
            async def read(self):
                if self.action=='read_hang':await asyncio.Event().wait()
                if isinstance(self.action,BaseException):raise self.action
                self.reads+=1
                value=(self.action if isinstance(self.action,bytes)
                    else pb.SubscribeUpdate(slot=pb.SubscribeUpdateSlot(slot=1800+self.reads)).SerializeToString())
                return self.decode(value)
            def cancel(self):
                if not self.cancelled:state.active-=1
                self.cancelled=True
            async def code(self):
                if self.action=='code_hang':await asyncio.Event().wait()
                return grpc.StatusCode.CANCELLED if self.cancelled else grpc.StatusCode.OK
            async def initial_metadata(self):return (('server','fixture'),)
            async def trailing_metadata(self):return (('request-id','offline'),)
        class Channel:
            def unary_unary(self,path,request_serializer,response_deserializer):
                def call(request,**options):
                    state.unary.append((path,request.SerializeToString(),options))
                    request_serializer(request)
                    call=UnaryCall(path,response_deserializer);state.unary_call=call;return call
                return call
            def stream_stream(self,path,request_serializer,response_deserializer):
                if path!='/geyser.Geyser/Subscribe':raise AssertionError('unexpected native method')
                index=len(state.requests)
                def call(**options):
                    state.stream_options.append(options)
                    raw=StreamCall(actions[index] if index<len(actions) else None,response_deserializer)
                    write=raw.write
                    async def captured(request):
                        wire=request_serializer(request)
                        state.requests.append(pb.SubscribeRequest.FromString(wire))
                        await write(request)
                    raw.write=captured
                    return raw
                return call
            async def close(self,**kwargs):state.closed=True
        channel=Channel()
        def factory(target,credentials,**options):
            self.assertEqual(target,self.diagnostic.HOST);state.options.extend(options['options']);return channel
        def acquire(*args,**kwargs):state.admissions.append((args,kwargs));return 0
        def http(config,ledger,governor,window):
            state.http_calls+=1
            class Response(io.BytesIO):
                def getcode(self):return 200
            def opener(request,timeout):
                state.http_request=request;state.http_timeout=timeout
                state.http_response=Response(b'{"jsonrpc":"2.0","id":1,"result":2000}')
                return state.http_response
            return self.diagnostic.http_tip(config,ledger,governor,window,opener=opener)
        return budget,state,channel,factory,SimpleNamespace(acquire=acquire),http

    def exercise(self,actions=(),*,unary_error=None,hang_unary=False,window=None):
        budget,state,channel,factory,governor,http=self.fixture(actions,unary_error=unary_error,hang_unary=hang_unary)
        result=asyncio.run(self.diagnostic.experiment(self.config,self.config.credential,
            budget,governor,self.root/f'probe-{self.serial}',channel_factory=factory,http=http,window=window))
        self.assertEqual(budget.snapshot()['native_reserved'],'0')
        self.assertEqual(budget.snapshot()['http_reserved'],'0')
        self.assertEqual(state.active,0);self.assertTrue(state.closed)
        return result,budget,state

    def test_exact_control_scout_requests_and_single_durable_dispatch_accounting(self):
        from meme_machine.yellowstone import geyser_pb2 as pb
        from meme_machine.solana_selective_source import scout_request
        result,budget,state=self.exercise()
        self.assertEqual(result['status'],'CAPABILITY_SAMPLE_COMPLETE_NOT_COVERAGE_PROOF')
        self.assertEqual(len(state.requests),2);control,scout=state.requests
        self.assertEqual(control.commitment,pb.FINALIZED);self.assertEqual(scout.commitment,pb.FINALIZED)
        self.assertEqual(control.from_slot,1744);self.assertEqual(scout.from_slot,1744)
        self.assertEqual(set(control.blocks_meta),{'b'});self.assertEqual(set(control.slots),{'f'})
        self.assertTrue(control.slots['f'].filter_by_commitment)
        self.assertFalse(control.accounts);self.assertFalse(control.transactions);self.assertFalse(control.transactions_status)
        expected=scout_request();expected.from_slot=1744
        self.assertEqual(scout,expected);self.assertEqual(set(scout.accounts),{'p'})
        self.assertEqual([(s.offset,s.length) for s in scout.accounts_data_slice],[(0,49)])
        self.assertEqual(state.peak,1);self.assertEqual([s.reads for s in state.calls],[64,64])
        self.assertTrue(all(s.cancelled for s in state.calls))
        self.assertEqual(result['usage_delta']['rpc_cu'],40)
        self.assertEqual(result['usage_delta']['solana_rpc_elements'],3)
        self.assertEqual(result['usage_delta']['http_attempts'],5)
        self.assertEqual(result['usage_delta']['native_opens'],2)
        self.assertEqual(result['usage_delta']['native_bytes'],result['delivered_protobuf_bytes'])
        self.assertEqual(result['usage_delta']['native_uncertain_bytes'],8*MAX_FRAME)
        self.assertEqual(len(state.admissions),5)
        self.assertTrue(all(a[0]==('solana','pump',50) for a in state.admissions))
        self.assertTrue(all(0<a[1]['deadline_seconds']<=3 for a in state.admissions))
        self.assertTrue(all(not o['wait_for_ready'] and 0<o['timeout']<=4 for o in state.stream_options))
        self.assertIn(('grpc.enable_retries',0),state.options)
        self.assertNotIn('disposable-secret',(self.root/f'probe-{self.serial}/result.json').read_text())
        self.assertEqual(result['paper_starts'],0);self.assertEqual(result['economic_history_writes'],0)

    def test_semantic_rejections_allow_only_one_commitment_only_comparison(self):
        from meme_machine.yellowstone import geyser_pb2 as pb
        error=grpc.aio.AioRpcError(grpc.StatusCode.INVALID_ARGUMENT,(),(),details='failed replay; disposable-secret')
        result,_,state=self.exercise((error,error))
        self.assertEqual(len(state.requests),3);self.assertEqual(state.peak,1)
        comparison=pb.SubscribeRequest();comparison.CopyFrom(state.requests[0]);comparison.commitment=pb.CONFIRMED
        self.assertEqual(state.requests[2],comparison)
        self.assertEqual([s['status'] for s in result['streams']],['INVALID_ARGUMENT','INVALID_ARGUMENT','MESSAGE_LIMIT'])
        self.assertEqual(result['streams'][0]['details'],'failed replay; [REDACTED]')
        self.assertEqual(result['usage_delta']['native_opens'],3)

    def test_terminal_provider_errors_never_open_a_later_stream(self):
        for status in (grpc.StatusCode.UNIMPLEMENTED,grpc.StatusCode.UNAVAILABLE,grpc.StatusCode.RESOURCE_EXHAUSTED):
            with self.subTest(status=status):
                error=grpc.aio.AioRpcError(status,(),(('retry-after','8'),),details='terminal provider response')
                result,_,state=self.exercise((error,))
                self.assertEqual(result['status'],'STOPPED');self.assertEqual(len(state.requests),1)
                self.assertEqual(result['streams'][0]['status'],status.name)
                self.assertEqual(result['streams'][0]['trailing_metadata'],{'retry-after':'8'})
                self.assertEqual(result['usage_delta']['native_opens'],1)

    def test_unsupported_unary_aborts_before_http_or_subscription(self):
        error=grpc.aio.AioRpcError(grpc.StatusCode.UNIMPLEMENTED,(),(),details='unsupported; disposable-secret')
        result,_,state=self.exercise(unary_error=error)
        self.assertEqual(len(state.unary),1);self.assertEqual(state.http_calls,0);self.assertEqual(state.requests,[])
        self.assertEqual(result['calls'][0]['status'],'UNIMPLEMENTED')
        self.assertEqual(result['calls'][0]['details'],'unsupported; [REDACTED]')
        self.assertEqual(result['usage_delta']['rpc_cu'],10)
        self.assertEqual(result['usage_delta']['http_uncertain_bytes'],MAX_FRAME)

    def test_aggregate_byte_credit_stops_without_an_extra_read_or_subscription(self):
        from meme_machine.yellowstone import geyser_pb2 as pb
        value=pb.SubscribeUpdate();value.account.account.data=b'x'*(MAX_FRAME-15)
        raw=value.SerializeToString();self.assertEqual(len(raw),MAX_FRAME)
        # Isolate native delivery credit from the independently smaller retained
        # exact-response limit; do not create a 40-MiB diagnostic test artifact.
        with patch.object(self.diagnostic,'OUTPUT_BYTES',128*MIB),patch.object(self.diagnostic,'record'):
            result,_,state=self.exercise((raw,))
        self.assertEqual(result['delivered_protobuf_bytes'],32*MIB)
        self.assertEqual(result['streams'][0]['status'],'BYTE_CREDIT_STOP')
        self.assertEqual(state.calls[0].reads,2);self.assertEqual(len(state.requests),1)
        self.assertEqual(result['usage_delta']['native_bytes'],32*MIB)

    def test_absolute_deadline_cancels_hung_unary_and_releases_receipt(self):
        import time
        budget,state,channel,factory,governor,http=self.fixture(hang_unary=True)
        window=self.diagnostic.Window();original=channel.unary_unary
        def expiring_unary(*args,**kwargs):
            invoke=original(*args,**kwargs)
            def call(request,**options):
                pending=invoke(request,**options)
                # Exercise expiry with a real in-flight call. Starting this
                # 50-ms remainder before SQLite fixture setup instead tests
                # legitimate pre-dispatch expiry on a busy offline runner.
                window.origin=time.monotonic()-43.95
                return pending
            return call
        channel.unary_unary=expiring_unary
        result=asyncio.run(self.diagnostic.experiment(self.config,self.config.credential,
            budget,governor,self.root/f'probe-{self.serial}',channel_factory=factory,http=http,window=window))
        self.assertEqual(result['status'],'STOPPED');self.assertEqual(len(state.unary),1)
        self.assertTrue(state.unary_call.cancelled);self.assertEqual(state.requests,[])
        self.assertLess(result['elapsed_seconds'],45)
        self.assertEqual(budget.snapshot()['native_reserved'],'0')
        self.assertEqual(budget.snapshot()['http_reserved'],'0')
        self.assertEqual(state.active,0);self.assertTrue(state.closed)
        budget,state,_,factory,governor,http=self.fixture()
        window=self.diagnostic.Window()
        def expired_admission(*args,**kwargs):window.origin-=45;return 0
        governor.acquire=expired_admission
        result=asyncio.run(self.diagnostic.experiment(self.config,self.config.credential,
            budget,governor,self.root/f'probe-{self.serial}',channel_factory=factory,http=http,window=window))
        self.assertEqual(result['status'],'STOPPED');self.assertEqual(state.unary,[])
        self.assertEqual(state.http_calls,0);self.assertEqual(budget.snapshot()['http_attempts'],'0')
        self.assertEqual(budget.snapshot()['http_reserved'],'0');self.assertTrue(state.closed)

    def test_stream_write_read_and_close_deadlines_preserve_cleanup(self):
        import time
        for action in ('write_hang','read_hang','code_hang'):
            with self.subTest(action=action):
                budget,state,channel,_,governor,_=self.fixture((action,))
                output=self.root/f'direct-{self.serial}';output.mkdir()
                result=dict(streams=[],delivered_protobuf_bytes=0)
                request=self.diagnostic.requests_at(1744)[0][1]
                window=self.diagnostic.Window(time.monotonic()-43.9)
                row=asyncio.run(self.diagnostic.stream_once(channel,'control_finalized',request,
                    self.config.credential,self.config,budget,governor,window,output,result))
                self.assertEqual(state.active,0);self.assertTrue(state.calls[0].cancelled)
                self.assertTrue(row['reservation_closed']);self.assertEqual(budget.snapshot()['native_reserved'],'0')
                self.assertEqual(budget.snapshot()['native_opens'],'1')
                self.assertLessEqual(time.monotonic()-window.origin,45)
                if action=='code_hang':self.assertIn('cleanup_failure',row)
                else:self.assertEqual(row['messages_delivered'],0)

    def test_http_tip_uses_actual_finalized_rpc_and_closes_response(self):
        budget,state,_,_,governor,http=self.fixture()
        row=http(self.config,budget,governor,self.diagnostic.Window())
        request=json.loads(state.http_request.data)
        self.assertEqual(request,dict(jsonrpc='2.0',id=1,method='getSlot',params=[dict(commitment='finalized')]))
        self.assertEqual(row['slot'],2000);self.assertEqual(row['http_status'],200)
        self.assertEqual(budget.snapshot()['rpc_cu'],'20');self.assertEqual(budget.snapshot()['http_attempts'],'1')
        self.assertEqual(budget.snapshot()['http_reserved'],'0')
        self.assertTrue(state.http_response.closed)
        self.assertGreater(state.http_timeout,0);self.assertLessEqual(state.http_timeout,5)


if __name__=='__main__':unittest.main()
