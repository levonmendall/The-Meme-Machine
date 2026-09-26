import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from certification import archive_native as archive


class EvidenceSnapshotTests(unittest.TestCase):
    def test_directional_survivor_and_shared_authority_are_archived_together(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);work=root/'work';out=root/'frozen'
            for lane in ('pump','pons'):
                native=work/lane;native.mkdir(parents=True)
                folder=native/'pump-survivor' if lane=='pump' else native/'pons-selective-continuation-v1-cohort/pons-survivor'
                folder.mkdir(parents=True)
                for path in (native/'directional-sleeve.sqlite',folder/'paper.sqlite',folder/'history.sqlite'):
                    with sqlite3.connect(path) as db:
                        db.execute('CREATE TABLE proof(value TEXT)');db.execute("INSERT INTO proof VALUES('durable')")
            records=archive.collect(work,out)
            self.assertFalse(any(r.get('error_type') for r in records))
            for path in work.rglob('*.sqlite'):
                with sqlite3.connect(out/path.relative_to(work)) as db:
                    self.assertEqual(db.execute('SELECT value FROM proof').fetchone()[0],'durable')

    def test_wal_cleanup_during_collection_cannot_break_frozen_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);work=root/'work';lane=work/'pons';lane.mkdir(parents=True)
            native=lane/'pons-selective-continuation-v1-cohort';native.mkdir()
            path=native/'trial-001.sqlite'
            writer=sqlite3.connect(path)
            writer.execute('PRAGMA journal_mode=WAL');writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('CREATE TABLE journal(action TEXT, basis INTEGER, proceeds INTEGER)')
            writer.execute("INSERT INTO journal VALUES('entry',123,0)");writer.commit()
            self.assertTrue(Path(str(path)+'-wal').exists())
            original=archive.copy_snapshot;closed=[]
            def copy(source,target,records):
                original(source,target,records)
                if Path(source)==path and not closed:writer.close();closed.append(True)
            out=root/'frozen';records=[]
            with patch.object(archive,'copy_snapshot',side_effect=copy):
                archive.collect(work,out,records)
            self.assertFalse(any(row.get('error_type') for row in records))
            saved=out/'pons'/native.name/path.name
            with sqlite3.connect(saved) as db:self.assertEqual(db.execute('SELECT * FROM journal').fetchall(),[('entry',123,0)])
            self.assertFalse(list(out.rglob('*-wal')));self.assertFalse(list(out.rglob('*-shm')))
            zipped=shutil.make_archive(str(root/'evidence'),'zip',out)
            with zipfile.ZipFile(zipped) as z:self.assertIsNone(z.testzip())
            self.assertTrue(path.exists())

    def test_committed_backup_is_independent_of_later_source_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'book.sqlite';target=root/'frozen.sqlite';rows=[]
            with sqlite3.connect(source) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE positions(id TEXT,status TEXT,basis INTEGER)')
                db.execute("INSERT INTO positions VALUES('original','open',999)");db.commit()
                archive.copy_snapshot(source,target,rows)
                db.execute("UPDATE positions SET status='settled',basis=0");db.commit()
            with sqlite3.connect(target) as db:
                self.assertEqual(db.execute('SELECT * FROM positions').fetchall(),[('original','open',999)])
            self.assertTrue(rows[0]['integrity_verified'])

    def test_snapshot_retains_other_evidence_and_marks_corrupt_database(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);work=root/'work';native=work/'pons'/'pons-selective-continuation-v1-cohort'
            native.mkdir(parents=True)
            (native/'broken.sqlite').write_bytes(b'SQLite format 3'+bytes([0])+b'broken')
            (native/'raw.jsonl').write_text('{"status":"unresolved"}\n')
            with self.assertRaisesRegex(RuntimeError,'snapshot_incomplete'):
                archive.stage(work,root,root/'snapshot','hourly')
            out=root/'snapshot'
            manifest=json.loads((out/'evidence-snapshot.json').read_text())
            self.assertFalse(manifest['snapshot_complete'])
            self.assertFalse(manifest['native_exposure_relabelled'])
            self.assertEqual((out/'certification-native/hourly/pons'/native.name/'raw.jsonl').read_text(),'{"status":"unresolved"}\n')
            self.assertTrue((native/'broken.sqlite').exists())
            self.assertEqual((out/'certification-native/hourly/pons'/native.name/'broken.sqlite.unverified-source').read_bytes(),(native/'broken.sqlite').read_bytes())

    def test_symlink_is_never_followed_into_unapproved_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);secret=root/'private';secret.write_text('not evidence')
            source=root/'link';source.symlink_to(secret)
            with self.assertRaisesRegex(ValueError,'symlink'):
                archive.copy_snapshot(source,root/'output',[])
            self.assertFalse((root/'output').exists())

    def test_cancel_quiescence_only_signals_verified_workers_and_never_settles(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            data=dict(status='FAILED',integration_sha='source',lanes={
                'pons':dict(pid=123,open_positions=1),'pump':dict(pid=456,open_positions=0)})
            (root/'result.json').write_text(json.dumps(data))
            calls=[]
            def matches(pid,lane,folder):
                if pid!=123:return False
                return not calls
            with patch.object(archive,'_worker_matches',side_effect=matches),patch.object(archive.os,'killpg',side_effect=lambda *a:calls.append(a)):
                rows=archive.quiesce_cancelled(root)
            self.assertEqual(calls,[(123,signal.SIGINT)])
            self.assertFalse(rows[0]['settlement_inferred'])
            self.assertEqual(json.loads((root/'result.json').read_text()),data)
