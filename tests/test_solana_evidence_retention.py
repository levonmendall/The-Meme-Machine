import gzip,json,tempfile,unittest
from pathlib import Path
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable
from tests.test_solana_evidence_plane import record,proof

class RetentionTests(unittest.TestCase):
    def test_boundary_keeps_pins_compacts_old_rows_and_rejects_reintroduction(self):
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db',clock=lambda:1000)
            from dataclasses import replace
            rows=[replace(record(),identity='r'+str(i),signature='s'+str(i),slot=i,market_time=i) for i in range(10,31)]
            writer.ingest(rows,proof=proof(10,30))
            scope=rows[0].scope
            writer.interest('open',scope,lower_slot=20,priority=0,lifecycle='open')
            self.assertEqual(writer.retain(1000),10)
            reader=EvidenceReader(writer.path)
            self.assertFalse(reader.covered(scope,10,19,as_of=2000))
            self.assertTrue(reader.covered(scope,20,30,as_of=2000))
            self.assertEqual(len(reader.window(scope,20,30,as_of=2000)),11)
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],11)
            with self.assertRaises(EvidenceUnavailable):writer.ingest([rows[0]])
            raw=[json.loads(line) for f in Path(temp).glob('*.archive/*.gz') for line in gzip.open(f,'rt')]
            self.assertEqual(len(raw),10);self.assertTrue(all(r['lineage'] for r in raw))
            self.assertGreater(reader.telemetry()['archive_bytes'],0)
            plan=reader.db.execute('EXPLAIN QUERY PLAN SELECT identity FROM addresses WHERE address=? AND slot BETWEEN ? AND ?',('pool',20,30)).fetchall()
            self.assertTrue(any('address_window' in str(r) for r in plan))
            reader.close();writer.close()
    def test_unresolved_gap_pins_raw_material(self):
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db',clock=lambda:1000)
            row=record();writer.ingest([row]);writer.gap(row.scope,row.slot,row.slot)
            self.assertEqual(writer.retain(1000),0)
            self.assertIsNotNone(writer.db.execute('SELECT body FROM records').fetchone()[0]);writer.close()
    def test_reservation_arriving_during_archive_io_keeps_hot_evidence(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        import threading
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db',clock=lambda:1000);row=record();writer.ingest([row])
            plan=writer.archive_plan(1000);entered=threading.Event();release=threading.Event()
            from meme_machine.solana_evidence_plane import publish_bytes
            def delayed(path,content):entered.set();release.wait(2);publish_bytes(path,content)
            with ThreadPoolExecutor(max_workers=1) as pool,patch('meme_machine.solana_evidence_plane.publish_bytes',side_effect=delayed):
                future=pool.submit(writer.write_archive,writer.path,plan)
                try:
                    self.assertTrue(entered.wait(1))
                    writer.interest('reserved',row.scope,lower_slot=row.slot,priority=1,lifecycle='reserved')
                    from dataclasses import replace
                    writer.ingest([replace(row,identity='new',signature='new',slot=row.slot+1)])
                    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)
                finally:release.set()
                receipt=future.result()
            self.assertEqual(writer.commit_archive(plan,receipt),0)
            self.assertIsNotNone(writer.db.execute('SELECT body FROM records WHERE identity=?',(row.identity,)).fetchone()[0]);writer.close()
