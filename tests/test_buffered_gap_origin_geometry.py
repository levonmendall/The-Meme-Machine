"""FULL publication may split a disconnect gap before descriptor preservation.

The actual buffered-source fixture, archive producer and FULL consumer create
the split rows. No gap identity, coverage predicate or recovery proof is mocked.
All providers and canonical/financial stores are disposable offline fixtures.
"""
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest

from meme_machine import solana_source_drain as drain
from meme_machine.solana_evidence_plane import EvidenceUnavailable,canonical
from meme_machine.solana_rolling_history import program_scope
from tests import test_buffered_prejoin_recovery as buffered


class BufferedGapOriginGeometryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=buffered.BufferedPrejoinRecoveryTests('runTest')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.db=self.fixture.db
        self.origins={family:self.db.execute('SELECT id,scope,lo,hi,created,reason,repaired '
            'FROM candidate_gaps WHERE id=?',(identity,)).fetchone()
            for family,identity in zip(buffered.FAMILIES,self.fixture.incident['gaps'])}
        # No descriptor has been requested or preserved for this incident.
        # Genuine prefix publication repairs each original open gap and adds
        # an active same-floor residual which cannot cover the buffered upper.
        self.prefix_proofs=self.fixture.recover_partition(buffered.FLOOR+1,buffered.HEAD-1)
        self.residuals={}
        for family,origin in self.origins.items():
            rows=self.db.execute('SELECT id,scope,lo,hi,created,reason,repaired FROM candidate_gaps '
                'WHERE scope=? AND lo=? AND created=? AND reason=? ORDER BY id',
                (origin[1],buffered.FLOOR,origin[4],origin[5])).fetchall()
            self.assertEqual(len(rows),2)
            root,residual=rows
            self.assertEqual(root[:6],origin[:6]);self.assertIsNotNone(root[6])
            self.assertEqual(residual[2:4],(buffered.FLOOR,buffered.FLOOR))
            self.assertIsNone(residual[6]);self.residuals[family]=residual

    def refused_descriptor(self):
        before=self.fixture.facts()
        with self.assertRaises(EvidenceUnavailable):self.fixture.descriptor()
        self.assertEqual(self.fixture.facts(),before)

    def test_first_descriptor_after_real_publication_keeps_original_root_through_restart(self):
        before=self.fixture.facts();descriptor=self.fixture.descriptor()
        self.assertEqual(self.fixture.facts(),before)
        self.assertEqual((descriptor['lower_slot'],descriptor['upper_slot']),
            (buffered.HEAD,buffered.UPPER))
        for family,origin in self.origins.items():
            self.assertEqual(descriptor['gap_origins'][family]['id'],origin[0])
            self.assertNotEqual(descriptor['gap_origins'][family]['id'],self.residuals[family][0])
        reference=self.fixture.preserve(descriptor)
        self.fixture.refused(reference)
        _jobs,proofs=self.fixture.recover()
        result=self.fixture.verify(reference)
        self.assertEqual(result['proof_ids'],proofs)
        self.assertTrue(result['economic_interval_recovered'])
        self.assertFalse(result['callback_completion_demonstrated'])
        self.assertFalse(result['original_queue_acknowledgement_verified'])
        self.assertFalse(result['original_source_drain_pass'])
        for family in buffered.FAMILIES:
            partition=result['retained_partitions'][family]
            self.assertEqual((partition['prefix_lower_slot'],partition['prefix_upper_slot']),
                (buffered.FLOOR,buffered.HEAD-1))
            self.assertTrue(partition['prefix_unavailable'])
            self.assertEqual(partition['prefix_missing_intervals'],1)
            self.assertTrue(partition['future_open_tail'])
            self.assertTrue(partition['future_unavailable'])
        self.assertEqual(self.fixture.descriptor(),descriptor)
        self.fixture.assert_incident_preserved()
        self.fixture.clean_session()
        result=drain.historical_observation_boundary(self.fixture.state)
        self.assertEqual(result['current_observation_state'],'DRAINED')
        with closing(sqlite3.connect(self.fixture.state.writer.path.as_uri()+'?mode=ro',uri=True)) as reader:
            reader.execute('PRAGMA query_only=ON')
            self.assertEqual(drain.historical_observation_boundary(reader),result)
        archived=drain.OBSERVATION_DRAIN_KEY+'_preserved.'+descriptor['failed_census_sha256']
        self.assertEqual(self.fixture.value(archived),self.fixture.incident['failed_raw'])
        self.assertTrue(self.fixture.verify(reference)['economic_interval_recovered'])
        self.fixture.assert_original_evidence()

    def test_competing_full_interval_origins_remain_ambiguous(self):
        for family,origin in self.origins.items():
            with self.subTest(family=family),self.fixture.changed_owner():
                self.db.execute('INSERT INTO candidate_gaps(scope,lo,hi,created,reason) VALUES(?,?,?,?,?)',
                    (origin[1],origin[2],origin[3],origin[4],origin[5]))
                self.refused_descriptor()
        self.fixture.assert_incident_preserved()

    def test_missing_or_corrupted_full_origin_cannot_select_short_residual(self):
        for family,origin in self.origins.items():
            for sql,args in [
                ('DELETE FROM candidate_gaps WHERE id=?',(origin[0],)),
                ('UPDATE candidate_gaps SET hi=? WHERE id=?',(buffered.HEAD-1,origin[0])),
                ("UPDATE candidate_gaps SET reason='other-provenance' WHERE id=?",(origin[0],)),
                ('UPDATE candidate_gaps SET created=? WHERE id=?',(self.fixture.base.at+1,origin[0]))]:
                with self.subTest(family=family,mutation=sql),self.fixture.changed_owner():
                    self.db.execute(sql,args);self.refused_descriptor()
        self.fixture.assert_incident_preserved()

    def test_self_consistent_handler_id_cannot_borrow_prefix_residual(self):
        # Retain the same handler/session/census relationship everywhere and
        # change only its recovery target to the genuine short residual.
        with self.fixture.changed_owner():
            ledger=json.loads(self.fixture.incident['handler_raw'])
            failed=deepcopy(self.fixture.incident['failed'])
            observed=deepcopy(self.fixture.incident['observed'])
            def redirect(records):
                for record in records:
                    if record.get('run',self.fixture.incident['run'])==self.fixture.incident['run']:
                        self.assertEqual(record['scope_hash'],drain.HandlerLedger.scope_hash((program_scope('pumpswap'),)))
                        record['recovery']=dict(kind='CANDIDATE_GAPS',gap_ids=[self.residuals['pumpswap'][0]])
            redirect(ledger['records']);redirect(failed['handler_accounting']['records'])
            redirect(observed['handler_dispositions'])
            self.fixture.put(drain.HANDLER_RECOVERY_KEY,canonical(ledger))
            self.fixture.put(drain.OBSERVATION_DRAIN_KEY,canonical(failed))
            self.db.execute('UPDATE acquisition_observations SET body=? WHERE id=?',
                (canonical(observed),self.fixture.incident['observation_id']))
            self.refused_descriptor()
        self.fixture.assert_incident_preserved()

    def test_recovered_buffered_interval_does_not_validate_wrong_residual_provenance(self):
        reference=self.fixture.preserve();self.fixture.recover()
        self.assertTrue(self.fixture.verify(reference)['economic_interval_recovered'])
        for family,residual in self.residuals.items():
            for sql,args in [
                ('UPDATE candidate_gaps SET created=created+1 WHERE id=?',(residual[0],)),
                ("UPDATE candidate_gaps SET reason='other-provenance' WHERE id=?",(residual[0],)),
                ('UPDATE candidate_gaps SET repaired=? WHERE id=?',(self.fixture.base.at,residual[0]))]:
                with self.subTest(family=family,mutation=sql),self.fixture.changed_owner():
                    self.db.execute(sql,args);self.fixture.refused(reference)
        self.fixture.assert_incident_preserved()
