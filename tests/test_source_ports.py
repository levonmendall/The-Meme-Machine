"""Real parent IPC/native reservations through original source transport shapes."""
import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import grpc

from meme_machine.operational.child_transport import ChildTransportFailure
from meme_machine.operational.parent_transport import ParentHTTP,NativeSourceBinding
from meme_machine.operational.source_ports import NativeGrpcChannel,NativeWebSocket
from meme_machine.operational.transport_bridge import EndpointAlias
from meme_machine.runtime.isolated_native_bootstrap import NativeRunnerPorts
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from meme_machine.yellowstone import geyser_pb2 as pb
from tests import test_child_transport as child_fixtures
from tests import test_parent_native_transport as fixtures
from tests import test_isolated_native_resources as sizing_fixtures


class SourcePortsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await child_fixtures.ChildTransportTests.asyncSetUp(self)
        self.sessions=[]
        def factory(source,transport,**kwargs):
            async def opened():
                native=fixtures._Native()
                native.transport=transport
                self.sessions.append(native)
                return native
            return opened
        self.enterContext(patch('meme_machine.operational.parent_transport.authenticated_native_factory',factory))
        sources=[replace(self.sol,alias=EndpointAlias(alias,'solana',self.sol.alias.methods))
            for alias in ('yellowstone','websocket')]
        sources+=[replace(self.sol,alias=EndpointAlias('current','solana',self.sol.alias.methods),
            operation='pump_current_qualification')]
        for op in ('pump_history_receipt','pump_recovery_restart','pump_source_identity'):
            for priority in range(1,7):
                sources.append(replace(self.sol,
                    alias=EndpointAlias(op+'_'+str(priority),'solana',self.sol.alias.methods),
                    operation=op,read_class='solana_evidence_'+str(priority)))
        self.http=ParentHTTP(self.budget,sources,opener=self.physical)
        self.addAsyncCleanup(self.http.aclose)
        self.channel,self.parent=await child_fixtures.ChildTransportTests.connected(self,
            native_sources=[NativeSourceBinding(sources[0],'yellowstone'),
                NativeSourceBinding(sources[1],'solana_websocket')])
        self.resources=IsolatedNativeResources(self.root/'state',
            sizing_facts=sizing_fixtures.authenticated(sizing_fixtures.receipt()),clock=lambda:1000)
        self.ports=NativeRunnerPorts(self.resources,self.channel)
        self.addCleanup(self.resources.close)
        self.addCleanup(self.ports.close)

    async def test_original_grpc_shape_two_independent_streams_and_full_handoff(self):
        async with self.ports.source_channel() as channel:
            method=channel.stream_stream('/geyser.Geyser/Subscribe',
                request_serializer=lambda value:value.SerializeToString(),response_deserializer=lambda value:value)
            calls=[method(),method(metadata=())]
            req=pb.SubscribeRequest(commitment=pb.FINALIZED)
            req.slots['f'].filter_by_commitment=True
            await asyncio.gather(*(call.write(req) for call in calls))
            self.assertEqual(len(self.sessions),2)
            self.assertEqual(self.budget.snapshot()['native_opens'],'2')
            for index,session in enumerate(self.sessions):
                self.assertEqual(session.writes,[req.SerializeToString()])
                session.values.put_nowait(b'actual-frame-'+str(index).encode())
            replies=await asyncio.gather(*(call.read() for call in calls))
            self.assertEqual(set(replies),{b'actual-frame-0',b'actual-frame-1'})
            self.assertFalse(self.parent.contents)
            self.assertTrue(all(call.cancel() for call in calls))
        self.assertTrue(all(session.closed for session in self.sessions))
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertFalse(self.parent.contents)
        self.assertFalse(self.physical.calls)

    async def test_pending_read_cancellation_closes_only_its_instance_and_joins_cleanup(self):
        async with self.ports.source_channel() as channel:
            factory=channel.stream_stream('/geyser.Geyser/Subscribe',
                request_serializer=lambda value:value,response_deserializer=lambda value:value)
            first,second=factory(),factory()
            task=asyncio.create_task(first.read())
            await second._stream()
            async with asyncio.timeout(1):
                while len(self.parent.contents)<1:await asyncio.sleep(.005)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue((await first.opening).closed)
            self.assertFalse((await second.opening).closed)
            self.sessions[1].values.put_nowait(b'other-stream')
            self.assertEqual(await second.read(),b'other-stream')
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertFalse(self.parent.contents)

    async def test_native_eof_preserves_original_grpc_eof(self):
        async with self.ports.source_channel() as channel:
            call=channel.stream_stream('/geyser.Geyser/Subscribe',
                request_serializer=lambda value:value,response_deserializer=lambda value:value)()
            await call._stream()
            self.sessions[0].values.put_nowait(grpc.aio.EOF)
            self.assertIs(await call.read(),grpc.aio.EOF)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')

    async def test_actual_logs_subscription_and_original_raw_payload(self):
        from meme_machine.solana_selective_history import PROGRAMS
        from websockets.exceptions import ConnectionClosed
        async with self.ports.source_websocket() as websocket:
            sub=json.dumps(dict(jsonrpc='2.0',id=1,method='logsSubscribe',
                params=[dict(mentions=[PROGRAMS['pump']]),dict(commitment='finalized')]))
            await websocket.send(sub)
            self.assertEqual(self.sessions[0].writes,[sub.encode()])
            body=b'{"jsonrpc":"2.0","id":1,"result":123}'
            self.sessions[0].values.put_nowait(body)
            self.assertEqual(await websocket.recv(),body)
            self.sessions[0].values.put_nowait(grpc.aio.EOF)
            with self.assertRaises(ConnectionClosed):await websocket.recv()
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')

    async def test_fixed_public_source_roles_no_url_or_priority_remap(self):
        config=self.ports.source_config()
        self.assertEqual(config.identity,self.sol.identity)
        self.assertFalse(any(hasattr(config,key) for key in ('http_url','stream_url','credential')))
        for operation,expected in [('history_receipt','pump_history_receipt'),
                ('recovery_restart','pump_recovery_restart'),('unattributed','pump_source_identity')]:
            for priority in range(1,7):
                ref=self.ports.source_rpc(priority,operation=operation).source
                self.assertEqual(ref.operation,expected)
                self.assertEqual(ref.read_class,'solana_evidence_'+str(priority))
        for priority in (True,0,7):
            with self.assertRaises(ValueError):self.ports.source_rpc(priority,operation='history_receipt')
        with self.assertRaises(ValueError):self.ports.source_rpc(1,operation='held')
        self.assertEqual(self.ports.rpc_port('pump','current').source.alias,'current')
        async with self.ports.source_channel() as channel:
            with self.assertRaises(ChildTransportFailure):
                channel.stream_stream('/arbitrary/method',request_serializer=bytes,response_deserializer=bytes)
            call=channel.stream_stream('/geyser.Geyser/Subscribe',request_serializer=bytes,response_deserializer=bytes)
            with self.assertRaises(ChildTransportFailure):call(metadata=(('x-token','forbidden'),))
        self.assertFalse(self.sessions)
        self.assertFalse(self.physical.calls)

    async def test_fixed_source_entry_refuses_missing_pons_profile_before_any_owner_or_provider(self):
        import threading
        from meme_machine.operational.isolated_native_source import run_contained
        class Reader:
            def apply_next(self,*args,**kwargs):raise AssertionError('unexpected sizing work')
        with patch('sqlite3.connect',side_effect=AssertionError('native state opened')):
            with self.assertRaisesRegex(ValueError,'read_role_unavailable'):
                await asyncio.to_thread(run_contained,resources=self.resources,ports=self.ports,
                    sizing_reader=Reader(),stopped=threading.Event())
        self.assertFalse(list(self.resources.root.rglob('*.sqlite')))
        self.assertFalse(self.physical.calls)

    async def test_private_native_cache_authority_uses_parent_identity_without_url(self):
        from pathlib import Path
        from contextlib import closing
        import os
        from meme_machine.lanes.pump import solana_evidence_runtime as runtime
        from meme_machine.runtime.candidate_history import CandidateHistory
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from meme_machine.solana_history_delivery import capture,deliver,acknowledge,generation
        from meme_machine.solana_rolling_history import program_scope
        from meme_machine.solana_selective_history import PROGRAMS
        from meme_machine.solana_selective_source import install,SelectiveSource,commit_candidate_batch,commit_control
        from tests.isolated_native_control_fixture import start_command_source
        from tests.test_pump_cache_source_authority import PumpCacheSourceAuthorityTests,FIXTURE
        from types import SimpleNamespace
        case=PumpCacheSourceAuthorityTests('runTest')
        case.setUp();self.addCleanup(case.doCleanups)
        cap=IsolatedNativeResources(self.root/'native-cache',
            sizing_facts=sizing_fixtures.authenticated(sizing_fixtures.receipt(case.seen)),
            clock=lambda:case.seen)
        ports=NativeRunnerPorts(cap,self.channel)
        self.addCleanup(cap.close);self.addCleanup(ports.close)
        case.root=cap.root;case.cache_path=cap.root/'candidate-history.sqlite'
        case.endpoint=AlchemyEndpoint.parse(fixtures.SOL)
        with patch.dict(os.environ,MM_SOLANA_CANDIDATE_HISTORY_DB=str(case.cache_path),
                MM_SOLANA_READ_RPC_URL=fixtures.SOL):
            driver,_close_source=await start_command_source(SimpleNamespace(
                resources=cap,ports=ports,addAsyncCleanup=self.addAsyncCleanup))
            def seed(state):
                # The actual source owns this canonical connection. Retain the
                # original frame/decode/FULL delivery/ACK/publication fixture;
                # never open a second writer or fabricate command readiness.
                history=install(state)
                history.clock=history.lifecycle.clock=lambda:case.seen
                state.fence.endpoint_identity=history.endpoint_identity=case.endpoint.identity
                history.lifecycle.delivery_separated=True
                history.startup.begin()
                values=[case.native_frame(100,case.at-60),
                    case.native_frame(101,case.creation_at,FIXTURE['pump'][0]),
                    case.native_frame(102,case.at,case.trade_tx),
                    case.native_frame(103,case.at+1)]
                original_clock=state.writer.clock
                state.writer.clock=lambda:case.seen
                try:
                    commit_candidate_batch(state,values,
                        {PROGRAMS['pump']:program_scope('pump')},'offline-cache-session',publish=False)
                    for value in values:commit_control(state,value)
                finally:
                    # Captured-frame health uses its original fixture clock;
                    # actual command envelope expiry keeps the service clock.
                    state.writer.clock=original_clock
                life=history.lifecycle
                first=capture(life);self.assertTrue(first['rows'])
                self.assertTrue(acknowledge(life,first,deliver(first)))
                proofs=capture(life);self.assertTrue(proofs['proofs'])
                self.assertTrue(acknowledge(life,proofs,deliver(proofs)))
                life.publish(proof_ids=tuple(proofs['publication_ids']))
                self.assertIsNone(life.unconsumed(program_scope('pump'),through=102))
                self.assertEqual(history.rolling.missing('pump',history.scope_for('pump',case.mint),
                    100,102,as_of=case.seen),[])
                source=SelectiveSource(SimpleNamespace(credential='offline',
                    identity=case.endpoint.identity),None)
                state.fence.health('source_drain_observation',source.drain_snapshot())
                authority=dict(candidate_scope=history.scope_for('pump',case.mint),
                    program_scope=program_scope('pump'),endpoint=case.endpoint.identity,
                    generation=generation(life))
                with closing(CandidateHistory(case.cache_path,clock=lambda:case.seen)) as cache:
                    expected=cache.covered_events('pump',case.mint,case.scope,case.at-60,case.at,
                        upper_slot=102,source_authority=authority)
                self.assertTrue(any(event.get('event_type')=='trade' for event in expected))
                return expected
            expected=await driver.work(seed)
            plane=ports.pump_evidence('pump');self.addCleanup(plane.close)
            def canonical_read():
                # The real synchronous native consumer needs its own thread;
                # its ACK must leave the source event loop free to reply.
                with closing(ports.pump_evidence('pump')) as consumer:
                    return consumer.pump_events(case.scope,case.mint,case.at-60,case.at,upper_slot=102)
            canonical=await asyncio.to_thread(canonical_read)
            self.assertTrue(any(event.get('event_type')=='trade' for event in canonical))
            del os.environ['MM_SOLANA_READ_RPC_URL']
            with patch.object(AlchemyEndpoint,'parse',side_effect=AssertionError('child URL lookup')):
                with runtime.LocalPumpTape(plane)._cached_window_authority(case.mint,
                        case.at-60,case.at,102) as authority,closing(CandidateHistory(case.cache_path)) as cache:
                    actual=cache.covered_events('pump',case.mint,case.scope,case.at-60,case.at,
                        upper_slot=102,source_authority=authority)
            self.assertEqual(actual,expected)
            self.assertEqual(plane.native_endpoint_identity,self.sol.identity)
            self.assertFalse(plane.reader.db.in_transaction)

    async def test_private_evidence_rejects_foreign_path_before_reader_open(self):
        from meme_machine.lanes.pump.solana_evidence_runtime import RuntimeEvidence,EvidenceUnavailable
        with patch('meme_machine.lanes.pump.solana_evidence_runtime.EvidenceReader',
                side_effect=AssertionError('foreign database opened')):
            with self.assertRaises(EvidenceUnavailable):
                RuntimeEvidence(self.root/'foreign.sqlite',owner='pump',
                    native_resources=self.resources,native_ports=self.ports)
        self.assertFalse((self.root/'foreign.sqlite').exists())


if __name__=='__main__':unittest.main()
