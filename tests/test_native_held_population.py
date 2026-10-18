"""Original native transactions and dormant observations; no market authority.

The existing financial fixture supplies real disposable financial/native books.
Its private owner packet explicitly SIMULATES the external root/host acquisition
boundary. Grants/reducers/COMMITs/ACKs are original code, never mocked successes.
No case proves sleeves/controllers/legacy/paused/protection population complete.
"""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from meme_machine.runtime import native_held_population as module
from meme_machine.runtime.native_held_population import _NativePopulationCapture, join_native_population
from meme_machine.runtime.directional_continuation import native_sync
from meme_machine.runtime.directional_sleeve import open_sleeve, policies
from meme_machine.shared_capital import CapitalError
from meme_machine.shared_capital.model import digest
from tests import test_held_financial_prefix as financial
from tests import test_pump_pons_capital_preparation as preparation
from tests.lanes.pons import test_pons_partial_accounting as partial


class NativeHeldPopulationTests(unittest.TestCase):
    # Assign only fixture methods. Importing/inheriting another TestCase here
    # would silently discover and rerun its unrelated cases.
    fixture = preparation.RuntimeIntegrationTests.fixture
    capture = financial.HeldFinancialPrefixTests.capture
    take = financial.HeldFinancialPrefixTests.take

    def case(self):
        root, authority, now, plan = self.fixture()
        pump = self.capture(authority)
        authority.verify_replay(held_replay=pump)
        prefix = self.take(pump)
        pons = self.capture(authority,family='pons')
        return SimpleNamespace(root=root,authority=authority,now=now,plan=plan,prefix=prefix,
            pump_owner=pump._owner,pons_owner=pons._owner,
            pump=_NativePopulationCapture(pump._owner,deadline=time.monotonic()+60,cancelled=lambda:False),
            pons=_NativePopulationCapture(pons._owner,deadline=time.monotonic()+60,cancelled=lambda:False))

    def view(self, capture):
        return capture.view(deadline=time.monotonic()+10,cancelled=lambda:False)

    def joined(self, case, captures):
        return join_native_population(case.prefix,list(captures),deadline=time.monotonic()+10,cancelled=lambda:False)

    def environment(self, case, family):
        setting = patch.dict(os.environ,MM_DIRECTIONAL_SLEEVE_DB=str(case.root/family/'directional-sleeve.sqlite'))
        setting.start();self.addCleanup(setting.stop)
        (case.root/family).mkdir(exist_ok=True)

    def paper(self, case, role='PUMP_CURRENT', *, observe=True, pool=None, path=None):
        from meme_machine.lanes.pump.paper_accounting import PaperBook as Current
        from meme_machine.runtime.survivor_paper_book import PaperBook as Survivor
        family = 'pump' if role.startswith('PUMP') else 'pons'
        self.environment(case,family)
        strategy = next(s for s in policies(family) if ('survivor' in s)==role.endswith('SURVIVOR'))
        location = case.root/module._BOOK_PATHS[role] if path is None else Path(path)
        location.parent.mkdir(parents=True,exist_ok=True)
        pool = pool or (case.pump if family=='pump' else case.pons)
        capture = pool.book() if observe else None
        arguments = dict(run_id='fixture',lane=strategy,policy_hash=policies(family)[strategy],initial=125000)
        if capture is not None:arguments['held_population'] = capture
        book = (Current if role=='PUMP_CURRENT' else Survivor)(location,**arguments)
        self.addCleanup(book.close)
        sleeve = open_sleeve(family,125000);self.addCleanup(sleeve.close)
        return book,sleeve,capture

    def reserve(self, case, book, sleeve, identity, *, at=None):
        at = case.now if at is None else at
        evidence = dict(asset='asset:'+identity,funding_evidence=dict(qualified=True))
        decision = dict(qualified=True)
        if 'survivor' in book.identity['lane']:
            from tests.shared_rally_support import observe_survivor
            observed = observe_survivor(sleeve,book.identity['lane'],'asset:'+identity,at)
            evidence.update(candidate=observed['id'],generation=observed['generation'],regime=observed['regime'])
            decision['candidate'] = observed['id']
        sleeve.reserve(identity,strategy=book.identity['lane'],amount=6250,at=at,**evidence)
        book.reserve(identity,6250,at,decision)

    def fill(self, case, book, sleeve, identity, *, at=None):
        at = case.now if at is None else at
        self.reserve(case,book,sleeve,identity,at=at)
        book.transition(identity,'filled',at,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
        book.transition(identity,'mark',at,amount=6250)
        native_sync(book,sleeve,identity)

    def pons_trial(self, case, *, index=1, identity='pons-native', observe=True, fill=True, at=None):
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper, STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        self.environment(case,'pons')
        folder = case.root/module._COHORT;folder.mkdir(parents=True,exist_ok=True)
        path = folder/f'trial-{index:03d}.sqlite'
        store = Store(path);self.addCleanup(store.close)
        guard = CohortCapital(folder/'pons-selective-cohort-capital.sqlite',125000)
        capture = case.pons.book() if observe else None
        arguments = dict(delay=1,natural_policy_hash=POLICY_HASH,on_commit=guard.observe)
        if capture is not None:arguments['held_population'] = capture
        paper = SelectivePaper(store,STRATEGY_NAMESPACE,125000,**arguments)
        quote = partial.PartialAccountingTests()
        if fill:
            at = case.now if at is None else at
            market = 'm' if index==1 else 'm'+str(index)
            features = dict(quote.features(at),market=market)
            guard.reserve(identity,6500,at=at,decision_hash=digest(features),trial_path=path,
                native_reservation_intent=dict(market=market,amount=6250,gas_budget=250,
                    features=features,now=at,kind='natural'))
            paper.reserve(identity,market=market,amount=6250,gas_budget=250,now=at,features=features)
            paper.advance(identity,now=at+1,action='entry',
                          quote=replace(quote.quote(at+1,'buy',6250,1000),market=market))
        return paper,guard,capture,quote

    def all_four(self, case):
        captures = []
        for role in module._BOOK_PATHS:
            book,sleeve,capture = self.paper(case,role)
            self.fill(case,book,sleeve,'fixture:'+role.lower())
            captures.append(capture)
        paper,guard,capture,quote = self.pons_trial(case)
        captures.append(capture)
        return captures

    def test_actual_all_four_members_match_original_financial_cut_only(self):
        case = self.case();captures = self.all_four(case)
        views = [self.view(capture) for capture in captures]
        self.assertEqual({value.role for value in views},
                         {'PUMP_CURRENT','PUMP_SURVIVOR','PONS_SURVIVOR','PONS_CURRENT_TRIAL'})
        self.assertTrue(all(value.status=='OBSERVED' and len(value.members)==1 for value in views))
        result = self.joined(case,captures)
        self.assertEqual((result.status,result.link_status),('INCOMPLETE','MATCHED_AT_CUT'))
        self.assertEqual({link[2] for link in result.links},
                         {'pump_current','pump_survivor','pons_current','pons_survivor'})
        self.assertEqual(len(result.links),4);self.assertEqual(result.unresolved,())
        self.assertTrue(result.missing);self.assertIn('PAUSED_AND_LEGACY',result.missing)
        self.assertIn('NATIVE_CONTROLLERS_AND_HISTORY',result.missing)
        self.assertFalse(result.funding_authority);self.assertFalse(result.readiness)
        self.assertEqual(result.protection,'UNEXERCISED')
        counts = dict(result.financial_pending_counts)
        self.assertEqual(set(counts),{'RESERVATION','COMMITMENT','OBLIGATION','PENDING_DELIVERY',
            'PENDING_BACKING','RUNTIME_PENDING','RUNTIME_INBOX','GLOBAL_OPEN','LEGACY_NATIVE_PENDING'})
        self.assertEqual(counts['LEGACY_NATIVE_PENDING'],'UNESTABLISHED')
        summary = result.summary()
        self.assertLessEqual(len(json.dumps(summary).encode()),4096)
        self.assertEqual(summary['status'],'INCOMPLETE');self.assertFalse(summary['held_boot'])
        with self.assertRaises(FrozenInstanceError):views[0].members = ()

    def test_member_versions_are_exact_events_and_not_book_largest_head(self):
        case = self.case();book,sleeve,capture = self.paper(case)
        self.fill(case,book,sleeve,'fixture:first')
        self.fill(case,book,sleeve,'fixture:second')
        book.transition('fixture:first','mark',case.now+1,amount=6300)
        actual = {}
        for seq,raw,parent,checksum in book.db.execute('SELECT * FROM journal ORDER BY seq'):
            position = json.loads(raw)['position']
            actual[position['id']] = seq,parent,checksum,position
        value = self.view(capture)
        self.assertGreater(max(m.version for m in value.members),min(m.version for m in value.members))
        for member in value.members:
            seq,parent,checksum,position = actual[member.identity]
            self.assertEqual((member.version,member.previous_hash,member.journal_hash),(seq,parent,checksum))
            self.assertEqual(json.loads(member.body),position)
            self.assertEqual(member.body_sha256,hashlib.sha256(member.body.encode()).hexdigest())
        first,_,c1,quote = self.pons_trial(case,identity='pons-first')
        # A second genuine grant requires the first held position's actual
        # executable mark; retain the original same-asset and valuation gates.
        first.advance('pons-first',now=case.now+1,action='mark',quote=quote.quote(case.now+1,'sell',1000,7000))
        second,_,c2,_ = self.pons_trial(case,index=2,identity='pons-second',at=case.now+1)
        self.assertEqual(self.view(c1).members[0].version,2)
        self.assertEqual(self.view(c2).members[0].version,1)

    def test_native_commit_survives_failed_global_ack_then_original_recovery(self):
        case = self.case();book,sleeve,capture = self.paper(case)
        self.reserve(case,book,sleeve,'fixture:pending')
        with patch.object(book.portfolio.client,'committed',side_effect=RuntimeError('lost_global_ack')):
            with self.assertRaisesRegex(RuntimeError,'lost_global_ack'):
                book.transition('fixture:pending','filled',case.now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
        value = self.view(capture)
        self.assertEqual(value.status,'OBSERVED');self.assertEqual(json.loads(value.members[0].body)['status'],'open')
        pending = self.joined(case,[capture])
        self.assertEqual(pending.status,'INCOMPLETE')
        self.assertEqual(pending.links[0][-1],'NATIVE_COMMITTED_GLOBAL_PENDING')
        self.assertTrue(book.portfolio.client.pending())
        book.portfolio.recover();book.portfolio.flush();native_sync(book,sleeve,'fixture:pending')
        settled = self.joined(case,[capture])
        self.assertEqual(settled.links[0][-1],'DELIVERY_RECORDED_AT_FINANCIAL_CUT')
        self.assertEqual(settled.link_status,'MATCHED_AT_CUT')
        self.assertFalse(book.portfolio.client.pending())

    def test_original_body_rollback_discards_only_provisional_native_observation(self):
        case = self.case();book,sleeve,capture = self.paper(case)
        with book.transaction():
            value = self.view(capture)
            self.assertEqual((value.status,value.reason),('INCOMPLETE','NATIVE_TRANSACTION_ACTIVE'))
        self.reserve(case,book,sleeve,'fixture:rollback');before = self.view(capture)
        original = book._record
        def interrupted(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('after_actual_native_record')
        with patch.object(book,'_record',side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError,'after_actual_native_record'):
                book.transition('fixture:rollback','filled',case.now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
        self.assertFalse(book.db.in_transaction)
        self.assertEqual(book._load('fixture:rollback')['status'],'reserved')
        after = self.view(capture)
        self.assertEqual(after.members,before.members);self.assertEqual(after.staged_events,0)
        self.assertTrue(book.portfolio.client.pending())
        book.portfolio.recover();book.portfolio.prepared.clear()
        self.assertFalse(book.portfolio.client.pending())

    def test_denied_actual_commit_leaves_no_successful_native_version(self):
        case = self.case();book,sleeve,capture = self.paper(case,'PUMP_SURVIVOR')
        self.reserve(case,book,sleeve,'fixture:denied');before = self.view(capture)
        def authorize(action,arg1,*args):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and arg1=='COMMIT' else sqlite3.SQLITE_OK
        book.db.set_authorizer(authorize)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                book.transition('fixture:denied','filled',case.now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
        finally:book.db.set_authorizer(None)
        self.assertFalse(book.db.in_transaction)
        self.assertEqual(self.view(capture).members,before.members)
        self.assertEqual(self.view(capture).staged_events,0)
        self.assertTrue(book.replay()['verified'])
        book.portfolio.recover();book.portfolio.prepared.clear()

    def test_actual_later_startup_replay_recovers_original_member_versions(self):
        case = self.case();book,sleeve,capture = self.paper(case,'PONS_SURVIVOR')
        self.fill(case,book,sleeve,'fixture:restart');expected = self.view(capture).members
        book.close();self._cleanups.remove((book.close,(),{}))
        fresh = _NativePopulationCapture(case.pons_owner,deadline=time.monotonic()+60,cancelled=lambda:False)
        restored,_,next_capture = self.paper(case,'PONS_SURVIVOR',pool=fresh)
        self.assertEqual(self.view(next_capture).members,expected)
        self.assertTrue(restored.replay()['verified'])
        self.assertEqual(self.joined(case,[next_capture]).link_status,'MATCHED_AT_CUT')

    def test_original_archive_without_member_version_cannot_use_book_head(self):
        from tests.native_snapshot_fixtures import copy_snapshot
        case = self.case();book,sleeve,_ = self.paper(case,'PUMP_SURVIVOR',observe=False)
        # A native fill has original replayable risk initialization. Do not
        # add the accounting-only mark helper: archival risk replay correctly
        # requires a real monitor's risk_state for such a mark.
        self.reserve(case,book,sleeve,'fixture:archived')
        book.transition('fixture:archived','filled',case.now,amount=6250,tokens=100,
                        evidence=dict(execution={'gas':0}))
        native_sync(book,sleeve,'fixture:archived')
        proof = book.replay();source = case.root/'native-prefix.sqlite';records = []
        copy_snapshot(case.root/module._BOOK_PATHS['PUMP_SURVIVOR'],source,records)
        authority = dict(schema='preserved-native-prefix-v1',snapshot_sha256=records[0]['sha256'],
            snapshot_name=module._BOOK_PATHS['PUMP_SURVIVOR'],state_hash=digest(proof),
            artifact=None,epoch_id=case.plan['seed']['epoch_id'],window_index=0)
        self.assertTrue(book._compact_preserved(source,authority))
        self.assertEqual(book.replay(),proof)
        self.assertEqual(book.db.execute('SELECT COUNT(*) FROM journal').fetchone()[0],0)
        book.close();self._cleanups.remove((book.close,(),{}))
        restored,_,capture = self.paper(case,'PUMP_SURVIVOR')
        value = self.view(capture)
        self.assertEqual((value.status,value.reason),('INCOMPLETE','ARCHIVE_MEMBER_VERSION_UNAVAILABLE'))
        self.assertEqual(value.members,())
        self.assertTrue(restored.replay()['verified'])
        self.assertTrue(any(reason=='FINANCIAL_NATIVE_MEMBER_UNOBSERVED'
                            for _,reason in self.joined(case,[capture]).unresolved))

    def test_original_rollback_failure_retains_unresolved_native_stage(self):
        case = self.case();book,sleeve,capture = self.paper(case)
        self.reserve(case,book,sleeve,'fixture:cleanup');before = self.view(capture).members
        original = book._record
        def interrupted(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('original_body_failed')
        book.db.set_authorizer(lambda action,arg1,*args: sqlite3.SQLITE_DENY
            if action==sqlite3.SQLITE_TRANSACTION and arg1=='ROLLBACK' else sqlite3.SQLITE_OK)
        try:
            with patch.object(book,'_record',side_effect=interrupted):
                with self.assertRaises(sqlite3.DatabaseError) as caught:
                    book.transition('fixture:cleanup','filled',case.now,amount=6250,tokens=100,
                                    evidence=dict(execution={'gas':0}))
        finally:book.db.set_authorizer(None)
        self.assertIsInstance(caught.exception.__context__,RuntimeError)
        self.assertTrue(book.db.in_transaction)
        value = self.view(capture)
        self.assertEqual((value.status,value.reason),('INCOMPLETE','NATIVE_COMMIT_UNRESOLVED'))
        self.assertEqual(value.members,before);self.assertEqual(value.staged_events,1)
        # Physical owner cleanup does not fabricate an observer ACK or clear
        # its unknown outcome. A fresh original replay is still required.
        book.db.execute('ROLLBACK')
        book.portfolio.recover();book.portfolio.prepared.clear()
        self.assertFalse(book.db.in_transaction)
        self.assertEqual(self.view(capture).staged_events,1)
        self.assertEqual(book._load('fixture:cleanup')['status'],'reserved')

    def test_partial_scale_and_terminal_between_samples_keep_actual_final_member(self):
        from meme_machine.runtime.directional_continuation import BRIDGE_GATES
        case = self.case();book,sleeve,capture = self.paper(case,'PUMP_SURVIVOR')
        self.fill(case,book,sleeve,'fixture:winner');before = self.view(capture)
        book.transition('fixture:winner','partial_harvest',case.now,amount=3125,tokens=25)
        native_sync(book,sleeve,'fixture:winner')
        book.transition('fixture:winner','mark',case.now,amount=7000)
        sleeve.reserve_scale('fixture:winner',amount=3125,original_basis=6250,at=case.now,request='winner-add',
            scale_state=dict(opened_at=case.now-1000,high_water_bps=10000,first_tail_crossed_at=case.now-900,
                original_basis=6250,realization_taken=True),
            scale_facts=dict({gate:True for gate in BRIDGE_GATES},fresh_strategy_requalified=True,
                fresh_execution_requalified=True,after_cost_return_bps=7000))
        book.transition('fixture:winner','scale_add',case.now,amount=3125,tokens=25,evidence=dict(request='winner-add'))
        native_sync(book,sleeve,'fixture:winner')
        book.transition('fixture:winner','settled',case.now+1,amount=9000)
        native_sync(book,sleeve,'fixture:winner')
        after = self.view(capture);member = after.members[0]
        self.assertEqual(json.loads(member.body),book._load('fixture:winner'))
        self.assertEqual(json.loads(member.body)['status'],'settled')
        self.assertGreater(member.version,before.members[0].version)
        self.assertGreater(after.committed_events,before.committed_events)
        self.assertEqual(self.joined(case,[capture]).link_status,'MATCHED_AT_CUT')
        self.fill(case,book,sleeve,'fixture:later',at=case.now+2)
        self.assertIn('fixture:winner',{m.identity for m in self.view(capture).members})

    def test_pons_native_commit_precedes_failed_cohort_observation(self):
        case = self.case();paper,guard,capture,quote = self.pons_trial(case)
        original = paper.on_commit
        paper.on_commit = lambda *args:(_ for _ in ()).throw(RuntimeError('cohort_observer_failed'))
        with self.assertRaisesRegex(RuntimeError,'cohort_observer_failed'):
            paper.advance('pons-native',now=case.now+2,action='mark',quote=quote.quote(case.now+2,'sell',1000,7000))
        value = self.view(capture);position = paper._get('pons-native')
        self.assertEqual(json.loads(value.members[0].body),position)
        self.assertFalse(guard.reconcile()['native_observation_complete'])
        result = self.joined(case,[capture])
        self.assertEqual(result.status,'INCOMPLETE');self.assertIn('COHORT_TRIAL_CENSUS',result.missing)
        paper.on_commit = original;guard.observe(paper,position)
        self.assertTrue(guard.reconcile()['native_observation_complete'])

    def test_missing_entire_book_and_real_funded_unmaterialized_request_stay_unresolved(self):
        case = self.case()
        # Acquire the real unmaterialized intent while the original portfolio
        # has no unmarked held position; a later zero/invalid mark cannot grant.
        self.environment(case,'pump');sleeve = open_sleeve('pump',125000);self.addCleanup(sleeve.close)
        strategy = next(name for name in policies('pump') if 'survivor' not in name)
        sleeve.reserve('fixture:unmaterialized',strategy=strategy,amount=6250,at=case.now,
                       asset='asset:unmaterialized',funding_evidence=dict(qualified=True))
        captures = self.all_four(case)
        missing = self.joined(case,captures[:-1])
        self.assertEqual(missing.link_status,'UNESTABLISHED')
        self.assertTrue(any(key=='pons:pons-native' and reason=='FINANCIAL_NATIVE_MEMBER_UNOBSERVED'
                            for key,reason in missing.unresolved))
        result = self.joined(case,captures)
        self.assertEqual(result.link_status,'UNESTABLISHED')
        self.assertTrue(any(key=='pump:fixture:unmaterialized' for key,_ in result.unresolved))
        self.assertTrue(case.authority.ledger()['reservations'])

    def test_wrong_owner_path_or_public_type_cannot_observe_a_genuine_book(self):
        case = self.case()
        _,_,crossed = self.paper(case,pool=case.pons)
        self.assertEqual(self.view(crossed).status,'INCOMPLETE')
        self.assertIn('crossed_owner',str(self.view(crossed).error))
        _,_,foreign = self.paper(case,path=case.root/'pump/foreign.sqlite')
        self.assertEqual(self.view(foreign).status,'INCOMPLETE')
        with self.assertRaises(TypeError):_NativePopulationCapture(case.pump_owner.identity(),deadline=time.monotonic()+5,cancelled=lambda:False)
        with self.assertRaises(TypeError):join_native_population(case.prefix,[{}],deadline=time.monotonic()+5,cancelled=lambda:False)

    def test_crossed_source_launch_and_replaced_owner_generation_refuse_join(self):
        from meme_machine.operational import normal_pons_boot as owner_module
        case = self.case();packet = case.pons_owner.identity()
        packet['launch']['application_commit'] = '8'*40
        packet['owner_generation'] = '7'*32
        owner = owner_module.NativePonsOwnerContext(packet,_issuer=owner_module._ISSUER)
        current = patch.object(owner_module,'_CURRENT',owner);current.start();self.addCleanup(current.stop)
        pool = _NativePopulationCapture(owner,deadline=time.monotonic()+60,cancelled=lambda:False)
        book,sleeve,capture = self.paper(case,'PONS_SURVIVOR',pool=pool)
        self.fill(case,book,sleeve,'fixture:source')
        with self.assertRaisesRegex(ValueError,'crossed_launch'):self.joined(case,[capture])
        packet['owner_generation'] = '6'*32
        replacement = owner_module.NativePonsOwnerContext(packet,_issuer=owner_module._ISSUER)
        with patch.object(owner_module,'_CURRENT',replacement):
            with self.assertRaises(Exception):self.view(capture)

    def test_foreign_thread_cannot_read_owned_members_or_query_native_handle(self):
        case = self.case();book,sleeve,capture = self.paper(case)
        self.fill(case,book,sleeve,'fixture:thread');before = dict(capture._members)
        trace = [];book.db.set_trace_callback(trace.append);errors = []
        def foreign():
            try:self.view(capture)
            except CapitalError as exc:errors.append(exc)
        thread = threading.Thread(target=foreign);thread.start();thread.join(timeout=5)
        self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
        self.assertEqual(trace,[]);self.assertEqual(capture._members,before)

    def test_aggregate_metadata_admission_across_distinct_books_is_observational(self):
        case = self.case();book,sleeve,first = self.paper(case)
        self.fill(case,book,sleeve,'fixture:bounded');used = case.pump._used
        with patch.object(module,'_MAX_BYTES',used+8):
            other,_,second = self.paper(case,'PUMP_SURVIVOR')
        self.assertTrue(other.replay()['verified'])
        self.assertEqual(self.view(first).status,'OBSERVED')
        self.assertEqual(self.view(second).status,'INCOMPLETE')
        self.assertIn('metadata_bound',str(self.view(second).error))
        self.assertIsNone(self.view(second).error.__traceback__)
        self.assertIsNone(self.view(second).error.__context__)
        self.assertEqual(case.pump._used,used)

    def test_staged_frame_limit_is_shared_across_real_outer_transactions(self):
        case = self.case();a,sa,ca = self.paper(case);b,sb,cb = self.paper(case,'PUMP_SURVIVOR')
        self.fill(case,a,sa,'fixture:a');self.fill(case,b,sb,'fixture:b')
        before = self.view(cb).members
        with patch.object(module,'_MAX_STAGE',1):
            with a.transaction():
                pa = a._load('fixture:a');pa['mark'] = 6300
                a._record(pa,'mark',case.now,{})
                with b.transaction():
                    pb = b._load('fixture:b');pb['mark'] = 6400
                    b._record(pb,'mark',case.now,{})
        self.assertEqual(self.view(ca).status,'OBSERVED')
        self.assertEqual(self.view(cb).status,'INCOMPLETE')
        self.assertEqual(self.view(cb).members,before)
        self.assertEqual(b._load('fixture:b')['mark'],6400)
        self.assertTrue(a.replay()['verified']);self.assertTrue(b.replay()['verified'])
        self.assertEqual(case.pump._staged_count,0)

    def test_cancel_or_deadline_during_real_encoding_cannot_publish_committed_version(self):
        for mode in ('cancel','deadline'):
            with self.subTest(mode=mode):
                case = self.case();stopped = [False];deadline = time.monotonic()+60
                pool = _NativePopulationCapture(case.pump_owner,deadline=deadline,cancelled=lambda:stopped[0])
                book,sleeve,capture = self.paper(case,pool=pool)
                self.reserve(case,book,sleeve,'fixture:interrupted');before = self.view(capture).members
                original = module._encode;entered = [];clock = [time.monotonic()]
                def encode(value,remaining,check):
                    if type(value) is dict and value.get('id')=='fixture:interrupted' and value.get('status')=='open':
                        calls = []
                        def during():
                            calls.append(None)
                            if len(calls)==3:
                                entered.append(True)
                                if mode=='cancel':stopped[0] = True
                                else:clock[0] = deadline
                            check()
                        return original(value,remaining,during)
                    return original(value,remaining,check)
                with patch.object(module,'_encode',side_effect=encode), \
                        patch('meme_machine.runtime.held_financial_prefix.time.monotonic',side_effect=lambda:clock[0]):
                    book.transition('fixture:interrupted','filled',case.now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
                    self.assertTrue(entered)
                    with self.assertRaises(Exception):self.view(capture)
                self.assertEqual(book._load('fixture:interrupted')['status'],'open')
                self.assertEqual(tuple(capture._members.values()),before)
                self.assertIsNotNone(capture._failure)

    def test_default_and_optin_same_original_command_tape_has_identical_native_sql(self):
        rows = [];at = None
        for enabled in (False,True):
            # Each fixture selects its genuine root and current private owners.
            # Consume it before the next fixture changes process environment.
            case = self.case()
            if at is None:at = case.now+1
            book,sleeve,capture = self.paper(case,observe=enabled)
            trace = [];book.db.set_trace_callback(trace.append)
            start = time.perf_counter();cpu = time.process_time()
            if enabled:
                self.fill(case,book,sleeve,'fixture:tape',at=at)
            else:
                with patch.object(module,'_encode',side_effect=AssertionError('default capture allocation')):
                    self.fill(case,book,sleeve,'fixture:tape',at=at)
            elapsed,cpu = time.perf_counter()-start,time.process_time()-cpu
            book.db.set_trace_callback(None)
            rows.append((trace,book._load('fixture:tape')))
            print('native_held_command_tape='+json.dumps(dict(enabled=enabled,wall_seconds=elapsed,
                cpu_seconds=cpu,native_connection_sql=len(trace),metadata_bytes=case.pump._used,
                scope='ONE_FIXED_ORIGINAL_COMMAND_TAPE_SETUP_AND_OTHER_CONNECTIONS_NOT_MEASURED_NOT_CAPACITY'),sort_keys=True),flush=True)
            if enabled:
                check_sql = [];book.db.set_trace_callback(check_sql.append)
                with patch('sqlite3.connect',side_effect=AssertionError('observer connection')):
                    self.assertEqual(self.view(capture).status,'OBSERVED')
                book.db.set_trace_callback(None);self.assertEqual(check_sql,[])
        self.assertEqual(rows[0],rows[1])


if __name__ == '__main__':
    unittest.main()
