"""Actual worker-thread snapshot connections must close on success and failure."""
from concurrent.futures import ThreadPoolExecutor
import json,sqlite3,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from meme_machine.runtime.lifecycle_timing import _open_meteora_identities

class LifecycleSnapshotConnectionTests(unittest.TestCase):
    def run_case(self,malformed=False):
        original=sqlite3.connect;closed=[];opened=[]
        class Tracked(sqlite3.Connection):
            def close(self):
                closed.append(threading.get_ident())
                return super().close()
        def connect(*args,**kwargs):
            db=original(*args,**kwargs,factory=Tracked);opened.append(db);return db
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'accounting.sqlite'
            db=original(path)
            db.execute('CREATE TABLE events(seq INTEGER,body TEXT)')
            rows=[dict(identity='open',action='reserve'),dict(identity='done',action='settle')]
            db.executemany('INSERT INTO events VALUES(?,?)',[(i,'malformed' if malformed else json.dumps(row)) for i,row in enumerate(rows)])
            db.commit();db.close()
            with ThreadPoolExecutor(max_workers=1) as worker:
                worker_id=worker.submit(threading.get_ident).result()
                try:
                    with patch('sqlite3.connect',side_effect=connect):
                        future=worker.submit(_open_meteora_identities,path)
                        if malformed:
                            with self.assertRaises(json.JSONDecodeError):future.result()
                        else:self.assertEqual(future.result(),['open'])
                    self.assertEqual(closed,[worker_id])
                    self.assertEqual(len(opened),1)
                finally:
                    for db in opened:worker.submit(db.close).result()

    def test_success_closes_snapshot_in_own_worker(self):self.run_case()
    def test_malformed_event_still_closes_snapshot_in_own_worker(self):self.run_case(True)
