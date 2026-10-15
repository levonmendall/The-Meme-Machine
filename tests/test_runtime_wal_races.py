"""Deterministic checkpoint/unlink races; no providers or preserved state."""
from contextlib import contextmanager
import importlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PREFIXES=('meme_machine','meme_machine.lanes.pump','meme_machine.lanes.meteora')
@contextmanager
def disappeared_wal():
    exists,stat=Path.exists,Path.stat
    def raced_exists(path):return True if str(path).endswith('-wal') else exists(path)
    def raced_stat(path,*args,**kwargs):
        if str(path).endswith('-wal'):raise FileNotFoundError(str(path))
        return stat(path,*args,**kwargs)
    with patch.object(Path,'exists',raced_exists),patch.object(Path,'stat',raced_stat):yield

class RuntimeWalRaceTests(unittest.TestCase):
    def test_writer_ingestion_survives_checkpointed_wal(self):
        for prefix in PREFIXES:
            with self.subTest(prefix=prefix),tempfile.TemporaryDirectory() as td:
                module=importlib.import_module(prefix+'.solana_evidence_plane')
                writer=module.EvidenceWriter(Path(td)/'evidence.sqlite')
                try:
                    with disappeared_wal():writer.ingest([])
                    self.assertEqual(writer.db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
                finally:writer.close()

    def test_reader_telemetry_survives_checkpointed_wal(self):
        for prefix in PREFIXES:
            with self.subTest(prefix=prefix),tempfile.TemporaryDirectory() as td:
                module=importlib.import_module(prefix+'.solana_evidence_plane')
                path=Path(td)/'evidence.sqlite';writer=module.EvidenceWriter(path)
                reader=module.EvidenceReader(path)
                try:
                    with disappeared_wal():row=reader.telemetry()
                    self.assertEqual(row['wal_bytes'],0)
                    self.assertGreater(row['db_bytes'],0)
                    self.assertEqual(row['hot_bytes'],row['db_bytes'])
                finally:reader.close();writer.close()

    def test_wal_race_alone_cannot_invalidate_fresh_health_or_refresh_stale_health(self):
        for prefix in PREFIXES:
            with self.subTest(prefix=prefix),tempfile.TemporaryDirectory() as td:
                module=importlib.import_module(prefix+'.solana_evidence_health')
                path=Path(td)/'evidence.sqlite';path.write_bytes(b'present database size fixture')
                db=sqlite3.connect(':memory:')
                try:
                    db.executescript('CREATE TABLE service_health(key TEXT,value TEXT); CREATE TABLE meta(key TEXT,value TEXT); CREATE TABLE coverage(scope TEXT,hi INTEGER,available INTEGER); CREATE TABLE stream_receipts(scope TEXT,slot INTEGER,parent INTEGER);')
                    db.executemany('INSERT INTO service_health VALUES(?,?)',[(k,json.dumps(v)) for k,v in {'phase':'ACTIVE','heartbeat':100,'finalized_frontier:pump':{'time':100,'seen':100,'slot':10}}.items()])
                    db.execute("INSERT INTO coverage VALUES('pump',10,100)")
                    db.execute("INSERT INTO stream_receipts VALUES('pump',10,9)")
                    reader=SimpleNamespace(db=db,path=path,covered=lambda *a,**k:True)
                    with disappeared_wal():
                        self.assertEqual(module.evidence_health(reader,'pump',100)['state'],'USABLE')
                        self.assertEqual(module.evidence_health(reader,'pump',116)['reason'],'evidence_heartbeat_stale')
                finally:db.close()

    def test_robinhood_candidate_snapshot_survives_checkpointed_wal(self):
        from meme_machine.runtime.robinhood.plane import Plane
        with tempfile.TemporaryDirectory() as td:
            plane=Plane(Path(td)/'candidates.sqlite')
            try:
                with disappeared_wal():row=plane.snapshot()
                self.assertEqual(row['wal_bytes'],0)
                self.assertGreater(row['database_bytes'],0)
            finally:plane.close()

    def test_only_missing_transient_file_is_zero_permission_errors_propagate(self):
        from meme_machine.runtime.sqlite_files import transient_file_size
        with patch.object(Path,'stat',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):transient_file_size('fixture-wal')
        with patch.object(Path,'stat',return_value=SimpleNamespace(st_size=123)):
            self.assertEqual(transient_file_size('fixture-wal'),123)
