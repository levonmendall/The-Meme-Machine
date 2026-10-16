"""Offline native Survivor trades through the real shared USD authority.

Synthetic canonical tapes/quotes prove execution and recovery, not profitability.
The lane suites separately exercise their authenticated provider adapters.
"""
from contextlib import nullcontext
from copy import deepcopy
from decimal import Decimal
import json
import os
import unittest
from unittest.mock import patch

from meme_machine.runtime.directional_continuation import native_sync
from meme_machine.runtime.directional_sleeve import open_sleeve, policies
from meme_machine.runtime.journal import digest
from meme_machine.runtime.rally_cycle import build_cycle
from meme_machine.runtime.survivor_commit import commit, monitor, restore_risk
from meme_machine.runtime.survivor_paper_book import PaperBook
from tests import test_pump_pons_capital_preparation as native_fixtures
from tests.test_shared_portfolio_epoch import shared_risk_candidate


class TapeAdapter:
    def __init__(self, at, facts, qualify):
        self.at,self.facts,self.qualify=at,facts,qualify
        self.loss_sizes=[];self.proceeds=0;self.quote_unavailable=False

    def now(self):return self.at
    def fresh_state(self,candidate):return dict(candidate=candidate,at=self.at)
    def fresh_quotes(self,state,budget):return self
    def loss(self,size):self.loss_sizes.append(size);return 100
    def entry(self,size):return dict(cost=size,quantity=size,gas=0,at=self.at)
    def reconstruct(self,state,quotes):return self.facts
    def turnover_cap(self,facts,decision):return 50_000
    def generation_fence(self,candidate,generation):return nullcontext()
    def validate_current(self,state,execution,now):
        if state['at']!=now or execution['at']!=now:raise ValueError('offline_stale_quote')
    def exit_quote(self,quantity):
        return None if self.quote_unavailable else dict(net_proceeds=self.proceeds,quantity=quantity,at=self.at)
    def validate_exit(self,execution,quantity,now):
        if (execution['at'],execution['quantity'])!=(now,quantity):raise ValueError('offline_stale_exit')


class FundedRallyLifecycles(unittest.TestCase):
    def qualification(self,family,at,graduation):
        if family=='pump':
            from tests.lanes.pump.test_pumpswap_survivor import facts
            from meme_machine.lanes.pump.pumpswap_survivor import evaluate_entry,POLICY
            f=facts();shift=at-f['now'];f['now']=at;f['graduation_at']=graduation
            f['base_end']+=shift
            for p in f['price_points']:p['at']+=shift
            for event in f['demand_events']:event['at']+=shift;event['quote']*=1000
            qualify=evaluate_entry;decision=qualify(f);features=decision['features']
            times={k:features[k] for k in ('peak_at','reset_at','base_start','base_end','breakout_at')}
            base_seconds=POLICY['base_seconds'];exit_policy=POLICY['exits']
        else:
            from tests.lanes.pons.test_pons_postgrad_survivor import facts
            from meme_machine.lanes.pons.pons_survivor_runtime import Runtime
            f=facts();shift=at-f['now'];f['now']=at;f['graduation_at']=graduation
            f['price_points']=[(t+shift,p) for t,p in f['price_points']]
            if f['price_points'][0][0]>graduation:
                f['price_points'].insert(0,(graduation,10000))
            f['capital_quote']=1_000_000
            qualify=object.__new__(Runtime).qualify;decision=qualify(f);features=decision['features']
            times={k:features[k] for k in ('peak_at','reset_at','base_start','base_end','breakout_at')}
            from meme_machine.lanes.pons.pons_postgrad_survivor import POLICY
            base_seconds=POLICY['reentry']['minimum_completed_base_seconds']
            # The adapter uses this exact normalization of the original exit policy.
            from meme_machine.lanes.pons.pons_survivor_runtime import risk_policy
            exit_policy=risk_policy()
        self.assertTrue(decision['candidate'],decision)
        cycle=build_cycle(candidate='synthetic-asset',venue=family,graduation=dict(at=graduation,
            canonical_event='synthetic-graduation'),**times,decision_at=at,
            evidence_id=digest(f),authoritative=True,complete=True,minimum_base_seconds=base_seconds)
        regime=dict(at=at,rally_cycle=cycle,buyer_population=['synthetic-demand'],independent_demand=6)
        return f,qualify,decision,regime,exit_policy

    def opened(self,family,*,historical=False):
        root,authority,now,plan=native_fixtures.RuntimeIntegrationTests.fixture(self,
            policy=None if historical else shared_risk_candidate(),new_epoch=not historical)
        folder=root/family;folder.mkdir(exist_ok=True)
        env=patch.dict(os.environ,MM_DIRECTIONAL_SLEEVE_DB=str(folder/'directional-sleeve.sqlite'))
        env.start();self.addCleanup(env.stop)
        strategy=next(s for s in policies(family) if 'survivor' in s)
        initial=125_000 if historical else 1_000_000
        sleeve=open_sleeve(family,initial);self.addCleanup(sleeve.close)
        book=PaperBook(folder/'paper.sqlite',run_id='rallies',lane=strategy,
            policy_hash=policies(family)[strategy],initial=initial);self.addCleanup(book.close)
        return authority,now,plan,sleeve,book,strategy

    def enter(self,family,at,graduation,sleeve,book,strategy,index,*,interrupt_fill=False,cancel=False):
        facts,qualify,decision,regime,policy=self.qualification(family,at,graduation)
        candidate=sleeve.observe('synthetic-asset',strategy=strategy,at=at,state='qualified',
            evidence=decision,regime=regime)
        regime=candidate['regime'];identity='rallies:'+str(index)
        adapter=TapeAdapter(at,facts,qualify)
        args=dict(book=book,sleeve=sleeve,identity=identity,candidate='synthetic-asset',
            generation=candidate['generation'],strategy=strategy,policy_hash=policies(family)[strategy],
            decision=decision,regime=regime,at=at,target=min(50000,sleeve.sizing_basis(500)['target']),
            minimum=1,retention_bps=5000,ordinary_limit=450,stress_limit=650,adapter=adapter,qualify=qualify)
        if cancel:
            with patch.object(adapter,'fresh_state',side_effect=ValueError('synthetic-evidence-unavailable')):
                with self.assertRaisesRegex(ValueError,'synthetic-evidence-unavailable'):commit(**args)
            self.assertEqual(book._load(identity)['status'],'cancelled')
            self.assertTrue(sleeve.get(identity)['cancelled'])
            return identity,adapter,regime,policy
        if interrupt_fill:
            client=book.portfolio.client;original=client.committed
            def lose_fill(native,**kw):
                pending=client.pending()
                if pending and pending[0][1].kind=='enter':raise RuntimeError('lost-filled-ack')
                return original(native,**kw)
            with patch.object(client,'committed',side_effect=lose_fill):
                with self.assertRaisesRegex(RuntimeError,'lost-filled-ack'):commit(**args)
            self.assertEqual(book._load(identity)['status'],'open')
            book.portfolio.recover();native_sync(book,sleeve,identity)
            self.assertEqual(commit(**args)['status'],'already_committed')
        else:self.assertEqual(commit(**args)['status'],'filled')
        self.assertIn(args['target'],adapter.loss_sizes);self.assertIn(args['target']*2,adapter.loss_sizes)
        self.assertTrue(book.replay()['verified']);sleeve.reconcile()
        return identity,adapter,regime,policy

    def exit(self,book,sleeve,identity,adapter,policy,at,*,partial=False,loss=False,lose_ack=False):
        if partial:
            adapter.at=at;position=book._load(identity);qty=position['tokens']//4
            adapter.proceeds=qty*130//100
            client=book.portfolio.client;original=client.committed
            def lose_partial(native,**kw):
                pending=client.pending()
                if pending and pending[0][1].kind=='harvest':raise RuntimeError('lost-partial-ack')
                return original(native,**kw)
            with patch.object(client,'committed',side_effect=lose_partial):
                with self.assertRaisesRegex(RuntimeError,'lost-partial-ack'):
                    monitor(book=book,sleeve=sleeve,identity=identity,policy=policy,adapter=adapter,
                        observation=dict(id='partial:'+identity,at=at,after_cost_return_bps=3000,
                            net_exit_proceeds=position['basis']*130//100,exit_liquidity_valid=True))
            book.portfolio.recover();native_sync(book,sleeve,identity)
            self.assertTrue(restore_risk(book,identity)['realization_taken']);at+=1
            self.assertEqual(book._load(identity)['tokens'],position['tokens']-qty)
        adapter.at=at;position=book._load(identity)
        adapter.proceeds=position['basis']*80//100 if loss else position['basis']
        observation=dict(id='terminal:'+identity,at=at,after_cost_return_bps=-2000 if loss else 0,
            net_exit_proceeds=adapter.proceeds,exit_liquidity_valid=True,creator_distribution=not partial and not loss)
        args=dict(book=book,sleeve=sleeve,identity=identity,policy=policy,adapter=adapter,observation=observation)
        adapter.quote_unavailable=True
        self.assertEqual(monitor(**args)['action'],'exit_pending')
        risk=restore_risk(book,identity)
        self.assertEqual(risk['lifecycle_clocks']['exit_intent_at'],at)
        self.assertEqual(book._load(identity)['status'],'open')
        adapter.quote_unavailable=False
        if lose_ack:
            client=book.portfolio.client;original=client.committed
            def lose_terminal(native,**kw):
                pending=client.pending()
                if pending and pending[0][1].kind=='settle':raise RuntimeError('lost-terminal-ack')
                return original(native,**kw)
            with patch.object(client,'committed',side_effect=lose_terminal):
                with self.assertRaisesRegex(RuntimeError,'lost-terminal-ack'):monitor(**args)
            self.assertEqual(book._load(identity)['status'],'settled')
            self.assertFalse((sleeve.reentry_verified(identity) or {}).get('obligations_clear'))
            book.portfolio.recover()
            final=book._load(identity)
            sleeve.release(identity,pnl=final['realized'],at=at,terminal_hash=digest(final),native_verified=True)
        else:self.assertEqual(monitor(**args)['action'],'full_exit')
        self.assertTrue(sleeve.reentry_verified(identity)['obligations_clear'])
        self.assertTrue(book.replay()['verified']);sleeve.reconcile()

    def test_three_distinct_funded_trades_partial_loss_and_ack_recovery_in_both_epochs(self):
        for family,historical,initial_loss in (('pump',False,False),('pons',False,False),
                ('pump',True,False),('pump',False,True),('pons',False,True)):
            with self.subTest(family=family,historical=historical,initial_loss=initial_loss):
                a,now,plan,sleeve,book,strategy=self.opened(family,historical=historical)
                before=deepcopy(a.ledger());graduation=now-(25000 if family=='pump' else 30*3600)
                cycles=[]
                for index in range(3):
                    at=now+index*12*3600
                    identity,adapter,regime,policy=self.enter(family,at,graduation,sleeve,book,strategy,index,
                        interrupt_fill=index==1)
                    cycles.append(regime['rally_cycle']['id'])
                    # Restart recovery from immutable native journal at every fill.
                    risk=restore_risk(book,identity)
                    self.assertEqual(risk['lifecycle_clocks']['entry_fill_at'],at)
                    self.exit(book,sleeve,identity,adapter,policy,at+(12*3600-600 if index<2 else 10),
                        partial=index==0 and not initial_loss,
                        loss=index==1 or index==0 and initial_loss,lose_ack=index==2)
                    a.verify_replay();snapshot=a.snapshot()
                    self.assertTrue(snapshot['capital']['conservation'])
                    self.assertEqual(Decimal(snapshot['capital']['deployed_basis']),0)
                    self.assertEqual(Decimal(snapshot['capital']['active_reservations']),0)
                    self.assertFalse(a.ledger()['runtime_pending'])
                    # Same cycle remains blocked even if demand counts/populations change.
                    repeated=dict(regime,at=at+12*3600,buyer_population=['changed'],independent_demand=99)
                    observed=sleeve.observe('synthetic-asset',strategy=strategy,at=repeated['at'],
                        state='qualified',evidence={'synthetic':True},regime=repeated)
                    with self.assertRaisesRegex(ValueError,'same_survivor_regime|traded_rally_cycle'):
                        sleeve.reserve('rallies:replayed-'+str(index),strategy=strategy,amount=1000,
                            at=repeated['at'],candidate='synthetic-asset',generation=observed['generation'],regime=observed['regime'])
                self.assertEqual(len(set(cycles)),3)
                final=a.ledger()
                self.assertEqual(final['epoch_id'],before['epoch_id'])
                self.assertEqual(final['inception_sha256'],before['inception_sha256'])
                self.assertEqual(final['contracts'],before['contracts'])
                self.assertEqual(final['initial_capital'],before['initial_capital'])
                self.assertEqual(Decimal(final['initial_capital']),500 if historical else 1000)
                self.assertEqual(book.reconcile()['settled'],3)
                self.assertEqual(sleeve.reconcile()['reserved'],0)
                report=sleeve.rally_report()['rows'][0]
                self.assertEqual(report['traded_count'],3)
                self.assertEqual([report['outcomes'][name]['terminal_count'] for name in ('first','second','third')],[1,1,1])
                self.assertTrue(all(report['outcomes'][name]['after_cost_return_bps'] is not None for name in ('first','second','third')))

    def test_cancelled_first_setup_preserves_capital_then_three_new_cycles_execute(self):
        for family in ('pump','pons'):
            with self.subTest(family=family):
                a,now,plan,sleeve,book,strategy=self.opened(family)
                graduation=now-(25000 if family=='pump' else 30*3600)
                self.enter(family,now,graduation,sleeve,book,strategy,0,cancel=True)
                self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),1000)
                self.assertEqual(sleeve.rally_report()['rows'][0]['traded_count'],0)
                for index in range(1,4):
                    at=now+index*8*3600
                    identity,adapter,regime,policy=self.enter(family,at,graduation,sleeve,book,strategy,index)
                    self.exit(book,sleeve,identity,adapter,policy,at+1)
                a.verify_replay()
                self.assertEqual(sleeve.rally_report()['rows'][0]['traded_count'],3)
                self.assertEqual(sleeve.rally_report()['rows'][0]['cancelled_count'],1)
                self.assertFalse(a.ledger()['runtime_pending'])
                self.assertEqual(Decimal(a.snapshot()['capital']['free_cash']),1000)

