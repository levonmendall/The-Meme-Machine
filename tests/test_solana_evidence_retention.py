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
