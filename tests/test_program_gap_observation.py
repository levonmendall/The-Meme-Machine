"""Exact retained program-gap observation; disposable canonical state only.

Production hashes are asserted before patching three synthetic fixture hashes.
No fixture outcome is a production callback disposition, ACK, or recovery proof.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

from meme_machine import solana_source_drain as drain
from meme_machine.solana_evidence_plane import EvidenceUnavailable
from meme_machine.solana_rolling_history import program_scope
from tests import test_contained_source_observation as fixture_module


PRODUCTION_HASHES = dict(
    PROGRAM_GAP_OBSERVATION_SHA256='948743b18d0a33cc85391d07ea4a4ae9dad34110c169ca95945a04473d6db228',
    PROGRAM_GAP_HANDLER_SHA256='29f00e3d71c40e1d306f50263b84f1ec25e455e20d112a5f04fdef25293d0fb0',
    PROGRAM_GAP_SESSION_SHA256='886dc272c37139e53dac962fda1473fc6eca4e8b2daf462495cb50509a831333')
SESSION = '41265de5e5164b90a108688caf6b1d73'
SESSION_AT = 1792187653.3547058
RUN = 'e' * 32
PID = 137773
LOWER = 457794040
HANDLER_SLOT = 457794201


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def checksum(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class ProgramGapObservationTests(fixture_module.ObservationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.production_program_hashes = {key: getattr(drain, key) for key in PRODUCTION_HASHES}
        # Synthetic fixture baseline has an acknowledged canonical outbox row.
        # The unrelated old pending proof remains present and unavailable.
        self.db.execute("UPDATE candidate_history_outbox SET consumed=? WHERE id='old-history'", (SESSION_AT,))
        self.pending_proofs = self.db.execute('SELECT * FROM candidate_pending_proofs').fetchall()
        self.record = dict(id=60266, run=RUN, source_pid=PID, native_thread_id=9,
            stream='fixture-rolling-pumpswap', session=SESSION, transport='websocket',
            family='candidate_logs', kind='log_or_ack', slot=HANDLER_SLOT, identity=None,
            seen=SESSION_AT - .3, started_monotonic=11.0, phase='LOG_BUFFER_WAIT',
            state='RECOVERABLE', failure_state='INTERRUPTED', error_type='CancelledError',
            scope_count=1, scope_hash=drain.HandlerLedger.scope_hash((program_scope('pumpswap'),)),
            recovery=dict(kind='CANDIDATE_GAPS', gap_ids=[39593]))
        self.handler_body = dict(version=1, records=[self.record])
        self.handler_raw = encode(self.handler_body)
        self.failed = self.marker(state='RECOVERY_REQUIRED', accepted_handlers=60346,
            settled_handlers=60345, pending_handlers=1, source_pid=PID, run_identity=RUN,
            closed_sessions=2, preserved_partial_sessions=1,
            queues={name: dict(accepted=count, committed=count, pending=0)
                for name, count in (('control', 556), ('rolling', 65), ('scout', 4120), ('candidate', 0))})
        self.failed['handler_accounting'] = dict(version=1, valid=True, run=RUN, pid=PID,
            native_thread_id=9, accepted=60346, returned=60345, active=0, recoverable=1,
            failed=0, unresolved=0, records=[deepcopy(self.record)])
        self.failed_raw = encode(self.failed)
        self.session_body = dict(plane='rolling', session=SESSION, drained=False,
            accepted_pending=0, accepted_pending_bytes=0, pending_slots=0, pending_bytes=0,
            early_log_min_slot=457794105, early_log_max_slot=HANDLER_SLOT,
            early_log_count=1, early_log_bytes=128, replay_from_slot=LOWER,
            recovery_obligations=[dict(scope=program_scope(family), lower_slot=LOWER, upper_slot=None)
                for family in ('pump', 'pumpswap')],
            handler_dispositions=[deepcopy(self.record)], complete_history_claim=False)
        self.session_raw = encode(self.session_body)
        self.put(drain.HANDLER_RECOVERY_KEY, self.handler_raw)
        self.put(drain.OBSERVATION_DRAIN_KEY, self.failed_raw)
        self.db.execute('''INSERT INTO acquisition_observations(id,job,kind,at,body)
            VALUES(231522,NULL,'source_session_drain',?,?)''', (SESSION_AT, self.session_raw))
        self.db.executemany('''INSERT INTO candidate_gaps(id,scope,lo,hi,created,repaired,reason)
            VALUES(?,?,?,NULL,?,NULL,'candidate_live_disconnect_or_filter_rebuild')''',
            [(39592, program_scope('pump'), LOWER, 1792187653.1304228),
             (39593, program_scope('pumpswap'), LOWER, 1792187653.352859)])
        for key, raw in (('PROGRAM_GAP_OBSERVATION_SHA256', self.failed_raw),
                ('PROGRAM_GAP_HANDLER_SHA256', self.handler_raw),
                ('PROGRAM_GAP_SESSION_SHA256', self.session_raw)):
            self.enterContext(patch.object(drain, key, checksum(raw)))

    def refused(self):
        before = self.facts()
        with self.assertRaises(EvidenceUnavailable):
            drain.historical_observation_boundary(self.state)
        self.assertEqual(self.facts(), before)

    def begin_known(self):
        started = self.current(state='RUNNING')
        started.update(historical_unknown_handlers=2,
            historical_source_drain_sha256=self.old_hash, historical_recovery_verified=False)
        boundary = drain.begin_source_observation(self.state, self.old_raw, started,
            handler_boundary=self.handler_raw)
        return started, boundary

    def finish_known(self, started, boundary, **changes):
        terminal = dict(started, state='DRAINED', terminal=True,
            terminal_at_monotonic=started['started_at_monotonic'] + 1)
        terminal.update(changes)
        drain.publish_source_drain(self.state, self.old_raw, terminal,
            handler_boundary=self.handler_raw, contained_observation=True,
            observation_boundary=boundary)
        return terminal

    def archive_key(self, key, raw):
        return key + '_preserved.' + checksum(raw)

    def test_exact_production_hashes_are_asserted_before_synthetic_fixture_patches(self):
        self.assertEqual(self.production_program_hashes, PRODUCTION_HASHES)
        for key, expected in PRODUCTION_HASHES.items():
            self.assertNotEqual(getattr(drain, key), expected)

    def test_exact_locator_is_read_only_observation_and_preserves_pending_proof(self):
        before = self.facts()
        changes = self.db.total_changes
        self.db.execute('PRAGMA query_only=ON')
        try:
            result = drain.historical_observation_boundary(self.state)
            self.assertEqual(result, drain.historical_observation_boundary(self.db))
        finally:
            self.db.execute('PRAGMA query_only=OFF')
        self.assertTrue(result['eligible'])
        self.assertEqual(result['current_observation_state'], 'PRESERVED_PROGRAM_GAP')
        self.assertTrue(result['program_gap_unavailable'])
        self.assertTrue(result['unreturned_observation_retained'])
        self.assertEqual(result['retained_unreturned_observations'], 1)
        self.assertFalse(result['historical_callback_completion'])
        self.assertFalse(result['current_handler_disposition_verified'])
        self.assertFalse(result['historical_recovery_verified'])
        self.assertEqual(self.db.total_changes, changes)
        self.assertEqual(self.facts(), before)
        self.assertEqual(self.db.execute('SELECT * FROM candidate_pending_proofs').fetchall(), self.pending_proofs)
        self.runtime_guard.assert_not_called()

    def test_normal_still_refuses_and_contained_retention_still_requires_funding_closure(self):
        before = self.facts()
        with self.assertRaisesRegex(EvidenceUnavailable, 'source_drain_historical_handlers_unlocated'):
            drain.retained_source_drain(self.state)
        self.assertEqual(drain.retained_source_drain(self.state, contained_observation=True), self.old_raw)
        self.runtime_guard.assert_called_once_with()
        self.runtime_guard.side_effect = EvidenceUnavailable('fixture funding closure rejected')
        with self.assertRaises(EvidenceUnavailable):
            drain.retained_source_drain(self.state, contained_observation=True)
        self.assertEqual(self.facts(), before)

    def test_begin_archives_exact_failed_observation_and_handler_then_exposes_crash(self):
        _, boundary = self.begin_known()
        self.assertEqual(self.value(self.archive_key(drain.OBSERVATION_DRAIN_KEY, self.failed_raw)), self.failed_raw)
        self.assertEqual(self.value(self.archive_key(drain.HANDLER_RECOVERY_KEY, self.handler_raw)), self.handler_raw)
        self.assertEqual(self.value(drain.SOURCE_DRAIN_KEY), self.old_raw)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), self.handler_raw)
        self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY), boundary)
        self.assertEqual(json.loads(boundary)['state'], 'RUNNING')
        self.refused()

    def test_clean_new_terminal_can_restart_with_same_known_unreturned_handler_still_explicit(self):
        started, boundary = self.begin_known()
        terminal = self.finish_known(started, boundary)
        result = drain.historical_observation_boundary(self.state)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['current_observation_state'], 'DRAINED')
        self.assertTrue(result['program_gap_unavailable'])
        self.assertEqual(result['retained_unreturned_observations'], 1)
        self.assertFalse(result['historical_callback_completion'])
        self.assertFalse(result['current_handler_disposition_verified'])
        self.assertEqual(json.loads(self.value(drain.OBSERVATION_DRAIN_KEY)), terminal)
        self.assertEqual(self.value(drain.SOURCE_DRAIN_KEY), self.old_raw)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), self.handler_raw)
        with closing(sqlite3.connect(self.state.writer.path.as_uri() + '?mode=ro', uri=True)) as reader:
            reader.execute('PRAGMA query_only=ON')
            self.assertTrue(drain.historical_observation_boundary(reader)['eligible'])
        with self.assertRaises(EvidenceUnavailable):
            drain.retained_source_drain(self.state)

    def test_new_failed_terminal_is_not_folded_into_the_known_exception(self):
        started, boundary = self.begin_known()
        self.finish_known(started, boundary, state='RECOVERY_REQUIRED',
            accepted_handlers=1, settled_handlers=0, pending_handlers=1)
        self.refused()
        self.assertEqual(self.value(drain.SOURCE_DRAIN_KEY), self.old_raw)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), self.handler_raw)

    def test_different_or_additional_current_handler_never_reuses_known_locator(self):
        for records in ([dict(self.record, id=60265)],
                [self.record, dict(self.record, id=60265, run='f' * 32)]):
            with self.subTest(records=len(records)):
                self.put(drain.HANDLER_RECOVERY_KEY, encode(dict(version=1, records=records)))
                self.refused()
        self.put(drain.HANDLER_RECOVERY_KEY, self.handler_raw)

    def test_source_pinned_observation_handler_and_session_bytes_are_all_required(self):
        for key, raw in ((drain.OBSERVATION_DRAIN_KEY, self.failed_raw),
                (drain.HANDLER_RECOVERY_KEY, self.handler_raw)):
            with self.subTest(key=key):
                self.put(key, raw + ' ')
                self.refused()
                self.put(key, raw)
        self.db.execute('UPDATE acquisition_observations SET body=? WHERE id=231522', (self.session_raw + ' ',))
        self.refused()

    def test_incomplete_census_or_different_queue_count_refuses_even_with_fixture_hash_repin(self):
        cases = [dict(accepted_handlers=60347, settled_handlers=60346),
            dict(pending_handlers=0, settled_handlers=60346), dict(terminal=False),
            dict(closed_sessions=3), dict(preserved_partial_sessions=2),
            dict(unpreserved_sessions=1), dict(unexpected_cancellation=True)]
        bodies = [dict(self.failed, **change) for change in cases]
        bad_queue = deepcopy(self.failed)
        bad_queue['queues']['rolling'].update(accepted=66, committed=66)
        bodies.append(bad_queue)
        for body in bodies:
            raw = encode(body)
            with self.subTest(body=body), patch.object(drain, 'PROGRAM_GAP_OBSERVATION_SHA256', checksum(raw)):
                self.put(drain.OBSERVATION_DRAIN_KEY, raw)
                self.refused()
        self.put(drain.OBSERVATION_DRAIN_KEY, self.failed_raw)

    def test_wrong_handler_phase_scope_or_disposition_cannot_become_known_gap(self):
        for change in (dict(phase='LOG_JOIN'), dict(scope_hash='b' * 64),
                dict(state='INTERRUPTED'), dict(slot=HANDLER_SLOT + 1),
                dict(recovery=dict(kind='CANDIDATE_GAPS', gap_ids=[39592]))):
            raw = encode(dict(version=1, records=[dict(self.record, **change)]))
            with self.subTest(change=change), patch.object(drain, 'PROGRAM_GAP_HANDLER_SHA256', checksum(raw)):
                self.put(drain.HANDLER_RECOVERY_KEY, raw)
                self.refused()
        self.put(drain.HANDLER_RECOVERY_KEY, self.handler_raw)

    def test_session_plane_identity_dispositions_and_complete_obligation_set_are_required(self):
        changes = [dict(plane='candidate'), dict(session='f' * 32), dict(drained=True),
            dict(accepted_pending=1), dict(pending_slots=1), dict(handler_dispositions=[]),
            dict(recovery_obligations=self.session_body['recovery_obligations'][:1]),
            dict(recovery_obligations=list(reversed(self.session_body['recovery_obligations'])))]
        for change in changes:
            raw = encode(dict(self.session_body, **change))
            with self.subTest(change=change), patch.object(drain, 'PROGRAM_GAP_SESSION_SHA256', checksum(raw)):
                self.db.execute('UPDATE acquisition_observations SET body=? WHERE id=231522', (raw,))
                self.refused()
        self.db.execute('UPDATE acquisition_observations SET body=? WHERE id=231522', (self.session_raw,))

    def test_original_gap_scope_bounds_origin_time_and_reason_remain_authoritative(self):
        changes = [('scope', program_scope('pump')), ('lo', LOWER + 1),
            ('hi', HANDLER_SLOT - 1), ('created', SESSION_AT + 1),
            ('created', 1792187653.352858), ('reason', 'different_recovery_reason')]
        original = self.db.execute('SELECT scope,lo,hi,created,repaired,reason FROM candidate_gaps WHERE id=39593').fetchone()
        for column, value in changes:
            with self.subTest(column=column, value=value):
                self.db.execute('UPDATE candidate_gaps SET ' + column + '=? WHERE id=39593', (value,))
                self.refused()
                self.db.execute('''UPDATE candidate_gaps SET scope=?,lo=?,hi=?,created=?,repaired=?,reason=?
                    WHERE id=39593''', original)

    def test_repaired_original_gap_is_refused_even_if_an_open_residual_exists(self):
        self.db.execute('UPDATE candidate_gaps SET repaired=? WHERE id=39593', (SESSION_AT + 1,))
        self.db.execute('''INSERT INTO candidate_gaps(id,scope,lo,hi,created,repaired,reason)
            VALUES(39999,?,?,NULL,?,NULL,'candidate_live_disconnect_or_filter_rebuild')''',
            (program_scope('pumpswap'), LOWER, 1792187653.352859))
        self.refused()

    def test_original_handoff_can_bound_open_gaps_without_repairing_or_hiding_old_slot(self):
        self.db.execute('UPDATE candidate_gaps SET hi=? WHERE id IN (39592,39593)', (HANDLER_SLOT + 300,))
        before = self.facts()
        result = drain.historical_observation_boundary(self.state)
        self.assertTrue(result['eligible'])
        self.assertTrue(result['program_gap_unavailable'])
        self.assertEqual(self.db.execute('SELECT id,repaired FROM candidate_gaps WHERE id IN (39592,39593) ORDER BY id').fetchall(),
            [(39592, None), (39593, None)])
        self.assertEqual(self.facts(), before)

    def test_pending_control_or_unacknowledged_canonical_program_rows_block_observation(self):
        drain.preserve_control_recovery(self.state, HANDLER_SLOT, HANDLER_SLOT)
        self.refused()
        self.db.execute('DELETE FROM service_health WHERE key=?', (drain.CONTROL_RECOVERY_KEY,))
        self.db.execute("UPDATE candidate_history_outbox SET consumed=NULL WHERE id='old-history'")
        self.refused()
        self.assertEqual(self.db.execute('SELECT * FROM candidate_pending_proofs').fetchall(), self.pending_proofs)

    def test_missing_session_or_different_observation_kind_cannot_use_external_summary(self):
        self.db.execute("UPDATE acquisition_observations SET kind='source_session_summary' WHERE id=231522")
        self.refused()
        self.db.execute('DELETE FROM acquisition_observations WHERE id=231522')
        self.refused()

    def test_archive_collision_rolls_back_both_archives_and_running_marker(self):
        for key, raw in ((drain.OBSERVATION_DRAIN_KEY, self.failed_raw),
                (drain.HANDLER_RECOVERY_KEY, self.handler_raw)):
            archive = self.archive_key(key, raw)
            self.put(archive, 'different immutable original')
            before = self.facts()
            with self.subTest(key=key), self.assertRaises(EvidenceUnavailable):
                self.begin_known()
            self.assertEqual(self.facts(), before)
            self.assertEqual(self.value(drain.OBSERVATION_DRAIN_KEY), self.failed_raw)
            self.db.execute('DELETE FROM service_health WHERE key=?', (archive,))

    def test_outer_owner_rollback_restores_failed_marker_and_both_archive_absences(self):
        before = self.facts()
        with self.assertRaisesRegex(RuntimeError, 'fixture rollback after begin'):
            with self.state.writer.transaction():
                self.begin_known()
                raise RuntimeError('fixture rollback after begin')
        self.assertEqual(self.facts(), before)
        self.assertEqual(self.value(drain.SOURCE_DRAIN_KEY), self.old_raw)
        self.assertEqual(self.value(drain.HANDLER_RECOVERY_KEY), self.handler_raw)


if __name__ == '__main__':
    unittest.main()
