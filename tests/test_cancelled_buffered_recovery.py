"""Legacy source-task cancellation is not a returned WebSocket callback.

The native joined frames, committed queues, interrupted callback, closed join,
session and gaps are produced by the original offline buffered-log fixture.
Only the exact legacy admission hashes are adapted to those disposable bytes.
Native archive preparation, FULL publication, ACK and independent verification
remain the real production paths, without a source restart or provider call.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine import solana_source_drain as drain
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_plane import EvidenceUnavailable, canonical
from meme_machine.solana_rolling_history import program_scope
from tests import test_buffered_prejoin_recovery as buffered


CENSUS = 'd01237f6fa0e819de4ab6b8c3068f6c8ba5565fec67d20d1780c7b302dd0caec'
LEDGER = '97cafc5760e592ef574954bb49ba2b271852b676c66a504cfb73a9d55d9876b6'


class CancelledBufferedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(drain.CANCELLED_BUFFERED_CENSUS_SHA256, CENSUS)
        self.assertEqual(drain.CANCELLED_BUFFERED_LEDGER_SHA256, LEDGER)
        self.base = buffered.BufferedPrejoinRecoveryTests('runTest')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.db = self.base.db
        body = deepcopy(self.base.incident['failed'])
        body['unexpected_cancellation'] = True
        raw = canonical(body)
        self.base.put(drain.OBSERVATION_DRAIN_KEY, raw)
        self.base.incident.update(failed=body, failed_raw=raw)
        self.admission = self.enterContext(patch.object(drain, 'CANCELLED_BUFFERED_CENSUS_SHA256',
            hashlib.sha256(raw.encode()).hexdigest()))
        self.enterContext(patch.object(drain, 'CANCELLED_BUFFERED_LEDGER_SHA256',
            hashlib.sha256(self.base.incident['handler_raw'].encode()).hexdigest()))

    def assert_preserved(self):
        self.base.assert_incident_preserved()
        self.assertTrue(json.loads(self.base.value(drain.OBSERVATION_DRAIN_KEY))['unexpected_cancellation'])
        self.assertEqual(self.base.incident['failed']['pending_handlers'], 1)

    def test_exact_admission_earns_only_pure_bounds_not_recovery(self):
        before, changes = self.base.facts(), self.db.total_changes
        self.db.execute('PRAGMA query_only=ON')
        try:
            descriptor = self.base.descriptor()
        finally:
            self.db.execute('PRAGMA query_only=OFF')
        self.assertEqual(descriptor['input_class'], 'CANCELLED_SOURCE_BUFFERED_LOGS')
        self.assertEqual((descriptor['lower_slot'], descriptor['upper_slot']), (buffered.HEAD, buffered.UPPER))
        self.assertEqual(descriptor['closed_join_observation_id'], self.base.incident['join_id'])
        self.assertEqual(descriptor['closed_join_sha256'],
            hashlib.sha256(self.base.incident['join_raw'].encode()).hexdigest())
        self.assertEqual(descriptor['handler_records'],
            [r for r in json.loads(self.base.incident['handler_raw'])['records']
                if r['run'] == self.base.incident['run']])
        self.assertEqual(self.db.total_changes, changes)
        self.assertEqual(self.base.facts(), before)
        reference = self.base.preserve(descriptor)
        self.base.refused(reference)
        self.assert_preserved()

    def test_actual_archive_full_ack_recovers_economics_preserving_cancelled_terminal(self):
        reference = self.base.preserve()
        _, proofs = self.base.recover()
        result = self.base.verify(reference)
        self.assertEqual(result['input_class'], 'CANCELLED_SOURCE_BUFFERED_LOGS')
        self.assertEqual(result['proof_ids'], proofs)
        self.assertTrue(result['economic_interval_recovered'])
        self.assertFalse(result['callback_completion_demonstrated'])
        self.assertFalse(result['original_queue_acknowledgement_verified'])
        self.assertFalse(result['original_source_drain_pass'])
        self.assertFalse(result['full_subscription_completeness_claim'])
        self.assertEqual(result['retained_partitions'], {family: dict(
            prefix_lower_slot=buffered.FLOOR, prefix_upper_slot=buffered.HEAD-1,
            prefix_unavailable=True, prefix_missing_intervals=1,
            future_lower_slot=buffered.UPPER+1, future_upper_slot=None,
            future_open_tail=True, future_unavailable=True, future_missing_intervals=1)
            for family in buffered.FAMILIES})
        with closing(CandidateHistory(self.base.cache)) as history:
            self.assertEqual(history.db.execute('PRAGMA synchronous').fetchone()[0], 2)
            self.assertTrue(history.events('pump', self.base.base.mint))
            for proof in proofs.values():
                self.assertIsNotNone(history.db.execute('SELECT 1 FROM source_receipts WHERE id=?',
                    ('coverage:'+proof,)).fetchone())
        boundary = drain.historical_observation_boundary(self.base.state)
        self.assertTrue(boundary['session_economic_recovery_verified'])
        self.assertFalse(boundary['historical_recovery_verified'])
        self.assertEqual(self.db.execute('SELECT DISTINCT slot FROM candidate_blocks').fetchall(), [(buffered.HEAD,)])
        self.assert_preserved()

    def test_archive_without_original_full_ack_is_not_economic_recovery(self):
        reference = self.base.preserve()
        _, proofs = self.base.recover(acknowledge_rows=False)
        self.base.refused(reference)
        self.base.publish(tuple(proofs.values()))
        self.assertTrue(self.base.verify(reference)['economic_interval_recovered'])
        self.assert_preserved()

    def test_default_input_validator_and_unselected_cancellation_still_refuse(self):
        with self.assertRaises(EvidenceUnavailable):
            drain._buffered_log_inputs(self.db, self.base.incident['failed_raw'],
                self.base.incident['handler_raw'], self.base.incident['observation_id'])
        with patch.object(drain, 'CANCELLED_BUFFERED_CENSUS_SHA256', '0' * 64):
            with self.assertRaises(EvidenceUnavailable):
                self.base.descriptor()
        self.assert_preserved()

    def test_both_full_legacy_hashes_and_literal_mode_are_required(self):
        args = (self.db, self.base.incident['failed_raw'], self.base.incident['handler_raw'],
            self.base.incident['observation_id'])
        for name in ('CANCELLED_BUFFERED_CENSUS_SHA256', 'CANCELLED_BUFFERED_LEDGER_SHA256'):
            with self.subTest(name=name), patch.object(drain, name, '0' * 64):
                with self.assertRaises(EvidenceUnavailable):
                    drain._buffered_log_inputs(*args, _cancelled_source=True)
        with self.assertRaises(EvidenceUnavailable):
            drain._buffered_log_inputs(*args, _cancelled_source=1)
        self.assert_preserved()

    def test_semantic_census_and_source_lifetime_checks_survive_adapted_hashes(self):
        original = self.base.incident['failed']
        changes = [dict(unexpected_cancellation=False), dict(terminal=False),
            dict(terminal_record_unavailable=True), dict(all_accepted_committed=False),
            dict(unpreserved_sessions=1), dict(closed_sessions=1),
            dict(preserved_partial_sessions=0), dict(closed_sessions=True),
            dict(terminal_at_monotonic=original['started_at_monotonic']),
            dict(started_at_monotonic=True)]
        body = deepcopy(original);body['handler_accounting']['active'] = 1
        changes.append(body)
        for change in changes:
            with self.subTest(change=tuple(change)), self.base.changed_owner():
                raw = canonical(dict(original, **change))
                self.base.put(drain.OBSERVATION_DRAIN_KEY, raw)
                with patch.object(drain, 'CANCELLED_BUFFERED_CENSUS_SHA256',
                        hashlib.sha256(raw.encode()).hexdigest()):
                    with self.assertRaises(EvidenceUnavailable):
                        self.base.descriptor()
        self.assert_preserved()

    def test_current_ledger_scope_phase_session_and_gap_are_real_proof_not_hash_substitutes(self):
        changes = (dict(phase='LOG_JOIN'), dict(session='a' * 32),
            dict(source_pid=self.base.incident['failed']['source_pid']+1),
            dict(scope_hash='a' * 64), dict(scope_count=2),
            dict(recovery=dict(kind='CANDIDATE_GAPS', gap_ids=[self.base.incident['gaps'][0]])))
        for change in changes:
            with self.subTest(change=tuple(change)), self.base.changed_owner():
                value = json.loads(self.base.incident['handler_raw'])
                for row in value['records']:
                    if row['run'] == self.base.incident['run']:
                        row.update(change)
                raw = canonical(value)
                self.base.put(drain.HANDLER_RECOVERY_KEY, raw)
                with patch.object(drain, 'CANCELLED_BUFFERED_LEDGER_SHA256',
                        hashlib.sha256(raw.encode()).hexdigest()):
                    with self.assertRaises(EvidenceUnavailable):
                        self.base.descriptor()
        self.assert_preserved()

    def test_closed_join_native_heads_and_gap_origins_are_independently_required(self):
        fixtures = (
            ('UPDATE acquisition_observations SET body=? WHERE id=?',
                (canonical(dict(json.loads(self.base.incident['join_raw']), completed=buffered.HEAD+1)),
                    self.base.incident['join_id'])),
            ('DELETE FROM acquisition_observations WHERE id=?', (self.base.incident['join_id'],)),
            ('UPDATE candidate_blocks SET slot=slot+1 WHERE scope=?', (program_scope('pump'),)),
            ('UPDATE candidate_gaps SET lo=lo+1 WHERE id=?', (self.base.incident['gaps'][0],)))
        for sql, args in fixtures:
            with self.subTest(sql=sql), self.base.changed_owner():
                self.db.execute(sql, args)
                with self.assertRaises(EvidenceUnavailable):
                    self.base.descriptor()
        self.assert_preserved()

    def test_restart_verifier_requires_actual_consumer_receipt_after_real_archive(self):
        reference = self.base.preserve()
        _, proofs = self.base.recover()
        self.assertTrue(self.base.verify(reference)['economic_interval_recovered'])
        for family, proof in proofs.items():
            with self.subTest(family=family), closing(sqlite3.connect(self.base.cache, isolation_level=None)) as history:
                row = history.execute('SELECT * FROM source_receipts WHERE id=?', ('coverage:'+proof,)).fetchone()
                self.assertIsNotNone(row)
                history.execute('DELETE FROM source_receipts WHERE id=?', ('coverage:'+proof,))
                try:
                    self.base.refused(reference)
                finally:
                    count = len(row)
                    history.execute('INSERT INTO source_receipts VALUES('+','.join('?' for _ in range(count))+')', row)
        self.assertTrue(self.base.verify(reference)['economic_interval_recovered'])
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
