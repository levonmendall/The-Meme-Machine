"""Actual pre-write cuts over the original four-regime replay fixture.

Root/systemd acquisition remains the fixture's explicit injected premise. No
cut, count, metadata digest or child-owned descriptor is a completion witness.
"""
from contextlib import closing
from copy import deepcopy
import os
import pickle
import sqlite3
import threading
import unittest
from unittest.mock import patch

from meme_machine.operational import normal_boot as boot
from meme_machine.operational import normal_boot_support as support
from meme_machine.operational.normal_boot_record import NormalBootUnavailable,digest
from tests.test_normal_boot_context import NativePrewriteReplayTests,physical_hash


class BootSupportTests(unittest.TestCase):
    def setUp(self):
        self.fixture=NativePrewriteReplayTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.source=self.root/support.SOURCE_PATH

    def populate(self):
        # Future availability and a deliberately dangling old key must remain
        # inside the fixed cut. Actual key census will classify them later;
        # this metadata-only producer may not omit or call either complete.
        with closing(sqlite3.connect(self.source)) as db:
            db.executemany('INSERT INTO candidate_outbox(sequence,identity,scope,slot,first_seen) '
                'VALUES(?,?,?,?,?)',[(2**62,'old-pump','program:pump',7,1.),
                    (2**62+1,'future-pump','program:pump',8,9e15),
                    (2**62+2,'old-swap','program:pumpswap',9,1.)])
            db.commit()
        self.fixture.record['boot_eligibility']['physical_generation_sha256']=physical_hash(self.root)

    def consume(self):return boot.consume_normal_boot(self.fixture.supervisor,cancelled=lambda:False)

    def test_actual_verified_scope_binds_exact_cuts_without_decoding_or_counting_population(self):
        self.populate();captured=[];original=support._capture
        def capture(reads,*args):
            db=reads.databases[self.source];queries=[]
            def authorize(action,table,column,*unused):
                if action==sqlite3.SQLITE_READ and table=='canonical_evidence':
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(authorize);db.set_trace_callback(queries.append)
            try:
                value=original(reads,*args)
                plan=db.execute('EXPLAIN QUERY PLAN SELECT sequence FROM candidate_outbox '
                    'INDEXED BY candidate_outbox_scope WHERE scope=? ORDER BY sequence DESC LIMIT 1',
                    ('program:pump',)).fetchall()
                self.assertTrue(any('SEARCH' in row[-1] and 'candidate_outbox_scope' in row[-1]
                    for row in plan))
                captured.extend(queries);return value
            finally:db.set_authorizer(None);db.set_trace_callback(None)
        before=physical_hash(self.root)
        with patch.object(support,'_capture',side_effect=capture):context=self.consume()
        boundary=context.boot_support();value=boundary.value();row=boundary.outbox_support('program:pump')
        self.assertEqual(row['upper_sequence'],2**62+1)
        self.assertEqual(boundary.outbox_support('program:pumpswap')['upper_sequence'],2**62+2)
        self.assertIsNone(boundary.outbox_support('program:meteora')['upper_sequence'])
        self.assertEqual(row['association']['native_input_sha256'],
            self.fixture.record['boot_eligibility']['native_input_sha256'])
        self.assertEqual((row['database']['device'],row['database']['inode']),
            (self.source.stat().st_dev,self.source.stat().st_ino))
        self.assertEqual(row['support_identity_sha256'],digest(value))
        self.assertEqual(physical_hash(self.root),before)
        self.assertFalse(any('count(' in sql.lower() or 'select body' in sql.lower() for sql in captured))
        self.assertNotIn('records',row);self.assertNotIn('complete',row)
        value['programs']['program:pump']=0
        self.assertEqual(boundary.outbox_support('program:pump')['upper_sequence'],2**62+1)
        with self.assertRaises(TypeError):pickle.dumps(boundary)
        context.close()
        with self.assertRaisesRegex(NormalBootUnavailable,'context_owner'):boundary.value()

    def test_later_append_does_not_move_authenticated_prewrite_cut(self):
        self.populate();context=self.consume();boundary=context.boot_support()
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('INSERT INTO candidate_outbox VALUES(?,?,?,?,?)',
                (2**62+3,'new-pump','program:pump',10,1.));db.commit()
        self.assertEqual(boundary.outbox_support('program:pump')['upper_sequence'],2**62+1)
        self.assertEqual(boundary.value()['retained_work']['source']['rowid_heads'],
            {'candidate_history_outbox':None,'candidate_pending_proofs':None})

    def test_missing_source_index_refuses_before_private_context_publication(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('DROP INDEX candidate_outbox_scope');db.commit()
        self.fixture.record['boot_eligibility']['physical_generation_sha256']=physical_hash(self.root)
        with self.assertRaisesRegex(NormalBootUnavailable,'support_source_schema'):self.consume()
        self.assertIsNone(boot._ACTIVE);self.assertFalse(self.fixture.launch._consumed)

    def test_capture_cancellation_or_physical_mutation_cannot_publish_context(self):
        original=support._capture;cancelled=False
        def capture(reads,*args):
            nonlocal cancelled
            value=original(reads,*args);cancelled=True;return value
        with patch.object(support,'_capture',side_effect=capture):
            with self.assertRaisesRegex(NormalBootUnavailable,'cancelled_or_expired'):
                boot.consume_normal_boot(self.fixture.supervisor,cancelled=lambda:cancelled)
        self.assertIsNone(boot._ACTIVE);self.assertFalse(self.fixture.launch._consumed)
        def mutate(reads,*args):
            value=original(reads,*args)
            with closing(sqlite3.connect(self.source)) as db:
                db.execute('INSERT INTO candidate_outbox VALUES(?,?,?,?,?)',(7,'raced','program:pump',7,1.))
                db.commit()
            return value
        with patch.object(support,'_capture',side_effect=mutate):
            with self.assertRaisesRegex(NormalBootUnavailable,'file_changed|directory_changed'):self.consume()
        self.assertIsNone(boot._ACTIVE);self.assertFalse(self.fixture.launch._consumed)

    def test_private_shape_owner_and_association_refuse_forged_or_crossed_values(self):
        context=self.consume();boundary=context.boot_support();value=boundary.value()
        with self.assertRaisesRegex(NormalBootUnavailable,'private_issuer'):
            support.NativeBootSupportBoundary(value,lambda:None)
        with self.assertRaisesRegex(NormalBootUnavailable,'child_owner_type'):support._for_child(value)
        bad=deepcopy(value);bad['programs']['program:pump']=True
        with self.assertRaisesRegex(NormalBootUnavailable,'support_programs'):support.validate_support_value(bad)
        bad=deepcopy(value);bad['database']['relative_path']='other.sqlite'
        with self.assertRaisesRegex(NormalBootUnavailable,'support_database'):support.validate_support_value(bad)
        launch={key:value['association'][key] for key in ('instance','record_sha256','certificate_sha256',
            'application_commit','application_tree','epoch_id','inception_sha256')}
        launch['epoch_id']='crossed'
        with self.assertRaisesRegex(NormalBootUnavailable,'launch_changed'):
            support.validate_support_association(value,launch)
        errors=[]
        def foreign():
            try:boundary.value()
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=foreign);worker.start();worker.join(2)
        self.assertEqual(len(errors),1);self.assertIn('context_owner',str(errors[0]))
