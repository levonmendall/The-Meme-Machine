"""Real canonical cold consumers retain the exact restored cohort boundary.

An existing disposable producer/FULL-consumer/ACK/archive/move fixture is
composed, never inherited. Real archive proofs and the original startup gate
are completed before retirement; no coverage or release predicate is mocked.
"""
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from meme_machine.runtime import candidate_history as references
from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.solana_evidence_plane import EvidenceReader, EvidenceUnavailable, EvidenceConflict, canonical, decode_body
from meme_machine.solana_history_delivery import capture, deliver, acknowledge
from meme_machine.solana_program_decoders import pump_events
from meme_machine.solana_rolling_history import program_scope
from meme_machine.solana_selective_history import CandidateReader, ConsumerReader, PROGRAMS
from meme_machine.solana_selective_runtime import consume_pump_discovery
from meme_machine.solana_selective_source import commit_control
from tests import test_candidate_commit_batches as native_frames
from tests import test_retained_canonical_reference as retained_fixture
from tests.test_solana_closure import NOW


class CanonicalColdArchiveCohortTests(unittest.TestCase):
    def setUp(self):
        self.base = retained_fixture.RetainedCanonicalReferenceTests('runTest')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        original_retirement = retained_fixture.ScopedRetirement

        def prepare_before_snapshot(history):
            retirement = original_retirement(history)
            transactions = deepcopy(retained_fixture.FIXTURE['pump'])
            self.lower = min(transaction['slot'] for transaction in transactions)
            self.upper = max(transaction['slot'] for transaction in transactions)
            # Actual finalized metadata bounds every fixed archive request.
            for slot in range(self.lower,self.upper+2):
                frame = replace(native_frames.frame(slot,logs=False),replay_from_slot=self.lower)
                commit_control(self.base.state,frame)
            history.startup.begin()
            for family in ('pump','pumpswap'):
                history.startup.feed_ack(family,self.lower,self.upper)
            history.startup.native(('pump','pumpswap'))
            candidate_transactions = [transaction for transaction in transactions
                if any(event.get('mint')==self.base.mint for event in pump_events(transaction))]
            self.assertTrue(candidate_transactions)
            self.proofs = []
            for family,address,data in (
                    ('pump',self.base.mint,candidate_transactions),
                    ('pump',PROGRAMS['pump'],transactions),
                    ('pumpswap',PROGRAMS['pumpswap'],[])):
                identity = history.request(family,address,self.lower,self.upper,
                    priority=0,deadline=NOW+120)
                planned = history.plan()
                self.assertIsNotNone(planned)
                job,_ = planned
                self.assertEqual(job['id'],identity)
                history.commit_page(job,dict(data=data),finalized_through=self.upper,seen=NOW)
                scope = history.scope_for(family,address)
                proof = history.db.execute('SELECT id FROM candidate_pending_proofs '
                    'WHERE scope=? AND lo=? AND hi=?',(scope,self.lower,self.upper)).fetchone()
                self.assertIsNotNone(proof)
                self.proofs.append(proof[0])
                self.publish(history)
            self.assertTrue(history.startup.advance()['released'])
            self.assertTrue(all(history.lifecycle.unconsumed(program_scope(family)) is None
                for family in ('pump','pumpswap')))
            with closing(CandidateHistory(history.lifecycle.path)) as shared:
                self.assertEqual(shared.db.execute('PRAGMA synchronous').fetchone()[0],2)
                self.assertTrue(all(shared.db.execute('SELECT 1 FROM source_receipts WHERE id=?',
                    ('coverage:'+identity,)).fetchone() for identity in self.proofs))
            with closing(EvidenceReader(history.writer.path)) as original:
                reader = ConsumerReader(original)
                self.expected_discovery = self.discovery_rows(reader,NOW)
                candidate = CandidateReader(original,'pump',self.base.mint)
                self.expected_window = candidate.window(candidate.scope,self.lower,self.upper,
                    as_of=NOW,address=self.base.mint)
                self.assertTrue(self.expected_discovery)
                self.assertTrue(self.expected_window)
            return retirement

        with patch.object(retained_fixture,'ScopedRetirement',side_effect=prepare_before_snapshot):
            self.base.prepare(cold=True)
        self.source = self.base.canonical
        self.consumer = self.base.consumer
        self.archive_id,self.old_archive,self.archive_hash = self.base.archives[0]
        self.archive = self.base.aws/Path(self.old_archive).relative_to(self.base.legacy)
        self.archive_bytes = self.archive.read_bytes()

    def publish(self,history):
        for _ in range(16):
            batch = capture(history.lifecycle)
            if batch is None:
                break
            self.assertTrue(acknowledge(history.lifecycle,batch,deliver(batch)))
            history.lifecycle.publish()
        history.lifecycle.publish()

    @staticmethod
    def discovery_rows(reader,as_of):
        return [(row[0],decode_body(row[1],reader.db),*row[2:])
            for row in reader.discovery(0,as_of=as_of)]

    def reads(self,path=None,*,as_of=NOW):
        with closing(EvidenceReader(self.source if path is None else path)) as original:
            consumer = ConsumerReader(original)
            discovery = self.discovery_rows(consumer,as_of)
            candidate = CandidateReader(original,'pump',self.base.mint)
            window = candidate.window(candidate.scope,self.lower,self.upper,
                as_of=as_of,address=self.base.mint)
            self.assertFalse(original.db.in_transaction)
            return discovery,window

    def refused(self,path=None):
        with self.assertRaises((ValueError,FileNotFoundError,sqlite3.Error,EvidenceUnavailable,EvidenceConflict)):
            self.reads(path)

    @contextmanager
    def canonical_change(self,sql,args,restore_sql,restore_args):
        with closing(sqlite3.connect(self.source,isolation_level=None)) as db:
            db.execute(sql,args)
            try:
                yield
            finally:
                db.execute(restore_sql,restore_args)

    def test_real_discovery_and_candidate_window_resolve_cold_alias_after_move_and_restart(self):
        self.assertFalse(Path(self.old_archive).exists())
        with self.assertRaises(sqlite3.OperationalError) as caught:
            sqlite3.connect((self.base.legacy/'shared/solana-evidence.sqlite').as_uri()+'?mode=ro',uri=True)
        self.assertEqual(caught.exception.sqlite_errorcode & 255,sqlite3.SQLITE_CANTOPEN)
        for _ in range(2):
            discovery,window = self.reads()
            self.assertEqual(discovery,self.expected_discovery)
            self.assertEqual(window,self.expected_window)
            self.assertTrue(all(row[8]==NOW for row in discovery))
            self.base.unchanged()
        with closing(EvidenceReader(self.source)) as original:
            self.assertEqual(ConsumerReader(original).discovery(0,as_of=NOW-1),[])
            candidate = CandidateReader(original,'pump',self.base.mint)
            with self.assertRaisesRegex(EvidenceUnavailable,'unresolved_evidence_gap'):
                candidate.window(candidate.scope,self.lower,self.upper,as_of=NOW-1,address=self.base.mint)
        self.base.unchanged()

    def test_actual_pump_discovery_consumes_original_cold_rows_with_release_and_durable_history(self):
        before_source = self.base.rows(self.source)
        with closing(EvidenceReader(self.source)) as original:
            reader = ConsumerReader(original)
            tape = SimpleNamespace(plane=SimpleNamespace(_selective_reader=lambda:reader,clock=lambda:NOW))
            events,sequence = consume_pump_discovery(tape,0)
            self.assertEqual(sequence,self.expected_discovery[-1][0])
            self.assertTrue(tape.candidate_history_rows)
            self.assertEqual([row['identity'] for row in tape.candidate_history_rows],
                [row[3] for row in self.expected_discovery])
            self.assertTrue(all(row['event']['available_time']==int(NOW) for row in tape.candidate_history_rows))
            self.assertTrue(all(event['event_type'] not in ('create','migration') for event in events))
            self.assertEqual(consume_pump_discovery(tape,sequence),([],sequence))
            self.assertFalse(original.db.in_transaction)
        self.assertEqual(self.base.rows(self.source),before_source)
        with closing(CandidateHistory(self.consumer)) as shared:
            self.assertEqual(shared.db.execute('SELECT * FROM canonical_event_refs ORDER BY rowid').fetchall(),
                self.base.original_refs)
            self.assertEqual(shared.events('pump',self.base.mint),self.base.expected)
        self.assertEqual(self.base.file_hash(self.base.history500),self.base.history500_hash)

    def test_wrong_mode_epoch_root_selected_plane_or_actual_canonical_database_refuses_alias(self):
        for key,value in (('MM_MODE','LIVE'),('MM_PAPER_EPOCH','paper-shared-500'),
                ('MM_STATE_ROOT',str(self.base.root/'wrong-root')),
                ('MM_SOLANA_EVIDENCE_PLANE_DB',str(self.base.aws/'shared/other.sqlite'))):
            with self.subTest(key=key),patch.dict(os.environ,{key:value}):
                self.refused()
        other = self.base.root/'other-canonical.sqlite'
        shutil.copyfile(self.source,other)
        self.refused(other)
        with self.assertRaisesRegex(ValueError,'candidate_canonical_reference_cohort_unverified'):
            references.retained_reference_path(self.old_archive,candidate_path=self.base.root/'other-consumer.sqlite',
                canonical_path=self.source,cold=True)
        self.base.unchanged()

    def test_missing_or_symlinked_cohort_members_refuse_without_recreating_files(self):
        for location in (self.archive,self.consumer,self.source,self.base.aws/'shared'):
            with self.subTest(location=location):
                saved = location.with_name(location.name+'.retained')
                location.rename(saved)
                try:
                    self.refused()
                    self.assertFalse(location.exists())
                    location.symlink_to(saved,target_is_directory=saved.is_dir())
                    self.refused()
                finally:
                    if location.is_symlink():
                        location.unlink()
                    saved.rename(location)
        self.base.unchanged()

    def test_archive_hash_identity_and_economic_corruption_are_not_cached_success(self):
        self.assertEqual(self.reads()[1],self.expected_window)
        original = self.archive_bytes
        payload = json.loads(zlib.decompress(original))
        variants = []
        changed_identity = deepcopy(payload)
        changed_identity[0]['record']['identity'] = 'different-archived-identity'
        variants.append(zlib.compress(canonical(changed_identity).encode()))
        changed_economics = deepcopy(payload)
        changed_economics[0]['record']['payload']['event']['market_time'] += 1
        variants.append(zlib.compress(canonical(changed_economics).encode()))
        variants.append(original[:-1])  # Matching checksum still needs zlib EOF.
        for packed in (original+b'changed',*variants):
            with self.subTest(bytes=len(packed)):
                checksum = self.archive_hash if packed==original+b'changed' else hashlib.sha256(packed).hexdigest()
                self.archive.write_bytes(packed)
                try:
                    with self.canonical_change('UPDATE scoped_cold_manifests SET hash=? WHERE id=?',
                            (checksum,self.archive_id),
                            'UPDATE scoped_cold_manifests SET hash=? WHERE id=?',(self.archive_hash,self.archive_id)):
                        self.refused()
                finally:
                    self.archive.write_bytes(original)
        self.assertEqual(self.reads()[1],self.expected_window)
        self.base.unchanged()

    def test_record_hash_and_original_availability_are_checked_by_both_canonical_callers(self):
        with closing(sqlite3.connect(self.source)) as db:
            discovery_identity = db.execute('''SELECT r.identity FROM candidate_outbox o
                JOIN canonical_evidence r ON r.identity=o.identity
                WHERE o.scope='program:pump' AND o.sequence>0 AND o.first_seen<=?
                    AND r.body IS NULL ORDER BY o.sequence LIMIT 1''',(NOW,)).fetchone()
            self.assertIsNotNone(discovery_identity)
            selected = dict(discovery=discovery_identity[0],window=self.expected_window[0]['identity'])
            self.assertIn(selected['discovery'],[row[3] for row in self.expected_discovery])
            self.assertIn(selected['window'],[row['identity'] for row in self.expected_window])
            metadata = {}
            for caller,identity in selected.items():
                visible = db.execute('SELECT body,hash,first_seen,archive FROM canonical_evidence '
                    'WHERE identity=?',(identity,)).fetchone()
                archived = db.execute('SELECT body,hash,first_seen,archive FROM scoped_cold_records '
                    'WHERE identity=?',(identity,)).fetchone()
                owner = db.execute('SELECT body,hash,first_seen,archive FROM rolling_economic_events '
                    'WHERE identity=?',(identity,)).fetchone()
                self.assertIsNotNone(visible)
                self.assertIsNone(visible[0],'the selected caller must really reach cold_record')
                self.assertTrue(visible[3])
                self.assertEqual(archived,visible)
                # The retained rolling row is the canonical view's first
                # branch. Its cold pointer shadows the archive metadata copy.
                self.assertEqual(owner,visible)
                metadata[caller] = visible
        for caller,identity in selected.items():
            _,checksum,available,_ = metadata[caller]
            for column,invalid,original in (('hash','f'*64,checksum),('first_seen',NOW+1,available)):
                with self.subTest(caller=caller,column=column),self.canonical_change(
                        'UPDATE rolling_economic_events SET '+column+'=? WHERE identity=?',(invalid,identity),
                        'UPDATE rolling_economic_events SET '+column+'=? WHERE identity=?',(original,identity)):
                    with closing(EvidenceReader(self.source)) as original_reader:
                        self.assertEqual(original_reader.db.execute('SELECT '+column+
                            ' FROM canonical_evidence WHERE identity=?',(identity,)).fetchone(),(invalid,))
                        self.assertIsNone(original_reader.db.execute('SELECT body FROM canonical_evidence '
                            'WHERE identity=?',(identity,)).fetchone()[0])
                        # A later honest as-of includes future first_seen, so
                        # both callers must compare it with archive availability.
                        if caller=='discovery':
                            consumer = ConsumerReader(original_reader)
                            with self.assertRaises((EvidenceUnavailable,EvidenceConflict)):
                                consumer.discovery(0,as_of=NOW+2)
                        else:
                            candidate = CandidateReader(original_reader,'pump',self.base.mint)
                            with self.assertRaises((EvidenceUnavailable,EvidenceConflict)):
                                candidate.window(candidate.scope,self.lower,self.upper,
                                    as_of=NOW+2,address=self.base.mint)
        self.base.unchanged()

    def test_default_current_foreign_and_original_do_locator_semantics_remain_unchanged(self):
        with patch.dict(os.environ):
            del os.environ['MM_SOLANA_EVIDENCE_PLANE_DB']
            self.assertEqual(self.reads()[1],self.expected_window)
        native = Path(self.old_archive)
        with patch.dict(os.environ,MM_STATE_ROOT=str(self.base.legacy),MM_MODE='LIVE'):
            self.assertEqual(references.retained_reference_path(native,candidate_path=None,cold=True),native)
        foreign = self.base.root/'other-cohort'/self.archive.name
        foreign.parent.mkdir()
        foreign.write_bytes(self.archive_bytes)
        # An ordinary current or foreign locator keeps the original direct
        # local-file behavior; the new helper changes only the known DO alias.
        for locator in (self.archive,foreign):
            with self.subTest(locator=locator),self.canonical_change(
                    'UPDATE scoped_cold_manifests SET path=? WHERE id=?',(str(locator),self.archive_id),
                    'UPDATE scoped_cold_manifests SET path=? WHERE id=?',(self.old_archive,self.archive_id)):
                with patch.dict(os.environ,MM_MODE='LIVE',MM_PAPER_EPOCH='other'):
                    self.assertEqual(self.reads()[1],self.expected_window)
        self.base.unchanged()
