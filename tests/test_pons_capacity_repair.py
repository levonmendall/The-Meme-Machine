"""Native exact-exit consolidation and inactive, account-wide capacity profiles."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_admission import Admission,OfflineProfile,native_lifecycle_work
from tests import test_pons_protective_capacity as capacity

BASE='ed7b3c6616c59bfce21e96097d175ed3212214c2'


class ExitCapacityRepairTests(unittest.TestCase):
    def fixture(self):
        f=capacity.ProtectiveCapacityTests();self.addCleanup(f.doCleanups);return f

    def test_exact_native_partial_batch_one_two_four_eight_twelve_twenty(self):
        for n in (1,2,4,8,12,20):
            with self.subTest(positions=n):
                f=self.fixture()
                old,ro,a,_=capacity.replay(f,n,price_factor=2.2,predecessor=BASE,paced=False,latency=0)
                new,rn,b,_=capacity.replay(f,n,price_factor=2.2,paced=False,latency=0)
                self.assertEqual(old,new);self.assertEqual(ro,rn)
                self.assertEqual(len(b.transports),6)
                self.assertTrue(all(r['realization_taken'] for r in rn))
                calls=[p for _,rows in b.transports for m,p in rows if m=='eth_call']
                self.assertEqual(len(calls),1+2*n)
                self.assertGreaterEqual(len(a.transports),len(b.transports))

    def test_two_three_four_rps_measure_last_response_and_native_commits(self):
        for rate in (2,3,4):
            for n in (1,2,4,8,12,20):
                for factor in (1.,.6,2.2):
                    with self.subTest(rate=rate,positions=n,factor=factor):
                        f=self.fixture();p,r,rpc,result=capacity.replay(f,n,price_factor=factor,rps=rate)
                        self.assertTrue(result['accounting']['reconciled'])
                        self.assertEqual(len(rpc.starts),6 if factor==2.2 else 4)
                        self.assertTrue(all(b-a>=1/rate-1e-8 for a,b in zip(rpc.starts,rpc.starts[1:])))
                        duration=rpc.clock-100+rpc.local_wall_seconds
                        if rate>=3:self.assertLess(duration,3)
                        print('NATIVE_RATE_ENVELOPE',json.dumps(dict(rps=rate,positions=n,
                            action=r[0]['last_action']['action'],starts=rpc.starts,responses=rpc.responses,
                            native_wall_seconds=rpc.local_wall_seconds,native_cpu_seconds=rpc.local_cpu_seconds,
                            modeled_completion_with_local_seconds=duration,within_three_seconds=duration<3)),flush=True)

    def test_partial_exit_batch_does_not_infer_sender_or_reuse_a_changed_fork(self):
        for fault in ('sender','execution_fork','partial_execution'):
            def inject(runtime,rpc):
                original=rpc.value
                def value(method,params):
                    result=original(method,params)
                    if fault=='sender' and method=='eth_getTransactionReceipt':result.pop('from')
                    if fault=='execution_fork' and len(rpc.transports)>=5 and method=='eth_getBlockByNumber' and params[0]!='latest':
                        result['hash']='fork'
                    return result
                rpc.value=value
                if fault=='partial_execution':
                    batch=rpc.batch
                    def partial(calls,**kw):
                        result=batch(calls,**kw)
                        return result[:-1] if len(rpc.transports)==5 else result
                    rpc.batch=partial
            f=self.fixture()
            p,r,rpc,result=capacity.replay(f,2,price_factor=2.2,rps=4,before_step=inject)
            self.assertTrue(result['accounting']['reconciled'])
            if fault=='sender':
                self.assertEqual(rpc.methods['eth_getTransactionByHash'],1)
                self.assertTrue(all(x['realization_taken'] for x in r))
            elif fault=='execution_fork':self.assertTrue(all(not x['realization_taken'] for x in r))
            else:self.assertTrue(all(x['realization_taken'] for x in r))

    def test_another_native_rpc_session_invalidates_the_same_endpoint_execution_proof(self):
        from meme_machine.lanes.pons.pons_quotes import canonical_boundary,unchanged_canonical_read
        with tempfile.TemporaryDirectory() as td:
            one=capacity.ActiveRPC(proved=True,admission_path=str(Path(td)/'provider'))
            two=capacity.ActiveRPC(proved=True,admission_path=str(Path(td)/'provider'))
            self.addCleanup(one.close);self.addCleanup(two.close)
            one.verify_chain();two.verify_chain()
            header=one.value('eth_getBlockByNumber',['latest',False])
            with patch('time.monotonic',side_effect=lambda:one.clock):
                canonical_boundary(one,header,'pons_survivor');proof=one.last_canonical_read
                self.assertTrue(unchanged_canonical_read(one,proof,header))
                own_sequence=one.used
                two.call('eth_gasPrice',[],scope='pons_paper')
                self.assertEqual(one.used,own_sequence)
                self.assertFalse(unchanged_canonical_read(one,proof,header))

    def test_source_change_during_an_exact_exit_batch_refuses_the_old_generation(self):
        from meme_machine.runtime.source_artifacts import REGISTRY
        def changed(runtime,rpc):
            batch=rpc.batch
            def update(calls,**kwargs):
                result=batch(calls,**kwargs)
                if len(rpc.transports)==5:REGISTRY.invalidate()
                return result
            rpc.batch=update
        f=self.fixture();p,r,rpc,result=capacity.replay(f,2,price_factor=2.2,rps=4,before_step=changed)
        self.assertTrue(result['accounting']['reconciled'])
        self.assertIn('source_changed',f.native_runtime.shared_exit_boundary)
        self.assertFalse(f.native_runtime.shared_held_executions)
        self.assertTrue(all(x['realization_taken'] for x in r))

    def test_real_clock_native_partial_exits_include_cpu_queue_wait_and_final_commits(self):
        import time
        from tests import test_pons_shared_native_acquisition as shared
        class RealRPC(capacity.ActiveRPC):
            def __init__(self,**kwargs):
                self.origin=time.perf_counter();super().__init__(**kwargs);self.real_latency=True
            @property
            def clock(self):return 100+time.perf_counter()-self.origin
            @clock.setter
            def clock(self,value):pass
            def sleep(self,seconds):time.sleep(seconds)
        for rate in (2,3):
            for n in (1,2,20):
                f=self.fixture()
                def rpc(**kwargs):
                    r=RealRPC(**kwargs,count=n,price_factor=2.2,rps=rate)
                    f.addCleanup(r.close);return r
                with patch.object(shared,'TraceRPC',side_effect=rpc):
                    p,r,transport,result=f.run_positions(n,proved=True,moving_clock=True,
                        before_step=lambda runtime,rpc:setattr(rpc,'origin',time.perf_counter()))
                self.assertTrue(result['accounting']['reconciled'])
                self.assertTrue(all(x['realization_taken'] for x in r))
                if rate==3:self.assertLess(transport.native_completed_at-100,3)
                print('REAL_CLOCK_SURVIVOR_PARTIAL',json.dumps(dict(positions=n,rps=rate,
                    physical_starts=len(transport.starts),starts=transport.starts,responses=transport.responses,
                    queue_wait_seconds=sum(transport.waits),complete_native_seconds=transport.native_completed_at-100,
                    within_three_seconds=transport.native_completed_at<103,native_accounting_verified=True)),flush=True)


class OfflineGovernorTests(unittest.TestCase):
    def open(self,root,profile,endpoint='https://offline.example/rpc',lane='pons'):
        return Admission(Path(root)/'governor.sqlite',endpoint,lane=lane,offline_profile=profile,
            clock=lambda:self.clock,sleeper=lambda s:setattr(self,'clock',self.clock+s))

    def test_no_production_activation_or_higher_unprofiled_rate(self):
        self.clock=100
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(BoundaryError,'ceiling_invalid'):
                Admission(Path(td)/'db','https://offline.example',lane='pons',interval=.25)
            import socket
            with patch.object(socket.socket,'connect',lambda *a:None):
                with self.assertRaisesRegex(BoundaryError,'offline_network_guard'):
                    self.open(td,OfflineProfile(4))
            default=Admission(Path(td)/'default','https://offline.example',lane='pons')
            self.assertIsNone(default.offline_profile);self.assertEqual(default.interval,.5)

    def test_actual_native_rpc_role_pacer_and_shared_admission_use_only_the_explicit_offline_profile(self):
        from meme_machine.lanes.pons.provider import Rpc
        from meme_machine.lanes.pons.provider_topology import PacedRpc
        from tests.lanes.pons import test_pons_finalization as native
        from meme_machine.runtime.robinhood.provider_usage import http_started,http_received
        self.clock=100
        with tempfile.TemporaryDirectory() as td:
            governor=self.open(td,OfflineProfile(4),native.ENDPOINT)
            with patch.dict('os.environ',{'MM_PROVIDER_RUNTIME_ROOT':td},clear=True):
                rpc=PacedRpc(native.ENDPOINT,role='directional_evidence_primary',requests_per_second=2,
                    offline_admission=governor,limit=20,per_scope=20,retries=0)
                starts=[]
                def physical(_rpc,*args):
                    starts.append(self.clock);http_started(1);http_received(1);return '0x1'
                with patch.object(Rpc,'_http',physical):
                    rpc.chain_verified=True
                    for i in range(4):rpc.call('eth_gasPrice',[],scope='exit')
                self.assertEqual(starts,[100,100.25,100.5,100.75])
                self.assertEqual(rpc.pacer.maximum_requests_per_second,4)
                self.assertEqual(governor.activity_marker(),(4,4))

    def test_account_wide_pump_pons_starts_weights_and_charged_failure_budget(self):
        self.clock=100;profile=OfflineProfile(4)
        with tempfile.TemporaryDirectory() as td:
            pons=self.open(td,profile);pump=self.open(td,profile,'https://offline.solana/rpc','pump')
            starts=[]
            for governor,methods in ((pons,['eth_call']*20),(pump,['getMultipleAccounts']),
                    (pons,['eth_getBlockReceipts']),(pump,['getTransaction'])):
                with native_lifecycle_work(held=True):
                    grant=governor.acquire('protection',deadline=103,methods=methods)
                starts.append(grant['admitted_at']);governor.complete(grant['resource_reservation'])
            for actual,expected in zip(starts,[100,100.25,100.5,100.75]):self.assertAlmostEqual(actual,expected,places=10)
            with self.assertRaisesRegex(BoundaryError,'method_weight_unknown'):
                pons.acquire('candidate',methods=['unknownMethod'])
            with pons.connect() as db:
                state=json.loads(db.execute('SELECT state FROM offline_resource_accounts').fetchone()[0])
            self.assertEqual(state['starts'],4);self.assertGreater(state['spent_microdollars'],0)
            before=state['spent_microdollars']
            def failed():raise BoundaryError('provider_http_429')
            with self.assertRaisesRegex(BoundaryError,'provider_http_429'):
                pons.invoke(failed,['eth_call'],'exit')
            with pons.connect() as db:
                after=json.loads(db.execute('SELECT state FROM offline_resource_accounts').fetchone()[0])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM offline_inflight').fetchone()[0],0)
            self.assertGreater(after['spent_microdollars'],before)

    def test_protection_payload_reservation_spending_and_failed_inflight_cleanup(self):
        self.clock=100;profile=OfflineProfile(4,max_modeled_microdollars=32)
        with tempfile.TemporaryDirectory() as td:
            governor=self.open(td,profile)
            with native_lifecycle_work(held=False):candidate=governor.acquire('entry',methods=['eth_call'])
            with native_lifecycle_work(held=True):held=governor.acquire('exit',methods=['eth_call'],deadline=103)
            self.assertAlmostEqual(held['admitted_at'],100.25,places=10)
            with governor.connect() as db:self.assertEqual(db.execute('SELECT SUM(bytes) FROM offline_inflight').fetchone()[0],4_000_000)
            governor.complete(candidate['resource_reservation']);governor.complete(held['resource_reservation'])
            with self.assertRaisesRegex(BoundaryError,'modeled_spending_ceiling'):
                governor.acquire('entry',methods=['eth_call'])
