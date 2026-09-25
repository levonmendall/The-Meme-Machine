import gzip,json,tempfile,unittest
from pathlib import Path
from meme_machine.solana_evidence_plane import EvidenceWriter,EvidenceReader,EvidenceUnavailable
from tests.test_solana_evidence_plane import record,proof

class RetentionTests(unittest.TestCase):
    def test_account_stream_inherits_lifecycle_pin_then_compacts_without_coverage(self):
        from dataclasses import replace
        from meme_machine.solana_evidence_service import FinalizedFence
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db',clock=lambda:1000)
            fence=FinalizedFence(writer,endpoint_identity='alchemy-test')
            row=replace(record(),scope='account:vault',identity='account:vault:10',slot=10,
                        kind='account',market_time=None,addresses=('vault',))
            writer.ingest([row])
            plan=writer.archive_plan(1000)
            receipt=writer.write_archive(writer.path,plan)
            # Lifecycle interest arrives after archive I/O and pins the account,
            # including its unchanged last observation before the reservation.
            fence.command(dict(op='interest',owner='reservation',scope='pump-program',
                lower_slot=20,priority=1,lifecycle='reserved',addresses=['vault']))
            self.assertEqual(writer.commit_archive(plan,receipt),0)
            self.assertEqual(writer.retain(1000),0)
            self.assertIsNotNone(writer.db.execute('SELECT body FROM records').fetchone()[0])
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM coverage').fetchone()[0],0)
            fence.disconnect('network_restart')
            writer.ingest([replace(row,identity='account:vault:21',slot=21)])
            fence.command(dict(op='release',owner='reservation',scope='pump-program',resolved=True))
            self.assertEqual(writer.retain(1000),2)
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM addresses').fetchone()[0],0)
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM lineage').fetchone()[0],0)
            writer.close()

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

    def test_archive_watermarks_fail_closed_without_removing_pins(self):
        from unittest.mock import patch
        from meme_machine.solana_evidence_plane import storage_health,STORAGE_WARNING_BYTES,STORAGE_CRITICAL_BYTES
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db');writer.ingest([record()])
            plan=writer.archive_plan(1000)
            writer.interest('reservation',record().scope,lower_slot=0,lifecycle='reserved',priority=1)
            with patch('os.statvfs',return_value=SimpleNamespace(f_bavail=STORAGE_WARNING_BYTES-1,f_frsize=1)):
                self.assertEqual(storage_health(writer.path)['state'],'warning')
            with patch('os.statvfs',return_value=SimpleNamespace(f_bavail=STORAGE_CRITICAL_BYTES-1,f_frsize=1)):
                self.assertEqual(storage_health(writer.path)['state'],'critical')
                with self.assertRaises(EvidenceUnavailable):writer.write_archive(writer.path,plan)
                with self.assertRaises(EvidenceUnavailable):writer.ingest([record()])
                reader=EvidenceReader(writer.path)
                with self.assertRaises(EvidenceUnavailable):reader.covered(record().scope,0,10,as_of=100)
                reader.close()
            self.assertEqual(writer.db.execute('SELECT active FROM interests').fetchone()[0],1)
            self.assertIsNotNone(writer.db.execute('SELECT body FROM records').fetchone()[0]);writer.close()

    def test_credential_rejected_before_evidence_archive_or_report_publication(self):
        from dataclasses import replace
        from meme_machine.durable_publication import publish_report
        from meme_machine.solana_provider_config import AlchemyEndpoint
        from unittest.mock import patch
        endpoint='https://solana-mainnet.g.alchemy.com/v2/offline-secret'
        with tempfile.TemporaryDirectory() as temp:
            writer=EvidenceWriter(Path(temp)/'db')
            with self.assertRaises(ValueError):writer.ingest([replace(record(),payload={'raw':endpoint})])
            self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
            with self.assertRaises(ValueError):writer.write_archive(writer.path,[{'raw':endpoint}])
            with patch.dict('os.environ',{'MM_SOLANA_READ_RPC_URL':endpoint}):
                result=publish_report(Path(temp)/'report.json',{'error':AlchemyEndpoint.parse(endpoint).credential})
                self.assertFalse(result['published'])
                self.assertFalse((Path(temp)/'report.json').exists())
            writer.close()
