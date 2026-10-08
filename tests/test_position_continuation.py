"""Accelerated native-book and supervisor phase boundaries; market I/O forbidden."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.operational.admission import available,configure,CONTINUATION_PROOFS
from meme_machine.operational.bounded_provider import Budget,PhaseBudget,CeilingReached,DeliveredResponse
from meme_machine.operational.position_continuation import (
    tick,position_only,readiness,provider_failure,provider_recovered,TOTAL_SECONDS)
from meme_machine.operational.supervisor import Supervisor,SOURCE_ROOT
from meme_machine.shared_capital.model import CapitalError


def envelope():
    return json.loads((SOURCE_ROOT/'operational/position-continuation/RESOURCE_ENVELOPE.example.json').read_text())

def proof():return {key:True for key in CONTINUATION_PROOFS}

def healthy():
    native=dict(current_restored=True,survivor_replay_verified=True,survivor_handoff_ready=True,exit_path_bound=True,flat=True)
    health=dict(lanes={lane:dict(reconciled=True,exit_code=None,native_continuation=deepcopy(native)) for lane in ('pump','pons')},
        providers={p:dict(state='CURRENT',queue_depth=0,oldest_wait_seconds=0) for p in ('solana','robinhood')})
    health['providers']['evidence']=dict(startup_released=True,phase='ACTIVE')
    health['continuation_resources']=dict(limits_verified=True,cgroup_memory_bytes=1024)
    return health,dict(reconciliation=dict(checks=dict(exact_conservation=True))),1024


class LifecycleTests(unittest.TestCase):
    from tests.test_pump_pons_capital_preparation import RuntimeIntegrationTests as Native
    fixture=Native.fixture;native_position=Native.native_position

    def service(self,*,armed=True):
        from tests.test_paper_bootstrap import AdmissionTests
        root,a,now,_=self.fixture();budget,data=AdmissionTests.scope(self,a,now,root,arm=armed)
        s=Supervisor(root,offline=True,admission='BOOTSTRAP');s.shared_capital=a;s.run_id=data['run_id']
        s.provider_budget=budget;s.admission_data=data;s.bootstrap_armed=armed
        s.processes={lane:SimpleNamespace() for lane in ('pump','pons')}
        s.last_native_health=healthy()[0]['lanes']
        return root,a,now,s

    def test_open_survivor_survives_1800_seconds_without_owner_shutdown(self):
        root,a,now,s=self.service();book,sleeve,identity=self.native_position(root,now,survivor=True)
        s.last_native_health['pump']['native_continuation']['flat']=False
        before=deepcopy(book._load(identity));scope=deepcopy(a.ledger()['runtime_admission'])
        with patch('time.time',return_value=now+1800):tick(s)
        self.assertFalse(s.stop_requested);self.assertEqual(s.runtime_lanes(),('pump',))
        self.assertEqual(book._load(identity),before)
        self.assertEqual(s.provider_budget.phase(),'CONTINUATION')
        after=a.ledger()['runtime_admission']
        for key in ('started_at','funding_until','stop_at','lifecycle_id','gross_reserved'):
            self.assertEqual(after[key],scope[key])
        self.assertEqual(available(a.ledger(),now+1800),'observation_only_funding_closed');a.verify_replay()

    def test_funding_and_optional_discovery_close_at_1200_while_monitoring_stays_open(self):
        root,a,now,s=self.service();self.native_position(root,now,survivor=True)
        with patch('time.time',return_value=now+1200):
            self.assertEqual(available(a.ledger(),now+1200),'bootstrap_funding_deadline')
            self.assertTrue(position_only(path=s.provider_budget.path));tick(s)
        self.assertFalse(s.stop_requested);self.assertEqual(s.provider_budget.phase(),'BOOTSTRAP')

    def test_restart_restores_original_clocks_consumption_and_single_lifecycle(self):
        root,a,now,s=self.service();book,_,identity=self.native_position(root,now,survivor=True)
        original=deepcopy(a.ledger()['runtime_admission']);book_replay=book.replay()
        s.provider_budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        usage=s.provider_budget.bootstrap.snapshot()['rpc_cu']
        path=root/'envelope.json';path.write_text(json.dumps(envelope()))
        resumed=Supervisor(root,offline=True,admission='BOOTSTRAP');resumed.shared_capital=a
        with patch.dict(os.environ,MM_POSITION_CONTINUATION_ENVELOPE=str(path)),patch('time.time',return_value=now+259199):
            resumed.configure_admission()
        self.assertEqual(resumed.admission,'CONTINUATION');self.assertEqual(resumed.runtime_lanes(),('pump',))
        self.assertEqual(resumed.provider_budget.bootstrap.snapshot()['rpc_cu'],usage)
        self.assertEqual(book.replay(),book_replay)
        scope=a.ledger()['runtime_admission']
        for key in ('started_at','funding_until','stop_at','lifecycle_id','gross_reserved'):
            self.assertEqual(scope[key],original[key])
        self.assertEqual(available(a.ledger(),now+1),'observation_only_funding_closed');a.verify_replay()

    def test_reconciliation_and_native_flat_proof_required_before_automatic_cleanup(self):
        root,a,now,s=self.service();book,sleeve,identity=self.native_position(root,now,survivor=True)
        from meme_machine.runtime.directional_continuation import native_sync
        with patch('time.time',return_value=now+1800):tick(s)
        book.transition(identity,'settled',now+1801,amount=6250);native_sync(book,sleeve,identity)
        s.last_native_health['pump']['native_continuation']['flat']=False
        with patch('time.time',return_value=now+1802):tick(s)
        self.assertFalse(s.stop_requested)
        s.last_native_health['pump']['native_continuation']['flat']=True
        with patch('time.time',return_value=now+1803):tick(s)
        self.assertTrue(s.stop_requested);self.assertEqual(s.provider_budget.phase(),'FLAT')
        self.assertFalse(a.ledger()['runtime_pending']);a.verify_replay()

    def test_absolute_recovery_deadline_escalates_without_fabricating_exit(self):
        root,a,now,s=self.service();book,_,identity=self.native_position(root,now,survivor=True)
        s.last_native_health['pump']['native_continuation']['flat']=False
        with patch('time.time',return_value=now+TOTAL_SECONDS-65):tick(s)
        self.assertEqual(s.provider_budget.phase(),'FAULT');self.assertTrue(s.stop_requested)
        self.assertFalse(s.provider_budget.fault()['protected']);self.assertEqual(book._load(identity)['status'],'open')
        self.assertIn('deadline_exhausted',s.provider_budget.fault()['reason'])

    def test_absent_incomplete_or_stale_continuation_proof_cannot_fund(self):
        root,a,now,s=self.service(armed=False)
        for n,value in enumerate((None,True,dict(native_managers=True))):
            with self.assertRaisesRegex(CapitalError,'native_continuation_not_ready'):
                a.command('bad:'+str(n),'runtime_admission',dict(s.admission_data,mode='BOOTSTRAP',continuation_ready=value),now)
        health,portfolio,rss=healthy()
        self.assertEqual(readiness(health,portfolio,rss,envelope()),proof())
        health['lanes']['pump']['native_continuation']['exit_path_bound']=False
        with self.assertRaisesRegex(ValueError,'not_ready'):readiness(health,portfolio,rss,envelope())
        health,portfolio,rss=healthy();health['providers']['evidence']['startup_released']=False
        with self.assertRaisesRegex(ValueError,'not_ready'):readiness(health,portfolio,rss,envelope())
        self.assertEqual(a.ledger()['runtime_admission']['mode'],'OBSERVATION');self.assertFalse(a.ledger()['positions'])

    def test_provider_recovery_deadline_survives_restart_and_never_reopens_funding(self):
        root,a,now,s=self.service();self.native_position(root,now,survivor=True)
        with patch('time.time',return_value=now+1800):provider_failure(s,'subscription_rejected')
        with patch('time.time',return_value=now+1801):provider_failure(s,'subscription_rejected')
        with patch('time.time',return_value=now+5399):provider_failure(s,'rate_limited')
        self.assertEqual(s.provider_budget.phase(),'CONTINUATION')
        with patch('time.time',return_value=now+5400):provider_failure(s,'rate_limited')
        self.assertEqual(s.provider_budget.phase(),'FAULT');self.assertFalse(s.provider_budget.fault()['protected'])
        self.assertEqual(available(a.ledger(),now+10),'observation_only_funding_closed')


class NativeHoldTests(unittest.TestCase):
    from tests.test_survivor_commit import SurvivorCommitTests as Native
    setUp=Native.setUp;tearDown=Native.tearDown;new_book=Native.new_book;fill=Native.fill;reopen=Native.reopen

    def test_native_72_hour_partial_high_water_restart_pending_exit_and_settlement(self):
        from meme_machine.runtime.survivor_commit import monitor,restore_risk
        self.fill();policy=dict(hard_stop_bps=-1200,first_profit_bps=2500,first_sell_bps=2500,
            trail_bps=2000,tight_arm_bps=6000,tight_trail_bps=1500,soft_confirmations=2,maximum_hold_seconds=259200)
        self.adapter.proceeds=32
        for hour in range(73):
            at=10+hour*3600;self.adapter.at=at
            if hour==72:self.adapter.quote_available=False
            action=monitor(book=self.book,sleeve=self.sleeve,identity='run:one',
                observation=dict(id='hour:'+str(hour),at=at,after_cost_return_bps=4000,net_exit_proceeds=140,exit_liquidity_valid=True),
                policy=policy,adapter=self.adapter)
            if hour in (1,36,71):self.reopen()
            state=restore_risk(self.book,'run:one')
            self.assertEqual(state['opened_at'],10);self.assertEqual(state['high_water_bps'],4000)
            self.assertEqual(state['remaining_quantity'],300);self.assertTrue(state['realization_taken'])
        self.assertEqual(action['action'],'exit_pending');self.reopen()
        risk=restore_risk(self.book,'run:one');self.assertEqual(risk['last_action']['reason'],'maximum_hold')
        self.assertEqual(self.book._load('run:one')['realized'],7)
        self.adapter.at=259211;self.adapter.quote_available=True;self.adapter.proceeds=90
        observation=dict(id='recovery',at=259211,after_cost_return_bps=4000,exit_liquidity_valid=True)
        action=monitor(book=self.book,sleeve=self.sleeve,identity='run:one',observation=observation,policy=policy,adapter=self.adapter)
        self.assertEqual(action['reason'],'maximum_hold');self.assertEqual(self.book._load('run:one')['status'],'settled')
        self.assertEqual(self.sleeve.reconcile()['available'],1022);self.assertTrue(self.book.replay()['verified'])
        before=deepcopy(self.book.reconcile())
        monitor(book=self.book,sleeve=self.sleeve,identity='run:one',observation=observation,policy=policy,adapter=self.adapter)
        self.assertEqual(self.book.reconcile(),before)

    def test_denied_addition_is_durable_and_preserves_native_risk_and_quantity(self):
        from meme_machine.operational.position_continuation import addition_rejection
        self.fill();before=self.book._load('run:one')
        addition_rejection(self.book,'run:one','funding_closed',1210)
        addition_rejection(self.book,'run:one','funding_closed',1211)
        self.reopen();self.assertEqual(self.book._load('run:one'),before)
        self.assertEqual(self.book.runtime_state('run:one','continuation-addition-rejection')['reason'],'funding_closed')

    def test_interrupted_unfilled_reservation_is_cancelled_without_an_exit_or_new_fill(self):
        from meme_machine.operational.position_continuation import cancel_unfilled
        self.sleeve.reserve('run:one',strategy='survivor',amount=100,at=10,candidate='mint',generation=1,regime=self.regime)
        self.book.reserve('run:one',100,10,{'decision':self.decision})
        row=dict(position='run:one');saved=[];history=SimpleNamespace(save=lambda r:saved.append(deepcopy(r)))
        with patch('meme_machine.operational.position_continuation.position_only',return_value=True):
            self.assertTrue(cancel_unfilled(self.book,self.sleeve,history,row,1210))
        self.assertEqual(self.book._load('run:one')['status'],'cancelled')
        self.assertEqual(self.sleeve.reconcile()['available'],1000)
        self.assertIsNone(saved[0]['position']);self.assertEqual(self.book.reconcile()['open_positions'],0)


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'usage.sqlite'
        Budget.create(self.path,continuation=envelope());self.budget=PhaseBudget(self.path)

    def test_phase_exhaustion_uses_separate_budget_without_reset_or_extra_attempt(self):
        self.budget.bootstrap.change(dict(rpc_cu=720000))
        self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        self.assertEqual(self.budget.phase(),'CONTINUATION');usage=self.budget.usage()['phases']
        self.assertEqual(usage['bootstrap']['rpc_cu'],'720000');self.assertEqual(usage['bootstrap']['http_attempts'],'0')
        self.assertEqual(usage['continuation']['rpc_cu'],'20');self.assertEqual(usage['continuation']['alchemy_rpc_cu'],'20')
        PhaseBudget(self.path).reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        self.assertEqual(self.budget.usage()['phases']['continuation']['rpc_cu'],'40')

    def test_delivered_response_and_live_stream_transfer_are_not_double_counted(self):
        import io
        token=self.budget.stream_open('yellowstone')
        charged=self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        self.budget.set_phase('CONTINUATION','offline_handoff')
        DeliveredResponse(io.BytesIO(b'x'*100),charged,self.budget).read()
        self.budget.native('yellowstone',1024,token=token)
        self.budget.stream_close(token,unread_possible=True);self.budget.stream_close(token,unread_possible=True)
        rows=self.budget.usage()['phases']
        self.assertEqual(rows['bootstrap']['http_bytes'],'100');self.assertEqual(rows['continuation']['http_bytes'],'0')
        self.assertEqual(rows['bootstrap']['http_attempts'],'2');self.assertEqual(rows['continuation']['http_attempts'],'0')
        self.assertEqual(rows['continuation']['native_bytes'],'1024');self.assertEqual(rows['continuation']['native_reserved'],'0')

    def test_reconnects_and_recovery_are_finite_and_exhaustion_is_actionable(self):
        self.budget.set_phase('CONTINUATION','offline')
        continuation=Budget(self.path,phase='continuation')
        with continuation.db() as db:db.execute("UPDATE run SET value='32' WHERE key='continuation.native_opens'")
        token=self.budget.stream_open('yellowstone');self.assertEqual(token['phase'],'recovery')
        self.budget.stream_close(token)
        with Budget(self.path,phase='recovery').db() as db:db.execute("UPDATE run SET value='32' WHERE key='recovery.native_opens'")
        with self.assertRaises(CeilingReached):self.budget.stream_open('yellowstone')
        self.assertEqual(self.budget.phase(),'FAULT');self.assertIn('reconnect',self.budget.fault()['reason'])

    def test_process_crash_charges_orphan_buffers_once_without_closing_live_peer(self):
        token=self.budget.stream_open('yellowstone')
        before=self.budget.bootstrap.snapshot();self.budget.reap_orphans()
        self.assertEqual(self.budget.bootstrap.snapshot()['native_reserved'],before['native_reserved'])
        with patch('meme_machine.shared_capital.runtime.process_identity',side_effect=OSError):
            self.budget.reap_orphans();self.budget.reap_orphans()
        after=self.budget.bootstrap.snapshot()
        self.assertEqual(after['native_reserved'],'0')
        self.assertEqual(after['native_uncertain_bytes'],before['native_reserved'])

    def test_idle_family_needs_no_provider_but_cannot_hide_an_obligation_or_fault(self):
        from meme_machine.operational.monitoring import continuation_idle,conditions
        sample=dict(timestamp=1000,position_continuation=dict(phase='CONTINUATION'),
            portfolio=dict(state='CURRENT',positions_by_lane={},reservations_by_lane={},pending_by_lane={}),
            lanes=dict(pump=dict(phase='CONTINUATION_IDLE')))
        self.assertTrue(continuation_idle(sample,'pump'))
        self.assertNotIn('evidence_unavailable',conditions(sample,'epoch',1000))
        sample['portfolio']['positions_by_lane']['pump']=1
        self.assertFalse(continuation_idle(sample,'pump'))
        self.assertIn('evidence_unavailable',conditions(sample,'epoch',1000))
        sample['position_continuation']['phase']='FAULT'
        self.assertIn('position_continuation_fault',conditions(sample,'epoch',1000))

    def test_protective_work_preempts_closed_optional_work_without_new_engine(self):
        from meme_machine.lanes.pons.provider_admission import decision_work,position_work
        from meme_machine.lanes.pons import BoundaryError
        @decision_work(5)
        def optional():return 'optional'
        @position_work
        def protective():return optional()
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path)):
            self.budget.position_work_only()
            with self.assertRaisesRegex(BoundaryError,'optional_work_closed'):optional()
            self.assertEqual(protective(),'optional')
        self.assertEqual(Supervisor('/unused',offline=True).runtime_lanes(),('pump','pons'))

    def test_bootstrap_spend_allowance_remains_three_dollars_and_continuation_is_independent(self):
        self.assertEqual(self.budget.bootstrap.snapshot()['modeled_spend_limit'],'3')
        self.budget.set_phase('CONTINUATION','offline')
        self.assertEqual(self.budget.selected().snapshot()['modeled_spend_limit'],'20')
        self.budget.selected().change(dict(rpc_cu=24000000))
        self.budget.reserve_http('https://solana-mainnet.g.alchemy.com/v2/offline',[dict(method='getSlot')])
        self.assertEqual(self.budget.phase(),'RECOVERY')
        self.assertEqual(self.budget.usage()['phases']['continuation']['rpc_cu'],'24000000')

    def test_empty_survivor_worker_stops_provider_work_while_other_manager_can_continue(self):
        from meme_machine.runtime.survivor_history import Worker
        calls=[]
        class Native:
            def step(self,*,admit):
                calls.append(admit)
                return dict(durable_handoff=True,accounting=dict(open_positions=0,reserved=0))
            def close(self):pass
        worker=Worker(Native,enrichment_enabled=False);self.addCleanup(worker.close)
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path)):
            self.budget.position_work_only();worker.prime()
            for at in (1200,1800,129600,259200):worker.tick(at,admit=True)
        self.assertEqual(calls,[False])

    def test_pons_native_step_keeps_protective_priority_after_optional_work_is_closed(self):
        from meme_machine.runtime.survivor_history import Worker
        from meme_machine.lanes.pons.provider_admission import decision_work,priority
        calls=[]
        class Native:
            @decision_work(4)
            def step(self,*,admit):
                calls.append((admit,priority('pons_survivor')))
                return dict(durable_handoff=True,accounting=dict(open_positions=1,reserved=0))
            def close(self):pass
        worker=Worker(Native,enrichment_enabled=False);self.addCleanup(worker.close)
        with patch.dict(os.environ,MM_BOUNDED_PROVIDER_DB=str(self.path)):
            self.budget.position_work_only();worker.prime()
        self.assertEqual(calls,[(False,0)])


class SelectiveShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_running_optional_program_subscription_is_cancelled_at_cutoff(self):
        import asyncio
        from meme_machine.solana_selective_source import SelectiveSource
        stop=asyncio.Event();closed=asyncio.Event();running=asyncio.Event()
        source=SimpleNamespace(stop=stop,observe=lambda *args,**kwargs:None)
        async def work(*args,**kwargs):return [dict(priority=6)]
        async def live(*args):
            running.set()
            try:await asyncio.Event().wait()
            finally:closed.set();stop.set()
        source.work=work;source.live=live
        with patch('meme_machine.operational.position_continuation.position_only',side_effect=lambda **_:running.is_set()):
            await asyncio.wait_for(SelectiveSource.rolling_programs(source,None),1)
        self.assertTrue(closed.is_set())
