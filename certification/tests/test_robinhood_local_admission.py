import json,sqlite3,tempfile,unittest
from pathlib import Path
from certification.pressure import PressureView


class LocalAdmissionTelemetryTests(unittest.TestCase):
    def test_local_rejections_are_incremental_and_do_not_fabricate_transports(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'admission.sqlite'
            db=sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE transports(seq INTEGER PRIMARY KEY,body TEXT);
                CREATE TABLE admissions(seq INTEGER PRIMARY KEY,body TEXT);
                CREATE TABLE limits(endpoint TEXT,next_at REAL,cooldown REAL,interval REAL);
                CREATE TABLE queue(id TEXT,endpoint TEXT,priority INTEGER,created REAL,deadline REAL);
                INSERT INTO limits VALUES('redacted',0,0,0.5);
            """)
            for granted,methods in [(False,['eth_call','eth_call','eth_getCode']),(True,['eth_getLogs'])]:
                event=dict(lane='ramses',granted=granted,scope='factory',methods=methods,
                    reason='granted' if granted else 'provider_shared_admission_deadline',
                    wait_seconds=30 if not granted else 1,ended=100,priority=50)
                db.execute('INSERT INTO admissions(body) VALUES(?)',(json.dumps(event),))
            db.commit();db.close()
            view=PressureView(path);first=view.snapshot();second=view.snapshot()
            row=second['admission_by_lane']['ramses']
            self.assertEqual(row['requested'],2);self.assertEqual(row['granted'],1)
            self.assertEqual(row['failed'],1)
            self.assertEqual(row['failed_by_method'],{'eth_call':1,'eth_getCode':1})
            self.assertEqual(row['failed_by_reason'],{'provider_shared_admission_deadline':1})
            self.assertEqual(row['failed_by_scope'],{'factory':1})
            self.assertEqual(row['granted_by_priority'],{'50':1})
            self.assertEqual(second['lanes'],{});self.assertEqual(second['last_sequence'],0)
            self.assertEqual(first['admission_by_lane'],second['admission_by_lane'])
