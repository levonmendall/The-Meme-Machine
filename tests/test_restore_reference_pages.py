"""Actual native FULL/ACK corpus through bounded startup source pages."""
from contextlib import closing, contextmanager, ExitStack
from copy import deepcopy
import hashlib
import gc
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import zlib
import unittest
import weakref
from unittest.mock import patch

from meme_machine.runtime.candidate_history import CandidateHistory
from meme_machine.runtime import candidate_restore_reads as pages
from meme_machine.runtime import operation_costs as costs
from meme_machine.runtime.stop import Shutdown
from meme_machine.solana_evidence_plane import digest
from meme_machine.solana_evidence_storage import encode
from tests.test_startup_archive_read_reuse import ArchiveCorpus, archive_io


@contextmanager
def diagnostics():
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, MM_OPERATION_COST_DIAGNOSTICS='1'))
        for name, value in (('_rows', costs._new_rows()), ('_active', {}),
                            ('_restore_counts', dict.fromkeys(costs.RESTORE_COUNT_NAMES, 0)),
                            ('_sequence', 0), ('_recorder_valid', True),
                            ('_recording_lost_calls', 0), ('_active_overflow_calls', 0)):
            stack.enter_context(patch.object(costs, name, value))
        yield


class RestoreReferencePagesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.corpus = ArchiveCorpus(self, Path(temporary.name))

    def read(self, shared, reader):
        return shared.events('pump', self.corpus.mint, kind_prefix='pump_',
            cancelled=reader.cancelled, _restore_archive_cache=reader.archives,
            _restore_reference_reader=reader)

    def test_actual_full_ack_cold_and_hot_rows_match_with_batched_metadata_and_no_decode_snapshot(self):
        from meme_machine import solana_evidence_storage as storage
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            archives = {}; queries = []; decoded = []
            with shared.restoration_reader(cancelled=lambda: False, archives=archives) as reader:
                original_db = reader._database
                def database(path):
                    db = original_db(path); db.set_trace_callback(queries.append); return db
                original_prepare = storage.prepare_decode
                def prepare(raw):
                    self.assertFalse(reader.db.in_transaction)
                    decoded.append(1); return original_prepare(raw)
                with patch.object(reader, '_database', database), patch.object(storage, 'prepare_decode', prepare), \
                        archive_io(self.corpus.archive.parent) as io:
                    actual = self.read(shared, reader)
                self.assertEqual(actual, self.corpus.expected)
                self.assertEqual((io['reads'], io['decodes']), (1, 1))
                # Each complete point capture uses the canonical view once.
                # It retains first-match semantics and never scans unused UNION
                # tails or performs a detached metadata-then-body lookup.
                self.assertEqual(sum('SELECT octet_length(body)' in q for q in queries), len(self.corpus.refs))
                self.assertEqual(sum('CASE WHEN body IS NULL' in q for q in queries), len(self.corpus.refs))
                self.assertEqual(sum('SELECT identity,body,hash,archive' in q for q in queries), 0)
                self.assertEqual(sum('SELECT identity,hash,archive' in q for q in queries), 0)
                self.assertEqual(sum('SELECT path,hash FROM scoped_cold_manifests WHERE id=' in q for q in queries), 1)
                self.assertFalse(reader.db.in_transaction)
                self.assertTrue(decoded)
                self.assertFalse(hasattr(shared, '_source_readers'))
            self.assertTrue(reader.closed)
            self.assertIsNone(reader.db)
        self.corpus.unchanged()

    def test_missing_reference_and_later_bad_hash_keep_original_first_failure(self):
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            rows = shared.db.execute("SELECT identity,kind,body,hash FROM canonical_event_refs WHERE lane='pump' AND candidate=? AND kind GLOB 'pump_*'",
                (self.corpus.mint,)).fetchall()
            first = json.loads(rows[0][2]); first['canonical_identity'] = 'missing-canonical'
            raw = json.dumps(first, sort_keys=True, separators=(',', ':'))
            shared.db.execute('UPDATE canonical_event_refs SET body=?,hash=? WHERE identity=?',
                (raw, hashlib.sha256(raw.encode()).hexdigest(), rows[0][0]))
            shared.db.execute('UPDATE canonical_event_refs SET hash=? WHERE identity=?', ('later-bad-hash', rows[-1][0]))
            with self.assertRaisesRegex(ValueError, 'candidate_canonical_reference_missing'):
                shared.events('pump', self.corpus.mint, kind_prefix='pump_')
            with shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
                with self.assertRaisesRegex(ValueError, 'candidate_canonical_reference_missing'):
                    self.read(shared, reader)
                self.assertFalse(reader.db.in_transaction)

    def test_per_reference_archive_stat_and_hash_still_reject_midpage_file_change(self):
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            original = shared._reference_body; seen = []
            def reference(*args, **kwargs):
                result = original(*args, **kwargs); seen.append(1)
                if len(seen) == 1:
                    self.corpus.archive.write_bytes(b'changed-after-first-reference')
                return result
            try:
                with shared.restoration_reader(cancelled=lambda: False, archives={}) as reader, \
                        patch.object(shared, '_reference_body', reference):
                    with self.assertRaisesRegex(ValueError, 'candidate_history_corruption'):
                        self.read(shared, reader)
                    self.assertEqual(reader.archives, {})
                    self.assertFalse(reader.db.in_transaction)
            finally:
                self.corpus.archive.write_bytes(self.corpus.archive_bytes)

    def test_source_generation_change_is_detected_at_next_bounded_page(self):
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            original = shared._reference_body; seen = []
            last = json.loads(self.corpus.refs[-1][2])['canonical_identity']
            def reference(*args, **kwargs):
                result = original(*args, **kwargs); seen.append(1)
                if len(seen) == 1:
                    # A later page must re-read canonical metadata; page facts
                    # never become process-wide immutable-cache authority.
                    self.corpus.history.db.execute('UPDATE rolling_economic_events SET hash=? WHERE identity=?',
                        ('changed-generation-hash', last))
                return result
            with patch.object(pages, 'PAGE_REFERENCES', 2), \
                    shared.restoration_reader(cancelled=lambda: False, archives={}) as reader, \
                    patch.object(shared, '_reference_body', reference):
                with self.assertRaisesRegex(ValueError, 'candidate_history_corruption'):
                    self.read(shared, reader)

    def test_source_sql_cancellation_rolls_back_owned_reader_and_does_not_replace_normal_hook(self):
        cancelled = threading.Event()
        with diagnostics(), closing(CandidateHistory(self.corpus.consumer)) as shared:
            # Normal readers are independent and retain their callback.
            shared.events('pump', self.corpus.mint)
            normal = next(iter(shared._source_readers.values())); callbacks = []
            normal.set_progress_handler(lambda: callbacks.append(1) or 0, 1)
            with shared.restoration_reader(cancelled=cancelled.is_set, archives={}) as reader:
                original_db = reader._database
                def database(path):
                    db = original_db(path)
                    db.set_trace_callback(lambda sql: cancelled.set() if 'FROM canonical_evidence' in sql else None)
                    return db
                with patch.object(reader, '_database', database):
                    with self.assertRaises(Shutdown): self.read(shared, reader)
                self.assertFalse(reader.db.in_transaction)
                counts = costs.snapshot()['restore_reference_counts']
                self.assertEqual(counts['pages_started'], 1)
                self.assertEqual(counts['pages_completed'], 0)
                self.assertEqual(sum(value for name, value in counts.items() if name.startswith('fallback_')), 0)
            normal.execute('SELECT 1').fetchone()
            self.assertTrue(callbacks)
            normal.set_progress_handler(None, 0)
        self.corpus.unchanged()

    def test_encoded_and_prepared_page_bounds_fall_back_without_rejecting_valid_history(self):
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
            for bound in ('PAGE_BYTES', 'PREPARED_BYTES'):
                with self.subTest(bound=bound), patch.object(pages, bound, 1), \
                        shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
                    self.assertEqual(self.read(shared, reader), self.corpus.expected)
                    self.assertFalse(reader.db.in_transaction)
        self.corpus.unchanged()

    def test_expired_sql_page_uses_original_scalar_without_favorable_history_or_ack(self):
        with diagnostics(), closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
            with patch.object(pages, 'SNAPSHOT_SECONDS', 0):
                self.assertEqual(self.read(shared, reader), self.corpus.expected)
            self.assertFalse(reader.db.in_transaction)
            counters = costs.snapshot()['restore_reference_counts']
            self.assertGreater(counters['fallback_source_snapshot_expired'], 0)
            self.assertEqual(counters['fallback_encoded_budget'], 0)
            self.assertEqual(counters['fallback_source_snapshot_expired'], counters['scalar_source_reads'])
        self.corpus.unchanged()

    def test_cold_metadata_and_manifest_share_hot_snapshot_while_writer_advances(self):
        self.corpus.history.db.execute('PRAGMA journal_mode=WAL')
        with closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
            original = reader._database; seen = []; writer_errors = []
            changed = next(iter(self.corpus.identities))
            def advance():
                try:
                    with closing(sqlite3.connect(self.corpus.source, timeout=0)) as writer:
                        for table in ('rolling_economic_events', 'records', 'shared_history_cache', 'scoped_cold_records'):
                            writer.execute('UPDATE ' + table + ' SET hash=? WHERE identity=?',
                                ('writer-new-generation', changed))
                        writer.commit()
                except BaseException as error: writer_errors.append(error)
            def database(path):
                db = original(path)
                def trace(sql):
                    if sql.startswith('SELECT path,hash FROM scoped_cold_manifests') and not seen:
                        self.assertTrue(db.in_transaction)
                        seen.append(1)
                        writer = threading.Thread(target=advance); writer.start(); writer.join(2)
                        self.assertFalse(writer.is_alive())
                db.set_trace_callback(trace)
                return db
            with patch.object(reader, '_database', database):
                self.assertEqual(self.read(shared, reader), self.corpus.expected)
            self.assertEqual(seen, [1]); self.assertEqual(writer_errors, [])
            self.assertFalse(reader.db.in_transaction)
            self.assertEqual(reader.db.execute('SELECT hash FROM canonical_evidence WHERE identity=?',
                (changed,)).fetchone(), ('writer-new-generation',))
        # Restart must authenticate the writer's new head, not the old snapshot.
        with closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
            with self.assertRaisesRegex(ValueError, 'candidate_history_corruption'):
                self.read(shared, reader)

    def test_expired_lease_retains_complete_captures_without_scalar_replay(self):
        with diagnostics(), closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
            original = reader._capture_source; captured = []
            def capture(db, key, budget, manifests):
                row = original(db, key, budget, manifests); captured.append(key)
                if len(captured) % 3 == 0: reader.deadline = 0
                return row
            with patch.object(reader, '_capture_source', capture):
                self.assertEqual(self.read(shared, reader), self.corpus.expected)
            sample = costs.snapshot(); counts = sample['restore_reference_counts']
            self.assertEqual(counts['scalar_source_reads'], 0)
            self.assertEqual(counts['fallback_source_snapshot_expired'], 0)
            self.assertEqual(len(captured), len(set(captured)))
            # Capture diagnostics sample leases, avoiding a fresh recorder for
            # every canonical key even when one lease captures several keys.
            self.assertLess(sample['rows']['pump.restore_source_capture']['calls'], len(captured))
            self.assertFalse(reader.db.in_transaction)
        self.corpus.unchanged()

    def test_fresh_lease_rechecks_actual_archival_row_and_matching_manifest(self):
        from meme_machine.solana_scoped_retirement import ScopedRetirement
        self.assertEqual(ScopedRetirement(self.corpus.history).restore('pump', self.corpus.mint),64)
        later = json.loads(self.corpus.refs[-1][2])['canonical_identity']
        with closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
            original = reader._capture_source; changed = []; actual = []
            def capture(db, key, budget, manifests):
                row = original(db, key, budget, manifests)
                if not changed:
                    # The original source archive operation commits while the
                    # current read snapshot remains coherent. The next lease
                    # must fetch the new NULL body/hash/archive+manifest anew.
                    self.corpus.retire({later}); changed.append(True); reader.deadline = 0
                if key == later: actual.append(row)
                return row
            with patch.object(reader, '_capture_source', capture):
                self.assertEqual(self.read(shared, reader), self.corpus.expected)
            self.assertEqual(len(actual),1)
            self.assertIsNone(actual[0][0][0]);self.assertIsNotNone(actual[0][1])
            self.assertFalse(reader.db.in_transaction)

    def test_partial_cold_capture_is_not_retained_and_no_progress_falls_back_one_key(self):
        with diagnostics(), closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
            original = reader._capture_source; interrupted = []
            def capture(db, key, budget, manifests):
                if not interrupted:
                    # Real canonical source data was selected, but the complete
                    # source/manifest unit was not returned to the page owner.
                    row = db.execute('SELECT body,hash,archive FROM canonical_evidence WHERE identity=?',(key,)).fetchone()
                    self.assertIsNotNone(row);interrupted.append(key)
                    raise pages._PageExpired()
                return original(db, key, budget, manifests)
            with patch.object(reader, '_capture_source', capture):
                self.assertEqual(self.read(shared, reader), self.corpus.expected)
            counts = costs.snapshot()['restore_reference_counts']
            self.assertEqual(counts['fallback_source_snapshot_expired'],1)
            self.assertEqual(counts['scalar_source_reads'],1)
            self.assertFalse(reader.db.in_transaction)
        self.corpus.unchanged()

    def test_cancellation_outranks_expiry_and_never_falls_back_a_pending_key(self):
        cancelled = threading.Event()
        with diagnostics(), closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=cancelled.is_set, archives={}) as reader:
            def capture(*args):
                cancelled.set();raise pages._PageExpired()
            with patch.object(reader, '_capture_source', capture),self.assertRaises(Shutdown):
                self.read(shared, reader)
            counts = costs.snapshot()['restore_reference_counts']
            self.assertEqual(counts['fallback_source_snapshot_expired'],0)
            self.assertEqual(counts['scalar_source_reads'],0)
            self.assertFalse(reader.db.in_transaction)
        self.corpus.unchanged()

    def test_page_diagnostics_are_fixed_no_payload_and_original_scalar_fault_path(self):
        with diagnostics(), closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=lambda:False,archives={}) as reader, \
                patch.object(reader, '_source_rows', side_effect=sqlite3.OperationalError('private-path-or-sql')):
            self.assertEqual(self.read(shared, reader), self.corpus.expected)
            sample = costs.snapshot(); counts = sample['restore_reference_counts']
            self.assertEqual(counts['pages_started'], counts['pages_completed'])
            self.assertEqual(counts['references'], len(self.corpus.refs))
            self.assertEqual(counts['fallback_source_read_error'], len(self.corpus.refs))
            self.assertEqual(counts['scalar_source_reads'], len(self.corpus.refs))
            self.assertEqual(counts['fallback_source_snapshot_expired'], 0)
            self.assertNotIn('private-path-or-sql', json.dumps(sample))
            self.assertNotIn(str(self.corpus.source), json.dumps(sample))
        self.corpus.unchanged()

    def test_foreign_reader_scope_and_closed_reader_refuse_without_borrowing_transaction(self):
        with closing(CandidateHistory(self.corpus.consumer)) as shared, \
                closing(CandidateHistory(self.corpus.consumer)) as other:
            reader = shared.restoration_reader(cancelled=lambda: False, archives={})
            try:
                with self.assertRaisesRegex(ValueError, 'reference_scope'):
                    shared.events('pump', self.corpus.mint, kind_prefix='pump_', cancelled=lambda:False,
                        _restore_archive_cache=reader.archives, _restore_reference_reader=reader)
                with self.assertRaisesRegex(ValueError, 'reference_owner'): self.read(other, reader)
                with self.assertRaisesRegex(ValueError, 'reference_scope'):
                    shared.events('pons', self.corpus.mint, kind_prefix='pump_', cancelled=reader.cancelled,
                        _restore_archive_cache=reader.archives, _restore_reference_reader=reader)
                shared.db.execute('BEGIN')
                with self.assertRaisesRegex(ValueError, 'requires_idle_connection'): self.read(shared, reader)
                self.assertTrue(shared.db.in_transaction)
                shared.db.execute('ROLLBACK')
            finally: reader.close()
            with self.assertRaisesRegex(ValueError, 'reference_owner'): self.read(shared, reader)
        self.corpus.unchanged()



class RestoreReferenceChunkTests(unittest.TestCase):
    """Small actual SQLite/codec units; native FULL/ACK is exercised above."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.source = self.root / 'source.sqlite'
        self.db = sqlite3.connect(self.source, isolation_level=None); self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE facts(identity TEXT PRIMARY KEY,body BLOB,hash TEXT,archive TEXT);
            CREATE TABLE alternates(identity TEXT PRIMARY KEY,body BLOB,hash TEXT,archive TEXT);
            CREATE VIEW canonical_evidence AS SELECT * FROM facts UNION ALL SELECT * FROM alternates;
            CREATE TABLE hot_chunks(hash TEXT PRIMARY KEY,body BLOB NOT NULL);
            CREATE TABLE hot_refs(identity TEXT,hash TEXT,PRIMARY KEY(identity,hash));''')
        self.shared = CandidateHistory(self.root / 'consumer.sqlite'); self.addCleanup(self.shared.close)
        self.body = dict(identity='source-record',scope='program:pump',slot=100,signature='sig',program='pump',
            addresses=['mint'],market_time=100,event_index=0,transaction_index=0,kind='transaction',
            payload=dict(meta=dict(logMessages=['a' * 1024] * 4),
                raw_lineage=dict(logs=['a' * 1024] * 4), nested={'values': [1, 2]}))
        raw = encode(self.body, self.db)
        self.db.execute('INSERT INTO facts VALUES(?,?,?,NULL)', ('source-record', raw, digest(self.body)))
        for identity in ('first', 'second'):
            self.shared.append_reference('pump','mint',self.body,path=self.source,identity=identity,kind='pump_transaction')

    def read(self, reader):
        return self.shared.events('pump','mint',kind_prefix='pump_',cancelled=reader.cancelled,
            _restore_archive_cache=reader.archives,_restore_reference_reader=reader)

    def replace_body(self, body):
        self.db.execute('UPDATE facts SET body=?,hash=?', (encode(body,self.db),digest(body)))
        for identity, raw in self.shared.db.execute('SELECT identity,body FROM canonical_event_refs').fetchall():
            ref = json.loads(raw); ref['canonical_hash'] = digest(body)
            raw = json.dumps(ref,sort_keys=True,separators=(',',':'))
            self.shared.db.execute('UPDATE canonical_event_refs SET body=?,hash=? WHERE identity=?',
                (raw,hashlib.sha256(raw.encode()).hexdigest(),identity))

    def test_only_actual_chunk_hashes_are_batched_and_duplicate_refs_have_independent_payloads(self):
        expected = self.shared.events('pump','mint')
        # An unrelated missing hot_ref must never be mistaken for a real field.
        self.db.execute("INSERT INTO hot_refs VALUES('source-record','unused-missing')")
        queries = []
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            original = reader._database
            def database(path):
                db = original(path); db.set_trace_callback(queries.append); return db
            with patch.object(reader,'_database',database): actual = self.read(reader)
        self.assertEqual(actual,expected)
        self.assertEqual(sum('FROM hot_chunks WHERE hash IN' in q for q in queries),2)
        actual[0]['payload']['meta']['logMessages'][0] = 'mutated'
        actual[0]['payload']['nested']['values'].append(3)
        self.assertEqual(actual[1],expected[1])
        self.assertEqual(self.shared.events('pump','mint'),expected)

    def test_original_ambiguous_view_first_match_is_preserved_not_last_row_wins(self):
        self.db.execute("INSERT INTO alternates VALUES('source-record','not-valid-json','bad',NULL)")
        expected = self.shared.events('pump','mint')
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            self.assertEqual(self.read(reader),expected)

    def test_length_only_admission_counts_unicode_octets_and_preserves_legacy_hash(self):
        body = deepcopy(self.body)
        body['payload']['legacy_unicode'] = '\u2603' * 1024
        self.replace_body(body)
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        self.db.execute('UPDATE facts SET body=?', (raw,))
        expected = self.shared.events('pump','mint',kind_prefix='pump_')
        queries = []
        with diagnostics(), patch.object(pages, 'PAGE_BYTES', len(raw)), \
                self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            original = reader._database
            def database(path):
                db = original(path); db.set_trace_callback(queries.append); return db
            with patch.object(reader, '_database', database):
                self.assertEqual(self.read(reader), expected)
            counts = costs.snapshot()['restore_reference_counts']
            self.assertEqual(counts['hot_keys_selected'], 0)
            self.assertEqual(counts['fallback_encoded_budget'], 2)
            self.assertEqual(counts['scalar_source_reads'], 2)
            self.assertTrue(any(q.startswith('SELECT octet_length(body),') and
                'CASE WHEN body IS NULL OR octet_length(body)<=CAST(' in q for q in queries))
            self.assertFalse(any(q.startswith('SELECT identity,body,hash,archive') for q in queries))
        # With exact encoded-byte admission, the same body is acquired once;
        # original stored content hash is still checked per reference.
        with diagnostics(), patch.object(pages, 'PAGE_BYTES', len(raw.encode('utf-8'))), \
                self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            self.assertEqual(self.read(reader), expected)
            counts = costs.snapshot()['restore_reference_counts']
            self.assertEqual(counts['hot_keys_selected'], 1)
            self.assertEqual(counts['hot_bytes_selected'], len(raw.encode('utf-8')))
            self.assertEqual(counts['scalar_source_reads'], 0)
        self.db.execute("UPDATE facts SET hash='corrupt-stored-hash'")
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            with self.assertRaisesRegex(ValueError, 'candidate_history_corruption'): self.read(reader)

    def test_null_first_duplicate_cannot_be_replaced_by_later_hot_body(self):
        self.db.execute('UPDATE facts SET body=NULL,archive=?', ('absent-manifest',))
        self.db.execute('CREATE TABLE scoped_cold_manifests(id TEXT PRIMARY KEY,path TEXT,hash TEXT)')
        self.db.execute('INSERT INTO alternates VALUES(?,?,?,NULL)',
            ('source-record', encode(self.body, self.db), digest(self.body)))
        with self.assertRaisesRegex(ValueError, 'candidate_canonical_reference_requires_restore'):
            self.shared.events('pump','mint',kind_prefix='pump_')
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            with self.assertRaisesRegex(ValueError, 'candidate_canonical_reference_requires_restore'):
                self.read(reader)
            self.assertFalse(reader.db.in_transaction)

    def test_distinct_encoded_prepared_and_chunk_budget_reasons_count_first_fallback_once(self):
        expected = self.shared.events('pump','mint',kind_prefix='pump_')
        encoded = len(self.db.execute('SELECT body FROM facts').fetchone()[0])
        for limit, bound, reason in ((1, 'PAGE_BYTES', 'encoded_budget'),
                                    (1, 'PREPARED_BYTES', 'prepared_budget'),
                                    (encoded, 'PAGE_BYTES', 'chunk_budget')):
            with self.subTest(reason=reason), diagnostics(), patch.object(pages, bound, limit), \
                    self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
                self.assertEqual(self.read(reader), expected)
                counts = costs.snapshot()['restore_reference_counts']
                self.assertEqual(counts['fallback_' + reason], 2)
                self.assertEqual(sum(value for name, value in counts.items() if name.startswith('fallback_')), 2)
                self.assertEqual(counts['scalar_source_reads'], 2)

    def test_missing_or_corrupt_actual_chunk_fails_without_empty_event_or_ack(self):
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            self.db.execute('DELETE FROM hot_chunks')
            with self.assertRaisesRegex(ValueError,'hot_evidence_corrupt'): self.read(reader)
            self.assertFalse(reader.db.in_transaction)
        self.assertEqual(self.shared.db.execute('SELECT COUNT(*) FROM canonical_event_refs').fetchone()[0],2)

    def test_chunk_byte_ceiling_uses_original_scalar_and_retains_exact_event(self):
        expected = self.shared.events('pump','mint')
        with patch.object(pages,'PAGE_BYTES',len(bytes(self.db.execute('SELECT body FROM facts').fetchone()[0]))), \
                self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            self.assertEqual(self.read(reader),expected)

    def test_equal_chunk_hash_in_other_source_cannot_hide_missing_retained_chunk(self):
        second = self.root / 'second-source.sqlite'
        with closing(sqlite3.connect(second, isolation_level=None)) as db:
            self.db.backup(db)
            self.shared.append_reference('pump','mint',self.body,path=second,identity='third',kind='pump_transaction')
            db.execute('DELETE FROM hot_chunks')
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            with self.assertRaisesRegex(ValueError,'hot_evidence_corrupt'): self.read(reader)
            self.assertFalse(reader.db.in_transaction)

    def test_later_malformed_outer_preserves_earlier_original_canonical_hash_error(self):
        self.db.execute("UPDATE facts SET hash='earlier-corrupt-hash'")
        self.db.execute('INSERT INTO facts VALUES(?,?,?,NULL)',
            ('later-malformed', b'SEP1' + zlib.compress(b'{"payload":null}'), 'later-hash'))
        ref = dict(path=str(self.source),canonical_identity='later-malformed',canonical_hash='later-hash',fields={})
        raw = json.dumps(ref,sort_keys=True,separators=(',',':'))
        self.shared.db.execute('INSERT INTO canonical_event_refs VALUES(?,?,?,?,?,?,?,?,?,?)',
            ('pump','mint','third',101,0,0,101,'pump_transaction',raw,hashlib.sha256(raw.encode()).hexdigest()))
        with self.assertRaisesRegex(ValueError,'candidate_history_corruption'):
            self.shared.events('pump','mint',kind_prefix='pump_')
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            with self.assertRaisesRegex(ValueError,'candidate_history_corruption'): self.read(reader)

    def test_later_second_snapshot_open_failure_preserves_earlier_canonical_hash_error(self):
        from meme_machine import solana_evidence_storage as storage
        second = self.root / 'later-source.sqlite'
        with closing(sqlite3.connect(second,isolation_level=None)) as db:
            self.db.backup(db)
        self.shared.append_reference('pump','mint',self.body,path=second,identity='third',kind='pump_transaction')
        self.db.execute("UPDATE facts SET hash='earlier-corrupt-hash'")
        original = storage.prepare_decode; prepared = []
        def prepare(raw):
            result = original(raw); prepared.append(1)
            if len(prepared) == 3: second.unlink()
            return result
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader, \
                patch.object(storage,'prepare_decode',prepare):
            with self.assertRaisesRegex(ValueError,'candidate_history_corruption'): self.read(reader)
        self.assertFalse(second.exists())

    def test_failed_preparation_drops_rich_exceptions_before_original_reference_turn(self):
        from meme_machine import solana_evidence_storage as storage
        class RetainedDocument: pass
        retained = []
        self.db.execute("UPDATE facts SET hash='earlier-corrupt-hash'")
        for n in range(4):
            key = 'malformed-' + str(n)
            self.db.execute('INSERT INTO facts VALUES(?,?,?,NULL)',
                (key, b'SEP1' + zlib.compress(b' ' * (1024 * 1024) + b'{'), 'bad'))
            ref = dict(path=str(self.source),canonical_identity=key,canonical_hash='bad',fields={})
            raw = json.dumps(ref,sort_keys=True,separators=(',',':'))
            self.shared.db.execute('INSERT INTO canonical_event_refs VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('pump','mint',key,101+n,0,0,101+n,'pump_transaction',raw,hashlib.sha256(raw.encode()).hexdigest()))
        original_prepare = storage.prepare_decode; original_body = self.shared._reference_body
        def prepare(raw):
            try: return original_prepare(raw)
            except json.JSONDecodeError as error:
                error.retained_document = RetainedDocument()
                retained.append(weakref.ref(error.retained_document))
                raise
        def body(*args, **kwargs):
            gc.collect()
            self.assertEqual(len(retained),4)
            self.assertTrue(all(value() is None for value in retained))
            return original_body(*args, **kwargs)
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader, \
                patch.object(storage,'prepare_decode',prepare), patch.object(self.shared,'_reference_body',body):
            with self.assertRaisesRegex(ValueError,'candidate_history_corruption'): self.read(reader)

    def test_reference_metadata_admission_pages_and_large_single_ref_use_original_scalar(self):
        self.shared.append_reference('pump','mint',self.body,path=self.source,identity='third',
            kind='pump_transaction',payload_fields={'legacy_large': '\u00e9' * 1024})
        expected = self.shared.events('pump','mint',kind_prefix='pump_')
        groups = []; scalar = []; original_group = pages.RestoreReferenceReader._source_rows
        original_body = self.shared._reference_body
        def group(reader, items, budget):
            groups.append(sum(reader._reference_bytes(item.raw) for item in items))
            return original_group(reader,items,budget)
        def body(*args, **kwargs):
            if args[2] == 'third': scalar.append(kwargs['_restore_lookup'].fallback)
            return original_body(*args, **kwargs)
        with patch.object(pages,'REFERENCE_BYTES',512), \
                self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader, \
                patch.object(pages.RestoreReferenceReader,'_source_rows',group), \
                patch.object(self.shared,'_reference_body',body):
            self.assertEqual(self.read(reader),expected)
        self.assertTrue(groups)
        self.assertTrue(all(size <= 512 for size in groups))
        self.assertEqual(scalar,[True])

    def test_mutating_yielded_chunk_cannot_mutate_cache_or_next_duplicate(self):
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            raw = self.shared.db.execute('SELECT identity,kind,body,hash FROM canonical_event_refs '
                "WHERE lane='pump' AND candidate='mint'")
            rows = reader.rows('pump','mint',raw)
            try:
                first = next(rows)
                first['payload']['meta']['logMessages'][0] = 'mutated-before-next-yield'
                first['payload']['nested']['values'].append(99)
                self.assertEqual(first['payload']['raw_lineage']['logs'],self.body['payload']['raw_lineage']['logs'])
                second = next(rows)
                self.assertEqual(second['payload'],self.body['payload'])
                with self.assertRaises(StopIteration): next(rows)
            finally: rows.close()

    def test_large_uncached_chunk_releases_completed_prepared_outer_before_next_reference(self):
        body = deepcopy(self.body)
        body['payload']['meta']['logMessages'] = ['a' * (4 * 1024 * 1024 + 1)]
        self.replace_body(body)
        consumed = []; original = self.shared._reference_body
        def reference(*args, **kwargs):
            for lookup in consumed:
                self.assertIsNone(lookup.prepared)
                self.assertIsNone(lookup.row)
                self.assertIsNone(lookup.raw)
                self.assertEqual(lookup.chunks,{})
                self.assertEqual(lookup.decoded_chunks,{})
            value = original(*args, **kwargs)
            consumed.append(kwargs['_restore_lookup'])
            return value
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader, \
                patch.object(self.shared,'_reference_body',reference):
            actual = self.read(reader)
        self.assertEqual(len(consumed),2)
        self.assertTrue(all(lookup.prepared is None for lookup in consumed))
        self.assertEqual(actual[0]['payload'],body['payload'])
        actual[0]['payload']['meta']['logMessages'][0] = 'changed'
        self.assertEqual(actual[1]['payload'],body['payload'])

    def test_nested_valid_chunk_declines_optional_cache_without_new_recursion_failure(self):
        body = deepcopy(self.body); nested = ['x' * 4096]
        for _ in range(350): nested = [nested]
        body['payload']['meta']['logMessages'] = nested
        self.replace_body(body)
        expected = self.shared.events('pump','mint',kind_prefix='pump_')
        with self.shared.restoration_reader(cancelled=lambda:False,archives={}) as reader:
            self.assertEqual(self.read(reader),expected)
