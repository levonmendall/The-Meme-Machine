"""Observability strategy invariants: breadth and qualification survive capacity pressure."""
from types import SimpleNamespace
import inspect
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.lanes.pump.engine import Engine
from meme_machine.lanes.pump.market_native_runtime import MarketNativeRuntime
from meme_machine.lanes.pump.market_native_shadow import discover_market_native
from meme_machine.lanes.pump.research import qualification_vector
from meme_machine.lanes.pump import runner as pump_runner
from meme_machine.lanes.meteora import runner as meteora_runner
from meme_machine.runtime.survivor_history import History
from meme_machine.lanes.pump.store import Store


class _Allocator:
    def allowed(self,*args,**kwargs):
        return 'capital_or_gas_reserve'


class _Metric:
    def priority_key(self):
        return (0,)


class StrategyObservabilityRuntimeTests(unittest.TestCase):
    def _engine(self):
        engine=object.__new__(Engine)
        engine.store=SimpleNamespace(state={'initial':1_000_000_000})
        engine.seeds={'anchor'}
        engine.groups={}
        engine.allocator=_Allocator()
        curve=SimpleNamespace(
            complete=False,real_sol=10_000_000_001,
            creator='creator',sol=1,token=100)
        engine.validate_snapshot=lambda snap,now:(curve,object())
        return engine

    def _qualification_case(self):
        nomination=dict(
            id='n',mint='mint',wallet='anchor',amount=100,tokens=100,
            market_time=100,available_time=100,slot=1,index=0,buy=True)
        events=[
            dict(id=f'e{i}',mint='mint',wallet=f'w{i}',amount=400_000_000,
                 tokens=1,buy=True,market_time=100,available_time=100,slot=1)
            for i in range(3)
        ]
        evidence=dict(
            snapshot=dict(mint='mint',accounts=[b'x'],slot=1,market_time=100),
            events=events,covered=True,concentration_bps=1000)
        return nomination,evidence

    @patch('meme_machine.lanes.pump.engine.pump.sell',return_value=(1_000_000_000,None))
    @patch('meme_machine.lanes.pump.engine.pump.buy',return_value=(100,1_000_000_000,None))
    @patch('meme_machine.lanes.pump.engine.pump.curve_mode',return_value={'mayhem':False})
    def test_strategy_qualification_is_independent_of_funding(self,*_):
        engine=self._engine()
        nomination,evidence=self._qualification_case()
        self.assertEqual(engine.strategy_qualify(nomination,evidence,100),'qualified')
        self.assertEqual(engine.qualify(nomination,evidence,100),'capital_or_gas_reserve')

    @patch('meme_machine.lanes.pump.research.pump.sell',return_value=(1_000_000_000,None))
    @patch('meme_machine.lanes.pump.research.pump.buy',return_value=(100,1_000_000_000,None))
    @patch('meme_machine.lanes.pump.research.pump.curve_mode',return_value={'mayhem':False})
    @patch('meme_machine.lanes.pump.engine.pump.sell',return_value=(1_000_000_000,None))
    @patch('meme_machine.lanes.pump.engine.pump.buy',return_value=(100,1_000_000_000,None))
    @patch('meme_machine.lanes.pump.engine.pump.curve_mode',return_value={'mayhem':False})
    def test_vector_records_unfunded_without_turning_it_into_strategy_rejection(self,*_):
        engine=self._engine()
        nomination,evidence=self._qualification_case()
        vector=qualification_vector(engine,nomination,evidence,100)
        self.assertEqual(vector['actual_reason'],'qualified')
        self.assertEqual(vector['allocator_reason'],'capital_or_gas_reserve')
        self.assertEqual(vector['funding_status'],'qualified_but_capital_unavailable')
        self.assertTrue(vector['current_threshold_pass'])
        self.assertNotIn('capital_or_gas_reserve',vector['all_rejections'])

    def test_market_native_candidate_can_reactivate_after_weak_first_observation(self):
        event=dict(id='e2',mint='mint',wallet='w',amount=1,tokens=1,buy=True,
                   market_time=100,available_time=100,slot=1)
        class Tape:
            def window(self,mint,now):
                return [event]
        rows=discover_market_native([event],Tape(),100,{'mint'})
        self.assertEqual(len(rows),1)
        self.assertFalse(rows[0]['first_discovery'])
        self.assertEqual(rows[0]['trigger'],'fresh_non_system_buy_reactivation')

    def test_evidence_queue_limit_is_pressure_not_candidate_loss(self):
        runtime=object.__new__(MarketNativeRuntime)
        runtime.evidence_queue_limit=1
        runtime.evidence_queue={}
        runtime.evidence_queue_capacity_pressure=0
        runtime.evidence_queue_capacity_skips=0
        runtime.capacity_losses=0
        runtime.evidence_enqueued=0
        a=dict(mint='a',nomination={'market_time':100})
        b=dict(mint='b',nomination={'market_time':100})
        runtime._queue_candidate(a,_Metric(),100)
        runtime._queue_candidate(b,_Metric(),100)
        self.assertEqual(set(runtime.evidence_queue),{'a','b'})
        self.assertEqual(runtime.evidence_queue_capacity_pressure,1)
        self.assertEqual(runtime.capacity_losses,0)

    def test_current_qualification_survives_zero_allocatable_capital(self):
        qualification=SimpleNamespace(
            mint='mint',observed_at=100,policy_hash='policy',score=1,
            reasons=(),confirmations=())
        signal=SimpleNamespace(repeat_buyer_clusters=3,repeat_buy_share_bps=5000)
        report={'qualifiers':[]}
        with patch.object(pump_runner,'_current_pump_sizing',
                          return_value=dict(realized_equity=100,target=5,
                                            allocatable_target=0,available=0)):
            reserved=pump_runner._reserve_position(
                report,{}, {},signal,qualification,
                {'available_time':100,'slot':1},'postgrad')
        self.assertFalse(reserved)
        self.assertEqual(
            report['qualified_unfunded'][0]['entry_status'],
            'qualified_but_capital_unavailable')
        self.assertEqual(report['qualifiers'],[])

    def test_execution_count_limit_does_not_masquerade_as_storage_exhaustion(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp+'/pump.sqlite','prospective',100_000_000,'test')
            try:
                store.state['entry_count']=100
                self.assertTrue(store.experiment_limit_reached())
                self.assertFalse(store.storage_pressure())
                self.assertTrue(store.pressure())
            finally:
                store.close()

    def test_meteora_attempt_pressure_never_becomes_candidate_rejection(self):
        budget=meteora_runner.CampaignAttemptBudget(1)
        self.assertEqual(
            meteora_runner._attempt_budget_state(budget,0,True),
            dict(pressure=False,evaluate=True))
        self.assertEqual(
            meteora_runner._attempt_budget_state(budget,1,True),
            dict(pressure=True,evaluate=True))

    def test_meteora_capital_check_occurs_after_strategy_qualification(self):
        source=inspect.getsource(meteora_runner.run_live)
        qualified=source.index('decision=qualify(features,policy)')
        funding=source.index("book.reconcile()['unsettled']",qualified)
        self.assertLess(qualified,funding)
        self.assertNotIn(
            "if book.reconcile()['unsettled']:\n                # During",
            source[:qualified])

    def test_survivor_candidate_limit_is_pressure_not_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            history=History(tmp+'/history.sqlite',policy='p',maximum_candidates=1)
            try:
                history.graduate('a',dict(at=1,identity='a'))
                history.graduate('b',dict(at=2,identity='b'))
                self.assertEqual({r['id'] for r in history.rows()},{'a','b'})
                self.assertEqual(history.get_meta('candidate_capacity_pressure'),1)
            finally:
                history.close()


if __name__=='__main__':
    unittest.main()
