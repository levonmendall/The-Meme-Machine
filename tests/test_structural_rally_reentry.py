"""Deterministic structural-rally re-entry and durable sleeve boundary regressions.

All market paths here are constructed fixtures, not observed profitability.
No RPC, signing, funds or PAPER process is accessed by these tests.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from meme_machine.runtime.rally_cycles import (
    _cycle, verified_cycle, pump_cycle, pons_cycle,
    legacy_new_regime, structural_new_regime, shadow_comparison, with_shadow_gate,
)
from meme_machine.runtime.survivor_risk import new_regime
from meme_machine.runtime.sleeve_reservations import SleeveReservations


def cycle(n, *, family='pons_survivor', asset='token'):
    origin=n*200
    if family=='pons_survivor':
        return _cycle(family,asset,peak_at=origin+10,base_start_at=origin+20,
            reset_at=origin+30,base_end_at=origin+50,breakout_at=origin+70,
            peak_price='200',reset_price='150',base_low='150',base_high='180',
            breakout_price='186')
    return _cycle(family,asset,peak_at=origin+10,reset_at=origin+20,
        base_start_at=origin+30,base_end_at=origin+50,breakout_at=origin+70,
        peak_price='200',reset_price='150',base_low='152',base_high='180',
        breakout_price='186')


def regime(n,*,family='pons_survivor',asset='token',buyer=1):
    proof=cycle(n,family=family,asset=asset)
    return dict(at=proof['breakout_at'],cycle=proof,
        high_reset_cycle=1200,base_id=['150','180'],
        buyer_population=['a',str(buyer)],independent_demand=5+buyer,
        flow_regime=buyer%2)


class StructuralCycleTests(unittest.TestCase):
    def test_explicit_peak_reset_base_breakout_for_both_survivors(self):
        for family in ('pump_survivor','pons_survivor'):
            with self.subTest(family=family):
                for n in (0,1,2):
                    c=cycle(n,family=family)
                    self.assertTrue(verified_cycle(c))
                    self.assertEqual(c['schema'],'survivor-structural-rally-cycle-v1')
                    self.assertTrue(c['completed'])
                    self.assertLess(c['peak_at'],c['reset_at'])
                    self.assertLess(c['base_end_at'],c['breakout_at'])
                    self.assertTrue(c['source'].startswith('authenticated_'))

    def test_new_rally_has_no_artificial_minimum_delay(self):
        for family in ('pump_survivor','pons_survivor'):
            first=regime(0,family=family)
            second=regime(1,family=family)
            # A new structural cycle can complete within an hour of the first.
            self.assertLess(second['at']-first['at'],3600)
            self.assertFalse(legacy_new_regime(first,second))
            self.assertTrue(structural_new_regime(first,second))
            self.assertTrue(new_regime(first,second))

    def test_changed_buyer_numbers_do_not_authorize_same_rally(self):
        for family in ('pump_survivor','pons_survivor'):
            first=regime(0,family=family)
            later=deepcopy(first)
            later.update(at=first['at']+7200,buyer_population=['totally','different'],
                         independent_demand=30,flow_regime=99)
            later['cycle']['breakout_at']=later['at']
            # A new authenticated breakout observation may keep the same cycle ID;
            # mutable buyer metrics and elapsed time do not make a new cycle.
            # A later, separately authenticated quote has the same peak/reset ID.
            refreshed=_cycle(family,'token',peak_at=first['cycle']['peak_at'],
                reset_at=first['cycle']['reset_at'],
                base_start_at=first['cycle']['base_start_at'],
                base_end_at=first['cycle']['base_end_at'],
                breakout_at=later['at'],peak_price='200',reset_price='150',
                base_low=first['cycle']['base_low'],base_high='180',breakout_price='186')
            self.assertEqual(refreshed['identity'],first['cycle']['identity'])
            later['cycle']=refreshed
            self.assertTrue(legacy_new_regime(first,later))
            self.assertFalse(structural_new_regime(first,later))

    def test_third_cycle_compares_as_new_even_when_numeric_metrics_repeat_first(self):
        first=regime(0,buyer=1)
        second=regime(1,buyer=2)
        third=regime(2,buyer=1)
        self.assertTrue(structural_new_regime(first,second))
        self.assertTrue(structural_new_regime(first,third))
        self.assertTrue(structural_new_regime(second,third))
        self.assertFalse(legacy_new_regime(first,third))
        self.assertEqual(third['high_reset_cycle'],first['high_reset_cycle'])
        self.assertEqual(third['base_id'],first['base_id'])

    def test_missing_corrupted_or_backdated_cycles_fail_closed(self):
        first=regime(0)
        nxt=regime(1)
        for changed in (dict(nxt,cycle=None),dict(nxt,cycle={}),
                        dict(nxt,cycle=dict(nxt['cycle'],identity='tampered')),
                        dict(nxt,cycle=dict(nxt['cycle'],reset_at=0)),
                        dict(nxt,at=first['at'])):
            self.assertFalse(structural_new_regime(first,changed),changed)
        forged=deepcopy(nxt)
        forged['cycle']['asset']='other'
        self.assertFalse(structural_new_regime(first,forged))
        same=deepcopy(nxt)
        same['cycle']['peak_at']=first['at']
        self.assertFalse(structural_new_regime(first,same))

    def test_legacy_position_recovery_never_invents_prior_cycle(self):
        old=dict(at=100,high_reset_cycle=1200,base_id=['a','b'])
        newer=regime(1)
        self.assertTrue(structural_new_regime(old,newer))
        self.assertFalse(structural_new_regime(dict(old,at=newer['cycle']['peak_at']),newer))
        self.assertFalse(structural_new_regime(dict(old,cycle={'unverified':'old'}),newer))

    def test_real_policy_evaluator_features_build_valid_cycles(self):
        from meme_machine.lanes.pump.pumpswap_survivor import evaluate_entry as pump_evaluate
        from meme_machine.lanes.pons.pons_postgrad_survivor import evaluate_entry as pons_evaluate
        from tests.lanes.pump.test_pumpswap_survivor import facts as pump_facts
        from tests.lanes.pons.test_pons_postgrad_survivor import facts as pons_facts
        for family,fn,fixture,make in (
            ('pump',pump_evaluate,pump_facts,pump_cycle),
            ('pons',pons_evaluate,pons_facts,pons_cycle)):
            with self.subTest(family=family):
                sample=fixture()
                decision=fn(sample)
                self.assertTrue(decision['candidate'],decision['all_rejections'])
                proof=make('token',decision['features'],at=sample['now'])
                self.assertIsNotNone(proof,decision['features'])
                self.assertTrue(verified_cycle(proof))
                self.assertEqual(proof['breakout_at'],sample['now'])

    def test_old_survivor_policy_hashes_are_exact_recovery_only(self):
        from meme_machine.runtime.policy_compatibility import known_hash,compatible_identity,active_hash
        from meme_machine.paper_policy_revision import SUPERSEDED_ACTIVE_SURVIVOR_HASHES
        for family in ('pump_survivor','pons_survivor'):
            old=SUPERSEDED_ACTIVE_SURVIVOR_HASHES[family]
            new=active_hash(family)
            self.assertNotEqual(new,old)
            self.assertTrue(known_hash(family,old))
            self.assertTrue(compatible_identity({'policy_hash':old},{'policy_hash':new},regime=family))
            self.assertFalse(compatible_identity({'policy_hash':'unrecognized'},
                {'policy_hash':new},regime=family))
        for current in ('pump_current','pons_current'):
            h=active_hash(current)
            self.assertTrue(compatible_identity({'policy_hash':h},{'policy_hash':h},regime=current))


    def test_flat_existing_opportunity_access_history_selects_new_policy(self):
        from meme_machine.runtime.survivor_history import History
        from meme_machine.runtime.policy_compatibility import active_hash
        from meme_machine.paper_policy_revision import SUPERSEDED_ACTIVE_SURVIVOR_HASHES
        with tempfile.TemporaryDirectory() as directory:
            for family in ('pump_survivor','pons_survivor'):
                with self.subTest(family=family):
                    path=Path(directory)/(family+'.sqlite')
                    old=SUPERSEDED_ACTIVE_SURVIVOR_HASHES[family]
                    new=active_hash(family)
                    history=History(path,policy=old)
                    history.graduate('token',dict(at=0,identity='native-graduation'))
                    history.append('token',through=100,events=[],points=[(0,'100'),(100,'110')],complete=True)
                    original=history.facts('token',100)[0]
                    history.close()
                    history=History(path,policy=new)
                    self.assertEqual(history.get_meta('policy'),new)
                    self.assertEqual(history.facts('token',100)[0],original)
                    self.assertEqual(history.get_meta('previous_policy:'+old)['revision'],
                                     'paper-opportunity-access-v1')
                    history.close()

    def test_open_existing_opportunity_access_history_refuses_switch(self):
        from meme_machine.runtime.survivor_history import History
        from meme_machine.runtime.policy_compatibility import active_hash
        from meme_machine.paper_policy_revision import SUPERSEDED_ACTIVE_SURVIVOR_HASHES
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'blocked.sqlite'
            history=History(path,policy=SUPERSEDED_ACTIVE_SURVIVOR_HASHES['pump_survivor'])
            row=history.graduate('token',dict(at=0,identity='native'))
            row['position']='unresolved-existing-trade'
            row['state']='runner'
            history.save(row)
            history.close()
            with self.assertRaisesRegex(ValueError,'transition_unresolved_survivor_history'):
                History(path,policy=active_hash('pump_survivor'))

    def test_flat_sleeve_can_select_only_exact_known_prior_survivor_hashes(self):
        from meme_machine.paper_policy_revision import SUPERSEDED_ACTIVE_SURVIVOR_HASHES
        from meme_machine.runtime.directional_sleeve import policies
        with tempfile.TemporaryDirectory() as directory:
            for family in ('pump','pons'):
                with self.subTest(family=family):
                    path=Path(directory)/(family+'.sqlite')
                    requested=policies(family)
                    original={strategy:(SUPERSEDED_ACTIVE_SURVIVOR_HASHES[family+'_survivor']
                        if 'survivor' in strategy else active)
                        for strategy,active in requested.items()}
                    base=dict(lane=family,capital=1000,cohort='existing')
                    sleeve=SleeveReservations(path,policies=original,**base)
                    sleeve.close()
                    sleeve=SleeveReservations(path,policies=requested,**base)
                    self.assertEqual(sleeve.identity['policies'],original)
                    self.assertEqual(sleeve.decision_policies,requested)
                    self.assertEqual(sleeve.reconcile()['available'],1000)
                    sleeve.close()


    def test_existing_decision_checkpoint_second_transition_preserves_original(self):
        """Current live epochs can have already selected opportunity-access v1."""
        from meme_machine.runtime.policy_compatibility import (
            active_hash,selection,SELECTION_KEY,SELECTION_NAMESPACE,selection_successor,
            save_runtime_selection,runtime_selection,regime_for)
        from meme_machine.paper_policy_revision import previous_hash,SUPERSEDED_ACTIVE_SURVIVOR_HASHES
        from meme_machine.runtime.directional_sleeve import policies
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.survivor_history import History
        from meme_machine.runtime.journal import canonical,digest
        from meme_machine.lanes.pump.pumpswap_survivor import STRATEGY_ID as PUMP_STRATEGY
        from meme_machine.lanes.pons.pons_postgrad_survivor import STRATEGY_VERSION as PONS_STRATEGY
        import json
        with tempfile.TemporaryDirectory() as directory:
            for family in ('pump','pons'):
                with self.subTest(family=family):
                    regime=family+'_survivor'
                    selected=SUPERSEDED_ACTIVE_SURVIVOR_HASHES[regime]
                    newest=active_hash(regime)
                    financial=previous_hash(regime)
                    strategy=PUMP_STRATEGY if family=='pump' else PONS_STRATEGY
                    book_path=Path(directory)/(family+'-paper.sqlite')
                    native=PaperBook(book_path,run_id='old-run',lane=strategy,
                                     policy_hash=financial,initial=1000)
                    identity=dict(native.identity)
                    initial=selection(identity,dict(identity,policy_hash=selected))
                    old_money=native.reconcile()
                    save_runtime_selection(native.db,initial)
                    native.close()
                    successor=selection(identity,dict(identity,policy_hash=newest))
                    self.assertTrue(selection_successor(initial,successor))
                    native=PaperBook(book_path,run_id='old-run',lane=strategy,
                                     policy_hash=newest,initial=1000)
                    self.assertEqual(native.identity,identity)
                    self.assertEqual(native.decision_policy_hash,newest)
                    self.assertEqual(native.reconcile(),old_money)
                    self.assertTrue(runtime_selection(native.db,successor))
                    archived=native.db.execute(
                        'SELECT body FROM runtime_state WHERE identity=? AND key=?',
                        (SELECTION_NAMESPACE,SELECTION_KEY+':previous:'+digest(initial))).fetchone()
                    self.assertIsNotNone(archived)
                    self.assertEqual(json.loads(archived[0]),initial)
                    native.close()
                    # A separate preserved strategy-history projection has
                    # chained decision identities, not a rewritten genesis.
                    history_path=Path(directory)/(family+'-history.sqlite')
                    history=History(history_path,policy=selected)
                    history.graduate('token',dict(at=0,identity='verified-grad'))
                    history.append('token',through=100,events=[],
                        points=[(0,'100'),(100,'110')],complete=True)
                    history_first=selection(dict(policy_hash=financial),dict(policy_hash=selected))
                    history.set_meta(SELECTION_KEY,history_first)
                    raw=history.facts('token',100)
                    history.close()
                    history=History(history_path,policy=newest)
                    self.assertEqual(history.get_meta(SELECTION_KEY),
                        selection(dict(policy_hash=selected),dict(policy_hash=newest)))
                    self.assertEqual(history.get_meta('previous_policy_selection:'+digest(history_first)),history_first)
                    self.assertEqual(history.facts('token',100),raw)
                    history.close()

                    path=Path(directory)/(family+'-sleeve.sqlite')
                    strategy_new=policies(family)
                    start={name:previous_hash(regime_for(name)) for name in strategy_new}
                    first_strategy={name:(selected if 'survivor' in name else active_hash(regime_for(name)))
                        for name in strategy_new}
                    args=dict(lane=family,capital=1000,cohort='old')
                    sleeve=SleeveReservations(path,policies=start,**args)
                    stored=dict(sleeve.identity)
                    old_policy_selection=selection(stored,dict(stored,policies=first_strategy))
                    sleeve.db.execute('INSERT OR REPLACE INTO opportunity_meta_v1 VALUES(?,?)',
                        (SELECTION_KEY,canonical(dict(old_policy_selection,checksum=digest(old_policy_selection)))))
                    sleeve.close()
                    sleeve=SleeveReservations(path,policies=strategy_new,**args)
                    self.assertEqual(sleeve.identity,stored)
                    self.assertEqual(sleeve.decision_policies,strategy_new)
                    self.assertEqual(sleeve.reconcile()['available'],1000)
                    saved=json.loads(sleeve.db.execute(
                        'SELECT value FROM opportunity_meta_v1 WHERE key=?',(SELECTION_KEY,)).fetchone()[0])
                    self.assertEqual(saved['decision_identity']['policies'],strategy_new)
                    archive=json.loads(sleeve.db.execute(
                        'SELECT value FROM opportunity_meta_v1 WHERE key=?',
                        (SELECTION_KEY+':previous:'+digest(old_policy_selection),)).fetchone()[0])
                    checksum=archive.pop('checksum')
                    self.assertEqual(checksum,digest(archive))
                    self.assertEqual(archive,old_policy_selection)
                    sleeve.close()

    def test_existing_selection_cannot_cross_unsettled_reservation(self):
        from meme_machine.runtime.policy_compatibility import (
            active_hash,selection,regime_for,SELECTION_KEY)
        from meme_machine.paper_policy_revision import previous_hash,SUPERSEDED_ACTIVE_SURVIVOR_HASHES
        from meme_machine.runtime.directional_sleeve import policies
        from meme_machine.runtime.journal import canonical,digest
        with tempfile.TemporaryDirectory() as directory:
            family='pump';path=Path(directory)/'blocked.sqlite'
            newest=policies(family)
            financial={name:previous_hash(regime_for(name)) for name in newest}
            previous={name:(SUPERSEDED_ACTIVE_SURVIVOR_HASHES['pump_survivor']
                if 'survivor' in name else active_hash(regime_for(name))) for name in newest}
            args=dict(lane=family,capital=1000,cohort='old')
            sleeve=SleeveReservations(path,policies=financial,**args)
            prior=selection(dict(sleeve.identity),dict(sleeve.identity,policies=previous))
            sleeve.db.execute('INSERT OR REPLACE INTO opportunity_meta_v1 VALUES(?,?)',
                (SELECTION_KEY,canonical(dict(prior,checksum=digest(prior)))))
            strategy=next(name for name in newest if 'survivor' in name)
            sleeve.reserve('open-unresolved',strategy=strategy,amount=100,at=1)
            sleeve.close()
            with self.assertRaisesRegex(ValueError,'transition_unresolved_sleeve'):
                SleeveReservations(path,policies=newest,**args)
            sleeve=SleeveReservations(path,policies=financial,**args)
            self.assertEqual(sleeve.get('open-unresolved')['held'],100)
            self.assertEqual(sleeve.reconcile()['available'],900)
            saved=sleeve.db.execute('SELECT value FROM opportunity_meta_v1 WHERE key=?',(SELECTION_KEY,)).fetchone()[0]
            self.assertEqual(saved,canonical(dict(prior,checksum=digest(prior))))
            sleeve.close()



class DurableSleeveRallyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'survivor.sqlite'
        self.kw=dict(lane='pons',capital=1000,
            policies={'current':'current-hash','survivor':'survivor-hash'},cohort='test')
        self.sleeve=SleeveReservations(self.path,**self.kw)
        self.addCleanup(lambda:self.sleeve.close())

    def observe(self,r):
        d=dict(candidate=True,all_rejections=[],stage='qualified',proposed_quote_amount=100)
        d=with_shadow_gate(d,self.sleeve,strategy='survivor',candidate='token',regime=r)
        row=self.sleeve.observe('token',strategy='survivor',at=r['at'],
            state='qualified' if d['candidate'] else d['stage'],evidence=d,regime=r)
        return row,d

    def reserve_settle(self,name,r,generation,*,pnl=0):
        self.sleeve.reserve(name,strategy='survivor',amount=100,at=r['at'],
            candidate='token',generation=generation,regime=r)
        with self.sleeve.commit_fence(name):
            pass
        self.sleeve.release(name,pnl=pnl,at=r['at']+1,
            terminal_hash='verified-native-'+name,native_verified=True)
        self.assertEqual(self.sleeve.get(name)['status'],'settled')

    def test_first_second_third_settle_restart_and_conserve_capital(self):
        for n in (0,1,2):
            r=regime(n,buyer=n%2+1)
            row,d=self.observe(r)
            self.assertTrue(d['candidate'],d)
            self.assertTrue(d['reentry_shadow']['structural_allows'])
            self.assertEqual(d['reentry_shadow']['prior_filled_lifecycles'],n)
            if n>0:self.assertFalse(d['reentry_shadow']['legacy_allows'])
            self.reserve_settle('trade-'+str(n),r,row['generation'],pnl=(n+1)*10)
            self.assertEqual(self.sleeve.reconcile()['available'],1000+sum((i+1)*10 for i in range(n+1)))
            self.sleeve.close()
            self.sleeve=SleeveReservations(self.path,**self.kw)
        replay=self.sleeve.reconcile()
        self.assertTrue(replay['reconciled'])
        self.assertEqual((replay['positions'],replay['available'],replay['reserved']),(3,1060,0))

    def test_same_rally_blocks_before_reservation_and_persists_shadow(self):
        first=regime(0)
        row,d=self.observe(first)
        self.reserve_settle('first',first,row['generation'])
        repeat=deepcopy(first)
        repeat.update(at=4000,independent_demand=99,buyer_population=['different'])
        repeat['cycle']=_cycle('pons_survivor','token',peak_at=first['cycle']['peak_at'],
            base_start_at=first['cycle']['base_start_at'],
            reset_at=first['cycle']['reset_at'],base_end_at=first['cycle']['base_end_at'],
            breakout_at=4000,peak_price='200',reset_price='150',base_low='150',
            base_high='180',breakout_price='186')
        row,d=self.observe(repeat)
        self.assertFalse(d['candidate'])
        self.assertIn('distinct_structural_rally_required',d['all_rejections'])
        self.assertTrue(d['reentry_shadow']['legacy_allows'])
        self.assertFalse(d['reentry_shadow']['structural_allows'])
        self.assertTrue(self.sleeve.candidate('token')['evidence']['reentry_shadow']['disagreement'])
        with self.assertRaisesRegex(ValueError,'superseded_reservation|same_survivor_regime'):
            self.sleeve.reserve('rejected',strategy='survivor',amount=100,at=4000,
                candidate='token',generation=row['generation'],regime=repeat)
        self.assertEqual(self.sleeve.reconcile()['available'],1000)

    def test_native_writer_rechecks_cycle_after_shadow_pass(self):
        first=regime(0)
        row,_=self.observe(first)
        self.reserve_settle('first',first,row['generation'])
        new=regime(1)
        row,decision=self.observe(new)
        self.assertTrue(decision['candidate'])
        # Replacement of the proposal at funding time cannot bypass the writer.
        same=deepcopy(first)
        same['at']=new['at']
        same['cycle']=_cycle('pons_survivor','token',peak_at=first['cycle']['peak_at'],
            base_start_at=first['cycle']['base_start_at'],
            reset_at=first['cycle']['reset_at'],base_end_at=first['cycle']['base_end_at'],
            breakout_at=new['at'],peak_price='200',reset_price='150',
            base_low='150',base_high='180',breakout_price='186')
        with self.assertRaisesRegex(ValueError,'superseded_candidate_regime'):
            self.sleeve.reserve('bad',strategy='survivor',amount=100,at=new['at'],
                candidate='token',generation=row['generation'],regime=same)
        self.assertEqual(self.sleeve.reconcile()['reserved'],0)


if __name__=='__main__':
    unittest.main()
