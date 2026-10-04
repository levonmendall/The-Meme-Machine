"""Offline integrity/crash/concurrency tests; no provider or market access."""
from dataclasses import replace
import json
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

from meme_machine.solana_evidence_plane import (
    EvidenceWriter, EvidenceReader, EvidenceUnavailable, EvidenceConflict,
    FinalizedRecord, IntervalProof, IngestionService, publish_json, digest,
)

ENDPOINT = 'a' * 64

def record(slot=10, value=1, scope='pump', identity=None, observed=100):
    return FinalizedRecord(identity or f'{scope}:signature:{slot}:0', scope, slot,
        f'signature:{slot}', 'program', ('pool',), slot,
        dict(value=value), 'alchemy_finalized_stream', ENDPOINT, observed)


def proof(lo=10, hi=10, scope='pump', at=100, repair=False):
    return IntervalProof(scope, lo, hi,
        'alchemy_finalized_repair' if repair else 'alchemy_finalized_stream',
        ENDPOINT, dict(finalized=True, complete=True, scope=scope,
                      lower_slot=lo, upper_slot=hi, lineage_hash=digest([scope,lo,hi])), at)


def crash_writer(path, ready):
    writer = EvidenceWriter(path)
    writer.ingest([record()], proof=proof())
    writer.db.execute('BEGIN IMMEDIATE')
    writer.db.execute("UPDATE cursors SET slot=999")
    ready.set()
    time.sleep(60)


class EvidencePlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'evidence.sqlite'
        self.writer = EvidenceWriter(self.path, clock=lambda: 110)

    def tearDown(self):
        if self.writer:
            self.writer.close()
        self.temp.cleanup()

    def reader(self):
        reader = EvidenceReader(self.path)
        self.addCleanup(reader.close)
        return reader

    def test_cold_socket_or_record_does_not_grant_coverage(self):
        self.writer.ingest([record()])
        with self.assertRaisesRegex(EvidenceUnavailable, 'gap'):
            self.reader().window('pump', 10, 10, as_of=100)

    def test_interval_requires_explicit_complete_finalized_witness(self):
        for field, value in [('complete', False), ('finalized', False), ('lower_slot', 9), ('lineage_hash', '')]:
            p=proof();w=dict(p.witness);w[field]=value
            with self.assertRaises(EvidenceUnavailable):
                self.writer.ingest([], proof=replace(p,witness=w))

    def test_public_source_and_unknown_provenance_rejected(self):
        for r in (replace(record(),source='public_finalized_stream'), replace(record(),endpoint_identity='secret'),
                  replace(record(),market_time=101),replace(record(),slot=-1)):
            with self.assertRaises(EvidenceUnavailable):self.writer.ingest([r])

    def test_covered_query_local_indexed_and_read_only(self):
        self.writer.ingest([record()],proof=proof())
        reader=self.reader()
        self.assertEqual(reader.window('pump',10,10,as_of=100,address='pool')[0]['payload'], {'value':1})
        with self.assertRaises(sqlite3.OperationalError):reader.db.execute('DELETE FROM records')
        plan=reader.db.execute('EXPLAIN QUERY PLAN SELECT * FROM records WHERE scope=? AND slot BETWEEN ? AND ?',('pump',10,12)).fetchall()
        self.assertIn('INDEX',str(plan))

    def test_duplicate_delivery_does_not_duplicate_evidence(self):
        self.writer.ingest([record(),record()],proof=proof())
        self.writer.ingest([replace(record(),source='alchemy_finalized_repair',observed_at=120)])
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM lineage').fetchone()[0],2)
        self.assertEqual(len(self.reader().window('pump',10,10,as_of=100)),1)

    def test_conflict_poison_survives_restart(self):
        self.writer.ingest([record()],proof=proof())
        with self.assertRaises(EvidenceConflict):self.writer.ingest([record(value=2)])
        self.writer.close();self.writer=EvidenceWriter(self.path)
        with self.assertRaises(EvidenceConflict):self.reader().window('pump',10,10,as_of=100)
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM conflicts').fetchone()[0],1)
        self.assertEqual(json.loads(self.writer.db.execute('SELECT body FROM records').fetchone()[0])['payload'],{'value':1})

    def test_conflict_within_batch_is_atomic(self):
        with self.assertRaises(EvidenceConflict):self.writer.ingest([record(),record(value=2)])
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)

    def test_gap_union_exact_boundaries_and_missing_middle(self):
        self.writer.ingest([],proof=proof(10,12))
        self.writer.ingest([],proof=proof(14,16))
        r=self.reader()
        self.assertFalse(r.covered('pump',10,16,as_of=100))
        self.writer.ingest([],proof=proof(13,13))
        self.assertTrue(r.covered('pump',10,16,as_of=100))
        self.assertFalse(r.covered('pump',9,16,as_of=100))
        self.assertFalse(r.covered('meteora',10,16,as_of=100))

    def test_late_repair_never_uncensors_old_decision(self):
        self.writer.gap('pump',10,12)
        self.writer.ingest([replace(record(),source='alchemy_finalized_repair',observed_at=120)],proof=proof(10,12,at=120,repair=True))
        r=self.reader()
        self.assertFalse(r.covered('pump',10,12,as_of=115))
        self.assertTrue(r.covered('pump',10,12,as_of=120))
        with self.assertRaises(EvidenceUnavailable):r.window('pump',10,12,as_of=115)

    def test_stream_resume_cannot_repair_old_gap(self):
        self.writer.gap('pump',10,12)
        self.writer.ingest([],proof=proof(10,20,at=120))
        self.assertFalse(self.reader().covered('pump',10,20,as_of=120))

    def test_restart_preserves_cursor_and_exposes_gap(self):
        self.writer.ingest([record()],proof=proof())
        self.writer.close();self.writer=EvidenceWriter(self.path,clock=lambda:110)
        self.assertEqual(self.writer.db.execute('SELECT slot FROM cursors').fetchone()[0],10)
        self.assertEqual(self.writer.db.execute('SELECT lo,hi,reason FROM gaps').fetchone(),(11,None,'writer_restart'))
        self.writer.reconnect('pump',15)
        self.assertEqual(self.writer.db.execute('SELECT hi FROM gaps').fetchone()[0],15)

    def test_single_writer_exclusion_and_thread_ownership(self):
        with self.assertRaises(EvidenceUnavailable):EvidenceWriter(self.path)
        errors=[]
        def other():
            try:self.writer.ingest([record()])
            except EvidenceUnavailable as e:errors.append(str(e))
        t=threading.Thread(target=other);t.start();t.join()
        self.assertEqual(errors,['writer_thread_violation'])

    def test_interests_pin_unresolved_lifecycle_across_other_owner_release(self):
        self.writer.ingest([record()],proof=proof())
        self.writer.interest('pump:reservation','pump',lower_slot=10,priority=1,lifecycle='reserved')
        self.writer.interest('meteora:candidate','pump',lower_slot=10)
        self.writer.release('meteora:candidate','pump')
        self.assertEqual(self.writer.archive(100),0)
        with self.assertRaises(EvidenceUnavailable):self.writer.release('pump:reservation','pump')
        self.writer.release('pump:reservation','pump',lifecycle_resolved=True)
        self.assertEqual(self.writer.archive(100),1)

    def test_archive_is_immutable_compressed_and_not_hidden_hot_read(self):
        self.writer.ingest([record()],proof=proof())
        self.assertEqual(self.writer.archive(100),1)
        self.assertEqual(self.writer.archive(100),0)
        with self.assertRaisesRegex(EvidenceUnavailable,'archive'):self.reader().window('pump',10,10,as_of=100)
        self.assertGreater(self.reader().telemetry()['archive_bytes'],0)
        with self.assertRaises(EvidenceConflict):self.writer.ingest([record(value=2)])

    def test_record_after_decision_is_not_available_retroactively(self):
        self.writer.ingest([replace(record(),observed_at=120)],proof=proof(at=120))
        self.assertFalse(self.reader().covered('pump',10,10,as_of=119))

    def test_consumer_cursor_monotone_and_lag_visible(self):
        self.writer.ingest([record(slot=20)])
        self.writer.acknowledge('pump','pump',10)
        with self.assertRaises(EvidenceUnavailable):self.writer.acknowledge('pump','pump',9)
        self.assertEqual(self.reader().telemetry()['consumer_lag'][0]['slots'],10)

    def test_repair_page_budget_durable_without_coverage(self):
        self.writer.gap('pump',10,12)
        for i in range(2):self.writer.repair_progress(1,cursor={'page':i},max_pages=2)
        with self.assertRaises(EvidenceUnavailable):self.writer.repair_progress(1,cursor={},max_pages=2)
        self.assertFalse(self.reader().covered('pump',10,12,as_of=130))

    def test_snapshot_reader_cannot_block_ingestion(self):
        self.writer.ingest([record()],proof=proof())
        a=self.reader();b=self.reader()
        for reader in (a,b):
            reader.db.execute('BEGIN')
            reader.db.execute('SELECT * FROM records').fetchall()
        for i in range(11,111):self.writer.ingest([record(slot=i,observed=200)],proof=proof(i,i,at=200))
        self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],101)
        for reader in (a,b):reader.db.execute('ROLLBACK')
        self.assertEqual(len(a.window('pump',10,110,as_of=200)),101)
        self.assertEqual(self.writer.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_service_detaches_caller_mutations(self):
        self.writer.close();self.writer=None
        service=IngestionService(self.path);service.start()
        try:
            value=record();service.submit([value],proof=proof())
            value.payload['value']=999
            service.queue.join()
            self.assertEqual(self.reader().window('pump',10,10,as_of=100)[0]['payload']['value'],1)
        finally:service.close()

    def test_unique_temporary_exports_under_concurrency(self):
        path=Path(self.temp.name)/'report.json';errors=[]
        def write(n):
            try:
                for i in range(20):publish_json(path,dict(writer=n,sequence=i))
            except BaseException as e:errors.append(e)
        workers=[threading.Thread(target=write,args=(n,)) for n in range(8)]
        for worker in workers:worker.start()
        for worker in workers:worker.join()
        self.assertEqual(errors,[])
        self.assertEqual(json.loads(path.read_text())['sequence'],19)
        self.assertEqual(list(path.parent.glob('*.tmp')),[])

    def test_sigkill_rolls_back_uncommitted_cursor_and_keeps_finalized_record(self):
        self.writer.close();self.writer=None
        context=multiprocessing.get_context('fork');ready=context.Event()
        child=context.Process(target=crash_writer,args=(self.path,ready));child.start()
        try:
            self.assertTrue(ready.wait(5));child.kill();child.join(5)
            self.writer=EvidenceWriter(self.path,clock=lambda:110)
            self.assertEqual(self.writer.db.execute('SELECT slot FROM cursors').fetchone()[0],10)
            self.assertEqual(self.writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
            self.assertEqual(self.writer.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:
            if child.is_alive():child.kill();child.join()


if __name__=='__main__':unittest.main()
