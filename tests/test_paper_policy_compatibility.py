"""Revision selection preserves native finance and refuses old unresolved exposure."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.paper_policy_revision import ACTIVE_REVISION,previous_hash,previous_policies
from meme_machine.runtime.policy_compatibility import (active_hash,known_hash,require_flat_portfolio,
    SELECTION_KEY,assert_shared_transition)
from meme_machine.runtime.journal import digest


class PaperPolicyCompatibilityTests(unittest.TestCase):
    def setUp(self):
        scratch={'TMPDIR':os.environ['TMPDIR']} if 'TMPDIR' in os.environ else {}
        self.environment=patch.dict(os.environ,scratch,clear=True);self.environment.start()
        self.addCleanup(self.environment.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def book_case(self,regime):
        if regime=='pump_current':
            from meme_machine.lanes.pump.paper_accounting import PaperBook
            from meme_machine.lanes.pump.pump_acceleration_strategy import STRATEGY_ID
        else:
            from meme_machine.runtime.survivor_paper_book import PaperBook
            if regime=='pump_survivor':
                from meme_machine.lanes.pump.pumpswap_survivor import STRATEGY_ID
            else:
                from meme_machine.lanes.pons.pons_postgrad_survivor import STRATEGY_VERSION as STRATEGY_ID
        return PaperBook,dict(run_id='fixture',lane=STRATEGY_ID,initial=1000)

    def test_three_native_books_keep_original_genesis_and_accounting_on_revision_restart(self):
        for regime in ('pump_current','pump_survivor','pons_survivor'):
            with self.subTest(regime=regime):
                book_type,args=self.book_case(regime);path=self.root/(regime+'.sqlite')
                book=book_type(path,policy_hash=previous_hash(regime),**args)
                book.reserve('fixture:1',100,10,dict(policy_hash=previous_hash(regime)))
                book.transition('fixture:1','filled',11,amount=100,tokens=1000)
                book.transition('fixture:1','partial_harvest',12,amount=70,tokens=500)
                book.transition('fixture:1','settled',13,amount=80)
                old_genesis=book.db.execute('SELECT body FROM genesis').fetchone()[0]
                old_hashes=book.db.execute('SELECT hash FROM journal ORDER BY seq').fetchall()
                financial=book.reconcile();book.close()
                book=book_type(path,policy_hash=active_hash(regime),**args)
                self.assertEqual(book.db.execute('SELECT body FROM genesis').fetchone()[0],old_genesis)
                self.assertEqual(book.db.execute('SELECT hash FROM journal ORDER BY seq').fetchall(),old_hashes)
                self.assertEqual(book.reconcile(),financial)
                self.assertEqual(book.identity['policy_hash'],previous_hash(regime))
                self.assertEqual(book.decision_policy_hash,active_hash(regime))
                book.reserve('fixture:2',100,14,dict(policy_hash=active_hash(regime)))
                book.transition('fixture:2','filled',15,amount=100,tokens=1000)
                opened=book.reconcile();book.close()
                book=book_type(path,policy_hash=active_hash(regime),**args)
                self.assertEqual(book.reconcile(),opened)
                event=json.loads(book.db.execute('SELECT body FROM journal ORDER BY seq DESC LIMIT 1').fetchone()[0])
                self.assertEqual(event['policy_revision'],ACTIVE_REVISION)
                self.assertEqual(event['decision_policy_hash'],active_hash(regime))
                book.close()

    def test_old_reserved_or_open_position_blocks_native_selection(self):
        for regime in ('pump_current','pump_survivor','pons_survivor'):
            with self.subTest(regime=regime):
                book_type,args=self.book_case(regime);path=self.root/(regime+'.sqlite')
                book=book_type(path,policy_hash=previous_hash(regime),**args)
                book.reserve('fixture:1',100,10,{})
                if regime!='pump_survivor':book.transition('fixture:1','filled',11,amount=100,tokens=1000)
                genesis=book.db.execute('SELECT body FROM genesis').fetchone()[0];book.close()
                with self.assertRaisesRegex(ValueError,'paper_policy_transition_unresolved_pump'):
                    book_type(path,policy_hash=active_hash(regime),**args)
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute('SELECT body FROM genesis').fetchone()[0],genesis)
                    self.assertIsNone(db.execute('SELECT 1 FROM runtime_state WHERE key=?',(SELECTION_KEY,)).fetchone())

    def test_selection_checkpoint_cannot_be_rebound_to_another_financial_identity(self):
        book_type,args=self.book_case('pump_current');path=self.root/'book.sqlite'
        book=book_type(path,policy_hash=previous_hash('pump_current'),**args);book.close()
        book=book_type(path,policy_hash=active_hash('pump_current'),**args)
        row=book.db.execute('SELECT body FROM runtime_state WHERE key=?',(SELECTION_KEY,)).fetchone()
        value=json.loads(row[0]);value['decision_identity']['initial']=2000
        book.db.execute('UPDATE runtime_state SET body=?,hash=? WHERE key=?',
            (json.dumps(value,sort_keys=True,separators=(',',':')),digest(value),SELECTION_KEY));book.close()
        with self.assertRaisesRegex(ValueError,'selection_checkpoint_conflict'):
            book_type(path,policy_hash=active_hash('pump_current'),**args)

    def test_sleeve_keeps_financial_policies_and_distinguishes_new_decisions(self):
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.runtime.directional_sleeve import policies
        for lane in ('pump','pons'):
            with self.subTest(lane=lane):
                active=policies(lane)
                old={strategy:previous_hash(lane+('_survivor' if 'survivor' in strategy else '_current')) for strategy in active}
                args=dict(lane=lane,capital=1000,cohort='fixture');path=self.root/(lane+'.sleeve')
                sleeve=SleeveReservations(path,policies=old,**args);old_genesis=sleeve.identity.copy();before=sleeve.reconcile();sleeve.close()
                sleeve=SleeveReservations(path,policies=active,**args)
                self.assertEqual(sleeve.identity,old_genesis);self.assertEqual(sleeve.reconcile(),before)
                strategy=next(s for s in active if 'survivor' not in s)
                row=sleeve.reserve('new',strategy=strategy,amount=50,at=10)
                self.assertEqual(row['decision_policy_hash'],active[strategy]);self.assertEqual(row['policy_revision'],ACTIVE_REVISION)
                sleeve.close();sleeve=SleeveReservations(path,policies=active,**args)
                self.assertEqual(sleeve.get('new'),row);sleeve.close()

    def test_delayed_sleeve_release_blocks_transition_until_native_ack(self):
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.runtime.directional_sleeve import policies
        active=policies('pump');old={s:previous_hash('pump_survivor' if 'survivor' in s else 'pump_current') for s in active}
        args=dict(lane='pump',capital=1000,cohort='fixture');path=self.root/'sleeve'
        sleeve=SleeveReservations(path,policies=old,**args);strategy=next(s for s in active if 'survivor' not in s)
        sleeve.reserve('old',strategy=strategy,amount=50,at=10);sleeve.close()
        with self.assertRaisesRegex(ValueError,'transition_unresolved_sleeve'):
            SleeveReservations(path,policies=active,**args)
        sleeve=SleeveReservations(path,policies=old,**args)
        sleeve.release('old',pnl=0,at=11,terminal_hash='verified-native-cancel',native_verified=True,cancelled=True);sleeve.close()
        sleeve=SleeveReservations(path,policies=active,**args);self.assertEqual(sleeve.reconcile()['reserved'],0);sleeve.close()

    def history(self):
        from meme_machine.runtime.survivor_history import History
        history=History(self.root/'history.sqlite',policy=previous_hash('pump_survivor'))
        history.graduate('candidate',dict(at=0,identity='graduation'))
        history.append('candidate',through=100000,events=[],
            points=[(0,'100'),(60,'96'),(1000,'100'),(100000,'105')],complete=True)
        return history

    def test_reset_calculation_recomputes_from_retained_raw_without_relabeling_old_prefix(self):
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pump.pumpswap_survivor import reduce_reset_history
        old_policy=previous_policies()['pump_survivor']['policy'];history=self.history()
        history.calculation_facts('candidate',100000,
            reducer=lambda rows,prefix:reduce_reset_history(rows,prefix,policy=old_policy),policy=previous_hash('pump_survivor'))
        saved=history.get_meta('calculation_prefix:candidate');raw=history.facts('candidate',100000)[0];history.close()
        history=History(self.root/'history.sqlite',policy=active_hash('pump_survivor'))
        self.assertEqual(history.get_meta('previous_calculation_prefix:'+previous_hash('pump_survivor')+':candidate'),saved)
        self.assertIsNone(history.get_meta('calculation_prefix:candidate'))
        self.assertEqual(history.facts('candidate',100000)[0],raw)
        history.calculation_facts('candidate',100000,reducer=reduce_reset_history,policy=active_hash('pump_survivor'))
        current=history.get_meta('calculation_prefix:candidate')['state']
        self.assertEqual(current['policy_hash'],active_hash('pump_survivor'));self.assertEqual(current['reset'],'96')
        history.close()

    def test_retired_old_reset_detail_stays_explicitly_unavailable(self):
        from meme_machine.runtime.survivor_history import History
        from meme_machine.lanes.pump.pumpswap_survivor import reduce_reset_history
        old_policy=previous_policies()['pump_survivor']['policy'];history=self.history()
        history.compact_archived(dict(state_hash='old-preserved-authority'),
            reducer=lambda rows,prefix:reduce_reset_history(rows,prefix,policy=old_policy))
        archive=history.get_meta('archive_prefix:candidate');raw=history.facts('candidate',100000)[0];history.close()
        history=History(self.root/'history.sqlite',policy=active_hash('pump_survivor'))
        self.assertEqual(history.get('candidate')['policy_recomputation_blocker'],'reset_history_revision_detail_unavailable')
        self.assertEqual(history.get_meta('archive_prefix:candidate'),archive)
        history.compact_archived(dict(state_hash='new-preserved-authority'),reducer=reduce_reset_history)
        self.assertEqual(history.facts('candidate',100000)[0],raw)
        self.assertEqual(history.get_meta('archive_prefix:candidate'),archive);history.close()

    def test_history_pending_position_refuses_selection(self):
        from meme_machine.runtime.survivor_history import History
        history=self.history();row=history.get('candidate');row.update(position='pending',state='runner');history.save(row);history.close()
        with self.assertRaisesRegex(ValueError,'transition_unresolved_survivor_history'):
            History(self.root/'history.sqlite',policy=active_hash('pump_survivor'))

    def test_all_unacknowledged_portfolio_buckets_block_the_initial_transition(self):
        for bucket in ('positions','reservations','commitments','obligations','runtime_pending','runtime_inbox','pending_deliveries','pending_backing'):
            with self.subTest(bucket=bucket):
                state=dict(positions={},reservations={});state[bucket]=[{}] if bucket=='pending_deliveries' else {'pending':{}}
                with self.assertRaisesRegex(ValueError,'transition_unresolved_'+bucket):require_flat_portfolio(state)
        require_flat_portfolio(dict(positions={},reservations={}))
        with self.assertRaisesRegex(ValueError,'evidence_unavailable'):require_flat_portfolio({})
        for unavailable in ({},dict(positions=[],reservations={}),dict(positions={},reservations={},runtime_pending=None)):
            with self.assertRaisesRegex(ValueError,'evidence_unavailable'):
                assert_shared_transition(self.root,unavailable)

    def test_history_and_accounting_reject_an_unrecognized_policy(self):
        from meme_machine.runtime.survivor_history import History
        history=self.history();history.close()
        with self.assertRaisesRegex(ValueError,'history_policy_drift'):History(self.root/'history.sqlite',policy='unrecognized')
        for regime in ('pump_current','pump_survivor','pons_current','pons_survivor'):
            self.assertTrue(known_hash(regime,previous_hash(regime)));self.assertTrue(known_hash(regime,active_hash(regime)))
            self.assertFalse(known_hash(regime,'unrecognized'))

    def test_old_filled_reference_survives_revision_zero_fill_retry_and_prefix_restart(self):
        from copy import deepcopy
        from tests.lanes.pons import test_pons_current_recovery as fixtures
        from tests.lanes.pons import test_pons_partial_accounting as accounting
        from meme_machine.lanes.pons import pons_selective_capital as capital_module
        from meme_machine.lanes.pons.pons_reentry import refresh_reference,reentry_decision,recover_references
        fixture=fixtures.ReentryNativeReferenceTests();old=previous_hash('pons_current')
        with patch.object(fixtures,'POLICY_HASH',old),patch.object(accounting,'POLICY_HASH',old),patch.object(capital_module,'POLICY_HASH',old):
            original=fixture.vector();qualifier,life,_=fixture.trial(self.root,0,original,cancel=False,compact=True)
        result=dict(qualifiers=[qualifier],lifecycles=[life])
        state=refresh_reference(self.root,result,qualifier,life)
        self.assertEqual(state['last_filled_trade']['original_at'],100)
        self.assertEqual(state['last_filled_trade']['vector_id'],digest(original))
        retry=deepcopy(original);retry.update(policy_hash=active_hash('pons_current'),asof=120,evidence_available_at=121)
        retry['trajectory'].update(graduation_eta_seconds=90,progress_15s_bps=100)
        self.assertIsNone(reentry_decision(state,retry)[0])
        cancelled,cancel_life,_=fixture.trial(self.root,1,retry,compact=True)
        result['qualifiers'].append(cancelled);result['lifecycles'].append(cancel_life)
        refresh_reference(self.root,result,cancelled,cancel_life)
        restarted=recover_references(self.root,json.loads(json.dumps(result)))['m']
        self.assertEqual(restarted['last_filled_trade']['vector'],original)
        self.assertEqual(restarted['last_filled_trade']['original_at'],100)
        self.assertEqual(restarted['last_attempt']['outcome'],'never_filled_cancellation')
        new=deepcopy(original);new.update(policy_hash=active_hash('pons_current'),asof=140,evidence_available_at=141)
        self.assertEqual(reentry_decision(restarted,new)[0],'reentry_regime_not_reset')

    def test_old_pons_native_reservation_blocks_and_delayed_capital_ack_stays_unresolved(self):
        from tests.lanes.pons import test_pons_current_recovery as fixtures
        from tests.lanes.pons import test_pons_partial_accounting as accounting
        from meme_machine.lanes.pons import pons_selective_capital as capital_module
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper,STRATEGY_NAMESPACE,GENESIS_CATEGORY
        from meme_machine.lanes.pons.evidence import Store
        from contextlib import closing
        fixture=fixtures.ReentryNativeReferenceTests();old=previous_hash('pons_current')
        with patch.object(fixtures,'POLICY_HASH',old),patch.object(accounting,'POLICY_HASH',old),patch.object(capital_module,'POLICY_HASH',old):
            qualifier,life,guard=fixture.trial(self.root,0,fixture.vector(),ack=False)
        path=self.root/'trial-000.sqlite'
        with closing(Store(path)) as store:
            original=store.get(GENESIS_CATEGORY,STRATEGY_NAMESPACE)
            with self.assertRaisesRegex(ValueError,'transition_unresolved_capital'):
                SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=active_hash('pons_current'))
            self.assertEqual(store.get(GENESIS_CATEGORY,STRATEGY_NAMESPACE),original)
        with self.assertRaisesRegex(ValueError,'transition_unresolved_capital'):
            capital_module.CohortCapital(self.root/'pons-selective-cohort-capital.sqlite',1000)
        guard.settle(life['lifecycle_id'],life['final_position'],at=life['final_position']['last_at'])
        revised=capital_module.CohortCapital(self.root/'pons-selective-cohort-capital.sqlite',1000)
        self.assertEqual(revised.financial_policy_hash,old)
        self.assertEqual(revised.reconcile()['reserved'],0)
        with closing(Store(path)) as store:
            paper=SelectivePaper(store,STRATEGY_NAMESPACE,1000,delay=1,natural_policy_hash=active_hash('pons_current'))
            self.assertEqual(store.get(GENESIS_CATEGORY,STRATEGY_NAMESPACE),original)
            self.assertEqual(paper.financial_policy_hash,old)

    def test_old_pons_nomination_is_retained_but_requires_fresh_revision_qualification(self):
        from meme_machine.runtime.robinhood.pons import Broker
        from tests.lanes.pons.test_pons_candidate_plane import event
        old=Broker(self.root/'plane',previous_hash('pons_current'),clock=lambda:100)
        original=event();old.enqueue(original);key=old.identity(original)
        before=old.plane.get(key);old.close()
        revised=Broker(self.root/'plane',active_hash('pons_current'),clock=lambda:101)
        after=revised.plane.get(key)
        self.assertEqual(after['generation'],before['generation']+1)
        self.assertEqual(after['observed'],before['observed'])
        self.assertEqual(after['payload'],before['payload']);self.assertIsNone(after['result'])
        self.assertIsNone(after['completed']);self.assertIsNone(revised.pop())
        revised.enqueue(event(2));self.assertIsNotNone(revised.pop());revised.close()

    def retired_pons_watch_case(self, name, *, buy_count=2):
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.runtime.robinhood.plane import digest
        from meme_machine.lanes.pons.abi import topic
        from tests.lanes.pons.test_pons_candidate_plane import event
        path=self.root/name
        clock=[100.]
        old=Broker(path,previous_hash('pons_current'),clock=lambda:clock[0],
            source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')
        buy=dict(event(buy_count),topics=[topic('CurveBuy(address,address,uint256,uint256,uint256,uint256)')])
        for number in range(1,buy_count+1):old.enqueue(dict(event(number),topics=buy['topics']))
        key=old.identity(buy);work=old.pop()
        old.plane.finish(work['work'],state='freshness_deadline_censored',reason='fixture_incomplete')
        clock[0]+=86401
        old.plane.maintain()
        self.assertIsNone(old.plane.get(key))
        body,checksum=old.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
        watch=json.loads(body);self.assertEqual(digest(watch),checksum)
        old.close()
        sell=dict(event(buy_count+1),topics=[topic('CurveSell(address,address,uint256,uint256,uint256,uint256)')])
        return path,clock,key,buy,sell,watch,work

    def test_retired_pons_watch_renews_before_new_policy_sell_without_authorizing_entry(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.runtime.robinhood.plane import canonical,digest
        path,clock,key,buy,sell,watch,stale=self.retired_pons_watch_case('orphan-sell')
        with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as revised:
            self.assertTrue(revised.enqueue(sell,needs_work=False))
            row=revised.plane.get(key)
            saved,checksum=revised.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
            saved=json.loads(saved)
            self.assertEqual(checksum,digest(saved));self.assertEqual(saved['interpretation'],revised.policy)
            self.assertEqual(row['interpretation'],canonical(revised.policy))
            self.assertEqual(saved['generation'],row['generation'])
            self.assertGreater(row['generation'],watch['generation'])
            self.assertEqual(saved['first_observed_at'],watch['first_observed_at'])
            self.assertEqual(saved['last_buy_observed_at'],watch['last_buy_observed_at'])
            self.assertEqual(saved['event'],buy)
            self.assertEqual(saved['latest_id'],revised.observation_id(sell))
            self.assertFalse(row['pending']);self.assertIsNone(row['result']);self.assertIsNone(row['completed'])
            self.assertEqual(revised.rows,{})
            self.assertFalse(revised.plane.current(stale['work']))
            self.assertFalse(revised.plane.finish(stale['work'],result={'qualified':True}))

    def test_retired_pons_watch_recovers_the_already_committed_unqualified_sell_cut(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.runtime.robinhood.plane import canonical,digest
        path,clock,key,_,sell,watch,_=self.retired_pons_watch_case('orphan-committed-cut')
        with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as revised:
            # The failed executable committed Plane.observe before discovering
            # the old orphan watch. Retain precisely that crash/failure cut.
            # Exact pons.py SHA256 at executed 1fe5a6f6: the successor source
            # necessarily has a different adapter binding when it reopens.
            binding=dict(revised.policy,adapter_source='ad75892a39a0b6ca898f90a0f698e7eb80ad8c7928820286babc46f5b697028c')
            revised.plane.observe(key,'pons',revised.observation_id(sell),sell,ordering=(3,0,0),
                watermark=dict(block=3,hash=sell['blockHash'],log=0,finality='confirmed'),
                interpretation=binding,observed=clock[0],deadline=clock[0]+5,priority=4,needs_work=False)
        with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as resumed:
            row=resumed.plane.get(key)
            raw,checksum=resumed.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
            saved=json.loads(raw)
            self.assertEqual(checksum,digest(saved));self.assertEqual(saved['interpretation'],resumed.policy)
            self.assertEqual(row['interpretation'],canonical(resumed.policy))
            self.assertEqual(saved['generation'],row['generation'])
            self.assertGreater(row['generation'],watch['generation'])
            self.assertEqual(saved['first_observed_at'],watch['first_observed_at'])
            self.assertFalse(row['pending']);self.assertIsNone(row['result']);self.assertIsNone(row['completed'])
            self.assertEqual(resumed.rows,{})
            self.assertFalse(resumed.enqueue(sell,needs_work=False))

    def test_retired_pons_watch_rejects_incompatible_identity_before_new_observation(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.runtime.robinhood.plane import canonical,digest
        for field,value in (('chain',1),('source','other-provider'),('config','other-config'),('policy','unknown-policy')):
            with self.subTest(field=field):
                path,clock,key,_,sell,watch,_=self.retired_pons_watch_case('orphan-invalid-'+field)
                watch['interpretation'][field]=value
                with closing(sqlite3.connect(path)) as db:
                    db.execute('UPDATE pons_current_watch SET body=?,hash=? WHERE candidate=?',
                        (canonical(watch),digest(watch),key));db.commit()
                with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                        source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as revised:
                    before=revised.plane.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
                    self.assertFalse(revised.enqueue(sell,needs_work=False))
                    self.assertIsNone(revised.plane.get(key))
                    self.assertEqual(revised.plane.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],before)

    def test_retired_pons_watch_keeps_corruption_and_unresolved_transition_failures(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.runtime.robinhood.plane import canonical
        for condition in ('corrupt','unresolved'):
            with self.subTest(condition=condition):
                path,clock,key,_,sell,watch,_=self.retired_pons_watch_case('orphan-'+condition)
                if condition=='corrupt':
                    with closing(sqlite3.connect(path)) as db:
                        changed=dict(watch,first_observed_at=0)
                        db.execute('UPDATE pons_current_watch SET body=? WHERE candidate=?',(canonical(changed),key));db.commit()
                with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                        source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as revised:
                    with patch('meme_machine.runtime.policy_compatibility.require_external_flat',
                            side_effect=ValueError('paper_policy_transition_unresolved_obligations')):
                        expected='watch_corruption' if condition=='corrupt' else 'transition_unresolved_obligations'
                        with self.assertRaisesRegex(ValueError,expected):revised.enqueue(sell,needs_work=False)
                    self.assertIsNone(revised.plane.get(key))

    def test_recreated_pons_watch_does_not_adopt_a_pending_or_claimed_generation(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import Broker
        for condition in ('pending','claim','result','same-policy-pending','same-policy-claim','same-policy-result'):
            with self.subTest(condition=condition):
                path,clock,key,_,sell,_,_=self.retired_pons_watch_case('orphan-active-'+condition)
                with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                        source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as revised:
                    if condition.startswith('same-policy-'):
                        with revised.plane.transaction():self.assertTrue(revised._renew_retained_interpretation(key))
                    revised.plane.observe(key,'pons',revised.observation_id(sell),sell,ordering=(3,0,0),
                        watermark=dict(block=3,hash=sell['blockHash'],log=0,finality='confirmed'),
                        interpretation=revised.policy,observed=clock[0],deadline=clock[0]+5,priority=4,needs_work=False)
                    if condition.endswith('pending'):revised.plane.db.execute('UPDATE candidates SET pending=1 WHERE id=?',(key,))
                    elif condition.endswith('claim'):
                        revised.plane.db.execute("UPDATE candidates SET claim='live-claim',owner=?,claim_until=? WHERE id=?",
                            (revised.plane.owner,clock[0]+5,key))
                    else:revised.plane.db.execute("UPDATE candidates SET result='{}' WHERE id=?",(key,))
                with self.assertRaisesRegex(ValueError,'watch_(interpretation|generation)_changed'):
                    Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                        source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')

    def test_retired_pons_watch_recovers_same_interpretation_projection_crash_without_generation_rewind(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.runtime.robinhood.plane import canonical,digest
        for cut in ('after-renewal','same-policy-retirement'):
            with self.subTest(cut=cut):
                path,clock,key,buy,sell,watch,stale=self.retired_pons_watch_case('orphan-generation-'+cut)
                with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                        source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as revised:
                    # First commit is the existing policy-renewal boundary.
                    with revised.plane.transaction():self.assertTrue(revised._renew_retained_interpretation(key))
                    if cut=='same-policy-retirement':
                        self.assertTrue(revised.enqueue(sell,needs_work=False))
                        clock[0]+=86401;revised.plane.maintain()
                        self.assertIsNone(revised.plane.get(key))
                        raw,checksum=revised.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
                        watch=json.loads(raw);self.assertEqual(digest(watch),checksum)
                        from tests.lanes.pons.test_pons_candidate_plane import event
                        sell=dict(event(4),topics=sell['topics'])
                    # Crash after Plane.observe commits but before the final
                    # projection binds its generation above the retained watch.
                    block=int(sell['blockNumber'],16)
                    revised.plane.observe(key,'pons',revised.observation_id(sell),sell,ordering=(block,0,0),
                        watermark=dict(block=block,hash=sell['blockHash'],log=0,finality='confirmed'),
                        interpretation=revised.policy,observed=clock[0],deadline=clock[0]+5,priority=4,needs_work=False)
                with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                        source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as resumed:
                    row=resumed.plane.get(key)
                    raw,checksum=resumed.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
                    saved=json.loads(raw)
                    self.assertEqual(digest(saved),checksum);self.assertEqual(saved['interpretation'],resumed.policy)
                    self.assertEqual(saved['generation'],row['generation'])
                    self.assertGreater(row['generation'],watch['generation'])
                    self.assertEqual(saved['event'],buy)
                    self.assertEqual(saved['first_observed_at'],watch['first_observed_at'])
                    self.assertFalse(row['pending']);self.assertIsNone(row['result']);self.assertIsNone(row['completed'])
                    self.assertFalse(resumed.plane.finish(stale['work'],result={'qualified':True}))
                    self.assertEqual(resumed.rows,{})

    def test_retired_pons_watch_projection_crash_preserves_accepted_buy_and_original_deadline(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.runtime.robinhood.plane import digest
        from tests.lanes.pons.test_pons_candidate_plane import event
        for cut,buy_count in (('prior-adapter',2),('same-policy-one-buy',1)):
            with self.subTest(cut=cut):
                path,clock,key,_,_,watch,stale=self.retired_pons_watch_case('orphan-buy-'+cut,buy_count=buy_count)
                block=buy_count+1;fresh=dict(event(block),topics=watch['event']['topics'])
                observed=clock[0];deadline=observed+5
                with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                        source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as revised:
                    # Renewal commits, then the BUY is accepted before its watch
                    # projection. One retained BUY gives equal generation1 fences.
                    with revised.plane.transaction():self.assertTrue(revised._renew_retained_interpretation(key))
                    binding=revised.policy
                    if cut=='prior-adapter':
                        binding=dict(binding,adapter_source='ad75892a39a0b6ca898f90a0f698e7eb80ad8c7928820286babc46f5b697028c')
                        raw=revised.plane.db.execute('SELECT body FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()[0]
                        prior_watch=dict(json.loads(raw),interpretation=binding,volume_quality={'fixture_stale_adapter':True})
                        from meme_machine.runtime.robinhood.plane import canonical
                        with revised.plane.transaction():
                            revised.plane.db.execute('UPDATE pons_current_watch SET body=?,hash=? WHERE candidate=?',
                                (canonical(prior_watch),digest(prior_watch),key))
                    revised.plane.observe(key,'pons',revised.observation_id(fresh),fresh,ordering=(block,0,0),
                        watermark=dict(block=block,hash=fresh['blockHash'],log=0,finality='confirmed'),
                        interpretation=binding,observed=observed,deadline=deadline,priority=4,needs_work=True)
                clock[0]+=.25
                with closing(Broker(path,active_hash('pons_current'),clock=lambda:clock[0],
                        source='https://robinhood-mainnet.g.alchemy.com/v2/OFFLINE_WATCH',config='same-config')) as resumed:
                    row=resumed.plane.get(key)
                    raw,checksum=resumed.plane.db.execute('SELECT body,hash FROM pons_current_watch WHERE candidate=?',(key,)).fetchone()
                    saved=json.loads(raw)
                    self.assertEqual(digest(saved),checksum);self.assertEqual(saved['interpretation'],resumed.policy)
                    self.assertEqual(saved['generation'],row['generation'])
                    self.assertGreater(row['generation'],watch['generation'])
                    self.assertEqual(saved['event'],fresh);self.assertEqual(saved['last_buy_observed_at'],observed)
                    self.assertEqual(saved['first_observed_at'],watch['first_observed_at'])
                    if cut=='prior-adapter':self.assertNotIn('volume_quality',saved)
                    else:self.assertIsNone(saved.get('volume_quality'))
                    self.assertEqual((row['observed'],row['deadline'],row['queued']),(observed,deadline,observed))
                    self.assertTrue(row['pending']);self.assertIsNone(row['result']);self.assertIsNone(row['completed'])
                    self.assertEqual(row['state'],'discovered')
                    self.assertFalse(resumed.plane.finish(stale['work'],result={'qualified':True}))
                    self.assertEqual(list(resumed.committed()),[])
                    scheduled=resumed.pop()
                    self.assertIsNotNone(scheduled);self.assertEqual(scheduled['event'],fresh)
                    self.assertEqual(scheduled['deadline'],deadline)
                    self.assertFalse(resumed.plane.get(key).get('result'))

    def cohort_recovery_case(self,name,*,colocated=False):
        from meme_machine.runtime.robinhood.pons import Broker
        from meme_machine.lanes.pons import pons_selective_capital as capital_module
        from tests.lanes.pons.test_pons_candidate_plane import event
        lane=self.root/name/'lane';lane.mkdir(parents=True)
        path=lane/'candidate-evidence.sqlite' if colocated else self.root/name/'shared'/'canonical.candidates.sqlite'
        capital=lane/'pons-selective-cohort-capital.sqlite'
        with patch.object(capital_module,'POLICY_HASH',previous_hash('pons_current')):
            book=capital_module.CohortCapital(capital,1000)
        broker=Broker(path,previous_hash('pons_current'),clock=lambda:100)
        broker.enqueue(event())
        result=dict(policy_hash=previous_hash('pons_current'),rows=[dict(token='retained',observed_at=99)],
            qualifiers=[],lifecycles=[],candidate_plane_path=str(path),retained_cursor=123)
        saved=dict(result=result,cursor=123,phase='paused',owner='not-a-live-owner',checkpoint_at=100)
        broker.plane.checkpoint('pons_cohort',saved)
        population=[tuple(row) for row in broker.plane.db.execute('SELECT * FROM candidates')]
        broker.close()
        return path,capital,book,saved,population

    def test_cohort_recovery_separates_shared_evidence_from_original_lane_capital(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import recover_cohort
        from meme_machine.runtime.robinhood.plane import Plane
        from meme_machine.lanes.pons import BoundaryError
        path,capital,_,saved,population=self.cohort_recovery_case('separate')
        with closing(sqlite3.connect(capital)) as db:
            before={table:db.execute('SELECT * FROM '+table).fetchall() for table in
                ('capital_genesis','capital_positions','capital_journal','runtime_state')}
        # Retain the failing colocated inference as the regression control on
        # this exact fixture, then exercise the explicit native-authority fix.
        with self.assertRaisesRegex(BoundaryError,'cohort_evidence_unavailable'):
            recover_cohort(path,active_hash('pons_current'))
        with patch('meme_machine.runtime.policy_compatibility.require_external_flat') as external:
            recovered=recover_cohort(path,active_hash('pons_current'),capital_path=capital)
        external.assert_called_once_with()
        self.assertEqual(recovered['rows'],saved['result']['rows'])
        self.assertEqual(recovered['retained_cursor'],123)
        self.assertEqual(recovered['previous_decision_policy_hash'],previous_hash('pons_current'))
        self.assertEqual(recovered['policy_hash'],active_hash('pons_current'))
        self.assertFalse((path.parent/'pons-selective-cohort-capital.sqlite').exists())
        with closing(Plane(path)) as plane:
            self.assertEqual(plane.checkpoint_read('pons_cohort'),saved)
            self.assertEqual([tuple(row) for row in plane.db.execute('SELECT * FROM candidates')],population)
        with closing(sqlite3.connect(capital)) as db:
            self.assertEqual({table:db.execute('SELECT * FROM '+table).fetchall() for table in before},before)

    def test_cohort_run_forwards_native_authority_before_any_provider_or_worker_start(self):
        from meme_machine.lanes.pons import pons_selective_cohort as cohort
        path,capital,_,_,_=self.cohort_recovery_case('forward')
        class StopAtRecovery(Exception):pass
        cache=path.with_name('canonical.sqlite')
        # plane_path changes only the candidate namespace. The native capital
        # authority remains in the controller's lane directory.
        with patch.object(cohort,'ROOT',capital.parent),patch.dict(os.environ,{'MM_RPC_CACHE_DB':str(cache)}), \
                patch.object(cohort,'recover_cohort',side_effect=StopAtRecovery) as recover:
            with self.assertRaises(StopAtRecovery):cohort.run('https://provider.invalid',campaign=True)
        recover.assert_called_once_with(path,cohort.POLICY_HASH,capital_path=capital)

    def test_cohort_recovery_never_substitutes_plane_local_capital_for_explicit_authority(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import recover_cohort
        from meme_machine.lanes.pons import pons_selective_capital as capital_module
        from meme_machine.lanes.pons import BoundaryError
        for condition in ('missing','unresolved','corrupt'):
            with self.subTest(condition=condition):
                path,capital,book,saved,_=self.cohort_recovery_case(condition)
                with patch.object(capital_module,'POLICY_HASH',previous_hash('pons_current')):
                    capital_module.CohortCapital(path.parent/'pons-selective-cohort-capital.sqlite',1000)
                    if condition!='missing':book.reserve('old',100,at=100,decision_hash='decision',trial_path='retained-trial')
                if condition=='missing':capital.unlink()
                elif condition=='corrupt':
                    with closing(sqlite3.connect(capital)) as db:
                        db.execute("UPDATE capital_positions SET body='{}'");db.commit()
                error=(BoundaryError,'cohort_evidence_unavailable') if condition=='missing' else (
                    (ValueError,'transition_unresolved_capital') if condition=='unresolved' else
                    (BoundaryError,'selective_cohort_projection_mismatch'))
                with self.assertRaisesRegex(*error):
                    recover_cohort(path,active_hash('pons_current'),capital_path=capital)
                self.assertEqual(saved['result']['policy_hash'],previous_hash('pons_current'))

    def test_cohort_recovery_preserves_external_flat_guard_and_colocated_compatibility(self):
        from contextlib import closing
        from meme_machine.runtime.robinhood.pons import recover_cohort
        from meme_machine.runtime.robinhood.plane import Plane
        path,capital,_,saved,_=self.cohort_recovery_case('external')
        with patch('meme_machine.runtime.policy_compatibility.require_external_flat',
                side_effect=ValueError('paper_policy_transition_unresolved_obligations')):
            with self.assertRaisesRegex(ValueError,'transition_unresolved_obligations'):
                recover_cohort(path,active_hash('pons_current'),capital_path=capital)
        with closing(Plane(path)) as plane:self.assertEqual(plane.checkpoint_read('pons_cohort'),saved)
        path,_,_,_,_=self.cohort_recovery_case('colocated',colocated=True)
        recovered=recover_cohort(path,active_hash('pons_current'))
        self.assertEqual(recovered['policy_hash'],active_hash('pons_current'))

    def test_four_revised_native_requests_keep_original_shared_financial_contracts(self):
        from copy import deepcopy
        from decimal import Decimal
        from tests.test_pump_pons_capital_preparation import RuntimeIntegrationTests
        from tests.test_shared_portfolio_epoch import shared_risk_candidate
        from meme_machine.runtime.directional_sleeve import open_sleeve,policies
        from meme_machine.runtime.directional_continuation import native_sync
        from meme_machine.lanes.pump.paper_accounting import PaperBook
        active={family:policies(family) for family in ('pump','pons')}
        previous={family:{strategy:previous_hash(family+('_survivor' if 'survivor' in strategy else '_current'))
            for strategy in values} for family,values in active.items()}
        # Only fixture inception selects the original contracts. The actual
        # native request/fill paths below run with the revised default policies.
        with patch('meme_machine.runtime.directional_sleeve.policies',side_effect=lambda family:previous[family]):
            root,authority,now,_=RuntimeIntegrationTests.fixture(self,policy=shared_risk_candidate(),new_epoch=True)
        original=authority.ledger()
        contracts=deepcopy(original['contracts']);epoch=original['epoch_id'];inception=original['inception_sha256']
        books=[]
        for family in ('pump','pons'):
            (root/family).mkdir(exist_ok=True)
            with patch.dict(os.environ,{'MM_DIRECTIONAL_SLEEVE_DB':str(root/family/'directional-sleeve.sqlite')}):
                sleeve=open_sleeve(family,1_000_000);self.addCleanup(sleeve.close)
                for strategy,policy in policies(family).items():
                    regime=family+('_survivor' if 'survivor' in strategy else '_current')
                    path=root/family/(strategy+'.sqlite')
                    book=PaperBook(path,run_id='revised-native',lane=strategy,policy_hash=policy,initial=1_000_000)
                    self.addCleanup(book.close);identity='revised-native:'+strategy
                    sleeve.reserve(identity,strategy=strategy,amount=50_000,at=now,asset=identity,
                        funding_evidence=dict(qualified=True,policy_hash=policy))
                    book.reserve(identity,50_000,now,dict(qualified=True,policy_hash=policy))
                    book.transition(identity,'filled',now,amount=50_000,tokens=100,evidence=dict(execution={'gas':0}))
                    book.transition(identity,'mark',now,amount=50_000);native_sync(book,sleeve,identity)
                    self.assertTrue(book.replay()['verified']);self.assertEqual(book.reconcile()['basis'],50_000)
                    books.append((family,identity,regime,policy,book.reconcile()))
        final=authority.ledger()
        self.assertEqual(final['epoch_id'],epoch);self.assertEqual(final['inception_sha256'],inception)
        self.assertEqual(final['contracts'],contracts)
        self.assertEqual(Decimal(authority.snapshot()['capital']['free_cash']),800)
        self.assertEqual(authority.snapshot()['capital']['deployed_basis'],'200')
        for family,identity,regime,policy,_ in books:
            request_id=final['runtime_native_requests'][family+':'+identity]
            request=final['requests'][request_id]
            observation=final['observations'][regime+':'+request['value']['candidate_id']]
            self.assertEqual(request['status'],'CONSUMED')
            self.assertEqual(request['value']['native_requested_units'],50_000)
            self.assertEqual(observation['policy_hash'],previous_hash(regime))
            self.assertEqual(observation['evidence']['effective_decision_policy_hash'],policy)
            self.assertEqual(observation['evidence']['policy_revision'],ACTIVE_REVISION)
        authority.verify_replay()

    def test_actual_terminal_reader_accepts_known_previous_policy_only_for_selected_revision(self):
        from meme_machine.runtime.directional_accounting import terminal
        from meme_machine.runtime.directional_sleeve import policies
        from meme_machine.runtime.sleeve_reservations import SleeveReservations
        from meme_machine.runtime.survivor_history import History
        from meme_machine.runtime.survivor_paper_book import PaperBook
        active=policies('pump');old={s:previous_hash('pump_survivor' if 'survivor' in s else 'pump_current') for s in active}
        current_strategy=next(s for s in active if 'survivor' not in s)
        survivor_strategy=next(s for s in active if 'survivor' in s)
        folder=self.root/'pump-survivor';folder.mkdir()
        current=PaperBook(self.root/'pump-acceleration-natural-prospective.accounting.sqlite3',
            run_id='fixture',lane=current_strategy,policy_hash=old[current_strategy],initial=1000)
        survivor=PaperBook(folder/'paper.sqlite',run_id='fixture',lane=survivor_strategy,
            policy_hash=old[survivor_strategy],initial=1000)
        history=History(folder/'history.sqlite',policy=old[survivor_strategy])
        sleeve=SleeveReservations(self.root/'directional-sleeve.sqlite',lane='pump',capital=1000,policies=old,cohort='fixture')
        self.addCleanup(sleeve.close);self.addCleanup(history.close);self.addCleanup(survivor.close);self.addCleanup(current.close)
        prior=dict(verified=True,accounting=current.reconcile(),open_positions=0)
        result=terminal('pump',self.root,prior)
        self.assertEqual(result['open_positions'],0);self.assertEqual(result['accounting']['initial'],1000)
        with patch('meme_machine.runtime.directional_sleeve.policies',return_value=dict(active,**{survivor_strategy:'arbitrary-foreign'})):
            with self.assertRaisesRegex(ValueError,'survivor_terminal_policy'):terminal('pump',self.root,prior)
        with patch('meme_machine.runtime.directional_sleeve.policies',return_value=dict(active,**{current_strategy:'arbitrary-foreign'})):
            with self.assertRaisesRegex(ValueError,'survivor_terminal_sleeve_identity'):terminal('pump',self.root,prior)
