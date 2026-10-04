"""A transport failure after a real paper fill must not abandon its lifecycle."""
import json,tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock,patch
from meme_machine.lanes.pons import BoundaryError
from meme_machine.lanes.pons.evidence import Store
from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
from meme_machine.lanes.pons.pons_selective_ledger import JOURNAL_CATEGORY
from meme_machine.lanes.pons.pons_selective_paper import run_lifecycle,STRATEGY_CAPITAL_QUOTE
from tests.lanes.pons import test_pons_partial_accounting as accounting_fixture
from meme_machine.runtime.execution_capacity import resize

MODULE='meme_machine.lanes.pons.pons_selective_paper.'
class PositionRecoveryTests(unittest.TestCase):
    @staticmethod
    def persistent_entry_signal(*args):
        return (
            dict(
                complete=True,progress_15s_bps=600,accelerating=True,
                graduation_eta_seconds=60,
            ),
            dict(
                independent_groups=4,new_independent_groups_15s=2,
                buy_sell_ratio_bps=20_000,current_net_quote=20,
                prior_net_quote=10,net_flow_accelerating=True,
                largest_buyer_flow_bps=1000,top3_buyer_flow_bps=3000,
                creator_sell_quote_15s=0,
            ),
            [],
        )

    def run_case(self,folder,fail_at):
        clock=[100];fixture=accounting_fixture.PartialAccountingTests();sell_calls=[];signal_times=[]
        state=MagicMock();state.buy_with_snipe.return_value=dict(refund=0,ready_to_graduate=False,tokens_out=1000)
        evaluation=dict(vector=dict(current_threshold_pass=True,policy_hash=POLICY_HASH,
            proposed_size={'amount_quote':100},evidence_available_at=100,
            trajectory={'graduation_eta_seconds':100},demand={'largest_buyer_flow_bps':100}),
            candidate=dict(receipt={'gasUsed':hex(21000)},curve='m',state=state,report={}),
            token='token',curve='m',source_transaction='source',market_events=[])
        rpc=MagicMock();rpc.used=0;rpc.telemetry.return_value={}
        budget_calls=[];auth_calls=[]
        def authenticate():
            auth_calls.append(True)
            if fail_at in ('pending_session_auth','persistent_session_auth') and len(auth_calls)>=2:
                if fail_at=='persistent_session_auth' or len(auth_calls)==2:
                    raise BoundaryError('provider_rpc_429')
        rpc.verify_chain.side_effect=authenticate
        def budget_read(*args,**kwargs):
            budget_calls.append((args,kwargs))
            if len(budget_calls)==1:raise BoundaryError('provider_session_budget_exhausted')
            if fail_at=='pending_session_auth':self.assertGreaterEqual(len(auth_calls),3)
            if fail_at=='persistent_session_auth':self.fail('unauthenticated operation dispatched')
            return '0x0'
        rpc.call.side_effect=budget_read
        def sleep(seconds):clock[0]+=max(0,seconds)
        def meta():return dict(block=int(clock[0]),block_hash='h'+str(int(clock[0])),event_at=int(clock[0]))
        def quote(_rpc,_candidate,side,amount,*args,**kwargs):
            if fail_at=='session_budget' and side=='sell':
                _rpc.call('eth_call',[],scope='selective_curve_mark')
            return fixture.quote(int(clock[0]),side,amount,1000 if side=='buy' else 98),meta()
        def wait_quote(_rpc,_candidate,side,amount,*args,**kwargs):
            if side=='sell':
                sell_calls.append(int(clock[0]))
                if fail_at in ('pending_session_budget','pending_session_auth','persistent_session_auth'):
                    _rpc.call('eth_call',[],scope='selective_pending_exit')
                if fail_at=='impossible_exit':raise BoundaryError('impossible_full_position_exit')
                if fail_at=='exit' and len(sell_calls)==1:raise BoundaryError('provider_rpc_429')
            q,m=quote(_rpc,_candidate,side,amount,*args,**kwargs);return q,m,None
        def signal(*args):
            signal_times.append(int(clock[0]))
            if fail_at=='signal' and len(signal_times)==1:raise BoundaryError('provider_rpc_429')
            if fail_at=='permanent':raise BoundaryError('provider_rpc_429')
            if fail_at=='authentication':raise BoundaryError('header_hash_mismatch')
            return {},{},[]
        db=Path(folder)/'trial.sqlite';capital=Path(folder)/'capital.sqlite'
        patches={'paper_rpc':lambda *a:rpc,'_gas_quote':lambda *a:(2,1),
            '_entry_capacity':lambda meta,amount,gas:resize(amount,1,lambda n:100,ordinary_limit=600),
            '_wait_curve_quote':wait_quote,'_curve_quote':quote,
            '_refresh_entry_persistence_signal':self.persistent_entry_signal,
            '_validate_final_entry':lambda *a:None,
            '_confirm_entry_delta':lambda *a:(a[5],[],{}),
            '_fresh_fill_full_exit_check':lambda *a:dict(executable=True),
            '_prove_impossible_full_exit':lambda *a:dict(reason='impossible_full_position_exit',sale_proceeds=0),
            '_latest_header':lambda *a:dict(number=hex(int(clock[0]))),
            '_graduation_transition':lambda *a:None,'_refresh_curve_signal':signal,
            'pregraduation_action':lambda **kw:dict(
                action='full_exit',reason='test_authenticated_exit',
                exit_tokens=int(kw['tokens'])),
            'time.time':lambda:clock[0],'time.sleep':sleep}
        with ExitStack() as stack:
            for name,value in patches.items():stack.enter_context(patch(MODULE+name,side_effect=value))
            result=run_lifecycle('unused',evaluation,db_path=db,capital_path=capital)
        store=Store(db)
        events=[json.loads(r[0]) for r in store.db.execute('SELECT body FROM records WHERE category=?',(JOURNAL_CATEGORY,))]
        store.close()
        book=CohortCapital(capital,STRATEGY_CAPITAL_QUOTE).reconcile()
        return result,book,events,signal_times,sell_calls

    def test_fresh_unexitable_fill_is_cancelled_before_entry(self):
        with tempfile.TemporaryDirectory() as d:
            clock=[100];fixture=accounting_fixture.PartialAccountingTests()
            state=MagicMock();state.buy_with_snipe.return_value=dict(
                refund=0,ready_to_graduate=False,tokens_out=1000)
            evaluation=dict(
                vector=dict(
                    current_threshold_pass=True,policy_hash=POLICY_HASH,
                    proposed_size={'amount_quote':100},evidence_available_at=100,
                    trajectory={'graduation_eta_seconds':100},
                    demand={'largest_buyer_flow_bps':100}),
                candidate=dict(
                    receipt={'gasUsed':hex(21000)},curve='m',state=state,report={}),
                token='token',curve='m',source_transaction='source',market_events=[])
            rpc=MagicMock();rpc.used=0;rpc.telemetry.return_value={}
            entry=fixture.quote(102,'buy',100,1000)
            meta=dict(block=102,block_hash='h102',event_at=102,state={})
            db=Path(d)/'trial.sqlite';capital=Path(d)/'capital.sqlite'
            with patch(MODULE+'_validate_final_entry'),\
                 patch(MODULE+'_entry_capacity',side_effect=lambda meta,amount,gas:resize(amount,1,lambda n:100,ordinary_limit=600)),\
                 patch(MODULE+'_confirm_entry_delta',return_value=({},[],{})),\
                 patch(MODULE+'paper_rpc',return_value=rpc),\
                 patch(MODULE+'_gas_quote',return_value=(2,1)),\
                 patch(MODULE+'_wait_curve_quote',return_value=(entry,meta,None)),\
                 patch(MODULE+'_refresh_entry_persistence_signal',
                   side_effect=self.persistent_entry_signal),\
             patch(MODULE+'_fresh_fill_full_exit_check',
                       side_effect=BoundaryError('impossible_full_position_exit')),\
                 patch(MODULE+'time.time',return_value=102),\
                 patch(MODULE+'time.sleep'):
                result=run_lifecycle(
                    'unused',evaluation,db_path=db,capital_path=capital)
            self.assertEqual(result['status'],'entry_failed')
            self.assertEqual(
                result['entry_failure'],'fill_full_exit_unavailable')
            self.assertEqual(result['final_position']['status'],'settled')
            self.assertEqual(
                CohortCapital(capital,STRATEGY_CAPITAL_QUOTE).reconcile()['unsettled'],0)
            store=Store(db)
            events=[json.loads(r[0]) for r in store.db.execute(
                'SELECT body FROM records WHERE category=?',(JOURNAL_CATEGORY,))]
            store.close()
            self.assertFalse(any(e['action']=='entry' for e in events))
            self.assertEqual(sum(e['action']=='cancel' for e in events),1)

    def test_post_entry_429_refreshes_evidence_on_same_lifecycle_then_settles(self):
        with tempfile.TemporaryDirectory() as d:r,b,events,times,_=self.run_case(d,'signal')
        self.assertEqual(r['status'],'settled',r.get('boundary'))
        self.assertEqual(len(r['provider_recoveries']),1)
        self.assertGreater(times[1],times[0])
        self.assertEqual(r['provider_recoveries'][0]['opened_at'],r['entry']['position']['last_at'])
        self.assertEqual(r['qualification_vector']['evidence_available_at'],100)
        self.assertEqual(b['unsettled'],0);self.assertEqual(b['reserved'],0)
        self.assertTrue(b['capital_integral_complete']);self.assertTrue(b['cash_basis_conservation'])
        self.assertEqual(sum(e['action']=='entry' for e in events),1)

    def test_pending_exit_429_keeps_original_intent_amount_and_due(self):
        with tempfile.TemporaryDirectory() as d:r,b,events,_,times=self.run_case(d,'exit')
        self.assertEqual(r['status'],'settled',r.get('boundary'))
        self.assertEqual(sum(e['action']=='exit_intent' for e in events),1)
        self.assertEqual(sum(e['action']=='exit' for e in events),1)
        recovery=r['provider_recoveries'][0]
        self.assertEqual(recovery['position_status'],'exit_pending')
        self.assertEqual(recovery['pending_exit_tokens'],1000)
        self.assertEqual(recovery['pending_due'],times[0])
        self.assertGreater(times[1],times[0]);self.assertEqual(b['unsettled'],0)
        self.assertEqual(r['exit']['reason'],'test_authenticated_exit')

    def test_persistent_pressure_is_bounded_and_filled_exposure_never_cancelled(self):
        with tempfile.TemporaryDirectory() as d:r,b,events,_,_=self.run_case(d,'permanent')
        self.assertEqual(r['boundary'],'selective_position_provider_recovery_exhausted')
        self.assertEqual(len(r['provider_recoveries']),5)
        self.assertEqual(b['unsettled'],1);self.assertGreater(b['reserved'],0)
        self.assertFalse(any(e['action']=='cancel' for e in events))

    def test_authentication_failure_is_not_retried_as_rate_pressure(self):
        with tempfile.TemporaryDirectory() as d:r,b,events,times,_=self.run_case(d,'authentication')
        self.assertEqual(r['boundary'],'header_hash_mismatch')
        self.assertNotIn('provider_recoveries',r);self.assertEqual(len(times),1)
        self.assertEqual(b['unsettled'],1)

    def test_impossible_pending_exit_drains_at_original_max_hold_with_zero_proceeds(self):
        from meme_machine.lanes.pons.pons_selective_continuation import EXIT_POLICY
        with tempfile.TemporaryDirectory() as d:r,b,events,_,times=self.run_case(d,'impossible_exit')
        self.assertEqual(r['status'],'settled',r.get('boundary'))
        self.assertEqual(r['settlement_kind'],'liquidity_writeoff')
        self.assertEqual(sum(e['action']=='entry' for e in events),1)
        self.assertEqual(sum(e['action']=='exit_intent' for e in events),1)
        self.assertFalse(any(e['action']=='exit' for e in events))
        self.assertEqual(sum(e['action']=='liquidity_writeoff' for e in events),1)
        self.assertGreaterEqual(r['final_position']['last_at']-r['entry']['position']['last_at'],EXIT_POLICY['max_total_hold_seconds'])
        self.assertEqual(r['final_position']['realized_proceeds'],0)
        self.assertEqual(r['realized_pnl_quote'],-r['entry']['position']['cost'])
        self.assertEqual(b['unsettled'],0)
        self.assertTrue(b['cash_basis_conservation'])
        self.assertTrue(b['capital_integral_complete'])

    def test_session_exhaustion_inside_monitor_preserves_one_entry_and_settles(self):
        with tempfile.TemporaryDirectory() as d:r,b,events,_,_=self.run_case(d,'session_budget')
        self.assertEqual(r['status'],'settled',r.get('boundary'))
        self.assertEqual(len(r['provider_session_rotations']),1)
        rotation=r['provider_session_rotations'][0]
        self.assertEqual(rotation['reason'],'local_session_budget')
        self.assertEqual(rotation['opened_at'],r['entry']['position']['last_at'])
        self.assertFalse(rotation['process_restart'])
        self.assertEqual(sum(e['action']=='entry' for e in events),1)
        self.assertEqual(sum(e['action']=='exit_intent' for e in events),1)
        self.assertEqual(sum(e['action']=='exit' for e in events),1)
        self.assertEqual(b['unsettled'],0);self.assertTrue(b['cash_basis_conservation'])
        self.assertTrue(b['capital_integral_complete'])

    def test_session_exhaustion_during_pending_exit_preserves_original_due(self):
        with tempfile.TemporaryDirectory() as d:r,b,events,_,times=self.run_case(d,'pending_session_budget')
        self.assertEqual(r['status'],'settled',r.get('boundary'))
        self.assertEqual(len(r['provider_session_rotations']),1)
        self.assertEqual(sum(e['action']=='exit_intent' for e in events),1)
        self.assertEqual(sum(e['action']=='exit' for e in events),1)
        self.assertEqual(r['provider_session_rotations'][0]['scope'],'selective_pending_exit')
        self.assertEqual(b['unsettled'],0)
        self.assertEqual(r['exit']['reason'],'test_authenticated_exit')

    def test_pending_exit_session_auth_recovery_keeps_ledger_and_original_clock(self):
        with tempfile.TemporaryDirectory() as d:r,b,events,_,times=self.run_case(d,'pending_session_auth')
        self.assertEqual(r['status'],'settled',r.get('boundary'))
        self.assertEqual(sum(e['action']=='entry' for e in events),1)
        self.assertEqual(sum(e['action']=='exit_intent' for e in events),1)
        self.assertEqual(sum(e['action']=='exit' for e in events),1)
        self.assertEqual(len(r['provider_recoveries']),1)
        recovery=r['provider_recoveries'][0]
        self.assertEqual(recovery['pending_due'],times[0])
        self.assertEqual(recovery['opened_at'],r['entry']['position']['last_at'])
        self.assertEqual(r['qualification_vector']['evidence_available_at'],100)
        rotations=r['provider_session_rotations']
        self.assertEqual(len(rotations),2)
        self.assertFalse(rotations[0]['authenticated'])
        self.assertTrue(rotations[1]['authenticated'])
        self.assertFalse(rotations[1]['local_session_rotation'])
        self.assertEqual(len(r['provider_sessions']),2)
        self.assertEqual(b['unsettled'],0);self.assertTrue(b['cash_basis_conservation'])

    def test_persistent_session_auth_failure_remains_bounded_with_pending_exposure(self):
        with tempfile.TemporaryDirectory() as d:r,b,events,_,_=self.run_case(d,'persistent_session_auth')
        self.assertEqual(r['boundary'],'selective_position_provider_recovery_exhausted')
        self.assertEqual(len(r['provider_recoveries']),5)
        self.assertEqual(sum(e['action']=='entry' for e in events),1)
        self.assertEqual(sum(e['action']=='exit_intent' for e in events),1)
        self.assertFalse(any(e['action'] in ('exit','cancel','liquidity_writeoff') for e in events))
