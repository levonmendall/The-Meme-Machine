import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from certification.governor import Governor

class ReservedPriorityTests(unittest.TestCase):
    def test_reserved_request_displaces_background_without_raising_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            g=Governor(Path(temp)/'governor.sqlite');now=time.monotonic()
            with sqlite3.connect(g.path) as db:
                db.executemany('INSERT INTO queue VALUES(?,?,?,?,?,?)',
                    [(str(i),'solana','evidence',50,now,now+30) for i in range(256)])
            wait=g.acquire('solana','pump',1,deadline_seconds=1,methods=['getMultipleAccounts'])
            self.assertLess(wait,.5);self.assertEqual(g.interval,.5)
            with sqlite3.connect(g.path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM queue').fetchone()[0],255)
                self.assertEqual(db.execute('SELECT priority,granted FROM grants').fetchone(),(1,1))
    def test_open_position_still_outranks_reserved(self):
        with tempfile.TemporaryDirectory() as temp:
            g=Governor(Path(temp)/'governor.sqlite');now=time.monotonic()
            with sqlite3.connect(g.path) as db:
                db.executemany('INSERT INTO queue VALUES(?,?,?,?,?,?)',
                    [('fill','solana','pump',1,now,now+20),('exit','solana','meteora',0,now,now+30)])
                self.assertEqual(g._head(db,'solana',now)[0],'exit')
