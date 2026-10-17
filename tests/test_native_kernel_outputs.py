"""Post-join kernel receipt checks over genuine disposable native FULL/ACK.

The original native frame decoder, source outbox, CandidateHistory delivery and
source acknowledgement create the positive rows. Corruptions touch only these
disposable test copies; no fabricated acknowledgement supplies the positive.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from meme_machine.operational import isolated_native_kernel_validation as validation
from meme_machine.runtime.journal import canonical


class NativeKernelOutputTests(unittest.TestCase):
    def setUp(self):
        from tests.test_pump_cache_source_authority import PumpCacheSourceAuthorityTests
        self.case=PumpCacheSourceAuthorityTests('runTest');self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.source=self.case.root/'solana-evidence.sqlite'
        self.state,self.history,_plane,_expected=self.case.selective_fixture(self.source)
        self.db=self.state.writer.db
        self.consumer=sqlite3.connect(self.case.cache_path,isolation_level=None)
        self.addCleanup(self.consumer.close)
        self.row=self.db.execute("SELECT id,family,address,body,hash FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL ORDER BY id LIMIT 1").fetchone()
        self.assertIsNotNone(self.row)
        self.identity=self.row[0];self.compact=json.loads(self.row[3])

    def count(self,endpoint=None):
        return validation._canonical_acks(self.db,self.consumer,self.source,
            endpoint_identity=endpoint or self.case.endpoint.identity)

    def test_actual_native_delivery_ack_binds_source_lineage_and_exact_candidate_reference(self):
        count=self.count()
        self.assertGreater(count,0)
        self.assertEqual(count,self.db.execute("SELECT COUNT(*) FROM candidate_history_outbox WHERE kind='canonical' AND consumed IS NOT NULL").fetchone()[0])
        with self.assertRaisesRegex(ValueError,'lineage'):self.count('0'*64)

    def test_self_hashed_empty_and_missing_or_cross_bound_receipts_do_not_count(self):
        self.db.execute('UPDATE candidate_history_outbox SET body=?,hash=? WHERE id=?',
            ('{}',hashlib.sha256(b'{}').hexdigest(),self.identity))
        with self.assertRaisesRegex(ValueError,'ack_shape'):self.count()
        self.db.execute('UPDATE candidate_history_outbox SET body=?,hash=? WHERE id=?',
            (self.row[3],self.row[4],self.identity))
        original=self.consumer.execute('SELECT * FROM source_receipts WHERE id=?',(self.identity,)).fetchone()
        proof=json.loads(original[5])
        for field,value in (('scope','candidate:pump:unrelated'),('canonical_identity','unrelated'),
                ('source_hash','0'*64)):
            bad=canonical(dict(proof,**{field:value}))
            self.consumer.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                (bad,hashlib.sha256(bad.encode()).hexdigest(),self.identity))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'ack_binding'):self.count()
        for body in ('{}','{"source_hash":null,"scope":null,"canonical_identity":null}'):
            self.consumer.execute('UPDATE source_receipts SET body=?,hash=? WHERE id=?',
                (body,hashlib.sha256(body.encode()).hexdigest(),self.identity))
            with self.assertRaisesRegex(ValueError,'ack_binding'):self.count()
        self.consumer.execute('INSERT OR REPLACE INTO source_receipts VALUES(?,?,?,?,?,?,?)',original)
        for field,value in (('family','pumpswap'),('address','unrelated'),('kind','scout')):
            self.consumer.execute('UPDATE source_receipts SET '+field+'=? WHERE id=?',(value,self.identity))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'consumer_ack_hash'):self.count()
            self.consumer.execute('INSERT OR REPLACE INTO source_receipts VALUES(?,?,?,?,?,?,?)',original)
        self.consumer.execute('DELETE FROM source_receipts WHERE id=?',(self.identity,))
        with self.assertRaisesRegex(ValueError,'consumer_ack_hash'):self.count()

    def test_unrelated_reference_count_and_self_hashed_wrong_reference_cannot_supply_full_ack(self):
        record_id=self.compact['record']['identity']
        reference=self.consumer.execute("SELECT * FROM canonical_event_refs WHERE json_extract(body,'$.canonical_identity')=? LIMIT 1",(record_id,)).fetchone()
        self.assertIsNotNone(reference)
        ref=json.loads(reference[8])
        for field,value in (('path',str(self.case.root/'unrelated.sqlite')),
                ('canonical_identity','unrelated'),('canonical_hash','0'*64),('fields',{})):
            raw=canonical(dict(ref,**{field:value}))
            self.consumer.execute('UPDATE canonical_event_refs SET body=?,hash=? WHERE lane=? AND candidate=? AND identity=?',
                (raw,hashlib.sha256(raw.encode()).hexdigest(),*reference[:3]))
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'canonical_reference_binding'):self.count()
            self.consumer.execute('INSERT OR REPLACE INTO canonical_event_refs VALUES(?,?,?,?,?,?,?,?,?,?)',reference)
        self.consumer.execute('DELETE FROM canonical_event_refs WHERE lane=? AND candidate=? AND identity=?',reference[:3])
        self.assertGreater(self.consumer.execute('SELECT COUNT(*) FROM canonical_event_refs').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'canonical_reference'):self.count()


class NativeKernelSQLitePathTests(unittest.TestCase):
    def test_canonical_ack_census_overflow_refuses_before_decoding_any_body(self):
        # Deliberately malformed negative rows; no synthetic ACK is accepted.
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE candidate_history_outbox(id TEXT,family TEXT,address TEXT,body TEXT,hash TEXT,kind TEXT,consumed INTEGER)')
            db.executemany('INSERT INTO candidate_history_outbox VALUES(?,?,?,?,?,?,?)',
                ((str(index),'pump','invalid','{}','invalid','canonical',1)
                    for index in range(1025)))
            with self.assertRaisesRegex(ValueError,'ack_bound'):
                validation._canonical_acks(db,db,Path('/unused'),endpoint_identity='a'*64)

    def test_existing_wal_commits_remain_visible_without_immutable_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'owned.sqlite'
            with closing(sqlite3.connect(path)) as writer:
                writer.execute('PRAGMA journal_mode=WAL');writer.execute('PRAGMA wal_autocheckpoint=0')
                writer.execute('CREATE TABLE fixture(value INTEGER)');writer.execute('INSERT INTO fixture VALUES(7)');writer.commit()
                self.assertTrue(path.with_name(path.name+'-wal').exists())
                with closing(validation._readonly(path)) as reader:
                    self.assertEqual(reader.execute('SELECT value FROM fixture').fetchall(),[(7,)])

    def test_every_sqlite_sidecar_refuses_foreign_path_links_before_sqlite_opens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);owned=root/'owned';owned.mkdir(mode=0o700)
            path=owned/'state.sqlite'
            with closing(sqlite3.connect(path)) as db:db.execute('CREATE TABLE fixture(value)')
            foreign=root/'foreign';foreign.write_bytes(b'private unrelated bytes')
            for suffix in ('-wal','-shm','-journal'):
                sidecar=path.with_name(path.name+suffix)
                for kind in ('symlink','hardlink'):
                    if kind=='symlink':sidecar.symlink_to(foreign)
                    else:os.link(foreign,sidecar)
                    with self.subTest(suffix=suffix,kind=kind),patch.object(validation.sqlite3,'connect',
                            side_effect=AssertionError('SQLite must not open unsafe sidecars')):
                        with self.assertRaisesRegex(ValueError,'database_sidecar'):validation._readonly(path)
                    sidecar.unlink()
            self.assertEqual(foreign.read_bytes(),b'private unrelated bytes')


if __name__=='__main__':unittest.main()
