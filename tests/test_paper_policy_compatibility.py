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
