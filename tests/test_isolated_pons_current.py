"""Owned Pons Current bootstrap contracts, with real metered offline parent IPC.

These proofs are not native live-source throughput or held financial protection.
The mandatory Nitro capability is checked before opening any native store.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from functools import partial
import json
import socket
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine.operational.parent_transport import ParentHTTP,NativeSourceBinding
from meme_machine.operational.child_transport import ChildChannel,ChildTransportFailure
from meme_machine.operational.parent_channel import ParentChannel,serve_connected
from meme_machine.operational.transport_bridge import EndpointAlias
from meme_machine.runtime.isolated_native_bootstrap import NativeRunnerPorts
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from tests import test_child_transport as child_fixtures
from tests import test_isolated_native_resources as sizing_fixtures


class IsolatedPonsCurrentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await child_fixtures.ChildTransportTests.asyncSetUp(self)
        methods=self.pons.alias.methods|{'eth_getBlockByNumber','eth_getLogs','eth_getCode',
            'eth_call','eth_getTransactionReceipt','eth_getTransactionByHash','eth_gasPrice'}
        self.pons=replace(self.pons,alias=EndpointAlias('pons-current','robinhood',methods),
            operation='pons_current_qualification')
        discovery=replace(self.pons,alias=EndpointAlias('pons-discovery','robinhood',self.pons.alias.methods),
            operation='pons_discovery')
        survivor=replace(self.pons,alias=EndpointAlias('pons-survivor','robinhood',self.pons.alias.methods),
            operation='pons_survivor_qualification')
        self.bindings=[self.pons,discovery,survivor]
        self.http=ParentHTTP(self.budget,self.bindings,opener=self.physical)
        self.addAsyncCleanup(self.http.aclose)
        self.channel,_=await child_fixtures.ChildTransportTests.connected(self)
        self.now=[1000]
        self.resources=IsolatedNativeResources(self.root/'private-native',
            sizing_facts=sizing_fixtures.authenticated(sizing_fixtures.receipt()),clock=lambda:self.now[0])
        self.ports=NativeRunnerPorts(self.resources,self.channel)
        self.addCleanup(self.resources.close);self.addCleanup(self.ports.close)
        self.env=patch.dict('os.environ',{'MM_MODE':'PAPER','MM_DIRECTIONAL_COMPOSITE_REQUIRED':'1'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        root=self.resources.root/'pons-current'
        self.paths=dict(ROOT=root,REPORT=root/'report.json',SKILL_DB=root/'pons-selective-wallet-skill.sqlite',
            PROGRESS=root/'cohort-progress.json',ROWS_LOG=root/'candidate-rows.jsonl',
            QUALIFIERS_LOG=root/'qualifiers.jsonl',PROVIDER_LOG=root/'provider-sessions.jsonl',
            RECOVERY_LOG=root/'sequencer-recoveries.jsonl')

    def assert_no_money(self):
        from tests.test_isolated_native_bootstrap import IsolatedNativeBootstrapTests
        IsolatedNativeBootstrapTests.assert_no_money(self)

    def context(self,**changes):
        from meme_machine.runtime.isolated_pons_current import PonsCurrentContext
        arguments=dict(resources=self.resources,ports=self.ports,paths=self.paths,
            endpoint=self.ports.rpc_port('pons','current').source)
        arguments.update(changes)
        return PonsCurrentContext(**arguments)

    async def test_actual_run_requires_real_nitro_capability_before_any_native_or_money_open(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        with patch.multiple(cohort,**self.paths),patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
            with self.assertRaisesRegex((ValueError,ChildTransportFailure),'nitro_stream_port_unavailable|child_native_source'):
                cohort.run(self.ports.rpc_port('pons','current').source,campaign=True,
                    native_resources=self.resources,native_ports=self.ports)
        self.assertFalse((self.resources.root/'pons-current').exists())
        self.assertFalse(self.physical.calls);self.assert_no_money()

    async def test_native_context_rejects_foreign_source_before_native_open(self):
        with patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
            with self.assertRaisesRegex(ValueError,'pons_current_source'):
                self.context(endpoint=self.ports.rpc_port('pons','discovery').source)
        self.assertFalse((self.resources.root/'pons-current').exists())
        self.assertFalse(self.physical.calls)

    async def test_native_context_rejects_external_or_symlink_projection_before_open(self):
        external=self.root/'external.json';external.write_text('preserve')
        for bad in (external,self.resources.root/'pons-current'/'linked-report.json'):
            if bad!=external:
                bad.parent.mkdir();bad.symlink_to(external)
            with self.subTest(path=bad),patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
                with self.assertRaisesRegex(ValueError,'pons_current_paths'):
                    self.context(paths=dict(self.paths,REPORT=bad))
        self.assertEqual(external.read_text(),'preserve');self.assertFalse(self.physical.calls)

    async def test_native_context_refuses_financial_environment_without_book_fallback(self):
        with patch.dict('os.environ',{'MM_PAPER_EPOCH':'must-not-adopt'}), \
                patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
            with self.assertRaisesRegex(ValueError,'pons_current_configuration'):self.context()
        self.assertFalse((self.resources.root/'pons-current').exists());self.assertFalse(self.physical.calls)

    async def test_expired_authenticated_sizing_refuses_before_nitro_and_native_store(self):
        self.now[0]=1006
        with patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
            with self.assertRaisesRegex(ValueError,'isolated_sizing_stale'):self.context()
        self.assertFalse((self.resources.root/'pons-current').exists());self.assertFalse(self.physical.calls)

    async def test_native_broker_and_checkpoint_borrow_actual_owned_plane_without_reopen_or_close(self):
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.runtime.robinhood import pons
        plane=self.resources.pons_plane()
        result=dict(candidate_plane_path=str(plane.path),rows=[dict(vector={})],discovery_sessions=[],sequencer_recoveries=[])
        # Monitor actual __init__; type checks keep requiring the genuine Plane.
        with patch.object(type(plane),'__init__',side_effect=AssertionError('Plane reopened')):
            broker=pons.Broker(plane.path,POLICY_HASH,plane=plane,source='alchemy:offline-parent-identity')
            pons.save_cohort_checkpoint(result,91,'candidate_consumed',plane=plane)
            broker.close()
        self.assertEqual(plane.checkpoint_read('pons_cohort')['cursor'],91)
        plane.checkpoint('still-open',dict(genuine=True))
        self.assertEqual(plane.checkpoint_read('still-open'),dict(genuine=True))
        self.assert_no_money();self.assertFalse(self.physical.calls)

    async def test_native_broker_and_checkpoint_reject_foreign_plane_paths(self):
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from meme_machine.runtime.robinhood.pons import Broker,save_cohort_checkpoint
        plane=self.resources.pons_plane();foreign=self.root/'must-not-open.sqlite'
        with patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
            with self.assertRaisesRegex(ValueError,'broker_plane_owner'):Broker(foreign,POLICY_HASH,plane=plane)
            with self.assertRaisesRegex(ValueError,'candidate_checkpoint_owner'):
                save_cohort_checkpoint(dict(candidate_plane_path=str(foreign)),0,'offline',plane=plane)
        self.assertFalse(foreign.exists());self.assert_no_money()

    async def test_native_qualification_worker_expiry_is_a_durable_candidate_boundary(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        from meme_machine.lanes.pons import BoundaryError
        self.now[0]=1006
        with patch.object(cohort,'evaluate_candidate',side_effect=AssertionError('qualification reached with stale sizing')):
            with self.assertRaisesRegex(BoundaryError,'native_USD_value_missing_or_stale'):
                cohort._evaluate_current_candidate(native_resources=self.resources)
        self.assertFalse(self.physical.calls);self.assert_no_money()

    async def test_real_native_discovery_chain_check_uses_parent_source_and_private_store(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        self.physical.body=json.dumps(dict(jsonrpc='2.0',id=1,result=hex(4663))).encode()
        with patch('meme_machine.lanes.pons.provider_topology.discovery_endpoint',
                side_effect=AssertionError('legacy URL resolution')):
            rpc=await asyncio.to_thread(cohort._discovery,'alchemy:metadata-only',native_ports=self.ports)
        self.assertIs(rpc._endpoint,self.ports.rpc_port('pons','discovery').source)
        self.assertEqual(rpc.role,'pons_mandatory_observation_primary')
        self.assertEqual(rpc.observation_route,'canonical_primary')
        self.assertEqual(len(self.physical.calls),1)
        self.assertEqual(self.physical.calls[0]['method'],'eth_chainId')
        self.assertEqual(self.budget.snapshot()['http_attempts'],'1')
        self.assertEqual(self.budget.snapshot()['http_reserved'],'0')
        self.assertTrue((self.resources.root/'pons-immutable.sqlite').is_file())
        self.assert_no_money()

    async def test_duplicate_current_owner_refuses_before_nitro_or_native_open(self):
        from meme_machine.runtime.isolated_pons_current import _claim_owner
        lease=_claim_owner(self.resources)
        try:
            with patch('sqlite3.connect',side_effect=AssertionError('SQLite opened')):
                with self.assertRaisesRegex(ValueError,'pons_current_already_owned'):self.context()
        finally:lease.release()
        # A failed physical capability does not strand the resource's lease.
        for _ in range(2):
            with self.assertRaisesRegex((ValueError,ChildTransportFailure),'nitro_stream_port_unavailable|child_native_source'):self.context()
        self.assertFalse((self.resources.root/'pons-current').exists())
        self.assertFalse(self.physical.calls);self.assert_no_money()

    async def native_connection(self,sessions):
        from meme_machine.lanes.pons.sequencer_feed import _WebSocket
        from meme_machine.lanes.pons.identity import metadata
        from tests.test_parent_sequencer_clock import _Socket
        from tests.lanes.pons.test_pons_finalization import block_header
        self.sockets=[];self.head=200
        def connect(client):
            self.assertEqual(client.url,'wss://feed.mainnet.chain.robinhood.com')
            sock=_Socket(sessions[len(self.sockets)]);self.sockets.append(sock)
            client.sock=sock;client.socket_observer(sock)
            return client
        self.enterContext(patch.object(_WebSocket,'connect',connect))
        codes={metadata(role)['address'].lower():metadata(role)['runtimeBytecode']['onchainBytecode']
            for role in ('pons_v2_factory','pons_v2_hook','uniswap_v4_manager')}
        def provider(request,timeout):
            calls=json.loads(request.data);rows=calls if isinstance(calls,list) else [calls]
            def result(call):
                method=call['method'];params=call['params']
                if method=='eth_chainId':return hex(4663)
                if method=='eth_getCode':return codes[params[0].lower()]
                if method=='eth_getBlockByNumber':
                    n=self.head if params[0]=='latest' else int(params[0],16)
                    return dict(block_header(n),timestamp=hex(1000+n-200))
                if method=='eth_getLogs':return []
                raise AssertionError(method)
            reply=[dict(jsonrpc='2.0',id=call['id'],result=result(call)) for call in rows]
            self.physical.body=json.dumps(reply if isinstance(calls,list) else reply[0]).encode()
            return self.physical(request,timeout)
        http=ParentHTTP(self.budget,self.bindings,opener=provider)
        self.addAsyncCleanup(http.aclose)
        native=NativeSourceBinding(self.bindings[1],'robinhood_sequencer')
        from meme_machine.operational.pons_native_profile import ParentPonsProfiles
        parent_channel=ParentChannel(http,native_sources=[native],
            pons_profiles=ParentPonsProfiles.configured(http,environ={}))
        parent,child=socket.socketpair()
        reader,writer=await asyncio.open_connection(sock=parent)
        serving=asyncio.create_task(serve_connected(reader,writer,parent_channel))
        channel=await asyncio.to_thread(ChildChannel,child)
        async def close():
            try:await asyncio.to_thread(channel.close)
            finally:await asyncio.wait_for(serving,3)
        self.addAsyncCleanup(close)
        self.ports=NativeRunnerPorts(self.resources,channel)
        self.addCleanup(self.ports.close)
        return parent_channel

    async def test_source_preflight_checks_profiles_and_nitro_without_buying_or_opening_state(self):
        from tests.lanes.pons.test_sequencer_feed import row
        await self.native_connection([[dict(version=1,messages=[row(200,block=200,timestamp=1000)])]])
        profiles=await asyncio.to_thread(self.ports.require_pons_profiles)
        self.assertEqual([profile.status for profile in profiles],['ABSENT']*3)
        for _ in range(2):
            self.assertIs(self.ports.require_pons_feed_source(),self.ports.rpc_port('pons','discovery').source)
        self.assertEqual(self.budget.snapshot()['native_opens'],'0')
        self.assertFalse(self.sockets)
        self.assertFalse(self.physical.calls)
        self.assertFalse(list(self.resources.root.glob('*.sqlite')))

    async def actual_run(self,*,cancel_after_checkpoint=False,expected_error=None):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        from meme_machine.runtime import stop
        actual_save=cohort.save_cohort_checkpoint;phases=[];updates=[]
        if not hasattr(self,'_current_executor'):
            # One actual Current consumer retains its real SQLite owner for the
            # same-cap restart. The shared default executor may choose a new
            # thread; it cannot transfer an existing Plane's ownership.
            self._current_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='fixture-pons-current')
            self.addCleanup(self._current_executor.shutdown,wait=True,cancel_futures=False)
        def checkpoint(result,cursor,phase,**kwargs):
            actual_save(result,cursor,phase,**kwargs);phases.append(phase)
            if cancel_after_checkpoint and phase=='discovery_ready':stop.requested.set()
        with patch.multiple(cohort,**self.paths), \
                patch.object(cohort,'save_cohort_checkpoint',side_effect=checkpoint), \
                patch('meme_machine.runtime.status.update',side_effect=lambda *a,**kw:updates.append(kw)), \
                patch('meme_machine.lanes.pons.pons_selective_capital.CohortCapital',
                    side_effect=AssertionError('financial constructor reached')), \
                patch('meme_machine.lanes.pons.pons_survivor_runtime.PaperBook',
                    side_effect=AssertionError('financial constructor reached')):
            with self.assertRaises(stop.Shutdown if expected_error is None else expected_error) as caught:
                call=partial(cohort.run,self.ports.rpc_port('pons','current').source,campaign=True,
                    native_resources=self.resources,native_ports=self.ports)
                await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(
                    self._current_executor,copy_context().run,call),10)
        self.last_error=caught.exception
        return phases,updates

    async def test_actual_native_current_nitro_rpc_survivor_checkpoint_and_cancel_without_money(self):
        from meme_machine.runtime import stop
        from tests.lanes.pons.test_sequencer_feed import row
        payload=dict(version=1,messages=[row(200,block=200,timestamp=1000)])
        await self.native_connection([[payload]])
        prior=stop.requested.is_set();stop.requested.clear()
        try:phases,updates=await self.actual_run(cancel_after_checkpoint=True)
        finally:
            if prior:stop.requested.set()
            else:stop.requested.clear()
        self.assertIn('discovery_ready',phases);self.assertIn('finalizing',phases)
        saved=self.resources.pons_plane().checkpoint_read('pons_cohort')
        # Native inclusive scout enrollment starts one block before the anchor.
        self.assertEqual(saved['cursor'],199)
        self.assertEqual(saved['result']['cohort_accounting']['status'],'UNEXERCISED')
        self.assertEqual(saved['result']['survivor']['last_boundary'],None)
        self.assertEqual(saved['result']['survivor']['accounting']['status'],'UNEXERCISED')
        self.assertFalse(saved['result']['authoritative_readiness'])
        self.assertTrue(updates);self.assertTrue(all(update.get('reconciled') is False for update in updates))
        self.assertEqual(self.budget.snapshot()['native_opens'],'1')
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertEqual(self.budget.snapshot()['native_bytes'],str(len(json.dumps(payload).encode())))
        self.assertFalse(self.resources._native_histories)
        self.assertFalse(self.resources._candidate_histories)
        self.assert_no_money()

    async def test_actual_native_partial_startup_stop_closes_unconnected_feed_and_releases_owner(self):
        from meme_machine.runtime import stop
        await self.native_connection([[],[]])
        prior=stop.requested.is_set();stop.requested.set()
        try:
            for _ in range(2):
                phases,_=await self.actual_run()
                self.assertEqual(phases,[])
                self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        finally:
            if prior:stop.requested.set()
            else:stop.requested.clear()
        self.assertEqual(self.budget.snapshot()['native_opens'],'2')
        self.assertFalse(self.physical.calls)
        self.assertFalse(self.resources._native_histories)
        self.assert_no_money()

    async def test_actual_survivor_factory_failure_preserves_first_error_and_drains_other_native_owners(self):
        from meme_machine.runtime import stop
        await self.native_connection([[]])
        foreign=self.resources.root/'pons-survivor-history.sqlite'
        with sqlite3.connect(foreign) as db:
            db.execute('CREATE TABLE sentinel(value TEXT)');db.execute("INSERT INTO sentinel VALUES('preserve')")
        original=foreign.read_bytes()
        prior=stop.requested.is_set();stop.requested.clear()
        try:phases,_=await self.actual_run(expected_error=ValueError)
        finally:
            if prior:stop.requested.set()
            else:stop.requested.clear()
        self.assertEqual(str(self.last_error),'isolated_native_foreign_state')
        self.assertEqual(phases,['finalizing'])
        self.assertEqual(foreign.read_bytes(),original)
        self.assertFalse(self.physical.calls)
        self.assertFalse(self.resources._native_histories)
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertEqual(self.resources.pons_plane().checkpoint_read('pons_cohort')['result']
            ['cohort_accounting']['status'],'UNEXERCISED')
        self.assert_no_money()

    async def test_actual_owned_restart_preserves_canonical_cursor_and_earns_fresh_native_session(self):
        from meme_machine.runtime import stop
        from tests.lanes.pons.test_sequencer_feed import row
        await self.native_connection([[dict(version=1,messages=[row(200,block=200,timestamp=1000)])],
            [dict(version=1,messages=[row(205,block=205,timestamp=1001)])]])
        prior=stop.requested.is_set();stop.requested.clear()
        try:
            await self.actual_run(cancel_after_checkpoint=True)
            first=self.resources.pons_plane().checkpoint_read('pons_cohort')
            inode=(self.resources.root/'pons-candidates.sqlite').stat().st_ino
            stop.requested.clear();self.head=205
            await self.actual_run(cancel_after_checkpoint=True)
            second=self.resources.pons_plane().checkpoint_read('pons_cohort')
        finally:
            if prior:stop.requested.set()
            else:stop.requested.clear()
        self.assertEqual(first['cursor'],199)
        # Fresh Nitro observation cannot skip an unpurchased canonical suffix.
        # A source task may finish its durable page during the ordinary drain,
        # even before Current consumes that page's returned cursor in memory.
        purchased=set()
        for request in self.physical.calls:
            for call in request if isinstance(request,list) else [request]:
                if call['method']=='eth_getLogs':
                    query=call['params'][0]
                    purchased.update(range(int(query['fromBlock'],16),int(query['toBlock'],16)+1))
        self.assertLessEqual(second['cursor'],205)
        self.assertTrue(set(range(first['cursor']+1,second['cursor']+1))<=purchased)
        self.assertEqual((self.resources.root/'pons-candidates.sqlite').stat().st_ino,inode)
        self.assertEqual(self.budget.snapshot()['native_opens'],'2')
        self.assertEqual(self.budget.snapshot()['native_reserved'],'0')
        self.assertFalse(self.resources._native_histories)
        self.assertFalse(self.resources._candidate_histories)
        self.assert_no_money()
