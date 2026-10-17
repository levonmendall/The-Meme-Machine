"""Prepared outer decoding preserves the existing lossless codec contract."""
import copy
import hashlib
import json
import sqlite3
import unittest
import zlib

from meme_machine import solana_evidence_storage as storage


LIMIT = 16 * 1024 * 1024


def compressed(value):
    return b'SEP1' + zlib.compress(json.dumps(value, separators=(',', ':')).encode(), 1)


def fixture():
    body = dict(identity='native-economic-record', payload=dict(
        event=dict(mint='retained-mint', nested=[dict(value=7)]),
        raw_lineage=dict(logs=['first-' + 'a' * 600 for _ in range(4)]),
        meta=dict(logMessages=['second-' + 'b' * 600 for _ in range(4)])))
    encoded, chunks = storage.prepare(body)
    return body, encoded, chunks


class NoDB:
    def execute(self, *args, **kwargs):
        raise AssertionError('unexpected database read')


class PreparedEvidenceDecodeTests(unittest.TestCase):
    def test_text_scalars_lists_and_literal_markers_keep_original_json_meaning(self):
        marker = {'_hot_log_chunk': 'a' * 64}
        values = [None, False, 17, 'scalar', ['list', marker],
            dict(payload=dict(raw_lineage=dict(logs=marker), meta=dict(logMessages=marker))),
            dict(payload=None)]
        for expected in values:
            with self.subTest(expected=expected):
                raw = json.dumps(expected)
                prepared = storage.prepare_decode(raw)
                self.assertFalse(prepared.compressed)
                self.assertEqual(prepared.references, ())
                self.assertEqual(prepared.inflated_outer_bytes, len(raw.encode()))
                self.assertEqual(storage.finish_decode(prepared, NoDB(), chunks=object(),
                    decoded_chunks=object()), expected)
                self.assertEqual(storage.decode(raw, NoDB()), expected)

    def test_text_utf8_width_does_not_add_surrogate_rejection(self):
        for value in ('é', '\ud800'):
            raw = '"' + value + '"'
            prepared = storage.prepare_decode(raw)
            self.assertEqual(prepared.inflated_outer_bytes,
                len(raw.encode('utf-8', 'surrogatepass')))
            self.assertEqual(storage.finish_decode(prepared), value)
            self.assertEqual(storage.decode(raw), value)

    def test_actual_encoder_two_chunks_prepare_without_io_and_finish_real_sqlite(self):
        body, encoded, chunks = fixture()
        self.assertIsInstance(encoded, bytes)
        self.assertEqual(len(chunks), 2)
        prepared = storage.prepare_decode(encoded)
        self.assertTrue(prepared.compressed)
        self.assertEqual(prepared.inflated_outer_bytes, len(zlib.decompress(encoded[4:])))
        self.assertEqual(prepared.references, (
            ('raw_lineage', 'logs', chunks[0][0]), ('meta', 'logMessages', chunks[1][0])))
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE hot_chunks(hash TEXT PRIMARY KEY,body BLOB NOT NULL)')
            db.executemany('INSERT INTO hot_chunks VALUES(?,?)', chunks)
            reads = []
            db.set_trace_callback(reads.append)
            self.assertEqual(storage.finish_decode(prepared, db), body)
            self.assertEqual(len(reads), 2)
            self.assertIn(chunks[0][0], reads[0])
            self.assertIn(chunks[1][0], reads[1])
            self.assertEqual(storage.decode(encoded, db), body)
        self.assertEqual(storage.decode(encoded, chunks=dict(chunks)), body)

    def test_only_actual_two_sep1_marker_paths_are_references(self):
        marker = {'_hot_log_chunk': 'a' * 64}
        value = dict(payload=dict(
            event=dict(logs=marker), raw_lineage=dict(logs=dict(marker, literal=True)),
            meta=['not a metadata mapping']))
        prepared = storage.prepare_decode(compressed(value))
        self.assertEqual(prepared.references, ())
        self.assertEqual(storage.finish_decode(prepared, NoDB()), value)

    def test_missing_first_chunk_precedes_malformed_second_checksum(self):
        raw = json.dumps(['first']).encode()
        first = hashlib.sha256(raw).hexdigest()
        value = dict(payload=dict(raw_lineage=dict(logs={'_hot_log_chunk': first}),
            meta=dict(logMessages={'_hot_log_chunk': []})))
        prepared = storage.prepare_decode(compressed(value))
        self.assertEqual(prepared.references[1][2], [])
        # Extracting references must not hash/coerce a later malformed value.
        with self.assertRaisesRegex(ValueError, '^hot_chunk_missing$'):
            storage.finish_decode(prepared, chunks={})
        with self.assertRaisesRegex(ValueError, '^hot_chunk_missing$'):
            storage.decode(compressed(value), chunks={})
        with self.assertRaises(TypeError):
            storage.decode(compressed(value), chunks={first: zlib.compress(raw)})

    def test_corrupt_or_wrong_hash_first_chunk_does_not_read_second(self):
        body, encoded, chunks = fixture()
        for broken, reason in ((b'not-zlib', 'hot_chunk_corrupt'),
                (zlib.compress(b'["different"]'), 'hot_chunk_hash_mismatch')):
            with self.subTest(reason=reason), sqlite3.connect(':memory:') as db:
                db.execute('CREATE TABLE hot_chunks(hash TEXT PRIMARY KEY,body BLOB NOT NULL)')
                db.execute('INSERT INTO hot_chunks VALUES(?,?)', (chunks[0][0], broken))
                reads = []
                db.set_trace_callback(reads.append)
                with self.assertRaisesRegex(ValueError, '^' + reason + '$'):
                    storage.finish_decode(storage.prepare_decode(encoded), db)
                self.assertEqual(len(reads), 1)
                self.assertIn(chunks[0][0], reads[0])

    def test_original_encoding_json_and_payload_failure_classes_remain(self):
        for raw in (None, bytearray(b'SEP1'), b'', b'SEP2invalid'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, '^hot_body_encoding$'):
                storage.decode(raw)
        with self.assertRaisesRegex(ValueError, '^hot_body_corrupt$'):
            storage.prepare_decode(b'SEP1not-zlib')
        for raw in ('{', b'SEP1' + zlib.compress(b'{')):
            with self.assertRaises(json.JSONDecodeError):
                storage.decode(raw)
        for value, error in (({}, KeyError), ([], TypeError), (dict(payload=None), AttributeError)):
            with self.subTest(value=value), self.assertRaises(error):
                storage.decode(compressed(value))

    def test_prepared_outer_remains_owned_and_default_calls_do_not_share_payloads(self):
        body, encoded, chunks = fixture()
        prepared = storage.prepare_decode(encoded)
        result = storage.finish_decode(prepared, chunks=dict(chunks))
        self.assertIs(result, prepared.value)
        result['payload']['event']['nested'][0]['value'] = 99
        self.assertEqual(storage.finish_decode(prepared, NoDB()), result)
        fresh = storage.decode(encoded, chunks=dict(chunks))
        self.assertEqual(fresh, body)
        self.assertIsNot(fresh['payload']['raw_lineage']['logs'],
            result['payload']['raw_lineage']['logs'])

    def test_original_verified_decoded_cache_precedence_and_alias_semantics(self):
        body, encoded, chunks = fixture()
        cache = {}
        first = storage.decode(encoded, chunks=dict(chunks), decoded_chunks=cache)
        self.assertEqual(set(cache), {checksum for checksum, _ in chunks})
        second = storage.finish_decode(storage.prepare_decode(encoded), NoDB(),
            chunks={}, decoded_chunks=cache)
        self.assertEqual(second, body)
        for parent, key, checksum in storage.prepare_decode(encoded).references:
            self.assertIs(first['payload'][parent][key], cache[checksum][1])
            self.assertIs(second['payload'][parent][key], cache[checksum][1])

    def test_original_four_megabyte_decoded_cache_bound_is_preserved(self):
        body, encoded, chunks = fixture()
        cache = {'previous': (4 * 1024 * 1024, ['already cached'])}
        before = copy.deepcopy(cache)
        self.assertEqual(storage.decode(encoded, chunks=dict(chunks), decoded_chunks=cache), body)
        self.assertEqual(cache, before)

    def test_outer_inflation_exact_original_limit_and_one_byte_overflow(self):
        prefix, suffix = b'{"payload":{"value":"', b'"}}'
        for extra in (0, 1):
            raw = prefix + b'x' * (LIMIT - len(prefix) - len(suffix) + extra) + suffix
            encoded = b'SEP1' + zlib.compress(raw, 1)
            if extra:
                with self.assertRaisesRegex(ValueError, '^hot_chunk_bound_or_corruption$'):
                    storage.prepare_decode(encoded)
            else:
                prepared = storage.prepare_decode(encoded)
                self.assertEqual(prepared.inflated_outer_bytes, LIMIT)
                self.assertEqual(len(storage.finish_decode(prepared)['payload']['value']),
                    LIMIT - len(prefix) - len(suffix))

    def test_plain_text_has_no_new_sixteen_megabyte_history_limit(self):
        raw = '"' + 'x' * LIMIT + '"'
        prepared = storage.prepare_decode(raw)
        self.assertEqual(prepared.inflated_outer_bytes, LIMIT + 2)
        self.assertEqual(len(storage.finish_decode(prepared)), LIMIT)

    def test_chunk_keeps_original_inflation_bound(self):
        value = dict(payload=dict(raw_lineage=dict(logs={'_hot_log_chunk': 'a' * 64})))
        raw = compressed(value)
        with self.assertRaisesRegex(ValueError, '^hot_chunk_bound_or_corruption$'):
            storage.finish_decode(storage.prepare_decode(raw),
                chunks={'a' * 64: zlib.compress(b'x' * (LIMIT + 1), 1)})


if __name__ == '__main__':
    unittest.main()
