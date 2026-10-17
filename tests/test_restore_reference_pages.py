"""Actual native FULL/ACK corpus through bounded startup source pages."""
from contextlib import closing
from copy import deepcopy
import hashlib
import gc
import json
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
from meme_machine.runtime.stop import Shutdown
from meme_machine.solana_evidence_plane import digest
from meme_machine.solana_evidence_storage import encode
from tests.test_startup_archive_read_reuse import ArchiveCorpus, archive_io


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
                expected_pages = (len(self.corpus.refs) + pages.PAGE_REFERENCES - 1) // pages.PAGE_REFERENCES
                self.assertEqual(sum('FROM canonical_evidence WHERE identity IN' in q for q in queries), 2 * expected_pages)
                self.assertEqual(sum('FROM scoped_cold_manifests WHERE id IN' in q for q in queries), 1)
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
        with closing(CandidateHistory(self.corpus.consumer)) as shared:
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
        with closing(CandidateHistory(self.corpus.consumer)) as shared, \
                shared.restoration_reader(cancelled=lambda: False, archives={}) as reader:
            with patch.object(pages, 'SNAPSHOT_SECONDS', 0):
                self.assertEqual(self.read(shared, reader), self.corpus.expected)
            self.assertFalse(reader.db.in_transaction)
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
