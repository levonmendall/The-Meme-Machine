"""Minimized Run-370 mechanisms; synthetic data is never market evidence."""
from dataclasses import replace
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceConflict,decode_body,digest
from meme_machine.solana_evidence_service import FinalizedFence,disconnect_classification
from meme_machine.solana_evidence_transport import Subscription
from tests.test_solana_evidence_plane import record,proof


class Run370StorageTests(unittest.TestCase):
    def test_restart_does_not_invent_account_interval_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db';w=EvidenceWriter(path,clock=lambda:100)
            w.db.execute("INSERT INTO cursors VALUES('account:pool',10,100)")
            w.db.execute("INSERT INTO cursors VALUES('program:meteora',10,100)")
            w.close();w=EvidenceWriter(path,clock=lambda:101)
            self.assertEqual(w.db.execute('SELECT scope,lo FROM gaps').fetchall(),[('program:meteora',11)])
            w.gap('program:meteora',12,14,'resumed_receipt')
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM gaps').fetchone()[0],1)
            w.close()

    def test_full_block_bound_applies_after_scope_filter_not_to_unrelated_votes(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=EvidenceWriter(Path(tmp)/'db',clock=lambda:100)
            f=FinalizedFence(w,endpoint_identity='a'*64)
            tx=dict(transaction=dict(signatures=['other'],message=dict(accountKeys=['other'])),meta={})
            message=dict(params=dict(result=dict(value=dict(slot=10,err=None,block=dict(parentSlot=9,blockTime=10,
                blockhash='h10',previousBlockhash='h9',transactions=[tx]*2049)))))
            f.block(Subscription('service','meteora','program','transactions',2),message,100)
            self.assertEqual(w.db.execute('SELECT census FROM stream_receipts').fetchone()[0],'[]')
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0);w.close()

    def test_repaired_gap_cannot_reopen_from_obsolete_receipt_and_floor_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=EvidenceWriter(Path(tmp)/'db',clock=lambda:1000);f=FinalizedFence(w,endpoint_identity='a'*64)
            w.ingest([record()],proof=proof())
            w.db.execute('INSERT INTO stream_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',('pump',10,9,'h','p',10,'[]',f.session,100,0))
            f.disconnect();w.reconnect('pump',11)
            self.assertEqual(w.retain(999),0) # unresolved interval really pins payload
            reader=EvidenceReader(w.path)
            self.assertFalse(reader.covered('pump',10,11,as_of=1000))
            w.ingest([],proof=proof(10,11,at=1001,repair=True))
            self.assertTrue(reader.covered('pump',10,11,as_of=1001))
            self.assertFalse(reader.covered('pump',10,11,as_of=1000))
            w.db.execute("UPDATE cursors SET slot=20 WHERE scope='pump'")
            f.disconnect();self.assertEqual(w.db.execute('SELECT lo FROM gaps WHERE repaired IS NULL').fetchall(),[(21,)])
            w.retain(2000)
            self.assertGreater(int(w.db.execute("SELECT value FROM meta WHERE key='retention_floor:pump'").fetchone()[0]),10)
            reader.close();w.close()

    def test_lossless_shared_logs_keep_all_execution_fields_and_archive_hashes(self):
        logs=['Program log: '+str(n)+'x'*90 for n in range(80)]
        payload=dict(transaction=dict(signatures=['sig'],message=dict(accountKeys=['program'],instructions=[{'data':'instruction'}])),
            meta=dict(logMessages=logs,loadedAddresses=dict(writable=['loaded'],readonly=['lookup']),
                preBalances=[1,2],postBalances=[3,4],preTokenBalances=[{'amount':7}],postTokenBalances=[{'amount':8}],
                innerInstructions=[{'index':0,'instructions':[{'data':'inner'}]}],err=None),slot=10,blockTime=10)
        rows=[replace(record(identity='tx'),payload=payload,kind='transaction',transaction_index=4),
              replace(record(identity='event'),payload=dict(event={'index':7},raw_lineage=dict(logs=logs,err=None)))]
        with tempfile.TemporaryDirectory() as tmp:
            w=EvidenceWriter(Path(tmp)/'db',clock=lambda:1000);w.ingest(rows,proof=proof())
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM hot_chunks').fetchone()[0],1)
            reader=EvidenceReader(w.path)
            got=reader.window('pump',10,10,as_of=100,address='pool')
            self.assertEqual({r['identity']:r for r in got},{r.identity:r.body() for r in rows})
            w.interest('position','pump',lower_slot=10,priority=0,lifecycle='open')
            self.assertEqual(w.archive(1000),0)
            w.release('position','pump',lifecycle_resolved=True);w.retain(1000)
            archived=[json.loads(line) for p in Path(tmp).glob('*.archive/*.gz') for line in gzip.open(p,'rt')]
            self.assertEqual({r['body']['identity']:r['body'] for r in archived},{r.identity:r.body() for r in rows})
            self.assertTrue(all(digest(r['body'])==r['hash'] for r in archived))
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM hot_chunks').fetchone()[0],0)
            reader.close();w.close()

    def test_legacy_address_migration_and_restart_preserve_full_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db';w=EvidenceWriter(path,clock=lambda:100);w.ingest([record()]);w.close()
            db=sqlite3.connect(path)
            db.executescript('''DROP VIEW addresses; DROP TRIGGER record_storage_delete;
                CREATE TABLE addresses(address TEXT,identity TEXT,slot INTEGER,PRIMARY KEY(address,identity));
                INSERT INTO addresses VALUES('pool','pump:signature:10:0',10);
                DROP TABLE address_refs;DROP TABLE address_keys;''');db.close()
            w=EvidenceWriter(path,clock=lambda:110)
            self.assertEqual(w.db.execute('SELECT * FROM addresses').fetchall(),[('pool','pump:signature:10:0',10)])
            self.assertEqual(w.db.execute('PRAGMA integrity_check').fetchone()[0],'ok');w.close()

    def test_corrupt_shared_material_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=EvidenceWriter(Path(tmp)/'db',clock=lambda:100)
            row=replace(record(),payload=dict(raw_lineage={'logs':['log'*100]*100}))
            w.ingest([row],proof=proof());w.db.execute("DELETE FROM hot_chunks")
            reader=EvidenceReader(w.path)
            with self.assertRaises(EvidenceConflict):reader.window('pump',10,10,as_of=100)
            reader.close();w.close()

    def test_close_attribution_does_not_publish_exception_secrets(self):
        from types import SimpleNamespace
        e=RuntimeError('https://provider/secret')
        e.sent=SimpleNamespace(code=1011,reason='keepalive ping timeout')
        self.assertEqual(disconnect_classification(e),'local_receive_backpressure_ping_timeout')
        e.sent=SimpleNamespace(code=1009,reason='secret')
        self.assertEqual(disconnect_classification(e),'source_message_size_limit')
        e.sent=None;e.rcvd=SimpleNamespace(code=1012,reason='secret')
        self.assertEqual(disconnect_classification(e),'provider_close_1012')
