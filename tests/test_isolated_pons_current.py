"""Owned Pons Current bootstrap contracts, with real metered offline parent IPC.

These proofs are not native live-source throughput or held financial protection.
The mandatory Nitro capability is checked before opening any native store.
"""
import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from meme_machine.operational.parent_transport import ParentHTTP
from meme_machine.operational.transport_bridge import EndpointAlias
from meme_machine.runtime.isolated_native_bootstrap import NativeRunnerPorts
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from tests import test_child_transport as child_fixtures
from tests import test_isolated_native_resources as sizing_fixtures


class IsolatedPonsCurrentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await child_fixtures.ChildTransportTests.asyncSetUp(self)
        self.pons=replace(self.pons,alias=EndpointAlias('pons-current','robinhood',self.pons.alias.methods),
            operation='pons_current_qualification')
        discovery=replace(self.pons,alias=EndpointAlias('pons-discovery','robinhood',self.pons.alias.methods),
            operation='pons_discovery')
        survivor=replace(self.pons,alias=EndpointAlias('pons-survivor','robinhood',self.pons.alias.methods),
            operation='pons_survivor_qualification')
        self.http=ParentHTTP(self.budget,[self.pons,discovery,survivor],opener=self.physical)
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
            with self.assertRaisesRegex(ValueError,'nitro_stream_port_unavailable'):
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
            with self.assertRaisesRegex(ValueError,'checkpoint_plane_owner'):
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
            with self.assertRaisesRegex(ValueError,'nitro_stream_port_unavailable'):self.context()
        self.assertFalse((self.resources.root/'pons-current').exists())
        self.assertFalse(self.physical.calls);self.assert_no_money()
