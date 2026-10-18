"""Dormant prefix observer over real temporary native/shared transactions.

Provider/qualification/owner readiness are the original explicit offline
fixtures.  No test claims live owner provenance or held protection authority.
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
from meme_machine.runtime.held_financial_prefix import _FinancialPrefix
from meme_machine.shared_capital import CapitalError
from meme_machine.shared_capital.model import canonical, digest
from meme_machine.shared_capital.runtime import RuntimeCapital
from tests import test_pump_pons_capital_preparation as fixtures


class HeldFinancialPrefixTests(unittest.TestCase):
    fixture = fixtures.RuntimeIntegrationTests.fixture

    def prefix(self, authority):
        proof = authority.verify_replay()
        return _FinancialPrefix(authority, authority.ledger(), proof)

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

    def test_initial_cut_uses_original_replay_cache_without_scan_or_new_connection(self):
        _, authority, _, _ = self.fixture()
        proof = authority.verify_replay();state = authority.ledger()
        changes = authority.db.total_changes
        with patch.object(authority, '_authenticated_replay_prefix', side_effect=AssertionError('full scan')), \
                patch.object(authority, 'verify_replay', side_effect=AssertionError('second replay')), \
                patch('sqlite3.connect', side_effect=AssertionError('new connection')):
            prefix = _FinancialPrefix(authority, state, proof)
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

    def test_missing_cache_or_supplied_state_and_proof_cannot_bootstrap(self):
        from meme_machine.shared_capital import authority as original
        _, authority, _, _ = self.fixture()
        proof = authority.verify_replay();state = authority.ledger()
        changed = dict(state, at=state['at']+1)
        for supplied, summary in ((changed,proof), (state,dict(proof,events=proof['events']+1)),
                                   (state,dict(proof,conservation=False))):
            with self.assertRaises(CapitalError):_FinancialPrefix(authority, supplied, summary)
        key = authority._replay_prefix_key()
        with original._REPLAY_PREFIX_LOCK:cached = original._REPLAY_PREFIXES.pop(key)
        try:
            with self.assertRaisesRegex(CapitalError, 'initial_replay_unavailable'):
                _FinancialPrefix(authority, state, proof)
        finally:
            with original._REPLAY_PREFIX_LOCK:original._REPLAY_PREFIXES[key] = cached

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
        thread = threading.Thread(target=lambda:values.append(self.advance(prefix)))
        thread.start();thread.join(timeout=5);self.assertFalse(thread.is_alive())
        self.assertEqual(values[0].reason,'FOREIGN_OWNER');self.assertEqual(trace,[])
        with patch.object(module.os,'getpid',return_value=os.getpid()+100000):
            self.assertEqual(self.advance(prefix).reason,'FOREIGN_OWNER')
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

    def test_missing_interval_stays_incomplete_until_exact_original_rows_exist(self):
        _, authority, now, _ = self.fixture();prefix = self.prefix(authority)
        authority.command('first','runtime_publish',{},now)
        authority.command('second','runtime_publish',{},now+1)
        lost = authority.db.execute('SELECT * FROM shared_capital_events WHERE sequence=?',
                                    (prefix._sequence+1,)).fetchone()
        authority.db.execute('DROP TRIGGER shared_capital_no_delete')
        authority.db.execute('DELETE FROM shared_capital_events WHERE sequence=?',(lost[0],))
        value = self.advance(prefix)
        self.assertEqual(value.status,'INCOMPLETE');self.assertEqual(value.reason,'MISSING_SEQUENCE')
        self.assertEqual(value.rows,0)
        # Restore the exact real committed row, never a supplied substitute hash.
        authority.db.execute('INSERT INTO shared_capital_events VALUES(?,?,?,?,?,?,?)',lost)
        value = self.advance(prefix)
        self.assertEqual(value.status,'COVERED_CUT')
        self.assertEqual(value.state_sha256,authority.verify_replay()['state_sha256'])

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
                authority.command('new','runtime_publish',{},now)
                row = list(authority.db.execute('SELECT * FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone())
                authority.db.execute('DROP TRIGGER shared_capital_no_update')
                if corrupt=='parent':row[5] = 'f'*64
                elif corrupt=='result':row[3] = canonical({'accepted':False})
                elif corrupt=='state_hash':row[4] = 'f'*64
                else:row[2] += ' '*(module._MAX_BYTES+1)
                row[6] = hashlib.sha256((row[5]+row[2]+row[3]+row[4]).encode()).hexdigest()
                authority.db.execute('UPDATE shared_capital_events SET body=?,result=?,state_hash=?,previous=?,hash=? WHERE sequence=?',
                                     (row[2],row[3],row[4],row[5],row[6],row[0]))
                changes = authority.db.total_changes;value = self.advance(prefix)
                self.assertEqual(value.status,'UNKNOWN');self.assertIsInstance(value.error,CapitalError)
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


if __name__ == '__main__':
    unittest.main()
