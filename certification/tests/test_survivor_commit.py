"""Native integer-book integration; no provider or profitability fixture."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from certification.sleeve_reservations import SleeveReservations
from certification.survivor_paper_book import PaperBook
from certification.survivor_commit import commit,monitor,restore_risk


class Adapter:
    def __init__(self,test):
        self.test=test;self.at=10;self.breadth=20;self.valid=True;self.loss_fn=lambda n:100
        self.hook=None;self.quote_available=True;self.proceeds=0;self.calls=[]
    def now(self):return self.at
    def fresh_state(self,candidate):self.calls.append('state');return {'at':self.at}
    def fresh_quotes(self,state,budget):
        self.calls.append('quote')
        if self.hook=='quote':self.test.supersede()
        return self
    def reconstruct(self,state,quotes):
        self.calls.append('demand')
        if self.hook=='demand':self.test.supersede()
        return dict(candidate=self.valid,policy_hash='b',all_rejections=[] if self.valid else ['no_breakout'],
                    features=dict(independent_buyers=self.breadth))
    def turnover_cap(self,facts,decision):return 100
    def loss(self,n):return self.loss_fn(n)
    def entry(self,n):return dict(cost=n,quantity=400)
    @contextmanager
    def generation_fence(self,candidate,generation):yield
    def validate_current(self,state,execution,now):self.calls.append('validate')
    def exit_quote(self,qty):
        if not self.quote_available:return None
        return dict(quantity=qty,net_proceeds=self.proceeds)
    def validate_exit(self,execution,qty,now):assert execution['quantity']==qty


class SurvivorCommitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.sleeve=SleeveReservations(self.root/'sleeve',lane='pump',capital=1000,
            policies={'current':'a','survivor':'b'},cohort='cohort')
        self.book=self.new_book();self.adapter=Adapter(self)
        self.decision=dict(candidate=True,policy_hash='b',features=dict(independent_buyers=20))
        self.regime=dict(at=1,base_id='a',high_reset_cycle='a',buyer_population=['a'])
        self.sleeve.observe('mint',strategy='survivor',at=1,state='qualified',evidence=self.decision,regime=self.regime)

    def new_book(self):
        return PaperBook(str(self.root/'paper'),run_id='run',lane='survivor',policy_hash='b',initial=1000)
    def tearDown(self):self.book.close();self.sleeve.close();self.tmp.cleanup()
    def supersede(self):
        self.sleeve.observe('mint',strategy='survivor',at=2,state='qualified',evidence={'new':True},regime=self.regime)
    def fill(self,retention=6500):
        return commit(book=self.book,sleeve=self.sleeve,identity='run:one',candidate='mint',generation=1,
            strategy='survivor',policy_hash='b',decision=self.decision,regime=self.regime,at=10,
            target=100,minimum=10,retention_bps=retention,ordinary_limit=600,stress_limit=600,
            adapter=self.adapter,qualify=lambda x:x)
    def reopen(self):self.book.close();self.book=self.new_book()

    def test_slow_reconstruction_refreshes_once_then_rechecks_all_inputs(self):
        self.adapter.commit_context_expired=lambda state:self.adapter.calls.count('demand')==1
        self.assertEqual(self.fill()['status'],'filled')
        self.assertEqual(self.adapter.calls,['state','quote','demand','state','quote','demand','validate'])

    def test_repeat_staleness_cancels_with_bounded_provider_work(self):
        self.adapter.commit_context_expired=lambda state:True
        with self.assertRaisesRegex(ValueError,'stale_commit'):self.fill()
        self.assertEqual(self.adapter.calls,['state','quote','demand','state','quote','demand'])
        self.assertEqual(self.sleeve.reconcile()['available'],1000)

    def test_exact_retention_boundaries_for_both_sleeves(self):
        for threshold,breadth in ((6000,12),(6500,13)):
            with self.subTest(threshold=threshold):
                if threshold==6500:self.tearDown();self.setUp()
                self.adapter.breadth=breadth
                result=self.fill(threshold)
                self.assertEqual(result['status'],'filled')
                self.assertEqual(result['telemetry']['generation'],1)
                self.assertEqual(self.book.reconcile()['basis'],100)
                # Idempotency consumes no new native or provider operation.
                before=list(self.adapter.calls);self.reopen()
                self.assertEqual(self.fill(threshold)['status'],'already_committed')
                self.assertEqual(before,self.adapter.calls)

    def test_below_retention_cancels_and_releases_exactly_once(self):
        self.adapter.breadth=12
        with self.assertRaisesRegex(ValueError,'breadth_retention'):self.fill()
        self.reopen();self.assertEqual(self.book._load('run:one')['status'],'cancelled')
        self.assertEqual(self.sleeve.reconcile()['available'],1000)

    def test_breakout_disappearance_does_not_fill(self):
        self.adapter.valid=False
        with self.assertRaisesRegex(ValueError,'no_breakout'):self.fill()
        self.assertEqual(self.book.reconcile()['open_positions'],0)

    def test_supersession_during_quote_and_reconstruction(self):
        for stage in ('quote','demand'):
            with self.subTest(stage=stage):
                if stage=='demand':
                    # Independent second fixture, not reuse of a cancelled ID.
                    self.tearDown();self.setUp()
                self.adapter.hook=stage
                with self.assertRaisesRegex(ValueError,'superseded_commit'):self.fill()
                self.assertNotIn('validate',self.adapter.calls)
                self.assertEqual(self.book.reconcile()['basis'],0)

    def test_restart_reserved_reacquires_state_and_capacity(self):
        self.sleeve.reserve('run:one',strategy='survivor',amount=100,at=10,candidate='mint',generation=1,regime=self.regime)
        self.book.reserve('run:one',100,10,{'decision':self.decision})
        # Other strategy can use only the remaining shared capital.
        self.sleeve.reserve('current',strategy='current',amount=900,at=10)
        self.reopen();self.adapter.loss_fn=lambda n:100 if n<=100 else 900
        self.assertEqual(self.fill()['position']['basis'],50)
        self.assertEqual(self.adapter.calls,['state','quote','demand','validate'])
        self.assertEqual(self.sleeve.reconcile()['available'],0)

    def test_zero_quote_capacity_cancels(self):
        self.adapter.loss_fn=lambda n:None
        with self.assertRaisesRegex(ValueError,'execution_capacity'):self.fill()
        self.assertEqual(self.sleeve.reconcile()['reserved'],0)

    def test_partial_original_quantity_exact_accounting_and_restart(self):
        self.fill();self.adapter.at=11;self.adapter.proceeds=32
        policy=dict(hard_stop_bps=-1200,first_profit_bps=2500,first_sell_bps=2500,
            trail_bps=2000,tight_arm_bps=6000,tight_trail_bps=1500,soft_confirmations=2,maximum_hold_seconds=259200)
        observation=dict(id='profit',at=11,after_cost_return_bps=2500,net_exit_proceeds=125,exit_liquidity_valid=True)
        a=monitor(book=self.book,sleeve=self.sleeve,identity='run:one',observation=observation,policy=policy,adapter=self.adapter)
        self.assertEqual(a['quantity'],100);self.reopen()
        p=self.book._load('run:one');self.assertEqual((p['tokens'],p['basis'],p['realized']),(300,75,7))
        self.assertTrue(restore_risk(self.book,'run:one')['realization_taken'])
        self.assertEqual(monitor(book=self.book,sleeve=self.sleeve,identity='run:one',observation=observation,policy=policy,adapter=self.adapter)['action'],'hold')
        self.adapter.at=12;self.adapter.proceeds=90
        observation=dict(id='stop',at=12,after_cost_return_bps=-1200,net_exit_proceeds=66,exit_liquidity_valid=True)
        monitor(book=self.book,sleeve=self.sleeve,identity='run:one',observation=observation,policy=policy,adapter=self.adapter)
        self.reopen();self.assertEqual(self.book._load('run:one')['realized'],22)
        self.assertEqual(self.sleeve.reconcile()['available'],1022)

    def test_same_regime_block_survives_restart(self):
        self.fill();self.book.transition('run:one','settled',11,amount=100,tokens=400)
        p=self.book._load('run:one')
        from certification.journal import digest
        self.sleeve.release('run:one',pnl=0,at=11,terminal_hash=digest(p),native_verified=True)
        self.reopen();self.sleeve.observe('mint',strategy='survivor',at=4000,state='qualified',evidence={'new':True},regime=self.regime)
        with self.assertRaisesRegex(ValueError,'same_survivor_regime'):
            self.sleeve.reserve('run:two',strategy='survivor',amount=100,at=4000,candidate='mint',generation=2,regime=dict(self.regime,at=4000))

    def test_unavailable_exit_preserves_full_exit_intent_after_restart(self):
        self.fill();self.adapter.at=11;self.adapter.quote_available=False
        policy=dict(hard_stop_bps=-1000,first_profit_bps=2000,first_sell_bps=2500,
            trail_bps=1200,tight_arm_bps=4000,tight_trail_bps=1000,soft_confirmations=2,maximum_hold_seconds=259200)
        observation=dict(id='stop',at=11,after_cost_return_bps=-1000,exit_liquidity_valid=True)
        self.assertEqual(monitor(book=self.book,sleeve=self.sleeve,identity='run:one',observation=observation,policy=policy,adapter=self.adapter)['action'],'exit_pending')
        self.reopen();self.adapter.at=12;self.adapter.quote_available=True;self.adapter.proceeds=100
        observation=dict(id='rebound',at=12,after_cost_return_bps=100,exit_liquidity_valid=True)
        action=monitor(book=self.book,sleeve=self.sleeve,identity='run:one',observation=observation,policy=policy,adapter=self.adapter)
        self.assertEqual(action['reason'],'hard_stop')
        self.assertEqual(self.book._load('run:one')['status'],'settled')

    @unittest.skipUnless(hasattr(__import__('os'),'fork'),'requires Linux process crash')
    def test_process_death_after_validation_reacquires_all_fresh_inputs(self):
        import os,signal
        pid=os.fork()
        if pid==0:
            self.adapter.validate_current=lambda *a:os.kill(os.getpid(),signal.SIGKILL)
            self.fill();os._exit(99)
        _,status=os.waitpid(pid,0)
        self.assertEqual(os.WTERMSIG(status),signal.SIGKILL)
        self.reopen();self.assertEqual(self.book._load('run:one')['status'],'reserved')
        self.assertEqual(self.fill()['status'],'filled')
        self.assertEqual(self.adapter.calls,['state','quote','demand','validate'])

    @unittest.skipUnless(hasattr(__import__('os'),'fork'),'requires Linux process crash')
    def test_native_fill_survives_process_death_before_sleeve_ack(self):
        import os,signal
        pid=os.fork()
        if pid==0:
            original=self.book.transition
            def crash(*a,**kw):
                original(*a,**kw)
                if a[1]=='filled':os.kill(os.getpid(),signal.SIGKILL)
            self.book.transition=crash;self.fill();os._exit(99)
        _,status=os.waitpid(pid,0)
        self.assertEqual(os.WTERMSIG(status),signal.SIGKILL)
        self.reopen();self.assertEqual(self.book._load('run:one')['status'],'open')
        self.assertEqual(self.sleeve.get('run:one')['status'],'reserved')
        self.assertEqual(self.sleeve.reconcile()['reserved'],100)
        self.assertEqual(self.fill()['status'],'already_committed')
        self.assertEqual(self.adapter.calls,[])

    def test_pons_below_sixty_percent_cancels(self):
        self.adapter.breadth=11
        with self.assertRaisesRegex(ValueError,'breadth_retention'):self.fill(6000)
        self.assertEqual(self.sleeve.reconcile()['available'],1000)

    def test_pons_twenty_percent_realization_exact_accounting(self):
        self.fill(6000);self.adapter.at=11;self.adapter.proceeds=30
        from certification.tests.test_survivor_risk_boundaries import POLICIES
        observation=dict(id='profit',at=11,after_cost_return_bps=2000,net_exit_proceeds=120,exit_liquidity_valid=True)
        result=monitor(book=self.book,sleeve=self.sleeve,identity='run:one',observation=observation,
                       policy=POLICIES['pons'],adapter=self.adapter)
        self.assertEqual(result['quantity'],100);self.reopen()
        p=self.book._load('run:one');self.assertEqual((p['tokens'],p['basis'],p['realized']),(300,75,5))
        self.assertTrue(restore_risk(self.book,'run:one')['realization_taken'])
