"""Actual native constructors/owners without a monetary book or live provider.

This establishes bookless startup/reporting/restoration/cancellation contracts,
not authenticated source throughput, held protection or authoritative readiness.
"""
import asyncio
import json
from dataclasses import replace
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine.operational.parent_transport import ParentHTTP
from meme_machine.operational.transport_bridge import EndpointAlias
from meme_machine.runtime.isolated_native_bootstrap import NativeRunnerPorts
from meme_machine.runtime.isolated_native_resources import IsolatedNativeResources
from meme_machine.runtime.survivor_history import Worker
from meme_machine.solana_evidence_plane import EvidenceWriter
from tests import test_child_transport as child_fixtures
from tests import test_isolated_native_resources as sizing_fixtures


class IsolatedNativeBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await child_fixtures.ChildTransportTests.asyncSetUp(self)
        self.sol=replace(self.sol,alias=EndpointAlias('pump-survivor','solana',
            self.sol.alias.methods|{'getGenesisHash'}),operation='pump_survivor_qualification')
        self.pons=replace(self.pons,alias=EndpointAlias('pons-survivor','robinhood',
            self.pons.alias.methods|{'eth_getLogs'}),operation='pons_survivor_qualification')
        current=replace(self.sol,alias=EndpointAlias('pump-current','solana',self.sol.alias.methods),
            operation='pump_current_qualification')
        self.http=ParentHTTP(self.budget,[self.sol,self.pons,current],opener=self.physical)
        self.addAsyncCleanup(self.http.aclose)
        self.channel,_=await child_fixtures.ChildTransportTests.connected(self)
        self.now=[1000]
        self.resources=IsolatedNativeResources(self.root/'private-native',
            sizing_facts=sizing_fixtures.authenticated(sizing_fixtures.receipt()),clock=lambda:self.now[0])
        self.ports=NativeRunnerPorts(self.resources,self.channel)
        self.addCleanup(self.resources.close)
        self.addCleanup(self.ports.close)
        self.env=patch.dict('os.environ',{'MM_MODE':'PAPER'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)

    def assert_no_money(self):
        forbidden={'genesis','positions','journal','sleeve_genesis','sleeve_positions',
            'sleeve_journal','capital_genesis','capital_positions','capital_journal',
            'portfolio_genesis','portfolio_events','shared_capital_genesis'}
        for path in self.resources.root.rglob('*.sqlite*'):
            if path.name.endswith(('-wal','-shm','-journal')):
                continue
            with sqlite3.connect(path) as db:
                tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(tables&forbidden,(path,tables&forbidden))
        self.assertFalse(list(self.resources.root.rglob('*paper.sqlite*')))
        self.assertFalse(list(self.resources.root.rglob('native-genesis.json')))

    async def pump_source(self):
        # Constructors now require the actual owned command generation as well
        # as the private DB. No positive financial/coverage flag is supplied.
        from tests.isolated_native_control_fixture import start_command_source
        return await start_command_source(self)

    def worker(self,lane):
        if lane=='pump':
            from meme_machine.lanes.pump.pumpswap_survivor_runtime import Runtime
            from meme_machine.lanes.pump.pump_acceleration_confirmations import ConfirmationBook
            factory=lambda:Runtime(self.resources.root/'pump-survivor',None,
                self.resources.facts.value()['scope'],ConfirmationBook.from_files(),
                native_resources=self.resources,native_ports=self.ports)
        else:
            from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
            factory=lambda:Runtime(self.resources.root/'pons-survivor',None,
                self.resources.facts.value()['scope'],self.ports.rpc_port('pons','survivor').source,
                scout_path=self.resources.root/'pons-candidates.sqlite',
                native_resources=self.resources,native_ports=self.ports)
        return Worker(factory,enrichment_enabled=False,native_resources=self.resources)

    async def test_actual_pump_survivor_native_worker_bookless_prime_and_close(self):
        await self.pump_source()
        with patch('meme_machine.lanes.pump.pumpswap_survivor_runtime.PaperBook',
                side_effect=AssertionError('financial constructor reached')):
            worker=self.worker('pump')
            result=await asyncio.to_thread(worker.prime)
            final=await asyncio.to_thread(worker.close)
        self.assertIsNone(result['last_boundary'])
        self.assertEqual(final['accounting']['status'],'UNEXERCISED')
        self.assertNotIn('verified',final['accounting_replay'])
        self.assertFalse(final['durable_handoff'])
        self.assertFalse(final['financial_authority'])
        self.assertFalse(final['machinery']['allocation_authority'])
        self.assertFalse(self.physical.calls)
        self.assert_no_money()

    async def test_actual_pons_survivor_wrong_chain_is_observed_without_financial_fallback(self):
        with patch('meme_machine.lanes.pons.pons_survivor_runtime.PaperBook',
                side_effect=AssertionError('financial constructor reached')):
            worker=self.worker('pons')
            result=await asyncio.to_thread(worker.prime)
            final=await asyncio.to_thread(worker.close)
        self.assertEqual(result['last_boundary'],'wrong_chain')
        self.assertEqual(len(self.physical.calls),1)
        self.assertEqual(self.physical.calls[0]['method'],'eth_chainId')
        self.assertEqual(final['accounting']['status'],'UNEXERCISED')
        self.assertEqual(final['held_protection'],'UNEXERCISED')
        self.assertFalse(self.resources._candidate_histories)
        self.assertFalse(final['durable_handoff'])
        self.assert_no_money()

    async def test_actual_pons_survivor_private_history_context_reaches_native_v4_rpc(self):
        from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
        from meme_machine.lanes.pons.pons_selective_v4 import _transport
        from meme_machine.lanes.pons import BoundaryError
        from meme_machine.runtime.robinhood import provider_authority
        from meme_machine.runtime.isolated_native_execution import isolated_native_execution
        physical=self.physical
        def provider(request,timeout):
            calls=json.loads(request.data)
            rows=calls if type(calls) is list else [calls]
            reply=[dict(jsonrpc='2.0',id=row['id'],result=
                hex(4663) if row['method']=='eth_chainId' else []) for row in rows]
            physical.body=json.dumps(reply if type(calls) is list else reply[0]).encode()
            return physical(request,timeout)
        self.http.opener=provider
        def native_owner():
            with isolated_native_execution(self.resources):
                runtime=Runtime(self.resources.root/'pons-survivor',None,
                    self.resources.facts.value()['scope'],self.ports.rpc_port('pons','survivor').source,
                    scout_path=self.resources.root/'pons-candidates.sqlite',
                    native_resources=self.resources,native_ports=self.ports)
                try:
                    with patch.object(provider_authority,'endpoint',side_effect=AssertionError('child URL lookup')):
                        context=runtime._position_context()
                        result=_transport(runtime.endpoint,
                            pool_ids=['0x'+'1'*64],start_block=1,end_block=2,max_events=256,
                            acquisition_state=runtime.history,evidence_context=context)
                        self.assertEqual(result['raw'],[])
                        self.assertIs(context.parent_port.source,self.ports.rpc_port('pons','survivor').source)
                        with self.assertRaisesRegex(BoundaryError,'provider_context_disagreement'):
                            _transport('alchemy:'+'f'*64,
                                pool_ids=['0x'+'1'*64],start_block=1,end_block=2,max_events=256,
                                acquisition_state=runtime.history,evidence_context=context)
                    self.assertTrue(any(key.startswith('pons_log_windows:') for key, in
                        runtime.history.db.execute('SELECT key FROM meta')))
                finally:
                    try:
                        from meme_machine.runtime.isolated_native_bootstrap import bookless_report
                        bookless_report(runtime,'pons')
                    finally:
                        runtime.close()
        await asyncio.to_thread(native_owner)
        self.assertFalse(self.resources._candidate_histories)
        calls=[row for call in self.physical.calls for row in (call if type(call) is list else [call])]
        self.assertEqual([row['method'] for row in calls],['eth_chainId','eth_getLogs'])
        self.assert_no_money()

    async def test_same_owned_history_restarts_actual_native_runtime_without_book_replay(self):
        await self.pump_source()
        worker=self.worker('pump')
        await asyncio.to_thread(worker.prime)
        await asyncio.to_thread(worker.close)
        path=self.resources.root/'pump-survivor-history.sqlite'
        inode=path.stat().st_ino
        worker=self.worker('pump')
        result=await asyncio.to_thread(worker.prime)
        await asyncio.to_thread(worker.close)
        self.assertEqual(path.stat().st_ino,inode)
        self.assertEqual(result['accounting_replay']['status'],'UNEXERCISED')
        self.assert_no_money()

    async def test_failed_actual_constructor_releases_native_owner_on_its_worker(self):
        # Missing real source owner remains a hard boundary. It must not strand
        # off-thread History handles or create a book while falling back.
        worker=self.worker('pump')
        with self.assertRaisesRegex(ValueError,'source_owner_not_started'):
            await asyncio.to_thread(worker.prime)
        with self.assertRaisesRegex(ValueError,'source_owner_not_started'):
            await asyncio.to_thread(worker.close)
        self.assertFalse(self.resources._native_histories)
        self.assertFalse(self.physical.calls)
        self.assert_no_money()

    async def test_stale_sizing_stops_native_step_before_provider_or_fake_funding(self):
        await self.pump_source()
        worker=self.worker('pump')
        await asyncio.to_thread(worker.prime)
        self.now[0]=1006
        # Existing Worker keeps original ownership and first failure during close.
        worker.future=worker.pool.submit(worker._step,True)
        with self.assertRaisesRegex(ValueError,'sizing_stale'):
            await asyncio.to_thread(worker.close)
        self.assertFalse(self.physical.calls)
        self.assert_no_money()

    async def test_unexpected_native_position_marker_is_preserved_and_blocks_before_provider(self):
        await self.pump_source()
        worker=self.worker('pump')
        await asyncio.to_thread(worker.prime)
        def retain_marker():
            history=worker.service.history
            row=history.graduate('offline-marker',dict(at=1000,identity='offline-fixture'))
            row.update(position='unexpected-private-native-owner',state='reserved')
            history.save(row)
        await asyncio.wrap_future(worker.pool.submit(retain_marker))
        worker.future=worker.pool.submit(worker._step,True)
        with self.assertRaisesRegex(ValueError,'unexpected_financial_continuation'):
            await asyncio.to_thread(worker.close)
        path=self.resources.root/'pump-survivor-history.sqlite'
        with sqlite3.connect(path) as db:
            body=db.execute('SELECT body FROM candidates WHERE id=?',('offline-marker',)).fetchone()[0]
        self.assertEqual(json.loads(body)['position'],'unexpected-private-native-owner')
        self.assertFalse(self.physical.calls)
        self.assert_no_money()

    async def test_real_pump_qualification_and_denial_keep_owned_pipeline_publication(self):
        from meme_machine.lanes.pump import runner
        from meme_machine.lanes.pump.pipeline import Pipeline
        from meme_machine.lanes.pump.pump_acceleration_strategy import qualify,policy_hash
        from meme_machine.runtime.isolated_native_bootstrap import PumpCurrentContext
        from tests.lanes.pump.test_pump_acceleration_strategy import PumpAccelerationStrategyTests
        signal=PumpAccelerationStrategyTests().strong_late();decision=qualify(signal)
        configured={'MM_MODE':'PAPER','MM_DIRECTIONAL_COMPOSITE_REQUIRED':'1',
            'MM_SOLANA_CANDIDATE_HISTORY_DB':str(self.resources.root/'candidate-history.sqlite'),
            'MM_SOLANA_EVIDENCE_PLANE_DB':str(self.resources.root/'solana-evidence.sqlite'),
            'MM_SOLANA_EVIDENCE_BROKER_DB':str(self.resources.root/'solana-broker.sqlite')}
        with patch.dict('os.environ',configured,clear=True):
            context=PumpCurrentContext(self.resources,self.ports,
                report_path=self.resources.root/'pump-current'/'report.json')
        pipeline=Pipeline(context.report_path.with_suffix('.pipeline.sqlite'),'pump',policy_hash())
        self.addCleanup(pipeline.close);context.bind_pipeline(pipeline)
        report=dict(qualifiers=[],attempts=[],full_evidence_candidates=[])
        snapshot=dict(available_time=1000,market_time=1000,slot=11)
        with patch.object(runner,'ISOLATED_CURRENT_CONTEXT',context),patch.object(runner,'ACCOUNTING',None),\
                patch.object(runner,'PIPELINE',pipeline),patch.object(runner,'CANDIDATE_HISTORY',context.history),\
                patch.object(runner,'FILL_PERSISTENCE_CONTEXT',None),patch.object(runner.time,'time',return_value=1000),\
                patch.object(runner,'PumpAccelerationPaperLifecycle',side_effect=AssertionError('intent created')):
            row=runner._record_attempt(report,signal,decision,'full_point_in_time',
                snapshot=snapshot,native_resources=self.resources)
            self.assertFalse(runner._reserve_position(report,{}, {},signal,decision,snapshot,signal.phase,
                decision_id=row['decision_id'],native_resources=self.resources))
        self.assertTrue(report['funding_denials'][0]['qualification_preserved'])
        self.assertEqual(pipeline.db.execute("SELECT COUNT(*) FROM progress WHERE stage='qualified'").fetchone()[0],1)
        self.assertEqual(context.history.db.execute('SELECT status FROM funding').fetchall(),[('denied',)])
        self.assert_no_money()

    async def test_actual_pump_current_early_failure_releases_context_owner_and_restarts(self):
        from meme_machine.lanes.pump import runner
        configured={'MM_MODE':'PAPER','MM_DIRECTIONAL_COMPOSITE_REQUIRED':'1',
            'MM_SOLANA_CANDIDATE_HISTORY_DB':str(self.resources.root/'candidate-history.sqlite'),
            'MM_SOLANA_EVIDENCE_PLANE_DB':str(self.resources.root/'solana-evidence.sqlite'),
            'MM_SOLANA_EVIDENCE_BROKER_DB':str(self.resources.root/'solana-broker.sqlite')}
        report=self.resources.root/'pump-current'/'report.json'
        with patch.dict('os.environ',configured,clear=True),patch.object(runner,'REPORT',report):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'discovery_runtime_bound'):
                    await asyncio.to_thread(runner.main,discovery_seconds=1,
                        native_resources=self.resources,native_ports=self.ports)
                self.assertFalse(self.resources._candidate_histories)
                self.assertIsNone(runner.ISOLATED_CURRENT_CONTEXT)
        self.assertFalse(self.physical.calls)
        self.assert_no_money()

    async def test_actual_pump_current_main_owned_startup_and_cancellation_without_book(self):
        from meme_machine.solana_provider_config import GENESIS
        self.physical.body=json.dumps(dict(jsonrpc='2.0',id=1,result=GENESIS)).encode()
        from meme_machine.lanes.pump import runner
        from meme_machine.runtime import stop
        await self.pump_source()
        report=self.resources.root/'pump-current'/'report.json'
        configured={'MM_MODE':'PAPER','MM_DIRECTIONAL_COMPOSITE_REQUIRED':'1',
            'MM_SOLANA_CANDIDATE_HISTORY_DB':str(self.resources.root/'candidate-history.sqlite'),
            'MM_SOLANA_EVIDENCE_PLANE_DB':str(self.resources.root/'solana-evidence.sqlite'),
            'MM_SOLANA_EVIDENCE_BROKER_DB':str(self.resources.root/'solana-broker.sqlite')}
        prior=stop.requested.is_set()
        stop.requested.clear()
        restore=runner._restore_observed_pump_candidates
        completed=[]
        def cancel_after_actual_restore(*args,**kwargs):
            result=restore(*args,**kwargs)
            completed.append(result)
            stop.requested.set()
            return result
        try:
            with patch.dict('os.environ',configured,clear=True), patch.object(runner,'REPORT',report), \
                    patch('meme_machine.lanes.pump.paper_accounting.PaperBook',
                        side_effect=AssertionError('financial constructor reached')), \
                    patch.object(runner,'_restore_observed_pump_candidates',side_effect=cancel_after_actual_restore):
                inodes=[]
                for _ in range(2):
                    stop.requested.clear()
                    with self.assertRaises(stop.Shutdown):
                        await asyncio.wait_for(asyncio.to_thread(runner.main,discovery_seconds=600,
                            native_resources=self.resources,native_ports=self.ports),10)
                    inodes.append(report.with_suffix('.pipeline.sqlite').stat().st_ino)
                    self.assertFalse(self.resources._candidate_histories)
                self.assertEqual(inodes[0],inodes[1])
        finally:
            if prior:stop.requested.set()
            else:stop.requested.clear()
            from meme_machine.lanes.pump import durable_publication
            publisher=durable_publication._publishers.pop(str(report.resolve()),None)
            if publisher is not None:
                self.assertTrue(await asyncio.to_thread(publisher.close,2))
        value=json.loads(report.read_text())
        self.assertEqual(value['accounting']['status'],'UNEXERCISED')
        self.assertEqual(value['accounting_replay']['status'],'UNEXERCISED')
        self.assertFalse(value['financial_authority'])
        self.assertEqual(completed,[0,0])
        self.assertEqual(value['restored_observed_candidates'],0)
        self.assertIn('ended',value)
        self.assertIsNone(runner.ACCOUNTING)
        self.assertIsNone(runner.PIPELINE)
        self.assertIsNone(runner.CANDIDATE_HISTORY)
        self.assertIsNone(runner.ISOLATED_CURRENT_CONTEXT)
        self.assertEqual([row['method'] for row in self.physical.calls],['getGenesisHash'])
        self.assert_no_money()


if __name__=='__main__':
    unittest.main()
