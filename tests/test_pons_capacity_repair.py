"""Native exact-exit consolidation and inactive, account-wide capacity profiles."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.provider_admission import Admission,OfflineProfile,native_lifecycle_work
from tests import test_pons_protective_capacity as capacity

BASE='ed7b3c6616c59bfce21e96097d175ed3212214c2'


class GovernorConnectionTests(unittest.TestCase):
    def governor(self,path):
        governor=Admission.__new__(Admission);governor.path=path
        return governor

    def test_new_shared_ledger_busy_mode_change_retries_and_keeps_full_durability(self):
        original=sqlite3.connect;busy=threading.Event();opened=[];closed=[];result={}
        class Tracked(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                try:return super().execute(sql,*args,**kwargs)
                except sqlite3.OperationalError as error:
                    if error.sqlite_errorcode==sqlite3.SQLITE_BUSY:busy.set()
                    raise
            def close(self):closed.append(self);return super().close()
        def connect(*args,**kwargs):
            kwargs.update(timeout=0,factory=Tracked)
            db=original(*args,**kwargs);opened.append(db);return db
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'shared.sqlite';writer=original(path,isolation_level=None)
            self.addCleanup(writer.close)
            writer.execute('CREATE TABLE retained(value TEXT)')
            writer.execute("INSERT INTO retained VALUES('unchanged')")
            writer.execute('BEGIN IMMEDIATE')
            def reopen():
                try:
                    db=self.governor(path).connect()
                    try:
                        result.update(mode=db.execute('PRAGMA journal_mode').fetchone()[0],
                            synchronous=db.execute('PRAGMA synchronous').fetchone()[0],
                            value=db.execute('SELECT value FROM retained').fetchone()[0])
                    finally:db.close()
                except BaseException as error:result['error']=error
            with patch('sqlite3.connect',side_effect=connect):
                worker=threading.Thread(target=reopen);worker.start()
                try:self.assertTrue(busy.wait(2),'real WAL-mode contention was not reproduced')
                finally:writer.execute('ROLLBACK')
                worker.join(2);self.assertFalse(worker.is_alive())
            self.assertNotIn('error',result)
            self.assertEqual(result,dict(mode='wal',synchronous=2,value='unchanged'))
            self.assertEqual(closed,opened)

    def test_existing_wal_connection_never_reissues_journal_mode_write(self):
        original=sqlite3.connect;statements=[]
        class Tracked(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                statements.append(sql);return super().execute(sql,*args,**kwargs)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'shared.sqlite';first=self.governor(path).connect();first.close()
            with patch('sqlite3.connect',side_effect=lambda *a,**kw:original(*a,**kw,factory=Tracked)):
                db=self.governor(path).connect()
                try:self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0],2)
                finally:db.close()
            self.assertNotIn('PRAGMA journal_mode=WAL',statements)

    def test_persistent_busy_is_bounded_propagated_and_failed_connection_closed(self):
        original=sqlite3.connect;opened=[];closed=[];busy=[]
        class Tracked(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                if sql.startswith('PRAGMA busy_timeout='):sql='PRAGMA busy_timeout=0'
                try:return super().execute(sql,*args,**kwargs)
                except sqlite3.OperationalError as error:
                    if error.sqlite_errorcode==sqlite3.SQLITE_BUSY:busy.append(sql)
                    raise
            def close(self):closed.append(self);return super().close()
        def connect(*args,**kwargs):
            kwargs.update(timeout=0,factory=Tracked)
            db=original(*args,**kwargs);opened.append(db);return db
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'shared.sqlite';writer=original(path,isolation_level=None)
            try:
                writer.execute('CREATE TABLE retained(value TEXT)');writer.execute('BEGIN IMMEDIATE')
                with patch('sqlite3.connect',side_effect=connect):
                    with self.assertRaises(sqlite3.OperationalError) as raised:self.governor(path).connect()
                self.assertEqual(raised.exception.sqlite_errorcode,sqlite3.SQLITE_BUSY)
                self.assertEqual(len(busy),10);self.assertEqual(closed,opened)
            finally:writer.close()

    def test_setup_retries_cannot_extend_the_existing_total_busy_wait(self):
        original=sqlite3.connect;closed=[];attempts=[]
        class Tracked(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                attempts.append(sql)
                error=sqlite3.OperationalError('original-timeout');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
                raise error
            def close(self):closed.append(self);return super().close()
        with tempfile.TemporaryDirectory() as td:
            with patch('sqlite3.connect',side_effect=lambda *a,**kw:original(*a,**kw,factory=Tracked)),\
                    patch('time.perf_counter',side_effect=[0,10]),patch('time.sleep') as sleep:
                with self.assertRaisesRegex(sqlite3.OperationalError,'original-timeout'):
                    self.governor(Path(td)/'shared.sqlite').connect()
            self.assertEqual(len(attempts),1);self.assertEqual(len(closed),1);sleep.assert_not_called()

    def test_nonbusy_setup_failure_is_not_retried_and_connection_closed(self):
        original=sqlite3.connect;opened=[];closed=[];attempts=[]
        class Tracked(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                attempts.append(sql)
                error=sqlite3.OperationalError('original-io-failure');error.sqlite_errorcode=sqlite3.SQLITE_IOERR
                raise error
            def close(self):closed.append(self);return super().close()
        def connect(*args,**kwargs):
            db=original(*args,**kwargs,factory=Tracked);opened.append(db);return db
        with tempfile.TemporaryDirectory() as td,patch('sqlite3.connect',side_effect=connect):
            with self.assertRaisesRegex(sqlite3.OperationalError,'original-io-failure'):
                self.governor(Path(td)/'shared.sqlite').connect()
            self.assertEqual(len(attempts),1);self.assertEqual(closed,opened)


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


class ProtectivePhaseTests(unittest.TestCase):
    def open(self,root,*,seconds=3,lane='pons',endpoint='https://offline.example/rpc'):
        return Admission(Path(root)/'governor.sqlite',endpoint,lane=lane,
            offline_profile=OfflineProfile(8,protective_cohort_seconds=seconds),
            clock=lambda:self.clock,sleeper=lambda s:setattr(self,'clock',self.clock+s))

    def test_phase_requires_explicit_offline_profile_and_protection_context(self):
        self.clock=100
        with tempfile.TemporaryDirectory() as td:
            default=Admission(Path(td)/'default','https://offline.example',lane='pons')
            with default.protective_cohort():self.assertEqual(default.interval,.5)
            disabled=self.open(td,seconds=0)
            with disabled.protective_cohort():
                with disabled.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM offline_protective_phases').fetchone()[0],0)
            with tempfile.TemporaryDirectory() as second:
                enabled=self.open(second)
                with self.assertRaisesRegex(BoundaryError,'requires_protection'):
                    with enabled.protective_cohort():self.fail('candidate obtained a protective phase')
            for seconds in (-1,3.001,float('inf'),float('nan')):
                with self.assertRaises(BoundaryError):OfflineProfile(8,protective_cohort_seconds=seconds).validate()

    def test_phase_has_no_purchase_and_exception_releases_it(self):
        self.clock=100
        with tempfile.TemporaryDirectory() as td:
            one=self.open(td)
            with native_lifecycle_work(held=True):
                with self.assertRaisesRegex(RuntimeError,'native-error'):
                    with one.protective_cohort():
                        with one.connect() as db:
                            state=json.loads(db.execute('SELECT state FROM offline_resource_accounts').fetchone()[0])
                        self.assertEqual(state['starts'],0);self.assertEqual(state['spent_microdollars'],0)
                        raise RuntimeError('native-error')
            with one.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM offline_protective_phases').fetchone()[0],0)

    def test_existing_inflight_response_does_not_delay_phase_or_gain_new_capacity(self):
        self.clock=100
        with tempfile.TemporaryDirectory() as td:
            one=self.open(td);peer=self.open(td)
            with native_lifecycle_work(held=True):grant=peer.acquire('exit',methods=['eth_call'])
            with native_lifecycle_work(held=True),one.protective_cohort():
                self.assertEqual(self.clock,100)
                with one.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM offline_inflight').fetchone()[0],1)
                    self.assertEqual(json.loads(db.execute('SELECT state FROM offline_resource_accounts').fetchone()[0])['starts'],1)
                peer.complete(grant['resource_reservation'])

    def test_account_wide_peer_waits_but_earlier_protection_deadline_precedes_phase(self):
        self.clock=100
        with tempfile.TemporaryDirectory() as td:
            one=self.open(td);peer=self.open(td,lane='pump',endpoint='https://offline.solana/rpc')
            with native_lifecycle_work(held=True),one.protective_cohort():
                own=one.acquire('exit',methods=['eth_call']);one.complete(own['resource_reservation'])
                urgent=peer.acquire('exit',methods=['getMultipleAccounts'],deadline=101)
                self.assertLess(urgent['admitted_at'],101);peer.complete(urgent['resource_reservation'])
                equal=peer.acquire('exit',methods=['getMultipleAccounts'],deadline=103)
                self.assertLess(equal['admitted_at'],103);peer.complete(equal['resource_reservation'])
                deferred=peer.acquire('exit',methods=['getMultipleAccounts'],deadline=104)
                self.assertGreaterEqual(deferred['admitted_at'],103);peer.complete(deferred['resource_reservation'])
                with one.connect() as db:
                    self.assertEqual(db.execute('SELECT until FROM offline_protective_phases').fetchone()[0],103)
                    state=json.loads(db.execute('SELECT state FROM offline_resource_accounts').fetchone()[0])
                self.assertEqual(state['starts'],4)
                self.assertEqual(state['spent_microdollars'],sum(OfflineProfile(8).cost([m])['microdollars']
                    for m in ('eth_call','getMultipleAccounts','getMultipleAccounts','getMultipleAccounts')))

    def test_earlier_queued_protection_is_not_displaced_when_claiming(self):
        self.clock=100
        with tempfile.TemporaryDirectory() as td:
            one=self.open(td);peer=self.open(td);ticket=peer.session+':existing'
            with peer.connect() as db:
                db.execute('INSERT INTO queue VALUES(?,?,?,?,?)',(ticket,peer.endpoint,0,100,101))
                db.execute('INSERT INTO queue_meta VALUES(?,?)',(ticket,'pons'))
            with native_lifecycle_work(held=True),one.protective_cohort():
                self.assertEqual(self.clock,100)
                with one.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM offline_protective_phases').fetchone()[0],0)
                    self.assertEqual(db.execute('SELECT id FROM queue').fetchone()[0],ticket)

    def test_phase_expiry_after_interruption_never_renews_or_grants_a_purchase(self):
        self.clock=100
        with tempfile.TemporaryDirectory() as td:
            one=self.open(td);peer=self.open(td)
            with native_lifecycle_work(held=True):grant=peer.acquire('exit',methods=['eth_call'])
            # Simulate process interruption after claiming. Another native
            # session must regain ordinary admission at the original expiry.
            with one.connect() as db:
                db.execute('INSERT INTO offline_protective_phases VALUES(?,?,?)',('offline-shared-account',one.session,103))
            peer.complete(grant['resource_reservation'])
            with native_lifecycle_work(held=True):new=peer.acquire('exit',methods=['eth_call'],deadline=104)
            self.assertGreaterEqual(new['admitted_at'],103);peer.complete(new['resource_reservation'])
            with one.connect() as db:
                self.assertEqual(db.execute('SELECT until FROM offline_protective_phases').fetchone()[0],103)
                self.assertEqual(json.loads(db.execute('SELECT state FROM offline_resource_accounts').fetchone()[0])['starts'],2)
            with native_lifecycle_work(held=True),peer.protective_cohort():
                with peer.connect() as db:self.assertEqual(db.execute('SELECT owner FROM offline_protective_phases').fetchone()[0],peer.session)
            with peer.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM offline_protective_phases').fetchone()[0],0)

    def test_real_native_staggered_current_and_survivor_exits_use_bounded_phase(self):
        from tests.test_pons_current_shared_owners import CurrentSharedOwnerTests
        # Eight RPS still missed Current deadlines in repeated development
        # traces. Test the higher *offline* envelope without relaxing either
        # controller's original deadline; production remains at two RPS.
        for n,rate in ((2,3),(10,12)):
            with self.subTest(current=n,survivors=n,rps=rate):
                fixture=CurrentSharedOwnerTests();self.addCleanup(fixture.doCleanups)
                profile=capacity.OfflineProfile
                with patch.object(capacity,'OfflineProfile',side_effect=lambda *a,**kw:
                        profile(*a,protective_cohort_seconds=3,**kw)):
                    result,rpcs,t=fixture.run_owners(n,sharing=True,stagger=True,paced=True,
                        latency=.1,price_factor=2.2,rps=rate,survivor_count=n,real_time=True)
                survivor=t['mixed_survivor'];physical=next(r for r in rpcs if getattr(r,'fixture_consumer',None)=='survivor')
                self.assertEqual(len(physical.starts),6)
                self.assertLess(survivor['completed_at']-survivor['first_required_at'],3)
                self.assertTrue(survivor['native_accounting_verified'])
                self.assertTrue(all(r['realization_taken'] for r in survivor['risks']))
                marks=[e for e in t['native_events'] if e['action']=='mark']
                self.assertEqual(len(marks),n)
                self.assertTrue(all(e['completed_monotonic']<=105+int(e['identity'].split(':')[-1])*.1+5 for e in marks))
                self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in result))
                print('REAL_CLOCK_RESERVED_PHASE',json.dumps(dict(current=n,survivors=n,rps=rate,
                    phase_seconds=3,physical_starts=sum(len(r.starts) for r in rpcs),
                    survivor_starts=len(physical.starts),survivor_completion_seconds=survivor['completed_at']-105,
                    current_risk_misses=0,native_accounting_verified=True)),flush=True)

    def test_native_phase_keeps_reorganization_refusal_and_independent_money(self):
        from tests.test_pons_current_shared_owners import CurrentSharedOwnerTests
        fixture=CurrentSharedOwnerTests();self.addCleanup(fixture.doCleanups)
        profile=capacity.OfflineProfile
        with patch.object(capacity,'OfflineProfile',side_effect=lambda *a,**kw:
                profile(*a,protective_cohort_seconds=3,**kw)):
            result,rpcs,t=fixture.run_owners(2,sharing=True,paced=True,latency=.1,
                price_factor=2.2,rps=4,survivor_count=2,failure='fork')
        self.assertTrue(all(r['final_position']['status']=='open' for r in result))
        self.assertTrue(all(not r['monitor'][0]['available'] for r in result))
        self.assertTrue(all(r['reconciliation']['cash_basis_conservation'] for r in result))
        mixed=t['mixed_survivor']
        self.assertTrue(mixed['native_accounting_verified'])
        self.assertTrue(all(not r['realization_taken'] for r in mixed['risks']))
