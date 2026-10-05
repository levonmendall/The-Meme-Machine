"""Offline regressions for the three CAPACITY runtime defects."""
import json
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch,MagicMock

from meme_machine.operational.supervisor import Supervisor
from meme_machine.runtime.cu import DEFAULT,estimate
from meme_machine.runtime.survivor_history import Worker


class CapacityRepairs(unittest.TestCase):
    def test_packaged_historical_cu_schedule_and_telemetry(self):
        self.assertTrue(DEFAULT.is_file())
        spec=json.loads(DEFAULT.read_bytes())
        self.assertEqual(spec['retrieved_at'],'2026-09-20')
        methods={'eth_call':2,'eth_getLogs':1,'eth_blockNumber':1,
                 'getAccountInfo':1,'getMultipleAccounts':1,'getTransaction':1}
        result=estimate(methods)
        self.assertEqual(result['unpriced_methods'],{})
        self.assertEqual(result['estimated_cu'],sum(spec['methods'][m]*n for m,n in methods.items()))
        self.assertIsNone(estimate({'unknown_method':1})['estimated_cu'])
        self.assertEqual(hashlib.sha256(DEFAULT.read_bytes()).hexdigest(),
            '0fc313816f46dd8783fcda04db92a467d28fa5514b936ccf9c09502ef6d4edf9')
        from meme_machine.runtime.evidence_worker import RepairRPC
        rpc=RepairRPC('https://solana-mainnet.g.alchemy.com/v2/offline-fixture',None)
        rpc._count('method:getGenesisHash')
        rpc._count('method:getTransactionsForAddress')
        telemetry=rpc.telemetry()['estimated_alchemy']
        self.assertEqual(telemetry['known_estimated_cu'],10)
        self.assertEqual(telemetry['unpriced_methods'],{'getTransactionsForAddress':1})
        self.assertIsNone(telemetry['estimated_cu'])

    def test_lane_environments_inspect_names_only(self):
        parent={k:'fixture' for k in ('MM_SOLANA_READ_RPC_URL','MM_SOLANA_PUBLIC_RPC_URL',
            'MM_SOLANA_EVIDENCE_BROKER_DB','MM_ONFINALITY_SOLANA_WS_URL',
            'MM_ROBINHOOD_READ_RPC_URL','MM_ROBINHOOD_SEQUENCER_FEED_URL',
            'MM_ROBINHOOD_STATE_DIR','MM_PROVIDER_DB','MM_RPC_CACHE_DB','MM_PROVIDER_GOVERNOR_DB')}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,parent,clear=True):
            supervisor=Supervisor(td);supervisor.epoch='preserved-fixture'
            for lane in ('pump','meteora','solana','pons','ramses'):
                with self.subTest(lane=lane):
                    names=set(supervisor.environment(lane))
                    self.assertTrue({'MM_MODE','MM_PAPER_EPOCH','MM_STATE_ROOT','MM_PORTFOLIO_ACCOUNTING_DB','PYTHONPATH'}<=names)
                    if lane in ('pump','meteora','solana'):
                        self.assertFalse(any(n.startswith('MM_ROBINHOOD_') for n in names))
                        self.assertFalse({'MM_PROVIDER_DB','MM_RPC_CACHE_DB'}&names)
                        self.assertTrue({'MM_SOLANA_READ_RPC_URL','MM_PROVIDER_GOVERNOR_DB','MM_SOLANA_EVIDENCE_PLANE_DB'}<=names)
                    else:
                        self.assertFalse(any(n.startswith(('MM_SOLANA_','MM_ONFINALITY_SOLANA_')) for n in names))
                        self.assertNotIn('MM_PROVIDER_GOVERNOR_DB',names)
                        self.assertTrue({'MM_ROBINHOOD_READ_RPC_URL','MM_ROBINHOOD_SEQUENCER_FEED_URL','MM_PROVIDER_DB','MM_RPC_CACHE_DB','MM_ROBINHOOD_STATE_DIR'}<=names)
                    if lane!='solana':self.assertIn('MM_DIRECTIONAL_SLEEVE_DB',names)

    def test_child_environments_reject_parent_credentials_and_state_overrides(self):
        poison={name:'untrusted-parent' for name in (
            'AWS_SECRET_ACCESS_KEY','ALCHEMY_TOKEN','SECRET_VENDOR_PASSWORD',
            'WALLET_PRIVATE_KEY','MM_LIVE_TRADING','MM_RPC_CAPABILITIES',
            'MM_BROKER_DB','MM_SOLANA_EVIDENCE_BROKER_DB',
            'MM_ROBINHOOD_PONS_PAPER_DB','MM_ROBINHOOD_RAMSES_COSTS_BY_POOL_JSON',
            'MM_PORTFOLIO_INCEPTION_RECEIPT','MM_ALLOCATION_ENABLED',
            'PYTHONPATH','MM_STATE_ROOT','MM_DIRECTIONAL_SLEEVE_DB')}
        transport={'HTTPS_PROXY':'http://offline-proxy:8080',
                   'SSL_CERT_FILE':'/offline/ca.pem','PATH':'/offline/bin'}
        providers={'MM_SOLANA_READ_RPC_URL':'solana-fixture',
                   'MM_ROBINHOOD_READ_RPC_URL':'robinhood-fixture'}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,
                dict(poison,**transport,**providers),clear=True):
            for offline in (False,True):
                supervisor=Supervisor(td,offline=offline);supervisor.epoch='preserved'
                for lane in ('pump','meteora','solana','pons','ramses'):
                    with self.subTest(lane=lane,offline=offline):
                        env=supervisor.environment(lane)
                        for name,value in poison.items():self.assertNotEqual(env.get(name),value)
                        for name,value in transport.items():self.assertEqual(env[name],value)
                        self.assertEqual(env['MM_STATE_ROOT'],str(Path(td).resolve()))
                        self.assertEqual(env['MM_PAPER_EPOCH'],'preserved')
                        self.assertEqual(env['MM_MODE'],'PAPER')
                        expected='MM_SOLANA_READ_RPC_URL' if lane in ('pump','meteora','solana') else 'MM_ROBINHOOD_READ_RPC_URL'
                        if offline:self.assertFalse(set(providers)&set(env))
                        else:self.assertEqual(env[expected],providers[expected])

    def survivor_lifecycle(self,lane):
        if lane=='pump':
            from meme_machine.lanes.pump import pumpswap_survivor_runtime as module
        else:
            from meme_machine.lanes.pons import pons_survivor_runtime as module
        owner=[];caller=threading.get_ident()
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{},clear=True):
            root=Path(td)
            with patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/'sleeve.sqlite'),
                    'MM_DIRECTIONAL_COHORT_ID':'offline-fixture'}),\
                 patch.object(module.Runtime,'discover',autospec=True),\
                 patch.object(module.Runtime,'_provider',autospec=True),\
                 patch.object(module,'RuntimeEvidence',create=True,return_value=MagicMock()):
                def factory():
                    owner.append(threading.get_ident())
                    args=(root/'survivor',10**9,'offline-fixture',1 if lane=='pump' else 'offline-endpoint')
                    return module.Runtime(*args)
                worker=Worker(factory)
                try:
                    self.assertIsNone(worker.prime(timeout=10)['last_boundary'])
                    self.assertNotEqual(owner,[caller])
                    for n in range(1,4):
                        worker.tick(n*6,admit=True)
                        worker.future.result(timeout=10)
                    status=worker.close()
                    self.assertEqual(status['machinery']['completed_steps'],4)
                    self.assertEqual(status['machinery']['successful_steps'],4)
                except BaseException:
                    worker.close();raise
                self.assertEqual(len(owner),1)
                self.assertTrue((root/'survivor/history.sqlite').is_file())

    def test_pump_survivor_prime_ticks_close(self):self.survivor_lifecycle('pump')
    def test_pons_survivor_prime_ticks_close(self):self.survivor_lifecycle('pons')

    def test_prime_wait_is_bounded_and_close_stays_on_executor(self):
        from concurrent.futures import TimeoutError
        entered=threading.Event();release=threading.Event();owners=[]
        class Service:
            def __init__(self):owners.append(threading.get_ident())
            def step(self,*,admit):entered.set();release.wait(10);return {}
            def close(self):owners.append(threading.get_ident())
        worker=Worker(Service)
        try:
            with self.assertRaises(TimeoutError):worker.prime(timeout=.05)
            self.assertTrue(entered.wait(1))
        finally:release.set();worker.close()
        self.assertEqual(owners[0],owners[1])


class ValuationRPCBounds(unittest.TestCase):
    def construct(self,lane):
        from meme_machine.runtime.usd_valuation import _rpc
        from meme_machine.lanes.pons import provider_topology as pons
        from meme_machine.lanes.ramses import provider_topology as ramses
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{
                'MM_ROBINHOOD_READ_RPC_URL':'https://robinhood-mainnet.g.alchemy.com/v2/offline-fixture',
                'MM_ROBINHOOD_STATE_DIR':td},clear=True),\
                patch('urllib.request.urlopen',side_effect=AssertionError('provider I/O forbidden')) as http,\
                patch('socket.socket.connect',side_effect=AssertionError('provider I/O forbidden')) as connect:
            rpc=_rpc(lane)
            self.assertEqual((rpc.limit,rpc.per_scope,rpc.retries),(200,200,0))
            if lane=='pons':
                self.assertIs(rpc.pacer,pons._DIRECTIONAL_PACER)
                self.assertEqual(rpc.pacer.requests_per_second,2.0)
                self.assertEqual(rpc.role,'directional_evidence_primary')
            else:
                self.assertIs(rpc.pacer,ramses._SHARED_PRIMARY_DLMM_PACER)
                self.assertEqual(rpc.pacer.requests_per_second,1.0)
                self.assertEqual(rpc.role,'dlmm_reconstruction_primary_shared_observation')
                self.assertTrue(rpc.primary_shared)
                self.assertFalse(rpc.primary_fallback)
            self.assertEqual(rpc.used,0)
            http.assert_not_called();connect.assert_not_called()

    def test_pons_valuation_constructor_bounds_and_pacing(self):self.construct('pons')
    def test_ramses_valuation_constructor_bounds_and_pacing(self):self.construct('ramses')

class EvidenceWorkerDiagnosticTests(unittest.TestCase):
    def test_maintenance_failure_keeps_only_fixed_numeric_fields(self):
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        error=EvidenceUnavailable('maintenance_service_deadline_exhausted')
        error.maintenance_failure=dict(side='archive',units=23,records=17,
            deadline_seconds=-4.5,pins=1,gaps=0,vm_steps=19000,
            provider='https://provider.invalid/v2/private-secret',
            recovery_seconds=float('inf'),safety_seconds='private-secret')
        result=failure_diagnostic(error)
        self.assertIn('"deadline_seconds": -4.5',result)
        self.assertIn('"records": 17',result)
        self.assertIn('"side": "archive"',result)
        self.assertNotIn('provider',result)
        self.assertNotIn('private-secret',result)
        self.assertNotIn('Infinity',result)

    def test_fixed_reason_visible_and_arbitrary_credentials_redacted(self):
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        self.assertEqual(failure_diagnostic(EvidenceUnavailable('authoritative_subscription_rejected')),
            'evidence_worker_failed:EvidenceUnavailable:authoritative_subscription_rejected')
        secret='https://provider.invalid/v2/private-secret'
        self.assertEqual(failure_diagnostic(RuntimeError(secret)),'evidence_worker_failed:RuntimeError')
        self.assertEqual(failure_diagnostic(EvidenceUnavailable(secret)),'evidence_worker_failed:EvidenceUnavailable')

    def test_native_writer_failure_keeps_safe_causal_reason(self):
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        from meme_machine.solana_evidence_plane import EvidenceUnavailable,IngestionService
        service=object.__new__(IngestionService)
        service.failed=EvidenceUnavailable('maintenance_observation_python_bound')
        try:service.check()
        except EvidenceUnavailable as error:
            self.assertEqual(failure_diagnostic(error),
                'evidence_worker_failed:EvidenceUnavailable:writer_failed:caused_by:'
                'EvidenceUnavailable:maintenance_observation_python_bound')
        else:self.fail('failed writer did not stop')

    def test_cause_messages_are_redacted_and_cycles_depth_are_bounded(self):
        from meme_machine.runtime.evidence_worker import failure_diagnostic
        from meme_machine.solana_evidence_plane import EvidenceUnavailable
        secret='https://provider.invalid/v2/private-secret'
        error=EvidenceUnavailable('writer_failed');error.__cause__=RuntimeError(secret)
        self.assertEqual(failure_diagnostic(error),
            'evidence_worker_failed:EvidenceUnavailable:writer_failed:caused_by:RuntimeError')
        error.__cause__=error
        self.assertEqual(failure_diagnostic(error),'evidence_worker_failed:EvidenceUnavailable:writer_failed')
        top=error=EvidenceUnavailable('writer_failed')
        for _ in range(10):
            child=EvidenceUnavailable('maintenance_observation_python_bound')
            error.__cause__=child;error=child
        result=failure_diagnostic(top)
        self.assertEqual(result.count(':caused_by:'),3)
        self.assertNotIn(secret,result)
