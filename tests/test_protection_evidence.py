"""Offline proof core; synthetic shared/acquisition receipts, real old PaperBook.

These fixtures exercise receipt formats and verification failures. They are not
market timing, full shared-accounting replay or authenticated host evidence.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from meme_machine.runtime.protection_evidence import (
    NS, TABLE, ZERO, Limits, ProofError, ProtectionJournal,
    SQLiteReceiptResolver, Window, canonical, digest, verify_window)
from meme_machine.runtime.survivor_paper_book import PaperBook


class ProtectionEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {'MM_PORTFOLIO_ACCOUNTING_DB':'', 'MM_PAPER_EPOCH':''})
        env.start(); self.addCleanup(env.stop)
        self.book = PaperBook(self.root/'native.sqlite', run_id='proof', lane='survivor',
                              policy_hash='b'*64, initial=500)
        self.addCleanup(lambda:self.book.close())
        self.life = 'proof:one'
        self.book.reserve(self.life, 100, 100, {})
        self.book.transition(self.life, 'filled', 100, amount=100, tokens=10)
        self.birth = self.native_ref()
        self.before_position = deepcopy(self.book._load(self.life))
        self.book.transition(self.life, 'mark', 101, amount=99)
        self.mark = self.native_ref()
        self.identity = dict(source_sha256='a'*64, policy_sha256='b'*64,
            configuration_sha256='c'*64, epoch_id='paper-proof-1000', inception_sha256='d'*64,
            native_genesis_sha256=digest(self.book.identity), regime='pons_survivor')
        self.owner = dict(boot_id='offline-boot', pid=123, process_start_ticks=456,
                          generation='offline-process-generation')
        self.shared = sqlite3.connect(self.root/'shared.sqlite', isolation_level=None)
        self.addCleanup(self.shared.close)
        self.shared.execute('CREATE TABLE shared_capital_events(sequence INTEGER PRIMARY KEY, '
            'operation_id TEXT,body TEXT,result TEXT,state_hash TEXT,previous TEXT,hash TEXT)')
        self.shared.execute('CREATE TABLE fixture_acquisition(id TEXT PRIMARY KEY,body TEXT,hash TEXT)')
        self.shared.execute('CREATE TABLE fixture_usd(id TEXT PRIMARY KEY,body TEXT,hash TEXT)')
        self.usd_value = dict(evidence_id='synthetic-usd', evidence_sha256='e'*64,
            as_of='1970-01-01T00:01:30Z', valid_until='1970-01-01T00:05:00Z')
        self.birth_ack = self.shared_delivery(self.birth, 'enter')
        self.mark_ack = self.shared_delivery(self.mark, 'mark')
        self.census_rows = [dict(lifecycle_id=self.life, entry_hash=self.birth['hash'], terminal_hash=None)]
        self.resolver = SQLiteReceiptResolver(self.book.db, self.shared, self.census,
            lambda key:self.fixture_read('fixture_acquisition', key),
            lambda key:self.fixture_read('fixture_usd', key))
        self.journal = ProtectionJournal(self.book.db, self.identity)
        self.owner_record = dict(owner=self.owner, at_ns=0, wall_ns=100*NS, binding=self.identity)
        self.append('OWNER', self.owner_record)
        self.open_record = dict(owner=self.owner, at_ns=NS, wall_ns=101*NS,
            lifecycle_id=self.life, birth_ref=self.birth, native_ref=self.birth,
            shared_ref=self.birth_ack, due_ns=2*NS)
        self.append('OPEN', self.open_record)

    def native_ref(self):
        return dict(hash=self.book.db.execute('SELECT hash FROM journal ORDER BY seq DESC LIMIT 1').fetchone()[0])

    def shared_row(self, operation, action, data, result):
        row = self.shared.execute('SELECT sequence,hash FROM shared_capital_events ORDER BY sequence DESC LIMIT 1').fetchone()
        seq, previous = (row[0]+1, row[1]) if row else (1, ZERO)
        body = dict(operation_id=operation, action=action, at=101, data=data)
        raw, output, state = canonical(body), canonical(result), 'f'*64
        value = hashlib.sha256((previous+raw+output+state).encode()).hexdigest()
        self.shared.execute('INSERT INTO shared_capital_events VALUES(?,?,?,?,?,?,?)',
                            (seq, operation, raw, output, state, previous, value))
        return dict(sequence=seq, hash=value)

    def shared_delivery(self, native, kind):
        data = dict(lane='pons', native_id=self.life, event_key='native:'+native['hash'],
            journal_hash=native['hash'], kind=kind, data={}, at='1970-01-01T00:01:41Z',
            value_evidence=deepcopy(self.usd_value), metadata={})
        self.shared_row('intent:pons:'+native['hash'], 'runtime_prepare', data,
                        dict(epoch_id=self.identity['epoch_id']))
        return self.shared_row('ack:pons:'+native['hash'], 'runtime_commit',
            {key:data[key] for key in ('lane','native_id','event_key','journal_hash')}, dict(accepted=True))

    def fixture_write(self, table, key, body):
        self.shared.execute(f'INSERT OR REPLACE INTO {table} VALUES(?,?,?)',
                            (key, canonical(body), digest(body)))

    def fixture_read(self, table, key):
        row = self.shared.execute(f'SELECT body,hash FROM {table} WHERE id=?', (key,)).fetchone()
        if row is None:raise ProofError('fixture_receipt_missing')
        body = __import__('json').loads(row[0])
        if digest(body) != row[1]:raise ProofError('fixture_receipt_hash')
        return body

    def census(self, start, end):
        return dict(epoch_id=self.identity['epoch_id'], inception_sha256=self.identity['inception_sha256'],
            regime=self.identity['regime'], start_cursor=start, end_cursor=end,
            lifecycles=deepcopy(self.census_rows))

    def turn(self):
        q = dict(evidence_sha256='1'*64, profile='pons_survivor_shared_monitor',
            position_sha256=digest(self.before_position), quantity=10, source_generation='offline-source',
            provider_sha256='2'*64, block_id='100', block_sha256='3'*64,
            started_ns=2*NS, completed_ns=21*NS//10, deadline_ns=5*NS)
        u = dict(evidence_id='synthetic-usd', evidence_sha256='e'*64, acquisition_id='original-usd-read',
            acquisition_owner=self.owner, acquired_ns=2*NS, acquisition_completed_ns=22*NS//10,
            observed_wall_ns=90*NS, valid_until_wall_ns=300*NS, requested_ns=2*NS,
            lock_acquired_ns=2*NS, consumed_ns=23*NS//10, consumed_wall_ns=102*NS, mode='FRESH')
        timing = dict(due_ns=2*NS, started_ns=2*NS, deadline_ns=5*NS, decision_ns=22*NS//10,
            risk_completed_ns=23*NS//10, native_durable_ns=24*NS//10,
            shared_ack_ns=25*NS//10, completed_ns=26*NS//10, next_due_ns=56*NS//10)
        return dict(owner=self.owner, at_ns=26*NS//10, wall_ns=103*NS,
            lifecycle_id=self.life, turn=1, previous_turn=ZERO, outcome='COMPLETE', reason='native_hold',
            native_before=self.birth, native_after=self.mark, shared_ref=self.mark_ack,
            timing=timing, quote=q, usd=u, usd_requirement='REQUIRED')

    def bind_acquisitions(self, p):
        q, u = p['quote'], p['usd']
        if q is not None:
            self.fixture_write('fixture_acquisition', q['evidence_sha256'],
                dict(source_sha256=self.identity['source_sha256'], policy_sha256=self.identity['policy_sha256'],
                    regime=self.identity['regime'], quote=q, native_before=p['native_before'],
                    native_after=p['native_after'], usd_required=p['usd_requirement']=='REQUIRED'))
        if u is not None:
            keys = ('evidence_id','evidence_sha256','acquisition_id','acquisition_owner','acquired_ns',
                'acquisition_completed_ns','observed_wall_ns','valid_until_wall_ns')
            self.fixture_write('fixture_usd', u['acquisition_id'],
                dict(source_sha256=self.identity['source_sha256'], policy_sha256=self.identity['policy_sha256'],
                    **{key:u[key] for key in keys}))

    def append(self, kind, p):
        result = self.journal.try_append(kind, p)
        self.assertTrue(result.proof_available, result.failure)
        return result.receipt

    def append_turn(self, p=None):
        p = self.turn() if p is None else p
        self.bind_acquisitions(p)
        return self.append('TURN', p)

    def window(self, **changes):
        w = Window(self.identity, self.owner, NS, 4*NS, 101*NS, 104*NS,
                   self.birth_ack, self.mark_ack, self.journal.head())
        return replace(w, **changes)

    def check(self, w=None):
        return verify_window(self.book.db, self.window() if w is None else w, self.resolver)

    def test_actual_old_book_replay_and_reopen_ignore_additive_schema(self):
        financial = self.book.replay(); accounting = self.book.reconcile()
        rows = list(self.book.db.execute('SELECT * FROM journal ORDER BY seq'))
        self.append_turn()
        self.assertEqual(self.book.replay(), financial)
        self.assertEqual(self.book.reconcile(), accounting)
        self.assertEqual(list(self.book.db.execute('SELECT * FROM journal ORDER BY seq')), rows)
        self.book.close()
        self.book = PaperBook(self.root/'native.sqlite', run_id='proof', lane='survivor',
                              policy_hash='b'*64, initial=500)
        self.assertEqual(self.book.replay(), financial)
        self.assertEqual(self.book.reconcile(), accounting)
        self.assertEqual(self.book.identity['initial'], 500)
        # The old PaperBook has already reopened/replayed without consulting
        # the additive proof schema. Proof readers must now use its new native
        # connection rather than the closed connection from before the restart.
        self.journal = ProtectionJournal(self.book.db, self.identity)
        self.resolver = SQLiteReceiptResolver(self.book.db, self.shared, self.census,
            lambda key:self.fixture_read('fixture_acquisition', key),
            lambda key:self.fixture_read('fixture_usd', key))
        self.assertTrue(self.check().ok)

    def test_complete_required_path_resolves_actual_native_and_shared_sql_rows(self):
        self.append_turn()
        result = self.check()
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(result.held_coverage)
        self.assertTrue(result.native_path_resolved)
        self.assertEqual((result.lifecycles, result.turns), (1,1))
        self.assertIn('HOST_ATTESTATION_REQUIRED', result.scope)

    def test_does_not_commit_or_roll_back_existing_caller_transaction(self):
        head = self.journal.head()
        self.book.db.execute('BEGIN IMMEDIATE')
        self.book.db.execute("INSERT INTO runtime_state VALUES('proof','owner','{}','sentinel')")
        changes = self.book.db.total_changes
        result = self.journal.try_append('END', dict(owner=self.owner, at_ns=10*NS, wall_ns=110*NS))
        self.assertEqual(result.failure, 'caller_transaction_active')
        self.assertTrue(self.book.db.in_transaction)
        self.assertEqual(self.book.db.total_changes, changes)
        self.book.db.execute('COMMIT')
        self.assertEqual(self.journal.head(), head)
        self.assertIsNotNone(self.book.db.execute("SELECT 1 FROM runtime_state WHERE key='owner'").fetchone())

    def test_install_refuses_caller_transaction_before_any_mutation(self):
        self.book.db.execute('BEGIN IMMEDIATE')
        changes = self.book.db.total_changes
        with self.assertRaisesRegex(ProofError, 'caller_transaction_active'):
            ProtectionJournal(self.book.db, self.identity)
        self.assertTrue(self.book.db.in_transaction)
        self.assertEqual(self.book.db.total_changes, changes)
        self.book.db.execute('ROLLBACK')
        self.assertTrue(self.book.replay()['verified'])

    def test_wrong_native_owner_thread_cannot_touch_connection(self):
        before = self.journal.head(); results=[]
        worker = threading.Thread(target=lambda:results.append(
            self.journal.try_append('END', dict(owner=self.owner, at_ns=10*NS, wall_ns=110*NS))))
        worker.start(); worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].failure, 'native_owner_thread_required')
        self.assertEqual(self.journal.head(), before)

    def test_busy_proof_writer_restores_timeout_and_does_not_stop_native_replay(self):
        lock = sqlite3.connect(self.root/'native.sqlite', isolation_level=None)
        self.addCleanup(lock.close)
        timeout = self.book.db.execute('PRAGMA busy_timeout').fetchone()[0]
        lock.execute('BEGIN IMMEDIATE')
        result = self.journal.try_append('END', dict(owner=self.owner, at_ns=10*NS, wall_ns=110*NS))
        lock.execute('ROLLBACK')
        self.assertEqual(result.failure, 'proof_write_unavailable')
        self.assertEqual(self.book.db.execute('PRAGMA busy_timeout').fetchone()[0], timeout)
        self.assertFalse(self.book.db.in_transaction)
        self.assertTrue(self.book.replay()['verified'])

    def test_failed_owned_proof_transaction_rolls_back_only_its_own_rows(self):
        original = self.book.db
        class FailingCommit:
            @property
            def in_transaction(inner):return original.in_transaction
            def execute(inner, sql, *args):
                if sql == 'COMMIT':raise sqlite3.OperationalError('offline_commit_failure')
                return original.execute(sql, *args)
        before = self.journal.head(); financial = self.book.replay()
        self.journal.db = FailingCommit()
        result = self.journal.try_append('END', dict(owner=self.owner, at_ns=10*NS, wall_ns=110*NS))
        self.journal.db = original
        self.assertEqual(result.failure, 'proof_write_unavailable')
        self.assertFalse(original.in_transaction)
        self.assertEqual(self.journal.head(), before)
        self.assertEqual(self.book.replay(), financial)

    def test_append_only_and_idempotent_conflicting_retry(self):
        first = self.append('OWNER', self.owner_record)
        self.assertEqual(first, self.append('OWNER', self.owner_record))
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'protection_append_only'):
            self.book.db.execute(f'DELETE FROM {TABLE} WHERE sequence=1')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'protection_append_only'):
            self.book.db.execute(f"UPDATE {TABLE} SET body='{{}}' WHERE sequence=1")
        head = self.journal.head()
        result = self.journal.try_append('OWNER', dict(self.owner_record, at_ns=1))
        self.assertEqual(result.failure, 'conflicting_proof_receipt')
        self.assertEqual(self.journal.head(), head)

    def test_capacity_keeps_all_rows_and_never_accepts_prune_or_verified_flags(self):
        db = sqlite3.connect(':memory:', isolation_level=None); self.addCleanup(db.close)
        db.execute('CREATE TABLE journal(seq INTEGER PRIMARY KEY,body TEXT,previous TEXT,hash TEXT)')
        db.execute('CREATE TABLE genesis(id INTEGER PRIMARY KEY,body TEXT)')
        db.execute('INSERT INTO genesis VALUES(1,?)', (canonical(self.book.identity),))
        journal = ProtectionJournal(db, self.identity, limits=Limits(max_records=8))
        for i in range(7):
            p = dict(owner=dict(self.owner, generation=str(i)), at_ns=i, wall_ns=100*NS+i, binding=self.identity)
            self.assertTrue(journal.try_append('OWNER', p).proof_available)
        before = list(db.execute(f'SELECT * FROM {TABLE}'))
        result = journal.try_append('OWNER', dict(owner=dict(self.owner, generation='overflow'),
            at_ns=8, wall_ns=100*NS, binding=self.identity))
        self.assertEqual(result.failure, 'proof_storage_capacity')
        self.assertEqual(list(db.execute(f'SELECT * FROM {TABLE}')), before)
        self.assertFalse(hasattr(journal, 'prune'))
        self.assertFalse(hasattr(journal, 'mark_verified'))

    def test_payload_byte_capacity_is_a_stop_not_an_eviction(self):
        db = sqlite3.connect(':memory:', isolation_level=None); self.addCleanup(db.close)
        db.execute('CREATE TABLE journal(seq INTEGER PRIMARY KEY,body TEXT,previous TEXT,hash TEXT)')
        db.execute('CREATE TABLE genesis(id INTEGER PRIMARY KEY,body TEXT)')
        db.execute('INSERT INTO genesis VALUES(1,?)', (canonical(self.book.identity),))
        journal = ProtectionJournal(db, self.identity, limits=Limits(max_records=100, max_bytes=4096))
        for i in range(20):
            before = list(db.execute(f'SELECT * FROM {TABLE}'))
            p = dict(owner=dict(self.owner, boot_id='B'*256, generation=str(i)+'G'*250),
                     at_ns=i, wall_ns=100*NS+i, binding=self.identity)
            result = journal.try_append('OWNER', p)
            if result.failure:
                self.assertEqual(result.failure, 'proof_storage_capacity')
                self.assertEqual(list(db.execute(f'SELECT * FROM {TABLE}')), before)
                break
        else:self.fail('byte bound was not enforced')
        self.assertLess(journal.head()['sequence'], 100)

    def test_caller_success_flags_are_not_a_receipt(self):
        self.append_turn()
        self.resolver.native = lambda ref:dict(verified=True)
        self.assertFalse(self.check().ok)

    def test_missing_native_or_shared_committed_receipt_is_not_success(self):
        self.append_turn()
        self.shared.execute('DELETE FROM shared_capital_events WHERE sequence=?', (self.mark_ack['sequence'],))
        result = self.check()
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'shared_receipt_unavailable')

    def test_prepared_intent_and_forged_ack_result_do_not_count(self):
        self.append_turn()
        self.shared.execute("UPDATE shared_capital_events SET result='null' WHERE sequence=?", (self.mark_ack['sequence'],))
        self.assertEqual(self.check().reason, 'shared_hash_mismatch')

    def test_original_quote_and_risk_deadlines_are_not_reset(self):
        p = self.turn(); p['timing']['risk_completed_ns']=6*NS
        p['timing'].update(native_durable_ns=61*NS//10, shared_ack_ns=62*NS//10,
            completed_ns=63*NS//10, next_due_ns=9*NS)
        p['at_ns']=63*NS//10
        self.append_turn(p)
        result = self.check(self.window(end_ns=7*NS, end_wall_ns=107*NS))
        self.assertEqual(result.reason, 'original_protection_deadline_missed')

    def test_slow_durable_risk_mark_cannot_hide_behind_component_deadline(self):
        p = self.turn()
        p['timing'].update(native_durable_ns=10*NS, shared_ack_ns=11*NS,
            completed_ns=12*NS, next_due_ns=15*NS)
        p['at_ns']=12*NS; p['wall_ns']=112*NS
        self.append_turn(p)
        result = self.check(self.window(end_ns=13*NS, end_wall_ns=113*NS))
        self.assertEqual(result.reason, 'held_risk_delivery_deadline_missed')
        # This is a mark, not a native delayed fill. No 3-second fill bound
        # is introduced; execution profile wiring remains unimplemented.

    def test_profile_must_be_independently_bound_and_cannot_expand_numeric_limit(self):
        p = self.turn(); p['quote']['deadline_ns']=20*NS
        self.append_turn(p)
        self.assertEqual(self.check().reason, 'quote_original_deadline_missed')

    def test_cached_usd_keeps_original_identity_and_validity(self):
        p = self.turn(); p['usd'].update(mode='CACHE', acquired_ns=NS, acquisition_completed_ns=15*NS//10)
        self.append_turn(p)
        self.assertTrue(self.check().ok)
        original = self.fixture_read('fixture_usd', 'original-usd-read')
        original['acquired_ns']=2*NS
        self.fixture_write('fixture_usd', 'original-usd-read', original)
        self.assertEqual(self.check().reason, 'usd_original_acquisition_identity_mismatch')

    def test_usd_expiry_cannot_be_extended_by_a_current_timestamp(self):
        p = self.turn(); p['usd']['valid_until_wall_ns']=400*NS
        self.append_turn(p)
        self.assertEqual(self.check().reason, 'shared_usd_evidence_mismatch')

    def test_usd_boot_or_process_generation_cannot_be_reused_after_restart(self):
        p = self.turn(); p['usd']['acquisition_owner']=dict(self.owner, generation='old-generation')
        self.append_turn(p)
        self.assertEqual(self.check().reason, 'usd_acquisition_clock_domain')

    def test_unchanged_hold_usd_not_consumed_is_retained_not_full_protection_pass(self):
        p = self.turn(); p.update(native_after=self.birth, shared_ref=self.birth_ack,
            usd=None, usd_requirement='NOT_CONSUMED')
        p['timing'].update(native_durable_ns=None, shared_ack_ns=None)
        self.append_turn(p)
        result = self.check()
        self.assertFalse(result.ok)
        self.assertTrue(result.native_path_resolved)
        self.assertFalse(result.held_coverage)
        self.assertIn('USD_NOT_CONSUMED', result.reason)

    def test_failed_acquisition_is_durable_but_invalidates_window(self):
        p = self.turn(); p.update(outcome='FAILED', reason='provider_unavailable', quote=None,
            usd=None, usd_requirement='NOT_CONSUMED', shared_ref=None)
        self.append_turn(p)
        result = self.check()
        self.assertEqual(result.reason, 'held_turn_failed')
        self.assertEqual(self.journal.head()['sequence'], 4)
        self.assertTrue(self.book.replay()['verified'])

    def test_closed_between_samples_lifecycle_requires_real_terminal_and_census(self):
        self.append_turn()
        self.book.transition(self.life, 'settled', 102, amount=98)
        terminal = self.native_ref(); terminal_ack = self.shared_delivery(terminal, 'settle')
        self.append('CLOSE', dict(owner=self.owner, at_ns=3*NS, wall_ns=103*NS,
            lifecycle_id=self.life, native_ref=terminal, shared_ref=terminal_ack))
        self.census_rows[0]['terminal_hash']=terminal['hash']
        result = self.check(self.window(end_cursor=terminal_ack))
        self.assertTrue(result.ok, result.reason)
        self.census_rows=[]
        self.assertEqual(self.check(self.window(end_cursor=terminal_ack)).reason, 'lifetime_census_incomplete')

    def test_retired_or_missing_lifecycle_cannot_hide_behind_flat_samples(self):
        self.append_turn()
        self.census_rows.append(dict(lifecycle_id='proof:retired', entry_hash='4'*64, terminal_hash='5'*64))
        self.assertEqual(self.check().reason, 'lifetime_census_incomplete')

    def test_new_generation_and_uncompleted_crash_interval_fail(self):
        self.append_turn()
        self.append('OWNER', dict(owner=dict(self.owner, boot_id='new-boot', generation='replacement'),
            at_ns=1, wall_ns=104*NS, binding=self.identity))
        self.assertEqual(self.check().reason, 'window_owner_changed')

    def test_overdue_tail_and_missing_turn_cannot_be_reconstructed(self):
        self.append_turn()
        result = self.check(self.window(end_ns=20*NS, end_wall_ns=120*NS))
        self.assertEqual(result.reason, 'held_tail_coverage_gap')

    def test_pinned_earlier_head_cannot_hide_later_failure(self):
        self.append_turn(); earlier = self.journal.head()
        self.append('END', dict(owner=self.owner, at_ns=3*NS, wall_ns=103*NS))
        self.assertEqual(self.check(self.window(head=earlier)).reason, 'pinned_head_not_current_snapshot')

    def test_binding_epoch_and_native_genesis_are_not_caller_override_flags(self):
        self.append_turn()
        result = self.check(self.window(identity=dict(self.identity, inception_sha256='9'*64)))
        self.assertEqual(result.reason, 'proof_binding_mismatch')
        with self.assertRaisesRegex(ProofError, 'native_genesis_mismatch'):
            ProtectionJournal(self.book.db, dict(self.identity, native_genesis_sha256='8'*64))

    def test_reviewed_new_source_owner_preserves_old_proof_and_financial_rows(self):
        self.append_turn()
        before = list(self.book.db.execute(f'SELECT * FROM {TABLE} ORDER BY sequence'))
        financial = self.book.replay()
        changed = dict(self.identity, source_sha256='7'*64, configuration_sha256='6'*64)
        replacement = ProtectionJournal(self.book.db, changed)
        result = replacement.try_append('OWNER', dict(owner=dict(self.owner, generation='new-source'),
            at_ns=5*NS, wall_ns=105*NS, binding=changed))
        self.assertTrue(result.proof_available, result.failure)
        self.assertEqual(list(self.book.db.execute(f'SELECT * FROM {TABLE} WHERE sequence<=? ORDER BY sequence',
            (len(before),))), before)
        self.assertEqual(self.book.replay(), financial)
        self.assertEqual(self.check().reason, 'window_owner_changed')


if __name__ == '__main__':
    unittest.main()
