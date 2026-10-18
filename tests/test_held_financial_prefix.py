"""Dormant prefix observer over real temporary native/shared transactions.

Provider/qualification/owner readiness are original explicit offline fixtures.
Private native-owner packets simulate the already-acquired host/root/source
premise; these tests do not exercise real protected owner acquisition.  No
supplied boolean/dictionary substitutes for the helper's private owner object.
"""
from dataclasses import FrozenInstanceError
from decimal import Inexact, Rounded, localcontext
import hashlib
import json
import os
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

from meme_machine.runtime import held_financial_prefix as module
from meme_machine.runtime.held_financial_prefix import _FinancialPrefix, _FinancialReplayCapture, _RetainedFinancialRead
from meme_machine.shared_capital import CapitalError
from meme_machine.shared_capital.model import canonical, digest
from meme_machine.shared_capital.runtime import RuntimeCapital
from tests import test_pump_pons_capital_preparation as fixtures


class HeldFinancialPrefixTests(unittest.TestCase):
    fixture = fixtures.RuntimeIntegrationTests.fixture

    def capture(self, authority, *, family='pump', epoch=None, inception=None, root=None):
        from meme_machine.operational import normal_pump_boot as pump, normal_pons_boot as pons
        from meme_machine.operational.normal_source_boot import _process_start
        lane = pump if family=='pump' else pons
        state = authority.ledger();at = time.monotonic()
        packet = dict(schema='normal-'+family+'-owner-subcap-v1',
            launch=dict(instance='b'*32,request_id='offline-held',stop_generation='INITIAL',
                record_sha256='a'*64,certificate_sha256='c'*64,
                application_commit='1'*40,application_tree='2'*40,
                epoch_id=state['epoch_id'] if epoch is None else epoch,
                inception_sha256=state['inception_sha256'] if inception is None else inception,
                boot_id='11111111-2222-3333-4444-555555555555',
                supervisor=dict(pid=os.getpid(),start_ticks=_process_start(os.getpid()),invocation_id='d'*32)),
            owner=dict(pid=os.getpid(),start_ticks=_process_start(os.getpid()),process_instance='e'*32),
            owner_generation='f'*32,native_clock_sha256='9'*64,
            root=str(authority.path.parent if root is None else root),
            issued_monotonic=at,not_after_monotonic=at+60)
        owner_type = lane.NativePumpOwnerContext if family=='pump' else lane.NativePonsOwnerContext
        # Simulate only the external already-acquired native owner boundary.
        # The anchor itself must still come from the genuine original verifier.
        owner = owner_type(packet,_issuer=lane._ISSUER)
        current = patch.object(lane,'_CURRENT',owner);current.start();self.addCleanup(current.stop)
        return _FinancialReplayCapture(owner)

    def prefix(self, authority):
        capture = self.capture(authority)
        authority.verify_replay(held_replay=capture)
        return capture.prefix()

    def advance(self, prefix, **bounds):
        return prefix.advance(deadline=time.monotonic() + 10, cancelled=lambda: False, **bounds)

    def cover(self, prefix):
        for _ in range(32):
            value = self.advance(prefix)
            if value.status != 'INCOMPLETE':
                return value
        self.fail('bounded original fixture did not reach its fixed cut')

    def native(self, root, now, *, family='pump', survivor=False, identity='fixture:one', reserve=True):
        from meme_machine.lanes.pump.paper_accounting import PaperBook as CurrentPaper
        from meme_machine.runtime.survivor_paper_book import PaperBook
        from meme_machine.runtime.directional_sleeve import open_sleeve, policies
        setting = patch.dict(os.environ, MM_DIRECTIONAL_SLEEVE_DB=str(root/family/'directional-sleeve.sqlite'))
        setting.start();self.addCleanup(setting.stop)
        (root/family).mkdir(exist_ok=True)
        strategy = next(s for s in policies(family) if ('survivor' in s) == survivor)
        book_type = CurrentPaper if family == 'pump' and not survivor else PaperBook
        book = book_type(root/family/(identity.replace(':','-')+'.sqlite'), run_id='fixture',
                         lane=strategy, policy_hash=policies(family)[strategy], initial=125000)
        self.addCleanup(book.close)
        sleeve = open_sleeve(family, 125000);self.addCleanup(sleeve.close)
        if reserve:
            evidence = dict(asset='asset:'+identity, funding_evidence=dict(qualified=True))
            if survivor:
                from tests.shared_rally_support import observe_survivor
                observed = observe_survivor(sleeve, strategy, 'asset:'+identity, now)
                evidence.update(candidate=observed['id'], generation=observed['generation'], regime=observed['regime'])
            sleeve.reserve(identity, strategy=strategy, amount=6250, at=now, **evidence)
            book.reserve(identity, 6250, now, dict(qualified=True))
            book.transition(identity, 'filled', now, amount=6250, tokens=100, evidence=dict(execution={'gas':0}))
            book.transition(identity, 'mark', now, amount=6250)
            from meme_machine.runtime.directional_continuation import native_sync
            native_sync(book, sleeve, identity)
        return book, sleeve, strategy

    def pons(self, root, now):
        from meme_machine.lanes.pons.evidence import Store
        from meme_machine.lanes.pons.pons_selective_capital import CohortCapital
        from meme_machine.lanes.pons.pons_selective_ledger import SelectivePaper, STRATEGY_NAMESPACE
        from meme_machine.lanes.pons.pons_selective_continuation import POLICY_HASH
        from tests.lanes.pons.test_pons_partial_accounting import PartialAccountingTests
        setting = patch.dict(os.environ, MM_DIRECTIONAL_SLEEVE_DB=str(root/'pons/directional-sleeve.sqlite'))
        setting.start();self.addCleanup(setting.stop)
        (root/'pons').mkdir(exist_ok=True)
        path = root/'pons/current-trial.sqlite'
        store = Store(path);self.addCleanup(store.close)
        guard = CohortCapital(root/'pons/capital.sqlite', 125000)
        paper = SelectivePaper(store, STRATEGY_NAMESPACE, 125000, delay=1,
                               natural_policy_hash=POLICY_HASH, on_commit=guard.observe)
        fixture = PartialAccountingTests();features = fixture.features(now)
        guard.reserve('pons-native', 6500, at=now, decision_hash=digest(features), trial_path=path,
            native_reservation_intent=dict(market='m',amount=6250,gas_budget=250,features=features,now=now,kind='natural'))
        paper.reserve('pons-native', market='m', amount=6250, gas_budget=250, now=now, features=features)
        paper.advance('pons-native', now=now+1, action='entry', quote=fixture.quote(now+1,'buy',6250,1000))
        return paper, guard, fixture

    def test_initial_cut_uses_real_private_anchor_without_second_scan_or_new_connection(self):
        _, authority, _, _ = self.fixture()
        capture = self.capture(authority)
        proof = authority.verify_replay(held_replay=capture);state = authority.ledger()
        changes = authority.db.total_changes
        with patch.object(authority, '_authenticated_replay_prefix', side_effect=AssertionError('full scan')), \
                patch.object(authority, 'verify_replay', side_effect=AssertionError('second replay')), \
                patch('sqlite3.connect', side_effect=AssertionError('new connection')):
            prefix = capture.prefix()
            value = self.advance(prefix)
        self.assertEqual(value.status, 'COVERED_CUT')
        self.assertEqual(value.state_sha256, digest(state))
        self.assertEqual(value.sequence, proof['events'])
        self.assertEqual(value.rows, 0)
        self.assertEqual(len(value.counts), 9)
        self.assertEqual(dict(value.counts)['LEGACY_NATIVE_PENDING'], 'UNESTABLISHED')
        self.assertEqual(authority.db.total_changes, changes)

    def test_join_accessor_retains_original_identity_maps_but_never_shares_mutable_state(self):
        root, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        self.native(root,now)
        value = self.cover(prefix)
        sequence, anchor, checksum, state = prefix._state_for_join()
        self.assertEqual((sequence,anchor,checksum),(value.sequence,value.journal_hash,value.state_sha256))
        actual = authority.ledger()
        for name in ('native_aliases','runtime_native_requests','native_deliveries','native_cursors'):
            self.assertEqual(state[name],actual[name]);self.assertTrue(state[name])
            state[name].clear()
        self.assertTrue(prefix._state_for_join()[3]['native_aliases'])
        errors = []
        def foreign():
            try:prefix._state_for_join()
            except CapitalError as exc:errors.append(exc)
        thread = threading.Thread(target=foreign);thread.start();thread.join(timeout=5)
        self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
        self.assertFalse(authority.db.in_transaction)
        with self.assertRaises(FrozenInstanceError):value.sequence = 0

    def test_only_published_original_anchor_can_bootstrap_once(self):
        _, authority, _, _ = self.fixture()
        capture = self.capture(authority)
        with self.assertRaisesRegex(CapitalError,'anchor_unavailable'):capture.prefix()
        for supplied in (authority.ledger(),authority.verify_replay(),True,object()):
            with self.assertRaises(CapitalError):_FinancialPrefix(supplied)
        authority.verify_replay(held_replay=capture)
        capture.prefix()
        with self.assertRaisesRegex(CapitalError,'anchor_unavailable'):capture.prefix()
        with self.assertRaises(TypeError):_FinancialReplayCapture(capture._identity)

    def test_actual_four_regimes_replay_contiguously_and_keep_exact_member_bodies(self):
        root, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        initial=prefix._sequence
        self.native(root, now, identity='fixture:pump-current')
        self.native(root, now, survivor=True, identity='fixture:pump-survivor')
        self.native(root, now, family='pons', survivor=True, identity='fixture:pons-survivor')
        self.pons(root, now)
        changes = authority.db.total_changes
        sql=[];authority.db.set_trace_callback(sql.append)
        started=time.perf_counter();cpu=time.process_time()
        with patch('sqlite3.connect', side_effect=AssertionError('observer must reuse connection')):
            value = self.cover(prefix)
        cost=dict(wall_seconds=time.perf_counter()-started,cpu_seconds=time.process_time()-cpu,
            sql_statements=len(sql),tail_rows=value.sequence-initial,
            covered_cut=value.sequence,scope='ONE_FIXED_ORIGINAL_FOUR_REGIME_JOURNAL_TAIL_NOT_CAPACITY')
        authority.db.set_trace_callback(None)
        print('held_financial_prefix_cost='+json.dumps(cost,sort_keys=True),flush=True)
        self.assertEqual(value.status, 'COVERED_CUT')
        members = {key:json.loads(body) for key,body in value.current_members}
        self.assertEqual({p['regime'] for p in members.values()},
                         {'pump_current','pump_survivor','pons_current','pons_survivor'})
        self.assertEqual(members, {key:row for key,row in authority.ledger()['positions'].items() if row['status']=='OPEN'})
        self.assertEqual(value.state_sha256, authority.verify_replay()['state_sha256'])
        self.assertEqual(authority.db.total_changes, changes)

    def test_real_reservation_native_commit_pending_and_global_ack_remain_distinct(self):
        root, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        book, sleeve, strategy = self.native(root, now, reserve=False)
        sleeve.reserve('fixture:pending', strategy=strategy, amount=6250, at=now,
                       asset='asset:pending', funding_evidence=dict(qualified=True))
        reserved = self.cover(prefix)
        self.assertEqual(dict(reserved.counts)['RESERVATION'], 1)
        with patch.object(book.portfolio.client, 'committed', side_effect=RuntimeError('lost_global_ack')):
            with self.assertRaisesRegex(RuntimeError, 'lost_global_ack'):
                book.reserve('fixture:pending', 6250, now, dict(qualified=True))
        self.assertTrue(book.replay()['verified'])
        pending = self.cover(prefix)
        self.assertEqual(dict(pending.counts)['COMMITMENT'], 1)
        self.assertEqual(dict(pending.counts)['RUNTIME_PENDING'], 1)
        actual = authority.ledger()['runtime_pending']
        self.assertEqual({key:json.loads(body) for kind,key,body in pending.pending if kind=='RUNTIME_PENDING'}, actual)
        book.portfolio.recover();book.portfolio.prepared.clear()
        book.transition('fixture:pending','filled',now,amount=6250,tokens=100,evidence=dict(execution={'gas':0}))
        acknowledged = self.cover(prefix)
        self.assertEqual(dict(acknowledged.counts)['RUNTIME_PENDING'], 0)
        self.assertEqual(dict(acknowledged.counts)['COMMITMENT'], 0)
        self.assertEqual(dict(acknowledged.counts)['GLOBAL_OPEN'], 1)

    def test_scale_partial_and_terminal_between_observation_cuts_are_retained(self):
        from meme_machine.runtime.directional_continuation import BRIDGE_GATES, native_sync
        root, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        book, sleeve, _ = self.native(root, now, survivor=True)
        book.transition('fixture:one','partial_harvest',now,amount=3125,tokens=25)
        native_sync(book,sleeve,'fixture:one')
        book.transition('fixture:one','mark',now,amount=7000)
        sleeve.reserve_scale('fixture:one',amount=3125,original_basis=6250,at=now,request='winner-add',
            scale_state=dict(opened_at=now-1000,high_water_bps=10000,first_tail_crossed_at=now-900,
                original_basis=6250,realization_taken=True),
            scale_facts=dict({gate:True for gate in BRIDGE_GATES},fresh_strategy_requalified=True,
                fresh_execution_requalified=True,after_cost_return_bps=7000))
        book.transition('fixture:one','scale_add',now,amount=3125,tokens=25,evidence=dict(request='winner-add'))
        native_sync(book,sleeve,'fixture:one')
        book.transition('fixture:one','settled',now+1,amount=9000)
        native_sync(book,sleeve,'fixture:one')
        value = self.cover(prefix)
        self.assertEqual(value.current_members, ())
        self.assertEqual(len(value.terminal_members), 1)
        terminal = json.loads(value.terminal_members[0][1])
        self.assertEqual(terminal['original_native_basis'], 6250)
        self.assertTrue(terminal['scale_committed'])
        self.assertIn('terminal_receipt', terminal)
        self.assertEqual(value.state_sha256, authority.verify_replay()['state_sha256'])

    def test_bounded_tail_keeps_fixed_cut_and_reconciles_another_real_writer(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        peer = RuntimeCapital(authority.path);self.addCleanup(peer.close)
        for index in range(4):peer.command('foreign:'+str(index),'runtime_publish',{},now+index)
        trace = [];authority.db.set_trace_callback(trace.append)
        first = self.advance(prefix,max_rows=1)
        self.assertEqual(first.status,'INCOMPLETE');self.assertEqual(first.rows,1)
        peer.command('foreign:later','runtime_publish',{},now+4)
        second = self.advance(prefix,max_rows=1)
        self.assertEqual(second.cut_sequence,first.cut_sequence)
        value = self.cover(prefix)
        self.assertEqual(value.status,'COVERED_CUT')
        self.assertEqual(value.state_sha256,peer.verify_replay()['state_sha256'])
        tails = [sql for sql in trace if 'FROM shared_capital_events WHERE sequence>' in sql]
        self.assertTrue(tails)
        self.assertTrue(all('sequence<=' in sql and 'ORDER BY sequence LIMIT' in sql for sql in tails))

    def test_head_growth_after_snapshot_cannot_claim_current_cut(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        peer = RuntimeCapital(authority.path);self.addCleanup(peer.close)
        authority.command('first','runtime_publish',{},now)
        original_one = module._one;grew = []
        def one(db,sql,parameters=()):
            result = original_one(db,sql,parameters)
            if sql=='ROLLBACK' and not grew:
                grew.append(True);peer.command('after-cut','runtime_publish',{},now+1)
            return result
        with patch.object(module,'_one',side_effect=one):value = self.advance(prefix)
        self.assertEqual(value.status,'INCOMPLETE');self.assertEqual(value.reason,'HEAD_ADVANCED')
        self.assertEqual(self.advance(prefix).status,'COVERED_CUT')

    def test_cancel_and_deadline_discard_provisional_state_and_preserve_live_flags(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        before = prefix._sequence
        authority.command('new','runtime_publish',{},now)
        calls = []
        def cancelled():calls.append(None);return len(calls)>=3
        changes = authority.db.total_changes
        authority._replaying = True
        try:
            value = prefix.advance(deadline=time.monotonic()+10,cancelled=cancelled)
            self.assertEqual(value.status,'INCOMPLETE');self.assertEqual(value.sequence,before)
            self.assertTrue(authority._replaying)
            value = prefix.advance(deadline=time.monotonic()-1,cancelled=lambda:False)
            self.assertEqual(value.reason,'DEADLINE');self.assertEqual(value.sequence,before)
        finally:authority._replaying = False
        self.assertEqual(authority.db.total_changes,changes)
        self.assertFalse(authority.db.in_transaction)
        self.assertEqual(self.advance(prefix).status,'COVERED_CUT')

    def test_foreign_thread_and_pid_never_query_connection(self):
        _, authority, _, _ = self.fixture();prefix = self.prefix(authority)
        trace = [];authority.db.set_trace_callback(trace.append);values = []
        cache = prefix._view_cache
        with patch.object(prefix,'_view',side_effect=AssertionError('owned projection access')), \
                patch.object(prefix._capture,'_check',side_effect=AssertionError('owner capability access')):
            thread = threading.Thread(target=lambda:values.append(self.advance(prefix)))
            thread.start();thread.join(timeout=5);self.assertFalse(thread.is_alive())
            with patch.object(module.os,'getpid',return_value=os.getpid()+100000):
                values.append(self.advance(prefix))
        for value in values:
            self.assertEqual((value.status,value.reason),('UNKNOWN','FOREIGN_OWNER'))
            self.assertEqual((value.current_members,value.terminal_members,value.pending),((),(),()))
            self.assertEqual(len(value.counts),9)
            self.assertTrue(all(count=='UNESTABLISHED' for _,count in value.counts))
        self.assertEqual(len(values),2)
        self.assertIs(prefix._view_cache,cache)
        self.assertEqual(trace,[])

    def test_existing_transaction_is_never_committed_or_rolled_back(self):
        _, authority, _, _ = self.fixture();prefix = self.prefix(authority)
        authority.db.execute('BEGIN')
        try:
            value = self.advance(prefix)
            self.assertEqual(value.reason,'OWNER_TRANSACTION_ACTIVE')
            self.assertTrue(authority.db.in_transaction)
        finally:authority.db.execute('ROLLBACK')

    def test_busy_original_mutex_defers_without_waiting_or_sql(self):
        _, authority, _, _ = self.fixture();prefix = self.prefix(authority)
        acquired = threading.Event();release = threading.Event()
        def owner():
            with authority._mutex:
                acquired.set();release.wait(timeout=5)
        thread = threading.Thread(target=owner);thread.start()
        try:
            self.assertTrue(acquired.wait(timeout=5))
            trace = [];authority.db.set_trace_callback(trace.append)
            value = self.advance(prefix)
            self.assertEqual(value.reason,'OWNER_BUSY');self.assertEqual(trace,[])
        finally:
            release.set();thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

    def test_interrupted_original_sql_handler_rolls_back_only_own_snapshot(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        authority.command('new','runtime_publish',{},now)
        calls = []
        def progress():
            calls.append(None)
            return int(len(calls)==30)
        authority.db.set_progress_handler(progress,1)
        self.addCleanup(lambda:authority.db.set_progress_handler(None,0))
        changes = authority.db.total_changes
        value = self.advance(prefix)
        self.assertEqual(value.status,'UNKNOWN');self.assertIsInstance(value.error,sqlite3.OperationalError)
        self.assertFalse(authority.db.in_transaction)
        self.assertEqual(authority.db.total_changes,changes)

    def test_missing_interval_with_schema_mutation_never_repairs_itself_from_new_head(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        authority.command('first','runtime_publish',{},now)
        authority.command('second','runtime_publish',{},now+1)
        lost = authority.db.execute('SELECT * FROM shared_capital_events WHERE sequence=?',
                                    (prefix._sequence+1,)).fetchone()
        authority.db.execute('DROP TRIGGER shared_capital_no_delete')
        authority.db.execute('DELETE FROM shared_capital_events WHERE sequence=?',(lost[0],))
        value = self.advance(prefix)
        self.assertEqual(value.status,'UNKNOWN')
        self.assertEqual(value.rows,0)
        # Restore the exact real committed row, never a supplied substitute hash.
        authority.db.execute('INSERT INTO shared_capital_events VALUES(?,?,?,?,?,?,?)',lost)
        value = self.advance(prefix)
        self.assertEqual(value.status,'UNKNOWN');self.assertEqual(value.reason,'LATCHED')

    def test_original_progress_handler_and_authorizer_remain_installed(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        authority.command('new','runtime_publish',{},now)
        calls = []
        def progress():calls.append(None);return 0
        denied = {sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,
                  sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_DROP_TABLE}
        def authorize(action,*args):return sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK
        authority.db.set_progress_handler(progress,1);authority.db.set_authorizer(authorize)
        self.addCleanup(lambda:authority.db.set_progress_handler(None,0))
        self.addCleanup(lambda:authority.db.set_authorizer(None))
        self.assertEqual(self.advance(prefix).status,'COVERED_CUT')
        before = len(calls);authority.db.execute('SELECT COUNT(*) FROM shared_capital_events').fetchone()
        self.assertGreater(len(calls),before)
        with self.assertRaises(sqlite3.DatabaseError):authority.db.execute('DELETE FROM shared_capital_projection')

    def test_byte_preflight_defers_before_any_tail_text_is_materialized(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        authority.command('new','runtime_publish',{},now)
        trace = [];authority.db.set_trace_callback(trace.append)
        before = prefix._sequence
        value = self.advance(prefix,max_bytes=1)
        self.assertEqual(value.status,'INCOMPLETE');self.assertEqual(value.reason,'BYTE_LIMIT')
        self.assertEqual(value.sequence,before)
        self.assertFalse(any(sql.startswith('SELECT * FROM shared_capital_events') for sql in trace))
        self.assertEqual(self.advance(prefix).status,'COVERED_CUT')

    def test_corrupt_parent_result_state_hash_and_oversize_rows_latch_unknown(self):
        for corrupt in ('parent','result','state_hash','oversize'):
            with self.subTest(corrupt=corrupt):
                _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
                prepared=[]
                def capture_before_commit(stage):
                    if stage=='before_commit':
                        prepared.append(authority.db.execute('SELECT * FROM shared_capital_events '
                            'ORDER BY sequence DESC LIMIT 1').fetchone())
                        raise RuntimeError('original_uncommitted_fixture_event')
                authority.fault=capture_before_commit
                try:
                    with self.assertRaisesRegex(RuntimeError,'original_uncommitted_fixture_event'):
                        authority.command('new','runtime_publish',{},now)
                finally:authority.fault=None
                self.assertEqual(len(prepared),1)
                self.assertFalse(authority.db.in_transaction)
                row=list(prepared[0])
                if corrupt=='parent':row[5] = 'f'*64
                elif corrupt=='result':row[3] = canonical({'accepted':False})
                elif corrupt=='state_hash':row[4] = 'f'*64
                else:row[2] += ' '*(module._MAX_BYTES+1)
                row[6] = hashlib.sha256((row[5]+row[2]+row[3]+row[4]).encode()).hexdigest()
                # Append a malformed future row without weakening the schema.
                # It derives from the actual original rolled-back transition;
                # no synthetic body/hash is accepted as a positive authority.
                authority.db.execute('INSERT INTO shared_capital_events VALUES(?,?,?,?,?,?,?)',row)
                changes = authority.db.total_changes;value = self.advance(prefix)
                self.assertEqual(value.status,'UNKNOWN');self.assertIsInstance(value.error,CapitalError)
                expected=('capital_journal_integrity' if corrupt=='parent' else
                    'held_financial_row_bound' if corrupt=='oversize' else 'nondeterministic_capital_replay')
                self.assertEqual(str(value.error),expected)
                self.assertEqual(self.advance(prefix).reason,'LATCHED')
                self.assertEqual(authority.db.total_changes,changes)
                self.assertFalse(authority.db.in_transaction)

    def test_projection_corruption_is_not_hidden_by_a_matching_journal_head(self):
        _, authority, _, _ = self.fixture();prefix = self.prefix(authority)
        state = authority.ledger();state['cash'] = '501'
        authority.db.execute('UPDATE shared_capital_projection SET body=? WHERE id=1',(canonical(state),))
        value = self.advance(prefix)
        self.assertEqual(value.status,'UNKNOWN')
        self.assertEqual(str(value.error),'replayed_projection_mismatch')

    def test_original_decimal_context_and_reducer_errors_are_preserved(self):
        root, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        self.native(root,now,survivor=True)
        with localcontext() as context:
            context.prec = 1;context.traps[Inexact] = True;context.traps[Rounded] = True
            before = context.copy();value = self.cover(prefix)
            self.assertEqual(value.status,'COVERED_CUT')
            self.assertEqual(context.prec,before.prec)
            self.assertEqual(context.flags,before.flags)
            self.assertEqual(context.traps,before.traps)
        self.assertEqual(value.state_sha256,authority.verify_replay()['state_sha256'])

    def test_default_replay_sql_is_unchanged_and_does_not_touch_capture_schema(self):
        _, authority, _, _ = self.fixture()
        authority.verify_replay()  # Warm the existing original verifier cache equally.
        first = [];authority.db.set_trace_callback(first.append)
        with patch.object(module,'_schema',side_effect=AssertionError('inactive observer')):
            proof = authority.verify_replay()
        second = [];authority.db.set_trace_callback(second.append)
        with patch.object(module,'_schema',side_effect=AssertionError('inactive observer')):
            self.assertEqual(authority.verify_replay(held_replay=None),proof)
        authority.db.set_trace_callback(None)
        self.assertEqual(first,second)
        self.assertFalse(any('sqlite_schema' in sql or 'PRAGMA' in sql for sql in first))
        self.assertEqual(first[0],'BEGIN');self.assertEqual(first[-1],'COMMIT')

    def test_unchanged_cut_and_status_polling_reuse_immutable_member_projection(self):
        root, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        self.native(root,now);first = self.cover(prefix)
        self.assertTrue(first.current_members)
        with patch.object(module,'deepcopy',side_effect=AssertionError('unnecessary full copy')), \
                patch.object(module,'canonical',side_effect=AssertionError('unnecessary member serialization')):
            same = self.advance(prefix)
            self.assertEqual(same.status,'COVERED_CUT')
            self.assertIs(same.current_members,first.current_members)
            cancelled = prefix.advance(deadline=time.monotonic()+5,cancelled=lambda:True)
            self.assertEqual(cancelled.reason,'CANCELLED')
            self.assertIs(cancelled.pending,first.pending)
            with patch.object(module,'_schema',side_effect=ValueError('observer_failed')):
                unknown = self.advance(prefix)
            self.assertEqual(unknown.status,'UNKNOWN')
            self.assertIs(self.advance(prefix).terminal_members,first.terminal_members)

    def test_interior_tamper_before_anchor_reaches_real_original_verifier(self):
        _, authority, now, _ = self.fixture()
        authority.command('later','runtime_publish',{},now)
        capture = self.capture(authority)
        endpoints = authority.db.execute('SELECT sequence,hash,state_hash FROM shared_capital_events'
            ' WHERE sequence IN (1,(SELECT MAX(sequence) FROM shared_capital_events)) ORDER BY sequence').fetchall()
        authority.db.execute('DROP TRIGGER shared_capital_no_update')
        authority.db.execute("UPDATE shared_capital_events SET body=body||' ' WHERE sequence=2")
        self.assertEqual(authority.db.execute('SELECT sequence,hash,state_hash FROM shared_capital_events'
            ' WHERE sequence IN (1,(SELECT MAX(sequence) FROM shared_capital_events)) ORDER BY sequence').fetchall(),endpoints)
        with self.assertRaisesRegex(CapitalError,'capital_journal_integrity'):
            authority.verify_replay(held_replay=capture)
        with self.assertRaisesRegex(CapitalError,'anchor_unavailable'):capture.prefix()
        self.assertIsNone(capture._anchor)

    def test_missing_immutable_trigger_before_anchor_refuses_observer_only(self):
        _, authority, _, _ = self.fixture();capture = self.capture(authority)
        proof = authority.verify_replay()
        authority.db.execute('DROP TRIGGER shared_capital_no_update')
        self.assertEqual(authority.verify_replay(held_replay=capture),proof)
        with self.assertRaisesRegex(CapitalError,'anchor_unavailable'):capture.prefix()
        self.assertIsInstance(capture._failure,CapitalError)
        self.assertFalse(authority.db.in_transaction)

    def test_drop_and_identical_restore_after_anchor_break_schema_generation(self):
        _, authority, _, _ = self.fixture();prefix = self.prefix(authority)
        schema = authority.db.execute("SELECT sql FROM sqlite_schema WHERE name='shared_capital_no_update'").fetchone()[0]
        head = authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone()
        authority.db.execute('DROP TRIGGER shared_capital_no_update')
        authority.db.execute(schema)
        self.assertEqual(authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone(),head)
        value = self.advance(prefix)
        self.assertEqual(value.status,'UNKNOWN');self.assertEqual(str(value.error),'held_financial_schema_changed')
        self.assertEqual(self.advance(prefix).reason,'LATCHED')

    def test_staged_anchor_cannot_escape_original_commit_failure(self):
        _, authority, _, _ = self.fixture();capture = self.capture(authority)
        observed = []
        def authorize(action,arg1,*args):
            if action==sqlite3.SQLITE_TRANSACTION and arg1=='COMMIT':
                observed.append((capture._phase,authority.db.in_transaction))
                with self.assertRaisesRegex(CapitalError,'anchor_unavailable'):capture.prefix()
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        authority.db.set_authorizer(authorize)
        try:
            with self.assertRaises(sqlite3.DatabaseError):authority.verify_replay(held_replay=capture)
        finally:authority.db.set_authorizer(None)
        self.assertEqual(observed,[('STAGED',True)])
        self.assertFalse(authority.db.in_transaction)
        self.assertIsNone(capture._anchor)
        with self.assertRaisesRegex(CapitalError,'anchor_unavailable'):capture.prefix()

    def test_original_cancellation_after_staging_discards_anchor_and_exception(self):
        from meme_machine.runtime.stop import Shutdown
        _, authority, _, _ = self.fixture();capture = self.capture(authority)
        def cancelled():return capture._phase=='STAGED'
        with patch.object(authority,'_startup_replay_cancel',cancelled):
            with self.assertRaises(Shutdown):authority.verify_replay(held_replay=capture)
        self.assertIsNone(capture._anchor);self.assertFalse(authority.db.in_transaction)
        self.assertFalse(authority._replaying)
        with self.assertRaises(CapitalError):capture.prefix()

    def test_ordinary_capture_refusal_preserves_original_summary(self):
        _, authority, _, _ = self.fixture();capture = self.capture(authority)
        proof = authority.verify_replay();failure = ValueError('observer_only')
        with patch.object(module,'_schema',side_effect=failure):
            self.assertEqual(authority.verify_replay(held_replay=capture),proof)
        self.assertIs(capture._failure,failure)
        with self.assertRaises(CapitalError) as caught:capture.prefix()
        self.assertIs(caught.exception.__cause__,failure)

    def test_native_owner_root_epoch_inception_and_lifetime_are_not_supplied_flags(self):
        _, authority, _, _ = self.fixture();proof = authority.verify_replay()
        for fields in ({'epoch':'crossed'}, {'inception':'0'*64}, {'root':authority.path.parent/'foreign'}):
            with self.subTest(fields=fields):
                capture = self.capture(authority,**fields)
                self.assertEqual(authority.verify_replay(held_replay=capture),proof)
                with self.assertRaises(CapitalError):capture.prefix()
        capture = self.capture(authority,family='pons')
        authority.verify_replay(held_replay=capture)
        prefix = capture.prefix();self.assertEqual(self.advance(prefix).status,'COVERED_CUT')
        capture._owner.close()
        self.assertEqual(self.advance(prefix).status,'UNKNOWN')

    def test_constructor_uses_its_original_initial_replay_for_capture(self):
        _, authority, _, _ = self.fixture();capture = self.capture(authority)
        peer = RuntimeCapital(authority.path,held_replay=capture);self.addCleanup(peer.close)
        prefix = capture.prefix()
        self.assertIs(prefix._authority,peer)
        self.assertEqual(self.advance(prefix).status,'COVERED_CUT')

    def test_retained_owned_rollback_preserves_primary_and_requires_real_owner_cleanup(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        primary = RuntimeError('original_observation_failure');denied = []
        def authorize(action,arg1,*args):
            if action==sqlite3.SQLITE_TRANSACTION and arg1=='ROLLBACK':
                denied.append(True);return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        authority.db.set_authorizer(authorize)
        self.addCleanup(lambda:authority.db.set_authorizer(None))
        with patch.object(module,'_head',side_effect=primary):
            with self.assertRaises(_RetainedFinancialRead) as caught:self.advance(prefix)
        issue = caught.exception
        self.assertIs(issue.primary,primary);self.assertIs(issue.__cause__,primary)
        self.assertIs(issue.authority,authority);self.assertIs(issue.prefix,prefix)
        self.assertTrue(issue.transaction_active);self.assertTrue(authority.db.in_transaction)
        with self.assertRaises(_RetainedFinancialRead) as again:self.advance(prefix)
        self.assertIs(again.exception,issue)
        # The original BEGIN naturally refuses; caller must not otherwise reuse
        # or raw-commit the borrowed owner while this handoff is retained.
        with self.assertRaises(sqlite3.OperationalError):authority.ledger()
        with self.assertRaises(_RetainedFinancialRead) as failed_cleanup:
            prefix.cleanup_retained_read(deadline=time.monotonic()+5,cancelled=lambda:False)
        self.assertIs(failed_cleanup.exception.__cause__,primary)
        self.assertIsNotNone(issue.cleanup_error);self.assertIsNotNone(issue.latest_cleanup_error)
        self.assertTrue(authority.db.in_transaction)
        errors = []
        def foreign():
            try:prefix.cleanup_retained_read(deadline=time.monotonic()+5,cancelled=lambda:False)
            except CapitalError as exc:errors.append(exc)
        thread = threading.Thread(target=foreign);thread.start();thread.join(timeout=5)
        self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1)
        self.assertTrue(authority.db.in_transaction)
        authority.db.set_authorizer(None)
        released = prefix.cleanup_retained_read(deadline=time.monotonic()+5,cancelled=lambda:False)
        self.assertEqual(released.status,'UNKNOWN');self.assertEqual(issue.cleanup_state,'RELEASED')
        self.assertFalse(authority.db.in_transaction)
        self.assertIsNone(getattr(authority,'_held_financial_retained_read',None))
        self.assertEqual(self.advance(prefix).reason,'LATCHED')
        # Only now can the original owner resume; cleanup grants nothing.
        authority.command('after-cleanup','runtime_publish',{},now)
        authority.verify_replay()
        self.assertGreaterEqual(len(denied),2)

    def test_execute_failure_after_real_begin_still_releases_owned_read(self):
        _, authority, _, _ = self.fixture();prefix = self.prefix(authority)
        original_one = module._one;primary = RuntimeError('execute_failed_after_begin')
        changes = authority.db.total_changes;trace = [];authority.db.set_trace_callback(trace.append)
        def one(db,sql,parameters=()):
            result = original_one(db,sql,parameters)
            if sql=='BEGIN':
                self.assertTrue(db.in_transaction)
                raise primary
            return result
        with patch.object(module,'_one',side_effect=one):value = self.advance(prefix)
        self.assertEqual(value.status,'UNKNOWN');self.assertIs(value.error,primary)
        self.assertFalse(authority.db.in_transaction)
        self.assertIsNone(getattr(authority,'_held_financial_retained_read',None))
        self.assertEqual(authority.db.total_changes,changes)
        self.assertIn('ROLLBACK',trace)


if __name__ == '__main__':
    unittest.main()
