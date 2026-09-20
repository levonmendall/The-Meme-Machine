"""Pons-native cash flow replay, isolated from generic paper machinery."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from robinhood_research import BoundaryError
from robinhood_research.evidence import Store, Stamp, digest
from robinhood_research.paper import Quote
from robinhood_research.pons_selective_capital import CohortCapital
from robinhood_research.pons_selective_continuation import POLICY_HASH
from robinhood_research.pons_selective_ledger import SelectivePaper, STRATEGY_NAMESPACE, JOURNAL_CATEGORY


class PartialAccountingTests(unittest.TestCase):
    def features(self, at):
        return dict(asof=at,market='m',authority='frozen_policy_paper',qualification='qualified',
                    policy_hash=POLICY_HASH,strategy_namespace=STRATEGY_NAMESPACE,shared_allocator=False)

    def quote(self,at,side,amount,out):
        return Quote('m',side,amount,out,2,1,Stamp(4663,at,f'h{at}',at,at,'finalized','natural'))

    def test_partial_cash_basis_costs_and_risk_time_survive_reopen_and_recycling(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trial.sqlite';store=Store(path);guard=CohortCapital(Path(tmp)/'capital.sqlite',1000)
            clock=[10_000_000_000]
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH,
                                 clock_ns=lambda:clock[0],on_commit=guard.observe)
            decision=self.features(10)
            guard.reserve('x',120,at=10,decision_hash=digest(decision),trial_path=path)
            paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=decision)
            for at,action,kwargs in (
                (11,'entry',dict(quote=self.quote(11,'buy',100,1000))),
                (12,'exit_intent',dict(exit_tokens=500)),
                (13,'exit',dict(quote=self.quote(13,'sell',500,70))),
            ):
                clock[0]=at*10**9;paper.advance('x',now=at,action=action,**kwargs)
            native=paper.reconcile();cohort=guard.reconcile()
            self.assertEqual((native['cash'],native['remaining_cost_basis'],native['booked_realized']),(966,51,17))
            self.assertEqual((cohort['cash'],cohort['remaining_cost_basis'],cohort['booked_realized']),(966,51,17))
            # Partial profit is visible, but cannot increase allocation authority.
            self.assertEqual((cohort['available'],cohort['reserved'],cohort['realized']),(880,120,0))
            self.assertEqual(cohort['native_execution_cost'],4)
            self.assertEqual(cohort['capital_at_risk_unit_nanoseconds'],324*10**9)
            store.close();store=Store(path)
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH,
                                 clock_ns=lambda:clock[0],on_commit=guard.observe)
            self.assertEqual(paper.reconcile(),native)
            clock[0]=14*10**9;paper.advance('x',now=14,action='exit_intent')
            clock[0]=15*10**9;position=paper.advance('x',now=15,action='exit',quote=self.quote(15,'sell',500,82))
            final=guard.settle('x',position,at=15)
            self.assertEqual((final['cash'],final['available'],final['booked_realized']),(1046,1046,46))
            self.assertEqual(final['capital_at_risk_unit_nanoseconds'],426*10**9)
            self.assertEqual(final['native_execution_cost'],6)
            self.assertTrue(final['capital_integral_complete'])
            self.assertTrue(final['cash_basis_conservation'])
            event=store.get(JOURNAL_CATEGORY,'x:3')
            self.assertEqual(event['quote']['amount_out'],70)
            self.assertEqual(event['quote']['fee_quote'],1)  # Embedded in quote, not subtracted twice.
            second=self.features(16);clock[0]=16*10**9
            guard.reserve('y',1000,at=16,decision_hash=digest(second),trial_path=path)
            paper.reserve('y',market='m',amount=980,gas_budget=20,now=16,features=second)
            self.assertEqual(guard.reconcile()['genesis'],1000)
            self.assertEqual(guard.reconcile()['available'],46)
            self.assertEqual(guard.reconcile()['capital_at_risk_unit_nanoseconds'],426*10**9)
            store.close()

    def test_deleted_projection_and_mutated_journal_fail_closed(self):
        store=Store(':memory:');paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,natural_policy_hash=POLICY_HASH)
        paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=self.features(10))
        with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):
            store.db.execute('DELETE FROM records WHERE category=?',(JOURNAL_CATEGORY,))
        store.db.execute('DELETE FROM pons_selective_paper')
        with self.assertRaisesRegex(BoundaryError,'projection_mismatch'):paper.reconcile()
        with self.assertRaisesRegex(BoundaryError,'projection_mismatch'):
            paper.reserve('y',market='m',amount=100,gas_budget=20,now=10,features=self.features(10))
        store.close()

    def test_executable_mark_is_observation_only_and_partial_exit_invalidates_it(self):
        store=Store(':memory:');paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH)
        paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=self.features(10))
        paper.advance('x',now=11,action='entry',quote=self.quote(11,'buy',100,1000))
        self.assertIsNone(paper.reconcile()['unrealized_at_recorded_marks'])
        paper.advance('x',now=12,action='mark',quote=self.quote(12,'sell',1000,130))
        rec=paper.reconcile()
        self.assertEqual((rec['cash'],rec['marked_position_value'],rec['unrealized_at_recorded_marks']),(898,128,26))
        self.assertEqual(rec['available'],880)
        with self.assertRaisesRegex(BoundaryError,'stale_state'):
            paper.advance('x',now=18,action='mark',quote=self.quote(12,'sell',1000,130))
        paper.advance('x',now=13,action='exit_intent',exit_tokens=500)
        paper.advance('x',now=14,action='exit',quote=self.quote(14,'sell',500,70))
        self.assertIsNone(paper.reconcile()['unrealized_at_recorded_marks'])
        store.close()

    def test_clock_regression_rolls_back_and_observer_failure_keeps_native_commit(self):
        store=Store(':memory:');clock=[20]
        paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH,clock_ns=lambda:clock[0])
        paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=self.features(10))
        clock[0]=19
        with self.assertRaisesRegex(BoundaryError,'clock_regression'):
            paper.advance('x',now=11,action='entry',quote=self.quote(11,'buy',100,1000))
        self.assertEqual(paper._get('x')['status'],'reserved')
        clock[0]=21
        def fail(*args):raise RuntimeError('observer_failed')
        paper.on_commit=fail
        with self.assertRaisesRegex(RuntimeError,'observer_failed'):
            paper.advance('x',now=11,action='entry',quote=self.quote(11,'buy',100,1000))
        self.assertEqual(paper._get('x')['status'],'open')
        self.assertEqual(paper.reconcile()['cash'],898)
        store.close()

    def test_lost_post_commit_observation_cannot_claim_consolidated_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trial.sqlite';store=Store(path);guard=CohortCapital(Path(tmp)/'capital.sqlite',1000)
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=POLICY_HASH,on_commit=guard.observe)
            decision=self.features(10)
            guard.reserve('x',120,at=10,decision_hash=digest(decision),trial_path=path)
            paper.reserve('x',market='m',amount=100,gas_budget=20,now=10,features=decision)
            paper.on_commit=None  # Reproduce a crash after native commit, before observer.
            position=paper.advance('x',now=11,action='entry',quote=self.quote(11,'buy',100,1000))
            rec=guard.reconcile()
            self.assertEqual(rec['available'],880)
            self.assertFalse(rec['native_observation_complete'])
            self.assertIsNone(rec['cash_basis_conservation'])
            self.assertEqual(rec['unobserved_native_positions'],['x'])
            guard.observe(paper,position)
            self.assertTrue(guard.reconcile()['cash_basis_conservation'])
            store.close()


if __name__=='__main__':unittest.main()
